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
    rules = {node: rule for node, name in leaves.items() if (rule := _rule(name))}

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

    # New schools and the majors they publish.
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

    out_rows: dict[str, list[dict]] = defaultdict(list)
    cells, k = [], 0
    for i, school in enumerate(with_depts, start=1):
        inst_id = f"KR{i:04d}"
        out_rows["institutions"].append({"institution_id": inst_id, "institution_name": school["name"],
                                         "region": school["region"],
                                         "institution_type": school["institution_type"]})
        area = _capital(school["region"])
        r = rank(len(depts[school["name"]]))
        for node, rule in sorted(rules.items()):
            if not any(rule.search(d) for d in depts[school["name"]]):
                continue
            pool = donors.get((node, area)) or donors.get((node, None)) or []
            if not pool:
                continue
            n = _cell_size(r, f"{seed}:{school['name']}:{node}", low, high)
            rng = random.Random(f"{seed}:{school['name']}:{node}")
            picked = rng.sample(pool, n) if len(pool) >= n else [rng.choice(pool) for _ in range(n)]
            cells.append({"school": school["name"], "major": leaves[node], "n": n})
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
                    for m, s in enumerate(sources_by_event[w["work_event_id"]], start=1):
                        out_rows["work_event_sources"].append(
                            {**s, "work_event_source_id": f"{wid}_S{m}", "work_event_id": wid,
                             "source_ref": ref})

    summary = {
        "dataset": f"HELLOMYME PRE_SEED {version}", "base": readme.get("Dataset", ""),
        "base_sha256": hashlib.sha256(Path(base).read_bytes()).hexdigest(), "seed": seed,
        "schools": len(out_rows["institutions"]), "cells": len(cells), "persons": k,
        "work_events": len(out_rows["work_events"]),
        "schools_without_departments": sorted(s["name"] for s in schools if not depts.get(s["name"])),
        "cell_size": {"min": min((c["n"] for c in cells), default=0),
                      "max": max((c["n"] for c in cells), default=0)},
    }
    _write(out, headers, sheets, out_rows, readme, version, summary)
    return summary


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
