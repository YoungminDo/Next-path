"""PRE_SEED add-on generator: cohorts for every 4-year school, from the official v1.3 workbook.

PRE_SEED is simulation data for development and the demand test (never shown as a person, never
identity-matched, labelled SIMULATION on every result). v1.3 covers 24 schools x 20 majors. This
builds an add-on workbook (e.g. v1.4) for the other 4-year universities, in the same format, so
the official importer validates and loads it next to v1.3 (retiring v1.4 alone removes it):

- Which schools: 대학교 / 산업대학 in hellomyme/reference/kr_institutions.csv (public data) that
  v1.3 does not have and whose departments are published (kr_school_departments.csv). A school
  without published departments gets nothing (no guessed majors).
- Which majors: a v1.3 major leaf only where the school has a matching department (fixed
  keyword rules below, on the published department names).
- How many: 30-45 people per school and major (30 = the cohort policy's min_exact_n, so the
  school itself can answer), larger for schools with more departments, with a fixed per-cell
  spread so the same number does not repeat everywhere.
- Who: each person is a whole v1.3 person of the same major (education years, every career
  event and its evidence row copied as they are), drawn from v1.3 schools in the same area
  (capital region or not; all v1.3 schools when the area has none). Only the ids, the source
  reference and the school change. Nothing else is invented or adjusted.

Deterministic: the same base workbook, reference files and seed give the same workbook.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import openpyxl

from hellomyme.importer.workbook import SHEETS, _sheet

REFERENCE = Path(__file__).resolve().parent.parent / "reference"
KINDS = ("대학교", "산업대학")
CAPITAL = ("서울", "경기", "인천", "수원")

# Department-name rules for the v1.3 major leaves (display name -> regex). A leaf without a rule
# matches departments that contain its name without the trailing 학과/학부/과.
RULES = {
    "경영학과": r"경영", "경제학과": r"경제", "통계학과": r"통계",
    "컴퓨터공학과": r"컴퓨터", "소프트웨어학과": r"소프트웨어",
    "산업공학과": r"산업공학|산업시스템|산업경영공학",
    "기계공학과": r"기계", "전자전기공학과": r"전자|전기",
    "미디어커뮤니케이션학과": r"미디어|커뮤니케이션|언론|신문방송",
    "광고홍보학과": r"광고|홍보",
    "시각디자인학과": r"시각디자인|커뮤니케이션디자인|산업디자인|디자인학",
    "심리학과": r"심리", "사회학과": r"^사회학|사회학과|사회학부", "영어영문학과": r"영어|영문",
    "국어국문학과": r"국어|국문|한국어문", "수학과": r"^수학|수학과|수리", "생명과학과": r"생명|생물",
    "화학공학과": r"화학공학|화공|화학생명공학", "행정학과": r"행정",
    "국제학과": r"국제학|국제관계|국제통상|국제지역",
}


def _rule(display_name: str) -> re.Pattern | None:
    if display_name in RULES:
        return re.compile(RULES[display_name])
    stem = re.sub(r"(학과|학부|과)$", "", display_name)
    return re.compile(re.escape(stem)) if len(stem) >= 2 else None


def _capital(region: str) -> bool:
    return any(c in (region or "") for c in CAPITAL)


def _cell_size(rank: float, key: str, low: int, high: int) -> int:
    """low..high by school size rank (0..1), with a fixed spread of +-3 per (school, major)."""
    spread = int(hashlib.sha256(key.encode()).hexdigest(), 16) % 7 - 3
    return max(low, min(high, round(low + (high - low) * rank) + spread))


def plan_cells(base_names: set[str], leaves: dict[str, str], *, seed: int = 14, low: int = 30,
               high: int = 45, institutions: Path | None = None,
               departments: Path | None = None) -> dict:
    """Which schools get people, for which majors (leaf key -> display name), and how many.
    Shared by the workbook add-on and the SQL add-on, so both make the same cohorts."""
    institutions = institutions or REFERENCE / "kr_institutions.csv"
    departments = departments or REFERENCE / "kr_school_departments.csv"
    rules = {node: rule for node, name in leaves.items() if (rule := _rule(name))}
    depts = defaultdict(list)
    with open(departments, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            depts[r["school"]].append(r["department"])
    with open(institutions, encoding="utf-8") as f:
        schools = [r for r in csv.DictReader(f) if r["school_level"] == "UNIVERSITY"
                   and r["school_kind"] in KINDS and r["name"] not in base_names]
    with_depts = sorted((s for s in schools if depts.get(s["name"])), key=lambda s: s["name"])
    sizes = sorted(len(depts[s["name"]]) for s in with_depts)

    def rank(n: int) -> float:
        return sum(1 for x in sizes if x < n) / max(len(sizes) - 1, 1)

    cells = []
    for school in with_depts:
        r = rank(len(depts[school["name"]]))
        for node, rule in sorted(rules.items()):
            if any(rule.search(d) for d in depts[school["name"]]):
                cells.append({"school": school, "node": node,
                              "n": _cell_size(r, f"{seed}:{school['name']}:{node}", low, high)})
    used = {c["school"]["name"] for c in cells}
    return {"schools": [s for s in with_depts if s["name"] in used], "cells": cells,
            "schools_without_departments": sorted(s["name"] for s in schools
                                                  if not depts.get(s["name"])),
            # Departments published, but none of them is one of the base majors.
            "schools_without_majors": sorted(s["name"] for s in with_depts
                                             if s["name"] not in used)}


def generate(base: Path, out: Path, *, version: str = "v1.4", seed: int = 14, low: int = 30,
             high: int = 45, institutions: Path | None = None,
             departments: Path | None = None) -> dict:
    institutions = institutions or REFERENCE / "kr_institutions.csv"
    departments = departments or REFERENCE / "kr_school_departments.csv"
    wb = openpyxl.load_workbook(base, read_only=True, data_only=True)
    try:
        present = {name: title for name, title in SHEETS.items() if title in wb.sheetnames}
        sheets = {name: _sheet(wb, title) for name, title in SHEETS.items()
                  if name != "readme" or title in wb.sheetnames}  # 00_README is optional
        headers = {name: [str(c.value) if c.value is not None else "" for c in next(
            wb[title].iter_rows(max_row=1))] for name, title in present.items()}
    finally:
        wb.close()
    readme = {r.get("Item", ""): r.get("Value", "") for r in sheets.get("readme", [])}

    # v1.3: schools, major leaves, donors by (major node, capital region or not).
    base_schools = {r["institution_id"]: r for r in sheets["institutions"]}
    base_names = {r["institution_name"] for r in base_schools.values()}
    nodes = sheets["taxonomy_nodes"]
    parents = {n.get("parent_node_id") for n in nodes}
    # Node rows name their taxonomy by sheet id (TAX_MAJOR) or by type (MAJOR), as the importer reads.
    tax_type = {t["taxonomy_id"]: t["taxonomy_type"] for t in sheets["taxonomies"]}
    tax_type.update({t["taxonomy_type"]: t["taxonomy_type"] for t in sheets["taxonomies"]})
    leaves = {n["taxonomy_node_id"]: n.get("display_name") or n["canonical_name"] for n in nodes
              if tax_type.get(n.get("taxonomy_id")) == "MAJOR" and n["taxonomy_node_id"] not in parents}
    edus_by_person = defaultdict(list)
    for e in sheets["educations"]:
        edus_by_person[e["person_id"]].append(e)
    events_by_person = defaultdict(list)
    for w in sheets["work_events"]:
        events_by_person[w["person_id"]].append(w)
    sources_by_event = defaultdict(list)
    for s in sheets["work_event_sources"]:
        sources_by_event[s["work_event_id"]].append(s)
    donors: dict[tuple[str, bool | None], list[dict]] = defaultdict(list)
    for p in sheets["persons"]:
        edus = edus_by_person.get(p["person_id"], [])
        if len(edus) != 1 or edus[0].get("major_taxonomy_node_id") not in leaves:
            continue  # only plain one-degree people are copied whole
        node = edus[0]["major_taxonomy_node_id"]
        area = _capital(base_schools.get(edus[0]["institution_id"], {}).get("region", ""))
        donors[(node, area)].append(p)
        donors[(node, None)].append(p)

    plan = plan_cells(base_names, leaves, seed=seed, low=low, high=high,
                      institutions=institutions, departments=departments)
    inst_ids = {}
    out_rows: dict[str, list[dict]] = defaultdict(list)
    for i, school in enumerate(plan["schools"], start=1):
        inst_ids[school["name"]] = f"KR{i:04d}"
        out_rows["institutions"].append({"institution_id": inst_ids[school["name"]],
                                         "institution_name": school["name"],
                                         "region": school["region"],
                                         "institution_type": school["institution_type"]})
    cells, k = [], 0
    for cell in plan["cells"]:
        school, node, n = cell["school"], cell["node"], cell["n"]
        pool = donors.get((node, _capital(school["region"]))) or donors.get((node, None)) or []
        if not pool:
            continue
        rng = random.Random(f"{seed}:{school['name']}:{node}")
        picked = rng.sample(pool, n) if len(pool) >= n else [rng.choice(pool) for _ in range(n)]
        cells.append({"school": school["name"], "major": leaves[node], "n": n})
        inst_id = inst_ids[school["name"]]
        for donor in picked:
            k += 1
            pid, ref = f"K{k:06d}", f"PS{version.lstrip('v').replace('.', '')}_K{k:06d}"
            out_rows["persons"].append({**donor, "person_id": pid, "source_ref": ref})
            for j, e in enumerate(edus_by_person[donor["person_id"]], start=1):
                out_rows["educations"].append({**e, "education_id": f"{pid}_E{j}", "person_id": pid,
                                               "institution_id": inst_id, "source_ref": ref})
            for j, w in enumerate(events_by_person[donor["person_id"]], start=1):
                wid = f"{pid}_W{j}"
                out_rows["work_events"].append({**w, "work_event_id": wid, "person_id": pid,
                                                "source_ref": ref})
                for m, src in enumerate(sources_by_event[w["work_event_id"]], start=1):
                    out_rows["work_event_sources"].append(
                        {**src, "work_event_source_id": f"{wid}_S{m}", "work_event_id": wid,
                         "source_ref": ref})

    summary = {
        "dataset": f"HELLOMYME PRE_SEED {version}", "base": readme.get("Dataset", ""),
        "base_sha256": hashlib.sha256(Path(base).read_bytes()).hexdigest(), "seed": seed,
        "schools": len(out_rows["institutions"]), "cells": len(cells), "persons": k,
        "work_events": len(out_rows["work_events"]),
        "schools_without_departments": plan["schools_without_departments"],
        "schools_without_majors": plan["schools_without_majors"],
        "cell_size": {"min": min((c["n"] for c in cells), default=0),
                      "max": max((c["n"] for c in cells), default=0)},
    }
    _write(out, headers, sheets, out_rows, readme, version, summary)
    return summary


def addon_sql(plan: dict, *, version: str = "v1.4", base_version: str = "v1.3",
              seed: int = 14) -> str:
    """The same add-on, written straight into a database that already holds the base version:
    one DO block (one transaction), donors drawn from the base's people in the database by the
    same rules (same major, same area first, a fixed hash order), rows written as the importer
    writes them (source record per person, key map, import batch) so retiring the version removes
    exactly this. It refuses to run twice and rolls back if any check fails."""
    def q(v: str) -> str:
        return "'" + v.replace("'", "''") + "'"

    rows = ",\n".join(f"({i}, {q(c['school']['name'])}, {q(c['node'])}, {int(c['n'])})"
                      for i, c in enumerate(plan["cells"], start=1))
    digest = hashlib.sha256(f"{version}:{base_version}:{seed}:{rows}".encode()).hexdigest()
    system, base_system = f"PRESEED_{version}", f"PRESEED_{base_version}"
    prefix = f"PS{version.lstrip('v').replace('.', '')}_K"
    capital = "(" + "|".join(CAPITAL) + ")"
    return f"""-- PRE_SEED {version} add-on (simulation data) from {base_version} in the database.
