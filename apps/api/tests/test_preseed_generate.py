"""PRE_SEED add-on generator: more 4-year schools from the official workbook, in its format, loaded
by the official importer next to the base and removable on its own."""
import csv
from pathlib import Path

import openpyxl
from sqlalchemy import text

from hellomyme.importer.generate import generate
from hellomyme.importer.preseed import run_import
from hellomyme.importer.retire import retire_dataset
from hellomyme.importer.workbook import SHEETS, _sheet
from tests.conftest import AS_OF
from tests.test_career_query import PEOPLE, build


def reference(tmp: Path) -> tuple[Path, Path]:
    inst, dept = tmp / "inst.csv", tmp / "dept.csv"
    cols = ["name", "name_en", "school_level", "school_kind", "institution_type", "region",
            "aliases"]
    with open(inst, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows([["생성수도권대학교", "", "UNIVERSITY", "대학교", "PRIVATE", "서울", ""],
                     ["생성지방대학교", "", "UNIVERSITY", "대학교", "NATIONAL", "부산", ""],
                     ["학과없는대학교", "", "UNIVERSITY", "대학교", "PRIVATE", "서울", ""],
                     ["생성전문대학", "", "JUNIOR_COLLEGE", "전문대학", "PRIVATE", "서울", ""],
                     ["질의대학교", "", "UNIVERSITY", "대학교", "PRIVATE", "서울", ""]])
    with open(dept, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["school", "college", "department"])
        w.writerows([["생성수도권대학교", "경영대학", "경영학과"],
                     ["생성수도권대학교", "공과대학", "기계공학과"],
                     ["생성지방대학교", "상경대학", "경영학부"],
                     ["생성전문대학", "경영계열", "경영학과"]])
    return inst, dept


def rows(path: Path, name: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        return _sheet(wb, SHEETS[name])
    finally:
        wb.close()


def test_add_on_copies_whole_people_to_schools_that_have_the_major(engine, tmp_path):
    base = build(tmp_path / "base.xlsx", PEOPLE)  # 45 people, 질의대학교, major leaf 경영학 (M3)
    inst, dept = reference(tmp_path)
    out = tmp_path / "addon.xlsx"
    s = generate(base, out, version="v9.4", institutions=inst, departments=dept, low=6, high=9)

    # Only 4-year schools beyond the base that publish a matching department.
    made = [r["institution_name"] for r in rows(out, "institutions")]
    assert made == ["생성수도권대학교", "생성지방대학교"]
    assert s["schools_without_departments"] == ["학과없는대학교"]
    assert 12 <= s["persons"] <= 18 and s["cells"] == 2
    persons, edus, events = rows(out, "persons"), rows(out, "educations"), rows(out, "work_events")
    assert len({p["person_id"] for p in persons}) == len(persons) == s["persons"]
    # Whole people: same years and the same career events as a base person, only ids/school differ.
    base_edu = {(e["admission_year"], e["graduation_year"], e["major_taxonomy_node_id"])
                for e in rows(base, "educations")}
    assert all((e["admission_year"], e["graduation_year"], e["major_taxonomy_node_id"]) in base_edu
               for e in edus)
    base_events = rows(base, "work_events")
    base_paths = {tuple(sorted((w["role_taxonomy_node_id"], w["start_date"]) for w in base_events
                               if w["person_id"] == p))
                  for p in {w["person_id"] for w in base_events}}
    by_person = {}
    for w in events:
        by_person.setdefault(w["person_id"], []).append((w["role_taxonomy_node_id"], w["start_date"]))
    assert all(tuple(sorted(v)) in base_paths for v in by_person.values())

    # Same inputs and seed: the same rows.
    again = tmp_path / "again.xlsx"
    generate(base, again, version="v9.4", institutions=inst, departments=dept, low=6, high=9)
    assert rows(again, "work_events") == events

    # The official importer accepts it beside the base; retiring the add-on removes only it.
    run_import(engine, base, as_of=AS_OF, dataset_version="gen-base")
    report = run_import(engine, out, as_of=AS_OF, dataset_version="v9.4")
    assert report["status"] == "COMPLETED", report
    assert report["imported"]["persons"] == s["persons"] and report["rejected_total"] == 0
    assert all(c["pass"] for c in report["integrity_checks"].values())
    with engine.begin() as conn:
        n = conn.execute(text(
            """SELECT count(*) FROM education e JOIN institution i USING (institution_id)
               WHERE i.name IN ('생성수도권대학교', '생성지방대학교')
                 AND e.data_layer = 'PRE_SEED'""")).scalar_one()
    assert n == s["persons"]
    gone = retire_dataset(engine, "v9.4", reason="test")
    assert gone["deleted_persons"] == s["persons"]
    with engine.begin() as conn:
        base_left = conn.execute(text(
            "SELECT count(*) FROM entity_key_map WHERE source_system = 'PRESEED_gen-base' "
            "AND entity_type = 'PERSON'")).scalar_one()
    assert base_left == len(PEOPLE)
