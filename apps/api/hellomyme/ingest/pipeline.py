"""Career ingestion: screenshots -> AI JSON (career_extraction.v1) -> automatic checks -> human
review -> DB. See docs/09_INGESTION_PIPELINE.md.

receive()        stores the AI output verbatim as a parse run, checks it, writes one review row
                 per extracted field and queues names no alias matched.
review_field()   records a reviewer's decision on one field (accept / correct / reject).
approve()        loads a fully reviewed run as one SEED person with its education and work
                 events, each linked to the screenshot that supports it. Replays are no-ops.
resolve_mapping() turns a queued name into an alias and fills the canonical id on every event
                 that carried that raw name. Raw text is never changed.

The AI never chooses canonical ids and nothing here invents a value the source did not show.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from sqlalchemy import Connection, text

SCHEMA_VERSION = "career_extraction.v1"
RULE_VERSION = "ingest_rules_v1"
SOURCE_SYSTEM = "HELLOMYME_INGEST"
AUTO_ACCEPT_CONFIDENCE = 0.9
EVENT_TYPES = {"EMPLOYMENT", "STARTUP", "SIDE_BUSINESS", "SELF_EMPLOYED", "FREELANCE", "STUDY",
               "CAREER_BREAK", "MILITARY", "PROJECT", "OTHER"}

# Employment type from the label the profile shows (Korean / English / Vietnamese). No label, no
# value: an unlabelled job stays NULL rather than being assumed full-time.
EMPLOYMENT_TYPE_RULES = [
    ("INTERN", r"인턴|intern|thực tập|thuc tap"),
    ("CONTRACT", r"계약직|파견|contract|freelance contract|hợp đồng"),
    ("PART_TIME", r"파트타임|아르바이트|part[- ]?time|bán thời gian"),
    ("FULL_TIME", r"정규직|full[- ]?time|toàn thời gian"),
]
DEGREE_RULES = [
    ("DOCTORATE", r"박사|ph\.?d|doctor|tiến sĩ"),
    ("MASTER", r"석사|master|mba|m\.s\.|thạc sĩ"),
    ("ASSOCIATE", r"전문학사|associate"),
    ("BACHELOR", r"학사|bachelor|b\.a\.|b\.s\.|bsc|cử nhân"),
]


class IngestError(Exception):
    pass


@dataclass
class Issue:
    severity: str  # BLOCK | WARN | INFO
    code: str
    entity: str | None = None
    local_id: str | None = None
    detail: dict = field(default_factory=dict)


@lru_cache
def _validator() -> Draft202012Validator:
    schema = json.loads((Path(__file__).parent / "career_extraction.v1.schema.json").read_text())
    return Draft202012Validator(schema)


def _pdate(d: dict | None) -> tuple[date | None, str | None]:
    if not d:
        return None, None
    y, _, m = d["value"].partition("-")
    return date(int(y), int(m or 1), 1), d["precision"]


def _first(rules, raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    return next((code for code, pat in rules if re.search(pat, low)), None)


def check(doc: dict, as_of: date) -> list[Issue]:
    """Schema errors and record rules. BLOCK rejects the run; WARN leaves the field it concerns
    pending for a reviewer; INFO is recorded only (a repeated event is dropped)."""
    issues = [Issue("BLOCK", "SCHEMA", detail={"path": "/".join(map(str, e.absolute_path)),
                                                "message": e.message[:300]})
              for e in _validator().iter_errors(doc)]
    if issues:
        return issues
    assets = {a["asset_id"] for a in doc["assets"]}
    seen: set[tuple[str, str]] = set()
    for entity, rows in (("EDUCATION", doc["educations"]), ("WORK_EVENT", doc["work_events"])):
        for r in rows:
            lid = r["local_id"]
            if (entity, lid) in seen:
                issues.append(Issue("BLOCK", "DUPLICATE_LOCAL_ID", entity, lid))
            seen.add((entity, lid))
            for ev in r["evidence"]:
                if ev["asset_id"] not in assets:
                    issues.append(Issue("BLOCK", "EVIDENCE_ASSET_UNKNOWN", entity, lid,
                                        {"asset_id": ev["asset_id"]}))
            for key in ("start", "end"):
                d = r.get(key)
                if d and (d["precision"] == "MONTH") != ("-" in d["value"]):
                    issues.append(Issue("BLOCK", "PRECISION_MISMATCH", entity, lid, {"field": key}))
                if d and not 1950 <= int(d["value"][:4]) <= 2100:
                    issues.append(Issue("BLOCK", "YEAR_OUT_OF_RANGE", entity, lid, {"field": key}))
            if any(i.severity == "BLOCK" and (i.entity, i.local_id) == (entity, lid) for i in issues):
                continue
            start, _ = _pdate(r.get("start"))
            end, _ = _pdate(r.get("end"))
            if start and end and end < start:
                issues.append(Issue("BLOCK", "END_BEFORE_START", entity, lid))
            if entity == "WORK_EVENT":
                if start and start > as_of:
                    issues.append(Issue("BLOCK", "START_AFTER_AS_OF", entity, lid))
                if r.get("is_current") and r.get("end"):
                    issues.append(Issue("BLOCK", "CURRENT_WITH_END_DATE", entity, lid))
                if not r.get("start"):
                    issues.append(Issue("WARN", "MISSING_START", entity, lid))
                if r.get("event_type_hint") in (None, "UNKNOWN"):
                    issues.append(Issue("WARN", "EVENT_TYPE_UNKNOWN", entity, lid))
    # Overlapping screenshots repeat the same job: same names + same start = one event.
    keys: dict[tuple, str] = {}
    for r in doc["work_events"]:
        k = (_norm(r.get("organization_raw")), _norm(r.get("role_raw")),
             (r.get("start") or {}).get("value"))
        if k in keys:
            issues.append(Issue("INFO", "DUPLICATE_EVENT", "WORK_EVENT", r["local_id"],
                                {"same_as": keys[k]}))
        else:
            keys[k] = r["local_id"]
    return issues


def _norm(s: str | None) -> str:
    return re.sub(r"[\s·・,./()\[\]_&+\-]+", "", (s or "").lower())


def _duplicates(issues: list[Issue]) -> set[str]:
    return {i.local_id for i in issues if i.code == "DUPLICATE_EVENT"}


# --- normalisation (deterministic lookups; the queue holds what they cannot match) ----------

def _lookup(conn: Connection, kind: str, raw: str | None) -> str | None:
    if not raw:
        return None
    approved = conn.execute(text(
        """SELECT resolved_ref::text FROM mapping_queue WHERE entity_kind = :k
             AND normalized_key = normalize_label(:r) AND status IN ('APPROVED','NEW_ENTITY')"""),
        {"k": kind, "r": raw}).scalar()
    if approved:
        return approved
    # Every candidate with its rank; a tie between different entries is ambiguous and goes to
    # the queue instead of being decided arbitrarily.
    if kind == "INSTITUTION":
        sql = """SELECT institution_id::text AS id, 0 AS rank FROM institution
                 WHERE normalize_label(name) = normalize_label(:r)"""
    elif kind == "ORGANIZATION":
        sql = """SELECT organization_id::text AS id, 0 AS rank FROM organization
                 WHERE normalize_label(name) = normalize_label(:r) AND NOT is_placeholder
                 UNION
                 SELECT organization_id::text, 0 FROM organization_alias
                 WHERE normalized_alias = normalize_label(:r) AND status = 'ACTIVE'"""
    else:  # the most specific taxonomy node wins
        sql = """SELECT n.taxonomy_node_id::text AS id, -n.depth AS rank
                 FROM taxonomy_node n JOIN taxonomy t USING (taxonomy_id)
                 WHERE t.taxonomy_type = :k AND t.status = 'ACTIVE' AND n.status = 'ACTIVE'
                   AND (normalize_label(n.display_name) = normalize_label(:r)
                        OR EXISTS (SELECT 1 FROM taxonomy_alias a
                                   WHERE a.taxonomy_node_id = n.taxonomy_node_id
                                     AND a.status = 'ACTIVE'
                                     AND a.normalized_alias = normalize_label(:r)))"""
    rows = conn.execute(text(sql), {"r": raw, "k": kind}).all()
    if not rows:
        return None
    best = min(r.rank for r in rows)
    top = {r.id for r in rows if r.rank == best}
    return top.pop() if len(top) == 1 else None


def _queue(conn: Connection, kind: str, raw: str) -> None:
    conn.execute(text(
        """INSERT INTO mapping_queue (entity_kind, raw_value) VALUES (:k, :r)
           ON CONFLICT (entity_kind, normalized_key)
           DO UPDATE SET occurrences = mapping_queue.occurrences + 1"""), {"k": kind, "r": raw})


# --- intake -----------------------------------------------------------------------------------

def receive(conn: Connection, raw_output: str, *, collector: str, source_type: str,
            permitted_use: str, legal_basis: str, model_version: str, prompt_version: str,
            as_of: date) -> dict:
    try:
        doc = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise IngestError(f"AI output is not JSON: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("submission_id"), str):
        raise IngestError("AI output has no submission_id")
    collector_id = conn.execute(text(
        "SELECT collector_id::text FROM collector WHERE name = :n ORDER BY created_at LIMIT 1"),
        {"n": collector}).scalar() or conn.execute(text(
        "INSERT INTO collector (name) VALUES (:n) RETURNING collector_id::text"),
        {"n": collector}).scalar_one()
    sub = conn.execute(text(
        """INSERT INTO source_submission (collector_id, external_submission_id, source_type,
               permitted_use, legal_basis)
           VALUES (:c, :s, :t, :u, :l)
           ON CONFLICT (collector_id, external_submission_id) DO UPDATE SET updated_at = now()
           RETURNING source_submission_id::text, status"""),
        {"c": collector_id, "s": doc["submission_id"], "t": source_type, "u": permitted_use,
         "l": legal_basis}).one()
    canonical = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    sha = hashlib.sha256(canonical.encode()).hexdigest()
    prior = conn.execute(text(
        """SELECT parse_run_id::text, status, issues FROM parse_run
           WHERE source_submission_id = :s AND output_sha256 = :h"""),
        {"s": sub.source_submission_id, "h": sha}).first()
    if prior:  # the same output again is the same run, whatever happened to it since
        return {"parse_run_id": prior.parse_run_id, "status": prior.status, "issues": prior.issues,
                "replayed": True}
    if sub.status in ("LOADED", "WITHDRAWN"):
        raise IngestError(f"submission {doc['submission_id']} is already {sub.status}")

    issues = check(doc, as_of)
    blocked = any(i.severity == "BLOCK" for i in issues)
    conn.execute(text(
        """UPDATE parse_run SET status = 'SUPERSEDED'
           WHERE source_submission_id = :s AND status IN ('NEEDS_REVIEW','READY')"""),
        {"s": sub.source_submission_id})
    run_id = conn.execute(text(
        """INSERT INTO parse_run (source_submission_id, model_version, prompt_version,
               schema_version, rule_version, raw_output, output_sha256, schema_valid, issues, status)
           VALUES (:s, :m, :p, :sv, :rv, CAST(:raw AS jsonb), :h, :ok, CAST(:iss AS jsonb), :st)
           RETURNING parse_run_id::text"""),
        {"s": sub.source_submission_id, "m": model_version, "p": prompt_version,
         "sv": str(doc.get("schema_version") or "unknown"), "rv": RULE_VERSION, "raw": canonical,
         "h": sha, "ok": not any(i.code == "SCHEMA" for i in issues),
         "iss": json.dumps([asdict(i) for i in issues], ensure_ascii=False),
         "st": "REJECTED" if blocked else "NEEDS_REVIEW"},
    ).scalar_one()
    conn.execute(text("UPDATE source_submission SET status = :st WHERE source_submission_id = :s"),
                 {"st": "REJECTED" if blocked else "IN_REVIEW", "s": sub.source_submission_id})
    if blocked:
        return {"parse_run_id": run_id, "status": "REJECTED",
                "issues": [asdict(i) for i in issues], "pending": 0, "unmapped": [],
                "replayed": False}

    assets = {}
    for a in doc["assets"]:
        assets[a["asset_id"]] = conn.execute(text(
            """INSERT INTO source_asset (source_submission_id, external_asset_id, page_order, sha256,
                   captured_at)
               VALUES (:s, :a, :p, :h, :c)
               ON CONFLICT (source_submission_id, external_asset_id)
               DO UPDATE SET page_order = EXCLUDED.page_order
               RETURNING source_asset_id::text"""),
            {"s": sub.source_submission_id, "a": a["asset_id"], "p": a["page_order"],
             "h": a.get("sha256"), "c": a.get("captured_at")}).scalar_one()

    unmapped: list[tuple[str, str]] = []
    rows: list[dict] = []

    def add(entity, lid, name, raw, normalized=None, ref=None, conf=None, ev=None, auto=True):
        rows.append({"r": run_id, "e": entity, "l": lid, "f": name, "raw": raw, "n": normalized,
                     "ref": ref, "c": conf, "a": assets.get(ev[0]["asset_id"]) if ev else None,
                     "t": " / ".join(x["text"] for x in ev) if ev else None,
                     "s": "AUTO_ACCEPTED" if auto else "PENDING"})

    def mapped(kind, entity, lid, name, raw, conf, ev):
        # Nothing shown -> nothing to review (stays unknown). A name no alias knows, or a
        # low-confidence reading, waits for a person.
        ref = _lookup(conn, kind, raw)
        if raw and not ref:
            unmapped.append((kind, raw))
        add(entity, lid, name, raw, raw, ref, conf, ev,
            auto=raw is None or (bool(ref) and (conf is None or conf >= AUTO_ACCEPT_CONFIDENCE)))

    def dated(entity, lid, key, d, ev, required=False):
        add(entity, lid, key, d and d["value"], d and f"{d['value']}|{d['precision']}", ev=ev,
            auto=bool(d) or not required)

    person = doc["person"]
    if person.get("display_name_raw"):
        add("PERSON", "person", "display_name", person["display_name_raw"],
            person["display_name_raw"])
    for e in doc["educations"]:
        lid, ev, conf = e["local_id"], e["evidence"], e.get("confidence") or {}
        mapped("INSTITUTION", "EDUCATION", lid, "institution", e["institution_raw"],
               conf.get("institution"), ev)
        mapped("MAJOR", "EDUCATION", lid, "major", e.get("major_raw"), conf.get("major"), ev)
        add("EDUCATION", lid, "degree_type", e.get("degree_raw"),
            _first(DEGREE_RULES, e.get("degree_raw")), ev=ev)
        for key in ("start", "end"):
            dated("EDUCATION", lid, key, e.get(key), ev)
    dupes = _duplicates(issues)
    for w in doc["work_events"]:
        lid, ev, conf = w["local_id"], w["evidence"], w.get("confidence") or {}
        if lid in dupes:
            continue
        mapped("ORGANIZATION", "WORK_EVENT", lid, "organization", w.get("organization_raw"),
               conf.get("organization"), ev)
        mapped("ROLE", "WORK_EVENT", lid, "role", w.get("role_raw"), conf.get("role"), ev)
        hint = w.get("event_type_hint")
        emp = "INTERN" if hint == "INTERN" else _first(EMPLOYMENT_TYPE_RULES,
                                                       w.get("employment_type_raw"))
        # An internship is employment with employment_type INTERN; UNKNOWN waits for a person.
        event_type = "EMPLOYMENT" if hint == "INTERN" else (hint if hint in EVENT_TYPES else None)
        add("WORK_EVENT", lid, "event_type", hint, event_type, ev=ev, auto=event_type is not None)
        add("WORK_EVENT", lid, "employment_type", w.get("employment_type_raw"), emp, ev=ev)
        dated("WORK_EVENT", lid, "start", w.get("start"), ev, required=True)
        dated("WORK_EVENT", lid, "end", w.get("end"), ev)
        cur = w.get("is_current")
        cur = None if cur is None else str(cur).lower()
        add("WORK_EVENT", lid, "is_current", cur, cur, ev=ev)
    conn.execute(text(
        """INSERT INTO extraction_field (parse_run_id, entity_type, local_id, field_name, raw_value,
               normalized_value, normalized_ref, confidence, source_asset_id, evidence_text,
               review_status)
           VALUES (:r, :e, :l, :f, :raw, :n, CAST(:ref AS uuid), :c, CAST(:a AS uuid), :t, :s)"""),
        rows)
    for kind, raw in dict.fromkeys(unmapped):
        _queue(conn, kind, raw)
    pending = sum(r["s"] == "PENDING" for r in rows)
    status = "NEEDS_REVIEW" if pending else "READY"
    conn.execute(text("UPDATE parse_run SET status = :st WHERE parse_run_id = CAST(:r AS uuid)"),
                 {"st": status, "r": run_id})
    return {"parse_run_id": run_id, "status": status, "issues": [asdict(i) for i in issues],
            "pending": pending, "unmapped": [{"kind": k, "raw": r} for k, r in unmapped],
            "replayed": False}


# --- review -----------------------------------------------------------------------------------

# A correction is the value the screenshot really shows: text for names, YYYY or YYYY-MM for
# dates, true/false for is_current, and the code itself for the coded fields.
CORRECTION_RULES = {
    "start": r"^[12][0-9]{3}(-(0[1-9]|1[0-2]))?$",
    "end": r"^[12][0-9]{3}(-(0[1-9]|1[0-2]))?$",
    "is_current": r"^(true|false)$",
    "event_type": "^(" + "|".join(sorted(EVENT_TYPES)) + ")$",
    "employment_type": r"^(FULL_TIME|PART_TIME|CONTRACT|INTERN|UNKNOWN)$",
    "degree_type": r"^(ASSOCIATE|BACHELOR|MASTER|DOCTORATE|OTHER)$",
}


def review_field(conn: Connection, extraction_field_id: str, decision: str, *,
                 corrected_value: str | None = None, reviewer_account_id: str | None = None) -> None:
    if decision not in ("ACCEPTED", "CORRECTED", "REJECTED"):
        raise IngestError("decision must be ACCEPTED, CORRECTED or REJECTED")
    if (decision == "CORRECTED") != (corrected_value is not None):
        raise IngestError("a correction needs corrected_value (and only a correction has one)")
    f = conn.execute(text(
        """SELECT f.field_name FROM extraction_field f JOIN parse_run r USING (parse_run_id)
           WHERE f.extraction_field_id = CAST(:i AS uuid) AND r.status IN ('NEEDS_REVIEW','READY')
           FOR UPDATE OF f"""), {"i": extraction_field_id}).first()
    if f is None:
        raise IngestError("field not found or its run is no longer open for review")
    if corrected_value is not None:
        corrected_value = corrected_value.strip()
        rule = CORRECTION_RULES.get(f.field_name, r"\S")
        if not re.search(rule, corrected_value):
            raise IngestError(f"{corrected_value!r} is not a valid {f.field_name}")
    conn.execute(text(
        """UPDATE extraction_field SET review_status = :d, corrected_value = :v,
               reviewer_account_id = CAST(:a AS uuid), reviewed_at = now()
           WHERE extraction_field_id = CAST(:i AS uuid)"""),
        {"d": decision, "v": corrected_value, "a": reviewer_account_id, "i": extraction_field_id})


def accept_pending(conn: Connection, parse_run_id: str, reviewer_account_id: str | None = None) -> int:
    """The reviewer's "checked, all correct" action for the fields still pending."""
    return conn.execute(text(
        """UPDATE extraction_field SET review_status = 'ACCEPTED',
               reviewer_account_id = CAST(:a AS uuid), reviewed_at = now()
           WHERE parse_run_id = CAST(:r AS uuid) AND review_status = 'PENDING'"""),
        {"r": parse_run_id, "a": reviewer_account_id}).rowcount


