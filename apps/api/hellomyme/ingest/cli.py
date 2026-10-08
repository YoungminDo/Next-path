"""hellomyme-ingest: operate the career ingestion pipeline (docs/09_INGESTION_PIPELINE.md).

  receive  <ai_output.json> ...   store an AI extraction, check it, open it for review
  fields   <parse_run_id>         list a run's fields (pending first)
  review   <field_id> accept|reject|correct [--value V]
  accept-pending <parse_run_id>   mark every still-pending field as checked
  approve  <parse_run_id>         load a fully reviewed run as one SEED person
  queue    [--kind KIND]          names waiting to be standardised
  map      <mapping_id> (--ref UUID | --new NAME)
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import text

from hellomyme.db import get_engine
from hellomyme.ingest import pipeline
from hellomyme.ingest.pipeline import IngestError

SOURCE_TYPES = ["PUBLIC_PROFILE", "LINKEDIN_USER_UPLOAD", "CAREER_DOCUMENT", "MANUAL_RESEARCH"]


def _dump(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2, default=str)
    print()


def main() -> None:
    p = argparse.ArgumentParser(prog="hellomyme-ingest", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("receive")
    r.add_argument("path")
    r.add_argument("--collector", required=True, help="collector name, e.g. ops-vn-01")
    r.add_argument("--source-type", required=True, choices=SOURCE_TYPES)
    r.add_argument("--permitted-use", required=True, help="e.g. AGGREGATE_ONLY")
    r.add_argument("--legal-basis", required=True, help="the basis on record for this source")
    r.add_argument("--model", required=True, help="extraction model version")
    r.add_argument("--prompt", required=True, help="extraction prompt version")
    r.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    f = sub.add_parser("fields")
    f.add_argument("parse_run_id")
    v = sub.add_parser("review")
    v.add_argument("field_id")
    v.add_argument("decision", choices=["accept", "reject", "correct"])
    v.add_argument("--value")
    a = sub.add_parser("accept-pending")
    a.add_argument("parse_run_id")
    ap = sub.add_parser("approve")
    ap.add_argument("parse_run_id")
    q = sub.add_parser("queue")
    q.add_argument("--kind", choices=["ORGANIZATION", "ROLE", "MAJOR", "INSTITUTION"])
    m = sub.add_parser("map")
    m.add_argument("mapping_id")
    g = m.add_mutually_exclusive_group(required=True)
    g.add_argument("--ref", help="existing organization/institution id or taxonomy node id")
    g.add_argument("--new", help="create this organization/institution")
    args = p.parse_args()

    try:
        with get_engine().begin() as conn:
            if args.cmd == "receive":
                _dump(pipeline.receive(
                    conn, Path(args.path).read_text(encoding="utf-8"), collector=args.collector,
                    source_type=args.source_type, permitted_use=args.permitted_use,
                    legal_basis=args.legal_basis, model_version=args.model,
                    prompt_version=args.prompt, as_of=args.as_of))
            elif args.cmd == "fields":
                rows = conn.execute(text(
                    """SELECT extraction_field_id, entity_type, local_id, field_name, raw_value,
                              normalized_value, normalized_ref, confidence, review_status,
                              corrected_value, evidence_text
                       FROM extraction_field WHERE parse_run_id = CAST(:r AS uuid)
                       ORDER BY review_status <> 'PENDING', entity_type, local_id, field_name"""),
                    {"r": args.parse_run_id}).mappings().all()
                _dump([dict(x) for x in rows])
            elif args.cmd == "review":
                decision = {"accept": "ACCEPTED", "reject": "REJECTED",
                            "correct": "CORRECTED"}[args.decision]
                pipeline.review_field(conn, args.field_id, decision, corrected_value=args.value)
                _dump({"field_id": args.field_id, "review_status": decision})
            elif args.cmd == "accept-pending":
                _dump({"accepted": pipeline.accept_pending(conn, args.parse_run_id)})
            elif args.cmd == "approve":
                _dump(pipeline.approve(conn, args.parse_run_id))
            elif args.cmd == "queue":
                rows = conn.execute(text(
                    """SELECT mapping_queue_id, entity_kind, raw_value, occurrences, created_at
                       FROM mapping_queue WHERE status = 'PENDING'
                         AND (CAST(:k AS text) IS NULL OR entity_kind = :k)
                       ORDER BY occurrences DESC, created_at"""), {"k": args.kind}).mappings().all()
                _dump([dict(x) for x in rows])
            elif args.cmd == "map":
                _dump(pipeline.resolve_mapping(conn, args.mapping_id, resolved_ref=args.ref,
                                               new_name=args.new))
    except IngestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
