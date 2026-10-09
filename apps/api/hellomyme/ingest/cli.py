"""hellomyme-ingest: operate the career ingestion pipeline (docs/09_INGESTION_PIPELINE.md).

  sheet    <workbook.xlsx> [--dry-run] [--report out.xlsx]
                                  load the ingestion workbook (template v2.1) as SEED people
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

from hellomyme.config import get_settings
from hellomyme.db import get_engine
from hellomyme.ingest import pipeline, sheet
from hellomyme.ingest.pipeline import IngestError

SOURCE_TYPES = ["PUBLIC_PROFILE", "LINKEDIN_USER_UPLOAD", "CAREER_DOCUMENT", "MANUAL_RESEARCH"]


def _dump(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2, default=str)
    print()


def main() -> None:
    p = argparse.ArgumentParser(prog="hellomyme-ingest", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("sheet", help="load the ingestion workbook (template v2.1)")
    w.add_argument("path")
    w.add_argument("--dry-run", action="store_true", help="check and report only; nothing is saved")
    w.add_argument("--report", help="also write the report as .xlsx (default: next to the workbook)")
    w.add_argument("--collector", default="workbook",
                   help="keep the same name across uploads so re-uploads update, not duplicate")
    w.add_argument("--legal-basis", help="basis for people without a 12_CONSENT row")
    w.add_argument("--accept-unreviewed", action="store_true",
                   help="treat pending/blank review_status as reviewed by the uploader")
    w.add_argument("--legal-reviewed", action="store_true",
                   help="required in production: the legal review in docs/09 §9 is done")
    w.add_argument("--as-of", type=date.fromisoformat, default=date.today())
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

    if args.cmd == "sheet":
        if get_settings().env == "production" and not args.legal_reviewed and not args.dry_run:
            p.error("production loads wait for the legal review (docs/09 §9); pass --legal-reviewed")
        engine = get_engine()
        with engine.connect() as conn:
            tx = conn.begin()
            report = sheet.import_workbook(
                conn, args.path, as_of=args.as_of, collector=args.collector,
                legal_basis=args.legal_basis, accept_unreviewed=args.accept_unreviewed)
            tx.rollback() if args.dry_run else tx.commit()
        report["dry_run"] = args.dry_run
        out = args.report or str(Path(args.path).with_name(
            Path(args.path).stem + ("_미리보기" if args.dry_run else "_적재결과") + ".xlsx"))
        sheet.write_report(report, out, dry_run=args.dry_run)
        _dump({"summary": report["summary"], "report": out, "dry_run": args.dry_run})
        return

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