-- {len(plan['cells'])} school x major cells, {sum(c['n'] for c in plan['cells'])} people. Generated by
-- hellomyme.importer.generate.addon_sql (seed {seed}); remove with the importer's --retire {version}.
DO $addon$
DECLARE
    b uuid;
    missing int;
BEGIN
    IF EXISTS (SELECT 1 FROM import_batch
                WHERE source_system = {q(system)} AND status = 'COMPLETED') THEN
        RAISE EXCEPTION 'PRE_SEED {version} is already imported';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM import_batch
                    WHERE source_system = {q(base_system)} AND status = 'COMPLETED') THEN
        RAISE EXCEPTION 'PRE_SEED {base_version} is not in this database';
    END IF;
    INSERT INTO import_batch (dataset_name, dataset_version, source_system, source_type, data_layer,
                              file_manifest, manifest_sha256, validation_rule_version, status)
    VALUES ('HELLOMYME_PRESEED', {q(version)}, {q(system)}, 'PRE_SEED_FILE', 'PRE_SEED',
            jsonb_build_object('generated_from', {q(base_version)}, 'seed', {seed},
                               'plan_sha256', {q(digest)}),
            {q(digest)}, 'preseed_generated_v1', 'RUNNING')
    RETURNING import_batch_id INTO b;

    CREATE TEMP TABLE np_plan (k int, school text, major_code text, n int) ON COMMIT DROP;
    INSERT INTO np_plan VALUES
{rows};

    SELECT count(*) INTO missing FROM np_plan pl
     WHERE NOT EXISTS (SELECT 1 FROM institution i WHERE i.name = pl.school AND i.is_active);
    IF missing > 0 THEN RAISE EXCEPTION '% planned schools are not in the institution list', missing; END IF;

    CREATE TEMP TABLE np_donor ON COMMIT DROP AS
    SELECT p.person_id, e.major_taxonomy_node_id AS major,
           coalesce(i.region, '') ~ {q(capital)} AS capital
      FROM entity_key_map k
      JOIN person p ON p.person_id = k.entity_id AND p.origin_layer = 'PRE_SEED' AND p.deleted_at IS NULL
      JOIN education e ON e.person_id = p.person_id
      LEFT JOIN institution i ON i.institution_id = e.institution_id
     WHERE k.source_system = {q(base_system)} AND k.entity_type = 'PERSON'
       AND (SELECT count(*) FROM education e2 WHERE e2.person_id = p.person_id) = 1;

    CREATE TEMP TABLE np_pick ON COMMIT DROP AS
    SELECT row_number() OVER (ORDER BY pl.k, d.ord) AS seq, pl.k, inst.institution_id AS inst_id,
           inst.name AS inst_name, d.person_id AS donor,
           gen_random_uuid() AS person_id, gen_random_uuid() AS source_id
      FROM np_plan pl
      JOIN institution inst ON inst.name = pl.school
      JOIN taxonomy_node mn ON mn.code = pl.major_code
      JOIN taxonomy mt ON mt.taxonomy_id = mn.taxonomy_id AND mt.taxonomy_type = 'MAJOR'
                       AND mt.status = 'ACTIVE'
      CROSS JOIN LATERAL (
          SELECT x.person_id, row_number() OVER () AS ord FROM (
              SELECT dn.person_id FROM np_donor dn
               WHERE dn.major = mn.taxonomy_node_id
               ORDER BY (dn.capital = (coalesce(inst.region, '') ~ {q(capital)})) DESC,
                        md5({q(str(seed))} || ':' || pl.school || ':' || pl.major_code
                            || ':' || dn.person_id::text)
               LIMIT pl.n) x) d;

    SELECT count(*) INTO missing FROM np_plan pl
     WHERE pl.n > (SELECT count(*) FROM np_pick pk WHERE pk.k = pl.k);
    IF missing > 0 THEN RAISE EXCEPTION '% cells could not be filled from {base_version}', missing; END IF;

    INSERT INTO source_record (source_id, source_type, data_layer, source_system, source_key,
                               import_batch_id, raw_payload, metadata, legal_basis)
    SELECT pk.source_id, 'PRE_SEED_FILE', 'PRE_SEED', {q(system)},
           {q(prefix)} || lpad(pk.seq::text, 6, '0'), b,
           jsonb_build_object('copied_from', ds.source_key, 'institution', pk.inst_name,
                              'donor', ds.raw_payload),
           jsonb_build_object('dataset_version', {q(version)}, 'generated_from', {q(base_version)},
                              'seed', {seed}),
           'GENERATED_DATASET'
      FROM np_pick pk JOIN person dp ON dp.person_id = pk.donor
      LEFT JOIN source_record ds ON ds.source_id = dp.primary_source_id;

    INSERT INTO person (person_id, origin_layer, declared_stage, primary_source_id, gender_code,
                        gender_source_id)
    SELECT pk.person_id, 'PRE_SEED', dp.declared_stage, pk.source_id, dp.gender_code,
           CASE WHEN dp.gender_source_id IS NULL THEN NULL ELSE pk.source_id END
      FROM np_pick pk JOIN person dp ON dp.person_id = pk.donor;
    INSERT INTO entity_key_map (source_system, entity_type, source_key, entity_id, import_batch_id)
    SELECT {q(system)}, 'PERSON', 'K' || lpad(seq::text, 6, '0'), person_id, b FROM np_pick;

    CREATE TEMP TABLE np_edu ON COMMIT DROP AS
    SELECT pk.seq, e.education_id AS old_id, gen_random_uuid() AS new_id, pk.person_id, pk.source_id,
           pk.inst_id, pk.inst_name, row_number() OVER (PARTITION BY pk.seq ORDER BY e.education_id) AS j
      FROM np_pick pk JOIN education e ON e.person_id = pk.donor;
    INSERT INTO education (education_id, person_id, institution_raw, institution_id, major_raw, major_id,
                           degree_type, graduation_year, admission_year, admission_date_precision,
                           graduation_date_precision, major_taxonomy_node_id, data_layer,
                           verification_level, normalization_status, normalization_confidence)
    SELECT ne.new_id, ne.person_id, ne.inst_name, ne.inst_id, e.major_raw, e.major_id, e.degree_type,
           e.graduation_year, e.admission_year, e.admission_date_precision, e.graduation_date_precision,
           e.major_taxonomy_node_id, 'PRE_SEED', 'UNVERIFIED', 'MAPPED', 1.0
      FROM np_edu ne JOIN education e ON e.education_id = ne.old_id;
    INSERT INTO education_source (education_source_id, education_id, source_id, supported_fields, is_primary)
    SELECT gen_random_uuid(), ne.new_id, ne.source_id,
           coalesce((SELECT es.supported_fields FROM education_source es
                      WHERE es.education_id = ne.old_id ORDER BY es.is_primary DESC LIMIT 1),
                    ARRAY['institution', 'major']), true
      FROM np_edu ne;
    INSERT INTO entity_key_map (source_system, entity_type, source_key, entity_id, import_batch_id)
    SELECT {q(system)}, 'EDUCATION', 'K' || lpad(seq::text, 6, '0') || '_E' || j, new_id, b FROM np_edu;

    CREATE TEMP TABLE np_we ON COMMIT DROP AS
    SELECT pk.seq, w.work_event_id AS old_id, gen_random_uuid() AS new_id, pk.person_id, pk.source_id,
           row_number() OVER (PARTITION BY pk.seq ORDER BY w.start_date, w.work_event_id) AS j
      FROM np_pick pk JOIN work_event w ON w.person_id = pk.donor AND w.retracted_at IS NULL;
    INSERT INTO work_event (work_event_id, person_id, event_type, organization_raw, organization_id,
                            role_raw, role_id, start_date, start_date_precision, end_date,
                            end_date_precision, is_current, role_taxonomy_node_id, employment_type,
                            data_layer, verification_level, normalization_status,
                            normalization_confidence)
    SELECT nw.new_id, nw.person_id, w.event_type, w.organization_raw, w.organization_id, w.role_raw,
           w.role_id, w.start_date, w.start_date_precision, w.end_date, w.end_date_precision,
           w.is_current, w.role_taxonomy_node_id, w.employment_type, 'PRE_SEED', 'UNVERIFIED',
           'MAPPED', 1.0
      FROM np_we nw JOIN work_event w ON w.work_event_id = nw.old_id;
    CREATE TEMP TABLE np_wes ON COMMIT DROP AS
    SELECT DISTINCT ON (nw.new_id) nw.seq, nw.j, gen_random_uuid() AS new_id, nw.new_id AS work_event_id,
           nw.source_id, s.supported_fields, s.evidence_confidence, s.is_primary
      FROM np_we nw JOIN work_event_source s ON s.work_event_id = nw.old_id
     ORDER BY nw.new_id, s.is_primary DESC;
    INSERT INTO work_event_source (work_event_source_id, work_event_id, source_id, supported_fields,
                                   evidence_confidence, is_primary)
    SELECT new_id, work_event_id, source_id, supported_fields, evidence_confidence, true FROM np_wes;
    INSERT INTO entity_key_map (source_system, entity_type, source_key, entity_id, import_batch_id)
    SELECT {q(system)}, 'WORK_EVENT', 'K' || lpad(seq::text, 6, '0') || '_W' || j, new_id, b FROM np_we
    UNION ALL
    SELECT {q(system)}, 'WORK_EVENT_SOURCE', 'K' || lpad(seq::text, 6, '0') || '_W' || j || '_S1', new_id, b
      FROM np_wes;

    -- The importer's integrity checks, on what was just written.
    SELECT count(*) INTO missing FROM np_we nw
     WHERE NOT EXISTS (SELECT 1 FROM work_event_source s WHERE s.work_event_id = nw.new_id);
    IF missing > 0 THEN RAISE EXCEPTION '% work events without evidence', missing; END IF;
    SELECT count(*) INTO missing FROM np_pick pk JOIN person p ON p.person_id = pk.person_id
     WHERE p.account_id IS NOT NULL;
    IF missing > 0 THEN RAISE EXCEPTION 'pre-seed people linked to accounts'; END IF;

    UPDATE import_batch SET status = 'COMPLETED', finished_at = now(), report = jsonb_build_object(
        'status', 'COMPLETED', 'import_batch_id', b, 'generated', true,
        'imported', jsonb_build_object(
            'persons', (SELECT count(*) FROM np_pick), 'education_records', (SELECT count(*) FROM np_edu),
            'work_events', (SELECT count(*) FROM np_we), 'work_event_sources', (SELECT count(*) FROM np_wes),
            'source_records', (SELECT count(*) FROM np_pick)),
        'schools', (SELECT count(DISTINCT school) FROM np_plan), 'cells', (SELECT count(*) FROM np_plan))
     WHERE import_batch_id = b;
