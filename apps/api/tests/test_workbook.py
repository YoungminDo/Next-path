"""v1.3 workbook import (taxonomy nodes, gender, admission year, precision) and retirement of a
superseded PRE_SEED version. Uses a tiny synthetic workbook, never product data."""
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import text

from hellomyme.importer.preseed import ImportAborted, run_import
from hellomyme.importer.retire import RetireRefused, retire_dataset
from tests.conftest import AS_OF, build_package

SOURCE = ("PRE_SEED", "PRE_SEED_FILE")
# Shared by the test workbooks; nodes are reused by code across imports.
NODES = [["R1", "ROLE", None, "비즈니스", "비즈니스", 1, "ACTIVE"],
         ["R2", "ROLE", "R1", "마케팅", "마케팅", 2, "ACTIVE"],
         ["R3", "ROLE", "R2", "브랜드 마케팅", "브랜드 마케팅", 3, "ACTIVE"],
         ["R2B", "ROLE", "R1", "데이터·AI", "데이터·AI", 2, "ACTIVE"],
         ["R3B", "ROLE", "R2B", "데이터 분석", "데이터 분석", 3, "ACTIVE"],
         ["M1", "MAJOR", None, "상경", "상경", 1, "ACTIVE"],
         ["M2", "MAJOR", "M1", "경영·경제", "경영·경제", 2, "ACTIVE"],
         ["M3", "MAJOR", "M2", "경영학", "경영학", 3, "ACTIVE"],
         ["I1", "INDUSTRY", None, "IT", "IT", 1, "ACTIVE"]]


def write_workbook(path: Path, *, bad_node: bool = False, ref: str = "WBT") -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    def sheet(title, header, rows):
        ws = wb.create_sheet(title)
        ws.append(header)
        for r in rows:
            ws.append(r)

    sheet("00_README", ["Item", "Value"], [["Dataset", "Test v9.9"], ["As-of date", "2026-10-07"]])
    sheet("06_TAXONOMY", ["taxonomy_id", "taxonomy_type", "name", "version"],
          [["TAX_ROLE", "ROLE", "R", "t1"], ["TAX_MAJOR", "MAJOR", "M", "t1"],
           ["TAX_INDUSTRY", "INDUSTRY", "I", "t1"]])
    sheet("07_TAXONOMY_NODE", ["taxonomy_node_id", "taxonomy_id", "parent_node_id",
                               "canonical_name", "display_name", "depth", "status"],
          NODES)
    sheet("01_PERSON", ["person_id", "user_stage", "gender_code", "data_layer", "source_ref",
                        "source_type"],
          [[f"P{i}", "PROFESSIONAL", g, *SOURCE[:1], f"{ref}_P{i}", SOURCE[1]]
           for i, g in enumerate(["FEMALE", "MALE", None], start=1)])
    sheet("02_EDUCATION", ["education_id", "person_id", "institution_id", "raw_major_name",
                           "major_taxonomy_node_id", "admission_year", "graduation_year",
                           "degree_type", "admission_precision", "graduation_precision",
                           "data_layer", "source_ref", "source_type"],
          [[f"E{i}", f"P{i}", "INST1", "경영학과", "M9" if bad_node and i == 1 else "M2",
            2016, 2020, "BACHELOR", "YEAR", "YEAR", "PRE_SEED", f"{ref}_P{i}", "PRE_SEED_FILE"]
           for i in range(1, 4)])
    sheet("03_WORK_EVENT", ["work_event_id", "person_id", "event_type", "organization_id",
                            "raw_role_title", "role_taxonomy_node_id", "start_date", "end_date",
                            "is_current", "start_precision", "end_precision", "data_layer",
                            "source_ref", "source_type"],
          [[f"W{i}", f"P{i}", "EMPLOYMENT", "ORG1", "브랜드 마케터", "R3", "2020-03-01", None,
            True, "MONTH", None, "PRE_SEED", f"{ref}_P{i}", "PRE_SEED_FILE"] for i in range(1, 4)])
    sheet("04_INSTITUTION", ["institution_id", "institution_name", "region", "institution_type"],
          [["INST1", "워크북대학교", "서울", "PRIVATE"]])
    sheet("05_ORGANIZATION", ["organization_id", "organization_name", "industry",
                              "company_size_band"], [["ORG1", "워크북컴퍼니", "IT", "LARGE"]])
    sheet("08_ORG_INDUSTRY", ["organization_industry_id", "organization_id",
                              "industry_taxonomy_node_id", "is_primary", "source_type"],
          [["OI1", "ORG1", "I1", True, "PRE_SEED_FILE"]])
    sheet("09_WORK_EVENT_SOURCE", ["work_event_source_id", "work_event_id", "source_ref",
                                   "source_type", "supported_fields", "evidence_confidence",
                                   "is_primary"],
          [[f"S{i}", f"W{i}", f"{ref}_P{i}", "PRE_SEED_FILE",
            "organization_id,role_id,start_date,is_current,event_type", None, "True"]
           for i in range(1, 4)])
    wb.save(path)
    return path


