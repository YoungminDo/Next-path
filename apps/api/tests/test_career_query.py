"""v1.4 query engine: time window, first employment, depth roll-up, cohort v2 fallback steps,
suppression. Synthetic workbook only."""
from datetime import date
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import text

from hellomyme.domain.career_query import (
    CareerQuery,
    QueryInvalid,
    evaluate,
    time_window,
)
from hellomyme.importer.preseed import run_import
from tests.conftest import AS_OF
from tests.test_workbook import NODES

INST = "질의대학교"


def build(path: Path, people: list[dict]) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    def sheet(title, header, rows):
        ws = wb.create_sheet(title)
        ws.append(header)
        for r in rows:
            ws.append(r)

    sheet("06_TAXONOMY", ["taxonomy_id", "taxonomy_type", "name", "version"],
          [["TAX_ROLE", "ROLE", "R", "t1"], ["TAX_MAJOR", "MAJOR", "M", "t1"],
           ["TAX_INDUSTRY", "INDUSTRY", "I", "t1"]])
    sheet("07_TAXONOMY_NODE", ["taxonomy_node_id", "taxonomy_id", "parent_node_id",
                               "canonical_name", "display_name", "depth", "status"], NODES)
    persons, edus, events, sources = [], [], [], []
    w = 0
    for i, p in enumerate(people, start=1):
        ref = f"CQ_P{i}"
        persons.append([f"P{i}", "PROFESSIONAL", p.get("gender"), "PRE_SEED", ref, "PRE_SEED_FILE"])
        edus.append([f"E{i}", f"P{i}", "INST1", "경영학과", "M3", p["adm"], p["grad"], "BACHELOR",
                     "YEAR", "YEAR", "PRE_SEED", ref, "PRE_SEED_FILE"])
        for role, start, end in p["events"]:
            w += 1
            title = {"R3": "브랜드 마케터", "R3B": "데이터 분석가"}[role]
            events.append([f"W{w}", f"P{i}", "EMPLOYMENT", "ORG1", title, role, start, end,
                           end is None, "MONTH", "MONTH" if end else None, "PRE_SEED", ref,
                           "PRE_SEED_FILE"])
            sources.append([f"S{w}", f"W{w}", ref, "PRE_SEED_FILE",
                            "organization_id,role_id,start_date,end_date,is_current,event_type",
                            None, "True"])
    sheet("01_PERSON", ["person_id", "user_stage", "gender_code", "data_layer", "source_ref",
                        "source_type"], persons)
    sheet("02_EDUCATION", ["education_id", "person_id", "institution_id", "raw_major_name",
                           "major_taxonomy_node_id", "admission_year", "graduation_year",
                           "degree_type", "admission_precision", "graduation_precision",
                           "data_layer", "source_ref", "source_type"], edus)
    sheet("03_WORK_EVENT", ["work_event_id", "person_id", "event_type", "organization_id",
                            "raw_role_title", "role_taxonomy_node_id", "start_date", "end_date",
                            "is_current", "start_precision", "end_precision", "data_layer",
                            "source_ref", "source_type"], events)
    sheet("04_INSTITUTION", ["institution_id", "institution_name", "region", "institution_type"],
          [["INST1", INST, "서울", "PRIVATE"]])
    sheet("05_ORGANIZATION", ["organization_id", "organization_name", "industry",
                              "company_size_band"], [["ORG1", "질의컴퍼니", "IT", "LARGE"]])
    sheet("08_ORG_INDUSTRY", ["organization_industry_id", "organization_id",
                              "industry_taxonomy_node_id", "is_primary", "source_type"],
          [["OI1", "ORG1", "I1", True, "PRE_SEED_FILE"]])
    sheet("09_WORK_EVENT_SOURCE", ["work_event_source_id", "work_event_id", "source_ref",
                                   "source_type", "supported_fields", "evidence_confidence",
                                   "is_primary"], sources)
    wb.save(path)
    return path


# 10 graduated 2020 (exact cohort), 35 graduated 2021 (reached by widening graduation by 2).
# First jobs: 30 marketing, 15 data. 10 marketers later moved to data in 2023.
PEOPLE = (
    [{"gender": "FEMALE", "adm": 2016, "grad": 2020,
      "events": [("R3", "2020-03-01", None)]} for _ in range(10)]
    + [{"gender": "MALE", "adm": 2017, "grad": 2021,
        "events": [("R3", "2021-03-01", "2023-01-01"), ("R3B", "2023-02-01", None)]}
       for _ in range(10)]
    + [{"gender": "MALE", "adm": 2017, "grad": 2021, "events": [("R3", "2021-03-01", None)]}
       for _ in range(10)]
    + [{"gender": None, "adm": 2017, "grad": 2021, "events": [("R3B", "2021-03-01", None)]}
       for _ in range(15)]
)