# --- load -------------------------------------------------------------------------------------

def _final(f) -> tuple[str | None, str | None]:
    """(value, ref) after review: corrections win, rejected fields become unknown."""
    if f.review_status == "REJECTED":
        return None, None
    if f.review_status == "CORRECTED":
        return f.corrected_value, None
    return f.normalized_value, f.normalized_ref


def _date(v: str | None) -> tuple[date | None, str | None]:
    if not v:
        return None, None
    value, _, precision = v.partition("|")
    return _pdate({"value": value, "precision": precision or ("MONTH" if "-" in value else "YEAR")})


def _resolved(conn: Connection, kind: str, f) -> tuple[str | None, str | None]:
    """Reviewed name plus its canonical id. A name mapped after intake, or a corrected name, is
    looked up again; a corrected name nobody knows yet joins the mapping queue."""
    value, ref = _final(f)
    if value and not ref:
        ref = _lookup(conn, kind, value)
        if not ref and f.review_status == "CORRECTED":
            _queue(conn, kind, value)
    return value, ref


def _mapping_status(*pairs: tuple[str | None, str | None]) -> str:
    present = [p for p in pairs if p[0]]
    mapped = [p for p in present if p[1]]
    return "MAPPED" if len(mapped) == len(present) else ("PARTIAL" if mapped else "UNMAPPED")