def test_workbook_import_writes_v14_fields(engine, tmp_path):
    report = run_import(engine, write_workbook(tmp_path / "wb.xlsx"), as_of=AS_OF,
                        dataset_version="wb-test")
    assert report["status"] == "COMPLETED", report
    assert report["imported"]["taxonomy_nodes"] == len(NODES)
    assert report["imported"]["organization_industries"] == 1
    assert all(c["pass"] for c in report["integrity_checks"].values())
    with engine.begin() as conn:
        rows = conn.execute(text(
            """SELECT p.gender_code, e.admission_year, e.admission_date_precision, mn.code AS major,
                      rn.code AS role, rn.depth, w.start_date_precision, w.end_date_precision,
                      w.employment_type
               FROM person p JOIN education e USING (person_id)
               JOIN work_event w USING (person_id)
               JOIN taxonomy_node mn ON mn.taxonomy_node_id = e.major_taxonomy_node_id
               JOIN taxonomy_node rn ON rn.taxonomy_node_id = w.role_taxonomy_node_id
               JOIN entity_key_map k ON k.entity_id = p.person_id
               WHERE k.source_system = 'PRESEED_wb-test' ORDER BY k.source_key""")).all()
        assert [r.gender_code for r in rows] == ["FEMALE", "MALE", "UNKNOWN"]  # blank is unknown
        r = rows[0]
        assert (r.admission_year, r.admission_date_precision, r.major, r.role, r.depth) == (
            2016, "YEAR", "M2", "R3", 3)
        assert (r.start_date_precision, r.end_date_precision) == ("MONTH", None)
        assert r.employment_type is None  # the workbook does not say; never guessed
        aliases = conn.execute(text(
            """SELECT a.alias_text FROM taxonomy_alias a JOIN taxonomy_node n USING (taxonomy_node_id)
               WHERE n.code IN ('M2','R3') ORDER BY 1""")).scalars().all()
        assert aliases == ["경영학과", "브랜드 마케터"]


def test_unknown_taxonomy_node_aborts(engine, tmp_path):
    with pytest.raises(ImportAborted) as exc:
        run_import(engine, write_workbook(tmp_path / "bad.xlsx", bad_node=True, ref="BAD"),
                   as_of=AS_OF, dataset_version="wb-bad")
    assert "ORPHAN_TAXONOMY_NODE" in {c["rule_code"] for c in exc.value.report["critical"]}


def test_retire_erases_old_version_and_keeps_batch(engine, tmp_path):
    run_import(engine, build_package(tmp_path / "old", per_group=4), as_of=AS_OF,
               dataset_version="wb-old")
    result = retire_dataset(engine, "wb-old", reason="superseded in test")
    assert result["deleted_persons"] == 16
    with engine.begin() as conn:
        left = conn.execute(text(
            "SELECT count(*) FROM source_record WHERE source_system = 'PRESEED_wb-old'")).scalar_one()
        status = conn.execute(text(
            "SELECT status FROM import_batch WHERE source_system = 'PRESEED_wb-old'")).scalar_one()
    assert (left, status) == (0, "RETIRED")
    with pytest.raises(RetireRefused):
        retire_dataset(engine, "wb-old", reason="again")