END
$addon$;
"""


def _write(out: Path, headers: dict, sheets: dict, rows: dict, readme: dict, version: str,
           summary: dict) -> None:
    wb = openpyxl.Workbook(write_only=True)
    info = [
        ("Dataset", f"HELLOMYME PRE_SEED {version}"),
        ("As-of date", readme.get("As-of date", "")),
        ("Description", "Add-on to the official PRE_SEED (simulation data): 4-year schools beyond "
                        f"{readme.get('Dataset', 'the base')}, copied from base people of the same "
                        "major; never real people."),
        ("Base workbook", f"{summary['base']} sha256 {summary['base_sha256']}"),
        ("Generated", f"{date.today().isoformat()} by hellomyme-make-preseed, seed {summary['seed']}"),
        ("Schools", str(summary["schools"])), ("Persons", str(summary["persons"])),
    ]
    ws = wb.create_sheet(SHEETS["readme"])
    ws.append(["Item", "Value"])
    for row in info:
        ws.append(list(row))
    # Taxonomy and organisations as in the base (the importer reuses them); people are new only.
    for name, title in SHEETS.items():
        if name == "readme":
            continue
        ws = wb.create_sheet(title)
        cols = headers[name]
        ws.append(cols)
        source = rows.get(name) if name in ("institutions", "persons", "educations", "work_events",
                                             "work_event_sources") else sheets[name]
        for r in source or []:
            ws.append([r.get(c) or None for c in cols])
    wb.save(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a PRE_SEED add-on workbook (more 4-year schools) from the official one")
    parser.add_argument("base", help="the official PRE_SEED workbook "
                                     "(e.g. HELLOMYME_PreSeed_Career_Data_v1.3.xlsx)")
    parser.add_argument("--out", required=True, help="workbook to write, e.g. preseed-v1.4.xlsx")
    parser.add_argument("--version", default="v1.4")
    parser.add_argument("--seed", type=int, default=14)
    parser.add_argument("--min", dest="low", type=int, default=30)
    parser.add_argument("--max", dest="high", type=int, default=45)
    args = parser.parse_args()
    summary = generate(Path(args.base), Path(args.out), version=args.version, seed=args.seed,
                       low=args.low, high=args.high)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