def _redacted(raw: dict) -> dict:
    """The SEED source record keeps the extraction without the person's name: the name lives
    only in person_pii (and in the deletable parse run)."""
    doc = json.loads(json.dumps(raw))
    person = doc.get("person") or {}
    if person.get("display_name_raw"):
        person["display_name_raw"] = "[person_pii]"
    for ev in person.get("evidence") or []:
        ev["text"] = "[person_pii]"
    return doc


def approve(conn: Connection, parse_run_id: str, *, reviewer_account_id: str | None = None) -> dict:
    run = conn.execute(text(
        """SELECT r.parse_run_id::text, r.status, r.raw_output, r.model_version, r.prompt_version,
                  r.rule_version, s.source_submission_id::text AS sub_id, s.external_submission_id,
                  s.source_type, s.permitted_use, s.legal_basis, s.loaded_person_id::text
           FROM parse_run r JOIN source_submission s USING (source_submission_id)
           WHERE r.parse_run_id = CAST(:r AS uuid) FOR UPDATE OF r, s"""),
        {"r": parse_run_id}).first()
    if run is None:
        raise IngestError("parse run not found")
    if run.status == "LOADED":
        return {"person_id": run.loaded_person_id, "loaded": False}
    if run.status not in ("NEEDS_REVIEW", "READY"):
        raise IngestError(f"parse run is {run.status}")
    fields = conn.execute(text(
        """SELECT entity_type, local_id, field_name, normalized_value, normalized_ref::text,
                  review_status, corrected_value, source_asset_id::text, evidence_text
           FROM extraction_field WHERE parse_run_id = CAST(:r AS uuid)"""), {"r": parse_run_id}).all()
    pending = [f"{f.entity_type}:{f.local_id}:{f.field_name}" for f in fields
               if f.review_status == "PENDING"]
    if pending:
        raise IngestError(f"{len(pending)} field(s) still need review: {pending[:10]}")

    by: dict[tuple[str, str], dict] = {}
    for f in fields:
        by.setdefault((f.entity_type, f.local_id), {})[f.field_name] = f

    # Resolve and check everything before writing anything.
    educations, events = [], []
    for (entity, lid), fs in sorted(by.items()):
        if entity == "EDUCATION":
            inst, major = _resolved(conn, "INSTITUTION", fs["institution"]), _resolved(
                conn, "MAJOR", fs["major"])
            if not inst[0] and not major[0]:
                continue
            start, sp = _date(_final(fs["start"])[0])
            end, ep = _date(_final(fs["end"])[0])
            if start and end and end.year < start.year:
                raise IngestError(f"education {lid}: graduation before admission after review")
            educations.append((fs, inst, major, _final(fs["degree_type"])[0], start, sp, end, ep))
        elif entity == "WORK_EVENT":
            org, role = _resolved(conn, "ORGANIZATION", fs["organization"]), _resolved(
                conn, "ROLE", fs["role"])
            if not org[0] and not role[0]:
                continue  # both names rejected: nothing left to load
            start, sp = _date(_final(fs["start"])[0])
            end, ep = _date(_final(fs["end"])[0])
            cur = _final(fs["is_current"])[0]
            is_current = None if cur is None else cur == "true"
            if start and end and end < start:
                raise IngestError(f"work event {lid}: end before start after review")
            if is_current and end:
                raise IngestError(f"work event {lid}: current job with an end date after review")
            events.append((fs, org, role, _final(fs["event_type"])[0],
                           _final(fs["employment_type"])[0], start, sp, end, ep, is_current))

    source_id = conn.execute(text(
        """INSERT INTO source_record (source_type, data_layer, source_system, source_key,
               raw_payload, metadata, legal_basis)
           VALUES (:t, 'SEED', :sys, :k, CAST(:raw AS jsonb), CAST(:meta AS jsonb), :l)
           RETURNING source_id::text"""),
        {"t": run.source_type, "sys": SOURCE_SYSTEM, "k": f"{run.external_submission_id}:{parse_run_id}",
         "raw": json.dumps(_redacted(run.raw_output), ensure_ascii=False), "l": run.legal_basis,
         "meta": json.dumps({"permitted_use": run.permitted_use, "model_version": run.model_version,
                             "prompt_version": run.prompt_version, "rule_version": run.rule_version,
                             "parse_run_id": parse_run_id, "pii_redacted": True})}).scalar_one()
    person_id = conn.execute(text(
        """INSERT INTO person (origin_layer, primary_source_id) VALUES ('SEED', :s)
           RETURNING person_id::text"""), {"s": source_id}).scalar_one()
    name = by.get(("PERSON", "person"), {}).get("display_name")
    if name and _final(name)[0]:
        conn.execute(text("INSERT INTO person_pii (person_id, display_name) VALUES (:p, :n)"),
                     {"p": person_id, "n": _final(name)[0]})

    out = {"person_id": person_id, "source_id": source_id, "education_ids": [],
           "work_event_ids": [], "loaded": True}
    for fs, inst, major, degree, start, sp, end, ep in educations:
        eid = conn.execute(text(
            """INSERT INTO education (person_id, institution_raw, institution_id, major_raw,
                   major_taxonomy_node_id, degree_type, admission_year, admission_date_precision,
                   graduation_year, graduation_date_precision, data_layer, verification_level,
                   normalization_status)
               VALUES (:p, :ir, CAST(:iid AS uuid), :mr, CAST(:mid AS uuid), :deg, :ay, :ap, :gy,
                       :gp, 'SEED', 'UNVERIFIED', :ns) RETURNING education_id::text"""),
            {"p": person_id, "ir": inst[0], "iid": inst[1], "mr": major[0], "mid": major[1],
             "deg": degree, "ay": start and start.year, "ap": sp, "gy": end and end.year, "gp": ep,
             "ns": _mapping_status(inst, major)}).scalar_one()
        supported = [n for n, v in (("institution", inst[0]), ("major", major[0]),
                                    ("degree_type", degree), ("admission_year", start),
                                    ("graduation_year", end)) if v]
        conn.execute(text(
            """INSERT INTO education_source (education_id, source_id, supported_fields, is_primary,
                   source_asset_id, evidence_text)
               VALUES (:e, :s, :f, true, CAST(:a AS uuid), :t)"""),
            {"e": eid, "s": source_id, "f": supported, "a": fs["institution"].source_asset_id,
             "t": fs["institution"].evidence_text})
        out["education_ids"].append(eid)
    for fs, org, role, event_type, emp, start, sp, end, ep, is_current in events:
        # A job nobody could classify loads as OTHER: kept, but outside employment statistics.
        weid = conn.execute(text(
            """INSERT INTO work_event (person_id, event_type, organization_raw, organization_id,
                   role_raw, role_taxonomy_node_id, employment_type, start_date,
                   start_date_precision, end_date, end_date_precision, is_current, data_layer,
                   verification_level, normalization_status)
               VALUES (:p, :t, :or, CAST(:oid AS uuid), :rr, CAST(:rid AS uuid), :emp, :sd, :sp,
                       :ed, :ep, :cur, 'SEED', 'UNVERIFIED', :ns)
               RETURNING work_event_id::text"""),
            {"p": person_id, "t": event_type or "OTHER", "or": org[0], "oid": org[1],
             "rr": role[0], "rid": role[1], "emp": emp, "sd": start, "sp": sp, "ed": end,
             "ep": ep, "cur": is_current, "ns": _mapping_status(org, role)}).scalar_one()
        supported = [n for n, v in (("organization", org[0]), ("role", role[0]),
                                    ("event_type", event_type), ("start_date", start),
                                    ("end_date", end), ("is_current", is_current)) if v is not None]
        conn.execute(text(
            """INSERT INTO work_event_source (work_event_id, source_id, supported_fields,
                   is_primary, source_asset_id, evidence_text)
               VALUES (:w, :s, :f, true, CAST(:a AS uuid), :t)"""),
            {"w": weid, "s": source_id, "f": supported, "a": fs["organization"].source_asset_id,
             "t": fs["organization"].evidence_text})
        out["work_event_ids"].append(weid)

    conn.execute(text(
        """UPDATE parse_run SET status = 'LOADED', reviewed_by = CAST(:a AS uuid), reviewed_at = now()
           WHERE parse_run_id = CAST(:r AS uuid)"""), {"r": parse_run_id, "a": reviewer_account_id})
    conn.execute(text(
        """UPDATE source_submission SET status = 'LOADED', loaded_person_id = :p, source_id = :s
           WHERE source_submission_id = CAST(:sub AS uuid)"""),
        {"p": person_id, "s": source_id, "sub": run.sub_id})
    out["identity_candidates"] = _identity_candidates(conn, person_id)
    return out


