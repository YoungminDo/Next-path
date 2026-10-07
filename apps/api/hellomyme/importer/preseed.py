"""PRE_SEED package import (CSV package up to v1.2, workbook from v1.3: see workbook.py).

schema mapping -> validation -> normalization -> deduplication -> import -> integrity check
-> report. The importer never generates or repairs data: rows that break a rule are rejected
(or flagged) and kept in import_issue with their raw content.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from pathlib import Path

from sqlalchemy import Connection, Engine, text

DATASET_NAME = "HELLOMYME_PRESEED"
# Identifiers such as PSP00001 are only unique within one dataset version (v1.1 and v1.2 reuse
# them for different generated people), so the source system is versioned.
SOURCE_SYSTEM_PREFIX = "PRESEED"
VALIDATION_RULE_VERSION = "preseed_validation_v1"
NAMESPACE = uuid.UUID("6f1c4a52-6c55-4d8e-9a0e-3a54b8f3c001")

FILES = (
    "institutions", "majors", "roles", "organizations",
    "persons", "educations", "work_events", "work_event_sources",
)
EVENT_TYPES = {
    "EMPLOYMENT", "STARTUP", "SIDE_BUSINESS", "SELF_EMPLOYED", "FREELANCE", "STUDY",
    "CAREER_BREAK", "MILITARY", "PROJECT", "OTHER",
}
STAGES = {"STUDENT", "JOB_SEEKER", "PROFESSIONAL"}
SIZE_BANDS = {"MICRO", "SMALL", "MID", "LARGE", "ENTERPRISE"}
# Source column name -> canonical evidence field name.
WORK_FIELD_MAP = {
    "organization_id": "organization", "role_id": "role", "event_type": "event_type",
    "start_date": "start_date", "end_date": "end_date", "is_current": "is_current",
}
# Rules that make the whole package untrustworthy: abort instead of importing the rest.
CRITICAL_RULES = {
    "DUPLICATE_ID", "ORPHAN_PERSON", "ORPHAN_INSTITUTION", "ORPHAN_MAJOR",
    "ORPHAN_ORGANIZATION", "ORPHAN_ROLE", "ORPHAN_WORK_EVENT", "DATA_LAYER_MISMATCH",
    "SOURCE_TYPE_MISMATCH", "TAXONOMY_INVALID", "TAXONOMY_NODE_INVALID", "ORPHAN_TAXONOMY_NODE",
    "TAXONOMY_NODE_TYPE_MISMATCH", "RAW_NAME_NODE_CONFLICT",
}
TAXONOMY_TYPES = {"ROLE", "MAJOR", "INDUSTRY"}
GENDER_CODES = {"MALE", "FEMALE", "OTHER", "UNDISCLOSED", "UNKNOWN"}
PRECISIONS = {"DAY", "MONTH", "YEAR"}
# Organizations that stand for a category rather than a real employer.
PLACEHOLDER_ORG = re.compile(r"^(.+ [A-Z]|창업/자영업)$")
FOUNDER_ROLE_NAMES = {"창업자"}
FREELANCER_ROLE_NAMES = {"프리랜서"}


class ImportAborted(Exception):
    def __init__(self, report: dict):
        super().__init__("pre-seed import aborted by critical validation failures")
        self.report = report


def source_system(dataset_version: str) -> str:
    return f"{SOURCE_SYSTEM_PREFIX}_{dataset_version}"


def stable_id(system: str, entity_type: str, key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{system}:{entity_type}:{key}")


@dataclass
class Issue:
    severity: str
    entity_type: str
    source_key: str | None
    row_number: int | None
    rule_code: str
    detail: dict = field(default_factory=dict)
    raw_row: dict | None = None


@dataclass
class Package:
    rows: dict[str, list[dict]]
    manifest: dict[str, str]

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.manifest, sort_keys=True).encode()).hexdigest()


def load_package(csv_dir: str | Path) -> Package:
    csv_dir = Path(csv_dir)
    rows, manifest = {}, {}
    for name in FILES:
        path = csv_dir / f"{name}.csv"
        if not path.exists():
            raise FileNotFoundError(f"missing {path.name} in {csv_dir}")
        data = path.read_bytes()
        manifest[path.name] = hashlib.sha256(data).hexdigest()
        reader = csv.DictReader(data.decode("utf-8-sig").splitlines())
        rows[name] = [{k: (v.strip() if v is not None else "") for k, v in r.items()}
                      for r in reader]
    return Package(rows=rows, manifest=manifest)


def _parse_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_bool(value: str) -> bool | None:
    if value == "":
        return None
    if value.lower() in ("true", "1"):
        return True
    if value.lower() in ("false", "0"):
        return False
    raise ValueError(value)


@dataclass
class Validated:
    taxonomy: dict[str, dict[str, dict]]
    persons: list[dict]
    educations: list[dict]
    work_events: list[dict]
    sources: list[dict]
    issues: list[Issue]
    staged_counts: dict[str, int]
    # v1.3+ workbook only: taxonomy_id -> row, node code -> row, org industry rows.
    taxonomies: dict[str, dict] = field(default_factory=dict)
    nodes: dict[str, dict] = field(default_factory=dict)
    org_industries: list[dict] = field(default_factory=list)

    def rejects(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "REJECT"]

    def critical(self) -> list[Issue]:
        return [i for i in self.rejects() if i.rule_code in CRITICAL_RULES]


def validate(pkg: Package, as_of: date, data_layer: str = "PRE_SEED",
             source_type: str = "PRE_SEED_FILE") -> Validated:
    issues: list[Issue] = []

    def issue(sev, entity, key, n, rule, row=None, **detail):
        issues.append(Issue(sev, entity, key, n, rule, detail, row))

    def unique_rows(name: str, id_col: str) -> dict[str, tuple[int, dict]]:
        seen: dict[str, tuple[int, dict]] = {}
        dup: set[str] = set()
        for n, row in enumerate(pkg.rows[name], start=2):  # header is line 1
            key = row.get(id_col, "")
            if not key:
                issue("REJECT", name, None, n, "MISSING_ID", row)
            elif key in seen:
                dup.add(key)
                issue("REJECT", name, key, n, "DUPLICATE_ID", row)
            else:
                seen[key] = (n, row)
        for key in dup:
            seen.pop(key)
        return seen

    taxonomy: dict[str, dict[str, dict]] = {}
    for name, id_col, required in (
        ("institutions", "institution_id", ("institution_name",)),
        ("majors", "major_id", ("major_name",)),
        ("roles", "role_id", ("role_name", "job_family")),
        ("organizations", "organization_id", ("organization_name",)),
    ):
        entries = {}
        for key, (n, row) in unique_rows(name, id_col).items():
            if any(not row.get(c) for c in required):
                issue("REJECT", name, key, n, "TAXONOMY_INVALID", row, missing=list(required))
            elif name == "organizations" and row.get("company_size_band") not in SIZE_BANDS | {""}:
                issue("REJECT", name, key, n, "TAXONOMY_INVALID", row,
                      company_size_band=row.get("company_size_band"))
            else:
                entries[key] = row
        taxonomy[name] = entries

    def check_layer(entity, key, n, row) -> bool:
        ok = True
        if row.get("data_layer") != data_layer:
            issue("REJECT", entity, key, n, "DATA_LAYER_MISMATCH", row,
                  expected=data_layer, actual=row.get("data_layer"))
            ok = False
        if row.get("source_type") != source_type:
            issue("REJECT", entity, key, n, "SOURCE_TYPE_MISMATCH", row,
                  expected=source_type, actual=row.get("source_type"))
            ok = False
        return ok

    taxonomies, nodes, node_type = _validate_taxonomy_nodes(pkg, issue)

    def check_node(entity, key, n, row, col, expected_type) -> bool:
        code = row.get(col, "")
        if not code:
            return True
        if code not in nodes:
            issue("REJECT", entity, key, n, "ORPHAN_TAXONOMY_NODE", row, column=col, node=code)
            return False
        if node_type[code] != expected_type:
            issue("REJECT", entity, key, n, "TAXONOMY_NODE_TYPE_MISMATCH", row, column=col,
                  node=code, expected=expected_type, actual=node_type[code])
            return False
        return True

    def check_precision(entity, key, n, row, *cols) -> bool:
        bad = [c for c in cols if row.get(c, "") not in PRECISIONS | {""}]
        if bad:
            issue("REJECT", entity, key, n, "PRECISION_INVALID", row, columns=bad)
        return not bad

    # The same raw text must not point at two different nodes (the dictionary is keyed by it).
    for entity, raw_col, node_col in (("educations", "raw_major_name", "major_taxonomy_node_id"),
                                      ("work_events", "raw_role_title", "role_taxonomy_node_id")):
        seen_nodes: dict[str, set[str]] = defaultdict(set)
        for row in pkg.rows[entity]:
            if row.get(raw_col) and row.get(node_col):
                seen_nodes[row[raw_col]].add(row[node_col])
        for raw_name, codes in seen_nodes.items():
            if len(codes) > 1:
                issue("REJECT", entity, raw_name, None, "RAW_NAME_NODE_CONFLICT",
                      nodes=sorted(codes))

    all_person_ids = {r.get("person_id") for r in pkg.rows["persons"]}
    persons: dict[str, dict] = {}
    for key, (n, row) in unique_rows("persons", "person_id").items():
        if not check_layer("persons", key, n, row):
            continue
        if row.get("user_stage") and row["user_stage"] not in STAGES:
            issue("REJECT", "persons", key, n, "STAGE_INVALID", row)
            continue
        if row.get("gender_code", "") not in GENDER_CODES | {""}:
            issue("REJECT", "persons", key, n, "GENDER_INVALID", row)
            continue
        persons[key] = row

    educations = []
    for key, (n, row) in unique_rows("educations", "education_id").items():
        if not check_layer("educations", key, n, row):
            continue
        if row["person_id"] not in persons:
            rule = "PARENT_REJECTED" if row["person_id"] in all_person_ids else "ORPHAN_PERSON"
            issue("REJECT", "educations", key, n, rule, row)
            continue
        if row.get("institution_id") and row["institution_id"] not in taxonomy["institutions"]:
            issue("REJECT", "educations", key, n, "ORPHAN_INSTITUTION", row)
            continue
        if row.get("major_id") and row["major_id"] not in taxonomy["majors"]:
            issue("REJECT", "educations", key, n, "ORPHAN_MAJOR", row)
            continue
        gy = row.get("graduation_year", "")
        if gy and not (gy.isdigit() and 1950 <= int(gy) <= 2100):
            issue("REJECT", "educations", key, n, "GRADUATION_YEAR_INVALID", row)
            continue
        ay = row.get("admission_year", "")
        if ay and not (ay.isdigit() and 1950 <= int(ay) <= 2100):
            issue("REJECT", "educations", key, n, "ADMISSION_YEAR_INVALID", row)
            continue
        if ay and gy and int(ay) > int(gy):
            issue("REJECT", "educations", key, n, "ADMISSION_AFTER_GRADUATION", row)
            continue
        if not check_node("educations", key, n, row, "major_taxonomy_node_id", "MAJOR"):
            continue
        if not check_precision("educations", key, n, row, "admission_precision",
                               "graduation_precision"):
            continue
        educations.append({**row, "_row": n})

    roles = taxonomy["roles"]
    work_events = []
    current_by_person: dict[str, list[dict]] = defaultdict(list)
    for key, (n, row) in unique_rows("work_events", "work_event_id").items():
        if not check_layer("work_events", key, n, row):
            continue
        if row["person_id"] not in persons:
            rule = "PARENT_REJECTED" if row["person_id"] in all_person_ids else "ORPHAN_PERSON"
            issue("REJECT", "work_events", key, n, rule, row)
            continue
        if row.get("organization_id") and row["organization_id"] not in taxonomy["organizations"]:
            issue("REJECT", "work_events", key, n, "ORPHAN_ORGANIZATION", row)
            continue
        if row.get("role_id") and row["role_id"] not in roles:
            issue("REJECT", "work_events", key, n, "ORPHAN_ROLE", row)
            continue
        if row.get("event_type") not in EVENT_TYPES:
            issue("REJECT", "work_events", key, n, "EVENT_TYPE_INVALID", row)
            continue
        if not check_node("work_events", key, n, row, "role_taxonomy_node_id", "ROLE"):
            continue
        if not check_precision("work_events", key, n, row, "start_precision", "end_precision"):
            continue
        try:
            start, end = _parse_date(row["start_date"]), _parse_date(row["end_date"])
            is_current = _parse_bool(row["is_current"])
        except ValueError as exc:
            issue("REJECT", "work_events", key, n, "VALUE_INVALID", row, error=str(exc))
            continue
        if start and end and end < start:
            issue("REJECT", "work_events", key, n, "END_BEFORE_START", row)
            continue
        if start and start > as_of:
            issue("REJECT", "work_events", key, n, "START_AFTER_AS_OF", row, as_of=str(as_of))
            continue
        if is_current and end:
            issue("REJECT", "work_events", key, n, "CURRENT_WITH_END_DATE", row)
            continue
        if end and end > as_of:
            issue("WARNING", "work_events", key, n, "END_AFTER_AS_OF", as_of=str(as_of))
        if is_current is False and end is None:
            issue("WARNING", "work_events", key, n, "ENDED_WITHOUT_END_DATE")
        role_name = roles.get(row.get("role_id"), {}).get("role_name")
        if role_name in FOUNDER_ROLE_NAMES and row["event_type"] != "STARTUP":
            issue("WARNING", "work_events", key, n, "FOUNDER_ROLE_NOT_STARTUP",
                  event_type=row["event_type"])
        if role_name in FREELANCER_ROLE_NAMES and row["event_type"] != "FREELANCE":
            issue("WARNING", "work_events", key, n, "FREELANCER_ROLE_NOT_FREELANCE",
                  event_type=row["event_type"])
        org = taxonomy["organizations"].get(row.get("organization_id"))
        if org and PLACEHOLDER_ORG.match(org["organization_name"]):
            issue("WARNING", "work_events", key, n, "PLACEHOLDER_ORGANIZATION",
                  organization=org["organization_name"])
        ev = {**row, "_row": n, "_start": start, "_end": end, "_is_current": is_current}
        work_events.append(ev)
        if is_current:
            current_by_person[row["person_id"]].append(ev)

    for pid, events in current_by_person.items():
        if persons[pid].get("user_stage") == "JOB_SEEKER" and any(
            e["event_type"] == "EMPLOYMENT" for e in events
        ):
            issue("WARNING", "persons", pid, None, "JOB_SEEKER_WITH_CURRENT_EMPLOYMENT")

    accepted_events = {e["work_event_id"]: e for e in work_events}
    all_event_ids = {r.get("work_event_id") for r in pkg.rows["work_events"]}
    sources = []
    sourced_events: Counter = Counter()
    for key, (n, row) in unique_rows("work_event_sources", "work_event_source_id").items():
        if row.get("source_type") != source_type:
            issue("REJECT", "work_event_sources", key, n, "SOURCE_TYPE_MISMATCH", row)
            continue
        ev = accepted_events.get(row["work_event_id"])
        if ev is None:
            rule = "PARENT_REJECTED" if row["work_event_id"] in all_event_ids else "ORPHAN_WORK_EVENT"
            issue("REJECT", "work_event_sources", key, n, rule, row)
            continue
        raw_fields = [f.strip() for f in row.get("supported_fields", "").split(",") if f.strip()]
        unknown = [f for f in raw_fields if f not in WORK_FIELD_MAP]
        if not raw_fields or unknown:
            issue("REJECT", "work_event_sources", key, n, "SUPPORTED_FIELDS_INVALID", row,
                  unknown=unknown)
            continue
        if row.get("source_ref") != ev.get("source_ref"):
            issue("WARNING", "work_event_sources", key, n, "SOURCE_REF_MISMATCH",
                  source_ref=row.get("source_ref"), event_source_ref=ev.get("source_ref"))
        try:
            conf = float(row["evidence_confidence"]) if row.get("evidence_confidence") else None
            primary = bool(_parse_bool(row.get("is_primary", "")))
        except ValueError as exc:
            issue("REJECT", "work_event_sources", key, n, "VALUE_INVALID", row, error=str(exc))
            continue
        sourced_events[row["work_event_id"]] += 1
        sources.append({**row, "_row": n, "_fields": [WORK_FIELD_MAP[f] for f in raw_fields],
                        "_confidence": conf, "_primary": primary})

    for eid, ev in accepted_events.items():
        if sourced_events[eid] == 0:
            issue("WARNING", "work_events", eid, ev["_row"], "NO_EVIDENCE_SOURCE")

    org_industries = []
    primary_orgs: Counter = Counter()
    for n, row in enumerate(pkg.rows.get("org_industries", []), start=2):
        key = row.get("organization_industry_id") or None
        if row.get("organization_id") not in taxonomy["organizations"]:
            issue("REJECT", "org_industries", key, n, "ORPHAN_ORGANIZATION", row)
            continue
        if not check_node("org_industries", key, n, row, "industry_taxonomy_node_id", "INDUSTRY"):
            continue
        try:
            primary = bool(_parse_bool(row.get("is_primary", "")))
        except ValueError as exc:
            issue("REJECT", "org_industries", key, n, "VALUE_INVALID", row, error=str(exc))
            continue
        if primary:
            primary_orgs[row["organization_id"]] += 1
            if primary_orgs[row["organization_id"]] > 1:
                issue("REJECT", "org_industries", key, n, "MULTIPLE_PRIMARY_INDUSTRY", row)
                continue
        org_industries.append({**row, "_primary": primary})

    return Validated(
        taxonomy=taxonomy,
        persons=[{**r, "_key": k} for k, r in persons.items()],
        educations=educations,
        work_events=work_events,
        sources=sources,
        issues=issues,
        staged_counts={name: len(rows) for name, rows in pkg.rows.items()},
        taxonomies=taxonomies,
        nodes=nodes,
        org_industries=org_industries,
    )


def _validate_taxonomy_nodes(pkg: Package, issue) -> tuple[dict, dict, dict]:
    """Taxonomy sheets are all-or-nothing: any broken node aborts the import (critical)."""
    taxonomies: dict[str, dict] = {}
    for n, row in enumerate(pkg.rows.get("taxonomies", []), start=2):
        if row.get("taxonomy_type") not in TAXONOMY_TYPES or not row.get("version"):
            issue("REJECT", "taxonomies", row.get("taxonomy_id"), n, "TAXONOMY_INVALID", row)
            continue
        taxonomies[row["taxonomy_id"]] = row
    # Node rows name their taxonomy either by sheet id (TAX_ROLE) or by type (ROLE).
    by_type = {t["taxonomy_type"]: t for t in taxonomies.values()}
    nodes: dict[str, dict] = {}
    node_type: dict[str, str] = {}
    for n, row in enumerate(pkg.rows.get("taxonomy_nodes", []), start=2):
        code = row.get("taxonomy_node_id", "")
        tax = taxonomies.get(row.get("taxonomy_id", "")) or by_type.get(row.get("taxonomy_id", ""))
        if not code or code in nodes or tax is None or not row.get("canonical_name"):
            issue("REJECT", "taxonomy_nodes", code or None, n, "TAXONOMY_NODE_INVALID", row)
            continue
        if row.get("status", "ACTIVE") not in {"DRAFT", "ACTIVE", "RETIRED"}:
            issue("REJECT", "taxonomy_nodes", code, n, "TAXONOMY_NODE_INVALID", row)
            continue
        nodes[code] = {**row, "_row": n, "_taxonomy_key": tax["taxonomy_id"]}
        node_type[code] = tax["taxonomy_type"]
    for code, row in nodes.items():
        parent = row.get("parent_node_id", "")
        expected_depth = 1
        if parent:
            if parent not in nodes or node_type[parent] != node_type[code]:
                issue("REJECT", "taxonomy_nodes", code, row["_row"], "TAXONOMY_NODE_INVALID", row,
                      parent=parent)
                continue
            expected_depth = int(nodes[parent].get("depth") or 0) + 1
        if row.get("depth") and int(row["depth"]) != expected_depth:
            issue("REJECT", "taxonomy_nodes", code, row["_row"], "TAXONOMY_NODE_INVALID", row,
                  depth=row["depth"], expected_depth=expected_depth)
    return taxonomies, nodes, node_type


def _report(v: Validated, imported: dict[str, int] | None, checks: dict | None) -> dict:
    by_rule = Counter((i.severity, i.entity_type, i.rule_code) for i in v.issues)
    rejected = Counter(i.entity_type for i in v.rejects())
    return {
        "staged": v.staged_counts,
        "accepted": {
            "persons": len(v.persons), "education_records": len(v.educations),
            "work_events": len(v.work_events), "work_event_sources": len(v.sources),
            "institutions": len(v.taxonomy["institutions"]), "majors": len(v.taxonomy["majors"]),
            "organizations": len(v.taxonomy["organizations"]), "roles": len(v.taxonomy["roles"]),
            "taxonomy_nodes": len(v.nodes), "organization_industries": len(v.org_industries),
        },
        "imported": imported,
        "rejected_records": dict(rejected),
        "rejected_total": sum(rejected.values()),
        "duplicate_records": sum(1 for i in v.issues if i.rule_code == "DUPLICATE_ID"),
        "normalization_warnings": sum(1 for i in v.issues if i.severity == "WARNING"),
        "issues_by_rule": [
            {"severity": s, "entity": e, "rule": r, "count": c}
            for (s, e, r), c in sorted(by_rule.items())
        ],
        "integrity_checks": checks,
    }


def load_any_package(path: str | Path) -> Package:
    if str(path).lower().endswith(".xlsx"):
        from hellomyme.importer.workbook import load_workbook_package
        return load_workbook_package(path)
    return load_package(path)


def run_import(engine: Engine, path: str | Path, *, as_of: date, dataset_version: str,
               date_precision: str = "MONTH") -> dict:
    pkg = load_any_package(path)
    with engine.begin() as conn:
        done = conn.execute(
            text("SELECT import_batch_id, report FROM import_batch "
                 "WHERE manifest_sha256 = :m AND status = 'COMPLETED'"),
            {"m": pkg.manifest_sha256},
        ).first()
    if done:
        return {"status": "ALREADY_IMPORTED", "import_batch_id": str(done.import_batch_id),
                "report": done.report}

    v = validate(pkg, as_of)
    if v.critical():
        raise ImportAborted({"status": "ABORTED", **_report(v, None, None),
                             "critical": [i.__dict__ for i in v.critical()[:50]]})

    with engine.begin() as conn:
        batch_id = conn.execute(
            text("""INSERT INTO import_batch (dataset_name, dataset_version, source_system,
                        source_type, data_layer, file_manifest, manifest_sha256,
                        validation_rule_version, status)
                    VALUES (:n, :v, :s, 'PRE_SEED_FILE', 'PRE_SEED', CAST(:fm AS jsonb), :m,
                            :rv, 'RUNNING') RETURNING import_batch_id"""),
            {"n": DATASET_NAME, "v": dataset_version, "s": source_system(dataset_version),
             "fm": json.dumps(pkg.manifest), "m": pkg.manifest_sha256,
             "rv": VALIDATION_RULE_VERSION},
        ).scalar_one()
    try:
        with engine.begin() as conn:
            imported = _write(conn, v, batch_id, dataset_version, date_precision)
            checks = _integrity_checks(conn, v, batch_id, source_system(dataset_version))
            failed = [k for k, c in checks.items() if not c["pass"]]
            if failed:
                raise RuntimeError(f"integrity checks failed: {failed}")
            report = {"status": "COMPLETED", "import_batch_id": str(batch_id),
                      **_report(v, imported, checks)}
            conn.execute(
                text("UPDATE import_batch SET status = 'COMPLETED', report = CAST(:r AS jsonb), "
                     "finished_at = now() WHERE import_batch_id = :b"),
                {"r": json.dumps(report, default=str), "b": batch_id},
            )
        return report
    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE import_batch SET status = 'FAILED', finished_at = now(), "
                     "report = CAST(:r AS jsonb) WHERE import_batch_id = :b"),
                {"r": json.dumps({"error": str(exc)}), "b": batch_id},
            )
        raise


def _taxonomy_version(conn: Connection, taxonomy: str, version: str) -> uuid.UUID:
    conn.execute(
        text("INSERT INTO taxonomy_version (taxonomy, version, description) VALUES (:t, :v, :d) "
             "ON CONFLICT (taxonomy, version) DO NOTHING"),
        {"t": taxonomy, "v": version, "d": "Imported from PRE_SEED package"},
    )
    return conn.execute(
        text("SELECT taxonomy_version_id FROM taxonomy_version WHERE taxonomy = :t AND version = :v"),
        {"t": taxonomy, "v": version},
    ).scalar_one()


def _map_keys(conn: Connection, system: str, entity_type: str,
              pairs: list[tuple[str, uuid.UUID]], batch_id: uuid.UUID) -> None:
    if pairs:
        conn.execute(
            text("INSERT INTO entity_key_map (source_system, entity_type, source_key, entity_id, "
                 "import_batch_id) VALUES (:s, :t, :k, :e, :b) ON CONFLICT DO NOTHING"),
            [{"s": system, "t": entity_type, "k": k, "e": e, "b": batch_id}
             for k, e in pairs],
        )


def _write(conn: Connection, v: Validated, batch_id, dataset_version: str,
           date_precision: str) -> dict[str, int]:
    system = source_system(dataset_version)
    key_id = partial(stable_id, system)
    tax_version = f"preseed_{dataset_version}"
    tax_ids: dict[str, dict[str, uuid.UUID]] = {}
    specs = {
        "institutions": ("INSTITUTION", "institution", "institution_name",
                         "INSERT INTO institution (name, region, institution_type, "
                         "taxonomy_version_id) VALUES (:name, :a, :b, :tv) "
                         "ON CONFLICT (name) DO NOTHING",
                         ("region", "institution_type")),
        "majors": ("MAJOR", "major", "major_name",
                   "INSERT INTO major (name, major_family, taxonomy_version_id) "
                   "VALUES (:name, :a, :tv) ON CONFLICT (name) DO NOTHING",
                   ("major_family", None)),
        "roles": ("ROLE", "role", "role_name",
                  "INSERT INTO role (name, job_family, taxonomy_version_id) "
                  "VALUES (:name, :a, :tv) ON CONFLICT (name) DO NOTHING",
                  ("job_family", None)),
        "organizations": ("ORGANIZATION", "organization", "organization_name",
                          "INSERT INTO organization (name, industry, company_size_band, "
                          "is_placeholder, taxonomy_version_id) VALUES (:name, :a, :b, :ph, :tv) "
                          "ON CONFLICT (name) DO NOTHING",
                          ("industry", "company_size_band")),
    }
    for name, (taxonomy, table, name_col, sql, (col_a, col_b)) in specs.items():
        tv = _taxonomy_version(conn, taxonomy, tax_version)
        rows = list(v.taxonomy[name].items())
        if rows:
            conn.execute(text(sql), [
                {"name": r[name_col], "a": r.get(col_a) or None,
                 "b": (r.get(col_b) or None) if col_b else None,
                 "ph": bool(PLACEHOLDER_ORG.match(r[name_col])), "tv": tv}
                for _, r in rows
            ])
        found = dict(conn.execute(
            text(f"SELECT name, {table}_id FROM {table} WHERE name = ANY(:names)"),
            {"names": [r[name_col] for _, r in rows]},
        ).all())
        tax_ids[name] = {k: found[r[name_col]] for k, r in rows}
        _map_keys(conn, system, table.upper(), list(tax_ids[name].items()), batch_id)

    node_ids = _write_taxonomy_nodes(conn, v)

    edu_by_person = defaultdict(list)
    for e in v.educations:
        edu_by_person[e["person_id"]].append(e)
    ev_by_person = defaultdict(list)
    for e in v.work_events:
        ev_by_person[e["person_id"]].append(e)
    src_by_event = defaultdict(list)
    for s in v.sources:
        src_by_event[s["work_event_id"]].append(s)

    def strip(row: dict) -> dict:
        return {k: val for k, val in row.items() if not k.startswith("_")}

    # One immutable SOURCE_RECORD per pre-seed source_ref (person-level), raw rows preserved.
    source_ids: dict[str, uuid.UUID] = {}
    source_rows = []
    for p in v.persons:
        ref = p.get("source_ref") or f"{p['_key']}"
        sid = key_id("source_record", ref)
        source_ids[ref] = sid
        events = ev_by_person[p["_key"]]
        source_rows.append({
            "id": sid, "key": ref, "b": batch_id, "sys": system,
            "raw": json.dumps({
                "person": strip(p),
                "educations": [strip(e) for e in edu_by_person[p["_key"]]],
                "work_events": [strip(e) for e in events],
                "work_event_sources": [strip(s) for e in events
                                       for s in src_by_event[e["work_event_id"]]],
            }, ensure_ascii=False),
            "meta": json.dumps({"dataset_version": dataset_version}),
        })
    _insert(conn, """INSERT INTO source_record (source_id, source_type, data_layer, source_system,
                        source_key, import_batch_id, raw_payload, metadata, legal_basis)
                     VALUES (:id, 'PRE_SEED_FILE', 'PRE_SEED', :sys, :key, :b,
                             CAST(:raw AS jsonb), CAST(:meta AS jsonb), 'GENERATED_DATASET')
                     ON CONFLICT (source_system, source_key) DO NOTHING""", source_rows)

    person_rows = [{"id": key_id("person", p["_key"]), "stage": p.get("user_stage") or None,
                    "src": source_ids[p.get("source_ref") or p["_key"]],
                    "g": p.get("gender_code") or "UNKNOWN"} for p in v.persons]
    n_persons = _insert(conn, """INSERT INTO person (person_id, origin_layer, declared_stage,
                                    primary_source_id, gender_code, gender_source_id)
                                 VALUES (:id, 'PRE_SEED', :stage, :src, :g,
                                         CASE WHEN :g = 'UNKNOWN' THEN NULL ELSE :src END)
                                 ON CONFLICT (person_id) DO NOTHING""", person_rows)
    _map_keys(conn, system, "PERSON", [(p["_key"], key_id("person", p["_key"])) for p in v.persons],
              batch_id)

    inst_names = {k: r["institution_name"] for k, r in v.taxonomy["institutions"].items()}
    major_names = {k: r["major_name"] for k, r in v.taxonomy["majors"].items()}
    edu_rows = [{
        "id": key_id("education", e["education_id"]),
        "pid": key_id("person", e["person_id"]),
        "iraw": inst_names.get(e["institution_id"]), "iid": tax_ids["institutions"].get(
            e["institution_id"]),
        "mraw": major_names.get(e["major_id"]), "mid": tax_ids["majors"].get(e["major_id"]),
        "deg": e.get("degree_type") or None,
        "gy": int(e["graduation_year"]) if e.get("graduation_year") else None,
        "ay": int(e["admission_year"]) if e.get("admission_year") else None,
        "ap": e.get("admission_precision") or None, "gp": e.get("graduation_precision") or None,
        "mnode": node_ids.get(e.get("major_taxonomy_node_id", "")),
    } for e in v.educations]
    n_edu = _insert(conn, """INSERT INTO education (education_id, person_id, institution_raw,
                                institution_id, major_raw, major_id, degree_type, graduation_year,
                                admission_year, admission_date_precision,
                                graduation_date_precision, major_taxonomy_node_id,
                                data_layer, verification_level, normalization_status,
                                normalization_confidence)
                             VALUES (:id, :pid, :iraw, :iid, :mraw, :mid, :deg, :gy, :ay, :ap, :gp,
                                     :mnode, 'PRE_SEED', 'UNVERIFIED', 'MAPPED', 1.0)
                             ON CONFLICT (education_id) DO NOTHING""", edu_rows)
    _insert(conn, """INSERT INTO education_source (education_source_id, education_id, source_id,
                        supported_fields, is_primary)
                     VALUES (:id, :eid, :sid, :fields, true)
                     ON CONFLICT (education_id, source_id) DO NOTHING""", [{
        "id": key_id("education_source", e["education_id"]),
        "eid": key_id("education", e["education_id"]),
        "sid": source_ids[e.get("source_ref") or e["person_id"]],
        "fields": [f for f, col in (("institution", "institution_id"), ("major", "major_id"),
                                    ("degree_type", "degree_type"),
                                    ("admission_year", "admission_year"),
                                    ("graduation_year", "graduation_year")) if e.get(col)],
    } for e in v.educations])
    _map_keys(conn, system, "EDUCATION", [(e["education_id"], key_id("education", e["education_id"]))
                                  for e in v.educations], batch_id)

    org_names = {k: r["organization_name"] for k, r in v.taxonomy["organizations"].items()}
    role_names = {k: r["role_name"] for k, r in v.taxonomy["roles"].items()}
    we_rows = [{
        "id": key_id("work_event", e["work_event_id"]),
        "pid": key_id("person", e["person_id"]),
        "type": e["event_type"],
        "oraw": org_names.get(e["organization_id"]),
        "oid": tax_ids["organizations"].get(e["organization_id"]),
        "rraw": role_names.get(e["role_id"]), "rid": tax_ids["roles"].get(e["role_id"]),
        "sd": e["_start"],
        "sp": (e.get("start_precision") or date_precision) if e["_start"] else None,
        "ed": e["_end"],
        "ep": (e.get("end_precision") or date_precision) if e["_end"] else None,
        "cur": e["_is_current"],
        "rnode": node_ids.get(e.get("role_taxonomy_node_id", "")),
    } for e in v.work_events]
    # employment_type stays NULL: the package does not say whether a job was an internship.
    n_we = _insert(conn, """INSERT INTO work_event (work_event_id, person_id, event_type,
                               organization_raw, organization_id, role_raw, role_id, start_date,
                               start_date_precision, end_date, end_date_precision, is_current,
                               role_taxonomy_node_id, data_layer, verification_level,
                               normalization_status, normalization_confidence)
                            VALUES (:id, :pid, :type, :oraw, :oid, :rraw, :rid, :sd, :sp, :ed,
                                    :ep, :cur, :rnode, 'PRE_SEED', 'UNVERIFIED', 'MAPPED', 1.0)
                            ON CONFLICT (work_event_id) DO NOTHING""", we_rows)
    _map_keys(conn, system, "WORK_EVENT", [(e["work_event_id"], key_id("work_event", e["work_event_id"]))
                                   for e in v.work_events], batch_id)

    wes_rows = [{
        "id": key_id("work_event_source", s["work_event_source_id"]),
        "weid": key_id("work_event", s["work_event_id"]),
        "sid": source_ids.get(s["source_ref"]) or key_id("source_record", s["source_ref"]),
        "fields": s["_fields"], "conf": s["_confidence"], "prim": s["_primary"],
    } for s in v.sources]
    n_wes = _insert(conn, """INSERT INTO work_event_source (work_event_source_id, work_event_id,
                                source_id, supported_fields, evidence_confidence, is_primary)
                             VALUES (:id, :weid, :sid, :fields, :conf, :prim)
                             ON CONFLICT (work_event_id, source_id) DO NOTHING""", wes_rows)
    _map_keys(conn, system, "WORK_EVENT_SOURCE",
              [(s["work_event_source_id"], key_id("work_event_source", s["work_event_source_id"]))
               for s in v.sources], batch_id)

    oi_rows = [{
        "oid": tax_ids["organizations"][r["organization_id"]],
        "node": node_ids[r["industry_taxonomy_node_id"]], "prim": r["_primary"],
    } for r in v.org_industries]
    # The workbook gives no per-organization source record, so source_id stays NULL.
    n_oi = _insert(conn, """INSERT INTO organization_industry (organization_id, taxonomy_node_id,
                               is_primary)
                            SELECT :oid, :node, :prim
                            WHERE NOT EXISTS (SELECT 1 FROM organization_industry
                                              WHERE organization_id = :oid
                                                AND taxonomy_node_id = :node
                                                AND valid_from IS NULL)
                            ON CONFLICT DO NOTHING""", oi_rows)

    issue_rows = [{
        "b": batch_id, "sev": i.severity, "ent": i.entity_type, "key": i.source_key,
        "n": i.row_number, "rule": i.rule_code, "detail": json.dumps(i.detail, default=str),
        "raw": json.dumps(i.raw_row, ensure_ascii=False) if i.raw_row else None,
    } for i in v.issues]
    _insert(conn, """INSERT INTO import_issue (import_batch_id, severity, entity_type, source_key,
                        row_number, rule_code, detail, raw_row)
                     VALUES (:b, :sev, :ent, :key, :n, :rule, CAST(:detail AS jsonb),
                             CAST(:raw AS jsonb))""", issue_rows)

    return {"persons": n_persons, "education_records": n_edu, "work_events": n_we,
            "work_event_sources": n_wes, "source_records": len(source_rows),
            "taxonomy_nodes": len(node_ids), "organization_industries": n_oi}


def _write_taxonomy_nodes(conn: Connection, v: Validated) -> dict[str, uuid.UUID]:
    """Create taxonomy versions and nodes (parents first) plus raw-text aliases.

    Existing nodes are reused, never modified: a changed structure needs a new taxonomy version.
    """
    if not v.nodes:
        return {}
    tax_uuid: dict[str, uuid.UUID] = {}
    for key, t in v.taxonomies.items():
        conn.execute(
            text("""INSERT INTO taxonomy (taxonomy_type, name, version, status)
                    SELECT :t, :n, :v, CASE WHEN EXISTS (SELECT 1 FROM taxonomy
                        WHERE taxonomy_type = :t AND status = 'ACTIVE') THEN 'DRAFT'
                        ELSE 'ACTIVE' END
                    ON CONFLICT (taxonomy_type, version) DO NOTHING"""),
            {"t": t["taxonomy_type"], "n": t.get("name") or t["taxonomy_id"], "v": t["version"]},
        )
        tax_uuid[key] = conn.execute(
            text("SELECT taxonomy_id FROM taxonomy WHERE taxonomy_type = :t AND version = :v"),
            {"t": t["taxonomy_type"], "v": t["version"]},
        ).scalar_one()

    node_ids: dict[str, uuid.UUID] = {}
    for code, row in sorted(v.nodes.items(), key=lambda kv: int(kv[1].get("depth") or 1)):
        tid = tax_uuid[row["_taxonomy_key"]]
        conn.execute(
            text("""INSERT INTO taxonomy_node (taxonomy_id, parent_node_id, code, canonical_name,
                        display_name, depth, sort_order, status)
                    VALUES (:tid, :parent, :code, :cn, :dn, 1, :so, :st)
                    ON CONFLICT (taxonomy_id, code) DO NOTHING"""),
            {"tid": tid, "parent": node_ids.get(row.get("parent_node_id", "")), "code": code,
             "cn": row["canonical_name"], "dn": row.get("display_name") or row["canonical_name"],
             "so": row["_row"], "st": row.get("status") or "ACTIVE"},
        )
        node_ids[code] = conn.execute(
            text("SELECT taxonomy_node_id FROM taxonomy_node WHERE taxonomy_id = :tid AND code = :c"),
            {"tid": tid, "c": code},
        ).scalar_one()

    aliases = {(node_ids[e["major_taxonomy_node_id"]], e["raw_major_name"])
               for e in v.educations if e.get("major_taxonomy_node_id") and e.get("raw_major_name")}
    aliases |= {(node_ids[w["role_taxonomy_node_id"]], w["raw_role_title"])
                for w in v.work_events if w.get("role_taxonomy_node_id") and w.get("raw_role_title")}
    _insert(conn, """INSERT INTO taxonomy_alias (taxonomy_node_id, alias_text, source_type)
                     VALUES (:node, :alias, 'PRE_SEED_FILE')
                     ON CONFLICT (taxonomy_node_id, alias_text, locale) DO NOTHING""",
            [{"node": node, "alias": alias} for node, alias in sorted(aliases)])
    return node_ids


def _insert(conn: Connection, sql: str, rows: list[dict], chunk: int = 5000) -> int:
    total = 0
    for i in range(0, len(rows), chunk):
        result = conn.execute(text(sql), rows[i:i + chunk])
        total += max(result.rowcount, 0)
    return total


def _integrity_checks(conn: Connection, v: Validated, batch_id, system: str) -> dict:
    key_id = partial(stable_id, system)
    def scalar(sql: str, **params):
        return conn.execute(text(sql), params).scalar_one()

    person_ids = [key_id("person", p["_key"]) for p in v.persons]
    checks = {}

    def check(name: str, actual, expected):
        checks[name] = {"actual": actual, "expected": expected, "pass": actual == expected}

    check("persons_present", scalar(
        "SELECT count(*) FROM person WHERE person_id = ANY(:ids)", ids=person_ids), len(person_ids))
    check("educations_present", scalar(
        "SELECT count(*) FROM education WHERE person_id = ANY(:ids)", ids=person_ids),
        len(v.educations))
    check("work_events_present", scalar(
        "SELECT count(*) FROM work_event WHERE person_id = ANY(:ids)", ids=person_ids),
        len(v.work_events))
    check("work_events_without_evidence", scalar(
        """SELECT count(*) FROM work_event w WHERE w.person_id = ANY(:ids)
           AND NOT EXISTS (SELECT 1 FROM work_event_source s
                           WHERE s.work_event_id = w.work_event_id)""", ids=person_ids),
        sum(1 for i in v.issues if i.rule_code == "NO_EVIDENCE_SOURCE"))
    check("preseed_persons_with_account", scalar(
        "SELECT count(*) FROM person WHERE origin_layer = 'PRE_SEED' AND account_id IS NOT NULL"),
        0)
    check("work_events_end_before_start", scalar(
        "SELECT count(*) FROM work_event WHERE end_date < start_date"), 0)
    check("educations_missing_major_node", scalar(
        """SELECT count(*) FROM education WHERE person_id = ANY(:ids)
           AND major_taxonomy_node_id IS NULL""", ids=person_ids),
        sum(1 for e in v.educations if not e.get("major_taxonomy_node_id")))
    check("work_events_missing_role_node", scalar(
        """SELECT count(*) FROM work_event WHERE person_id = ANY(:ids)
           AND role_taxonomy_node_id IS NULL""", ids=person_ids),
        sum(1 for e in v.work_events if not e.get("role_taxonomy_node_id")))
    check("non_preseed_rows_in_batch", scalar(
        """SELECT count(*) FROM source_record WHERE import_batch_id = :b
           AND data_layer <> 'PRE_SEED'""", b=batch_id), 0)
    return checks