@pytest.fixture(scope="module")
def ids(engine, tmp_path_factory):
    report = run_import(engine, build(tmp_path_factory.mktemp("cq") / "cq.xlsx", PEOPLE),
                        as_of=AS_OF, dataset_version="cq-test")
    assert report["status"] in ("COMPLETED", "ALREADY_IMPORTED"), report
    with engine.begin() as conn:
        node = dict(conn.execute(text(
            """SELECT n.code, n.taxonomy_node_id::text FROM taxonomy_node n
               JOIN taxonomy t USING (taxonomy_id) WHERE t.status = 'ACTIVE'""")).all())
        inst = conn.execute(text("SELECT institution_id::text FROM institution WHERE name = :n"),
                            {"n": INST}).scalar_one()
    return {"inst": inst, **node}


def run(engine, **kw):
    with engine.connect() as conn:
        return evaluate(conn, CareerQuery(as_of_date=AS_OF, **kw), layers=["PRE_SEED"])


def test_time_window_is_inclusive_and_calendar_based():
    assert time_window(date(2026, 10, 7), "1Y") == (date(2025, 10, 8), date(2026, 10, 7))
    assert time_window(date(2028, 2, 29), "1Y") == (date(2027, 3, 1), date(2028, 2, 29))
    assert time_window(date(2026, 10, 7), "ALL") == (None, date(2026, 10, 7))
    with pytest.raises(QueryInvalid):
        time_window(date(2026, 10, 7), "2Y")


def test_exact_cohort_widens_graduation_and_reports_it(engine, ids):
    out = run(engine, target_metric="FIRST_ROLE_DISTRIBUTION", institution_ids=(ids["inst"],),
              major_node_ids=(ids["M3"],), graduation_year_from=2020, graduation_year_to=2020)
    assert out["exact_n"] == 10 and out["effective_n"] == 45
    assert out["fallback_reason"] == ["WIDEN_GRADUATION_YEAR_2Y"]
    assert out["effective_filters"]["graduation_year"] == {"from": 2018, "to": 2022}
    assert out["requested_filters"]["graduation_year"] == {"from": 2020, "to": 2020}
    # Rolled up to the ACQUISITION default depth (2): 마케팅 30, 데이터·AI 15.
    assert [(c["code"], c["n"]) for c in out["cells"]] == [("R2", 30), ("R2B", 15)]
    assert out["taxonomy_depth"] == 2 and not out["suppressed"]


def test_requested_depth_is_clamped_to_surface_view(engine, ids):
    out = run(engine, target_metric="FIRST_ROLE_DISTRIBUTION", institution_ids=(ids["inst"],),
              requested_depth=9)
    assert out["taxonomy_depth"] == 3
    assert {c["code"] for c in out["cells"]} == {"R3", "R3B"}


def test_lookback_window_filters_by_first_employment_start(engine, ids):
    # 3Y as of 2026-10-07 starts 2023-10-08: no first job in the cohort starts that late.
    out = run(engine, target_metric="FIRST_ROLE_DISTRIBUTION", institution_ids=(ids["inst"],),
              lookback="3Y")
    assert out["exact_n"] == 0 and out["suppressed"] and out["cells"] == []
    assert out["time_window"] == {"start": "2023-10-08", "end": "2026-10-07"}


def test_gender_filter_uses_demographic_threshold_and_is_dropped(engine, ids):
    out = run(engine, target_metric="FIRST_ROLE_DISTRIBUTION", institution_ids=(ids["inst"],),
              gender_codes=("FEMALE",))
    # 10 women < demographic_min_n (50): gender is dropped, the drop is reported.
    assert out["exact_n"] == 10
    assert "DROP_GENDER" in out["fallback_reason"]
    assert "gender_codes" not in out["effective_filters"]
    assert out["effective_n"] == 45


def test_next_role_and_stayed(engine, ids):
    out = run(engine, target_metric="NEXT_ROLE_DISTRIBUTION", institution_ids=(ids["inst"],),
              from_role_node_ids=(ids["R2"],))
    assert out["effective_n"] == 30
    assert [(c["code"], c["n"]) for c in out["cells"]] == [("STAYED", 20), ("R2B", 10)]


def test_small_cells_fold_into_other_and_small_cohorts_suppress(engine, ids):
    out = run(engine, target_metric="CURRENT_ROLE_DISTRIBUTION", institution_ids=(ids["inst"],))
    assert out["effective_n"] == 45
    assert sum(c["n"] for c in out["cells"]) + (out["other"] or {}).get("n", 0) == 45
    tiny = run(engine, target_metric="NEXT_ROLE_DISTRIBUTION", institution_ids=(ids["inst"],),
               from_role_node_ids=(ids["R2B"],))
    assert tiny["suppressed"] and tiny["cells"] == [] and tiny["unknown_n"] is None


def test_unknown_metric_and_node_are_rejected(engine, ids):
    with pytest.raises(QueryInvalid):
        run(engine, target_metric="SALARY")
    with pytest.raises(QueryInvalid):
        run(engine, target_metric="FIRST_ROLE_DISTRIBUTION",
            major_node_ids=("00000000-0000-0000-0000-000000000000",))