def _identity_candidates(conn: Connection, person_id: str) -> int:
    """Same name and same first organisation as an existing non-PRE_SEED person -> candidate pair
    for a human. Never merged automatically."""
    return conn.execute(text(
        """WITH me AS (
               SELECT normalize_label(pp.display_name) AS n,
                      (SELECT normalize_label(w.organization_raw) FROM work_event w
                        WHERE w.person_id = :p ORDER BY w.start_date NULLS LAST LIMIT 1) AS o
               FROM person_pii pp WHERE pp.person_id = :p)
           INSERT INTO identity_match (candidate_person_id, target_person_id, evidence, confidence)
           SELECT CAST(:p AS uuid), other.person_id,
                  jsonb_build_object('rule', 'name+first_org', 'rule_version', CAST(:rv AS text)), 0.6
           FROM me JOIN person_pii opp ON normalize_label(opp.display_name) = me.n
           JOIN person other ON other.person_id = opp.person_id
           WHERE other.person_id <> :p AND other.origin_layer <> 'PRE_SEED' AND me.n <> ''
             AND me.o IS NOT NULL
             AND me.o = (SELECT normalize_label(w.organization_raw) FROM work_event w
                         WHERE w.person_id = other.person_id ORDER BY w.start_date NULLS LAST LIMIT 1)
           ON CONFLICT DO NOTHING"""),
        {"p": person_id, "rv": RULE_VERSION}).rowcount


# --- standardisation --------------------------------------------------------------------------

def resolve_mapping(conn: Connection, mapping_queue_id: str, *, resolved_ref: str | None = None,
                    new_name: str | None = None, reviewer_account_id: str | None = None) -> dict:
    """Map a queued raw name to an existing canonical entry (resolved_ref) or a new one (new_name,
    organisations and institutions only). Adds the alias so the next submission maps on its own,
    and fills the canonical id on already-loaded rows that carry this raw name."""
    q = conn.execute(text(
        """SELECT entity_kind, raw_value, normalized_key, status FROM mapping_queue
           WHERE mapping_queue_id = CAST(:i AS uuid) FOR UPDATE"""), {"i": mapping_queue_id}).first()
    if q is None:
        raise IngestError("mapping not found")
    if q.status != "PENDING":
        raise IngestError(f"mapping is already {q.status}")
    if (resolved_ref is None) == (new_name is None):
        raise IngestError("give exactly one of resolved_ref or new_name")
    status = "APPROVED"
    if new_name is not None:
        if q.entity_kind not in ("ORGANIZATION", "INSTITUTION"):
            raise IngestError("new entries are only created for organizations and institutions")
        table = q.entity_kind.lower()
        tv = conn.execute(text(
            """INSERT INTO taxonomy_version (taxonomy, version, description)
               VALUES (:t, 'ingest', 'Created from the ingestion mapping queue')
               ON CONFLICT (taxonomy, version) DO UPDATE SET description = EXCLUDED.description
               RETURNING taxonomy_version_id"""), {"t": q.entity_kind}).scalar_one()
        resolved_ref = conn.execute(text(
            f"""INSERT INTO {table} (name, taxonomy_version_id) VALUES (:n, :tv)
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING {table}_id::text"""), {"n": new_name.strip(), "tv": tv}).scalar_one()
        status = "NEW_ENTITY"
    elif q.entity_kind in ("ORGANIZATION", "INSTITUTION"):
        table = q.entity_kind.lower()
        if not conn.execute(text(f"SELECT 1 FROM {table} WHERE {table}_id = CAST(:r AS uuid)"),
                            {"r": resolved_ref}).first():
            raise IngestError(f"{resolved_ref} is not an existing {table}")
    if q.entity_kind in ("ROLE", "MAJOR"):
        ok = conn.execute(text(
            """SELECT 1 FROM taxonomy_node n JOIN taxonomy t USING (taxonomy_id)
               WHERE n.taxonomy_node_id = CAST(:r AS uuid) AND t.taxonomy_type = :k"""),
            {"r": resolved_ref, "k": q.entity_kind}).first()
        if not ok:
            raise IngestError(f"{resolved_ref} is not a {q.entity_kind} node")
        conn.execute(text(
            """INSERT INTO taxonomy_alias (taxonomy_node_id, alias_text, source_type)
               VALUES (CAST(:r AS uuid), :a, 'MAPPING_QUEUE') ON CONFLICT DO NOTHING"""),
            {"r": resolved_ref, "a": q.raw_value})
    elif q.entity_kind == "ORGANIZATION":
        conn.execute(text(
            """INSERT INTO organization_alias (organization_id, alias_text, source_type)
               VALUES (CAST(:r AS uuid), :a, 'MAPPING_QUEUE') ON CONFLICT DO NOTHING"""),
            {"r": resolved_ref, "a": q.raw_value})
    conn.execute(text(
        """UPDATE mapping_queue SET status = :s, resolved_ref = CAST(:r AS uuid),
               reviewer_account_id = CAST(:a AS uuid), resolved_at = now()
           WHERE mapping_queue_id = CAST(:i AS uuid)"""),
        {"s": status, "r": resolved_ref, "a": reviewer_account_id, "i": mapping_queue_id})
    # Fill the canonical id where the raw name matches; the raw text itself is left as it is.
    table, col, raw_col, other_raw, other_col = {
        "ORGANIZATION": ("work_event", "organization_id", "organization_raw", "role_raw",
                         "role_taxonomy_node_id"),
        "ROLE": ("work_event", "role_taxonomy_node_id", "role_raw", "organization_raw",
                 "organization_id"),
        "MAJOR": ("education", "major_taxonomy_node_id", "major_raw", "institution_raw",
                  "institution_id"),
        "INSTITUTION": ("education", "institution_id", "institution_raw", "major_raw",
                        "major_taxonomy_node_id"),
    }[q.entity_kind]
    filled = conn.execute(text(
        f"""UPDATE {table} SET {col} = CAST(:r AS uuid),
                normalization_status = CASE WHEN {other_raw} IS NULL OR {other_col} IS NOT NULL
                                            THEN 'MAPPED' ELSE 'PARTIAL' END
            WHERE {col} IS NULL AND normalize_label({raw_col}) = :k
              AND data_layer IN ('SEED','VERIFIED')"""),
        {"r": resolved_ref, "k": q.normalized_key}).rowcount
    return {"status": status, "resolved_ref": resolved_ref, "rows_filled": filled}
