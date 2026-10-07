import csv
import os
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault(
    "HELLOMYME_DATABASE_URL",
    "postgresql+psycopg://hellomyme:hellomyme@localhost:5432/hellomyme_test",
)
os.environ["HELLOMYME_ENV"] = "test"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from hellomyme.db import get_engine  # noqa: E402

API_DIR = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 10, 7)


def alembic_config() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", os.environ["HELLOMYME_DATABASE_URL"])
    return cfg


def reset_schema() -> None:
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS analytics CASCADE"))
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(), "head")


@pytest.fixture(scope="session")
def engine():
    reset_schema()
    return get_engine()


# --- synthetic test package -----------------------------------------------------------------
# Small, deterministic CSV package in the PRE_SEED file format, used only to exercise the
# importer and engines in tests. It is not product data and is never imported outside tests.

INSTITUTIONS = [("INST001", "테스트대학교", "서울", "PRIVATE"), ("INST002", "검증대학교", "부산", "NATIONAL")]
MAJORS = [("MAJ001", "경영학과", "BUSINESS"), ("MAJ002", "컴퓨터공학과", "ENGINEERING")]
ROLES = [("ROLE001", "MARKETING", "브랜드 마케터"), ("ROLE002", "DATA", "데이터 애널리스트"),
         ("ROLE003", "ENGINEERING", "소프트웨어 엔지니어"), ("ROLE004", "FOUNDER", "창업자")]
ORGS = [("ORG001", "테스트전자", "TECH_MANUFACTURING", "ENTERPRISE"),
        ("ORG002", "테스트플랫폼", "TECH_PLATFORM", "LARGE"),
        ("ORG003", "스타트업 A", "STARTUP", "SMALL")]


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def build_package(directory: Path, per_group: int = 40, mutate=None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    persons, educations, events, sources = [], [], [], []
    n = we = 0
    for inst in INSTITUTIONS:
        for major in MAJORS:
            for i in range(per_group):
                n += 1
                pid = f"PSP{n:05d}"
                ref = f"TEST_{pid}"
                gy = 2015 + (i % 8)
                persons.append([pid, "PROFESSIONAL", "PRE_SEED", ref, "PRE_SEED_FILE"])
                educations.append([f"EDU{n:05d}", pid, inst[0], major[0], gy, "BACHELOR",
                                   "PRE_SEED", ref, "PRE_SEED_FILE"])
                first_role = ROLES[i % 3][0]
                second_role = ROLES[(i + 1) % 3][0]
                jobs = [(first_role, ORGS[i % 2][0], date(gy, 3, 1), date(gy + 2, 3, 1)),
                        (second_role, ORGS[(i + 1) % 3][0], date(gy + 2, 4, 1), None)]
                for role, org, start, end in jobs:
                    we += 1
                    weid = f"WE{we:07d}"
                    events.append([weid, pid, "EMPLOYMENT", org, role, start.isoformat(),
                                   end.isoformat() if end else "", str(end is None),
                                   "PRE_SEED", ref, "PRE_SEED_FILE"])
                    sources.append([f"WES{we:07d}", weid, ref, "PRE_SEED_FILE",
                                    "organization_id,role_id,start_date,end_date,is_current,"
                                    "event_type", "", "True"])
    tables = {"persons": persons, "educations": educations, "work_events": events,
              "work_event_sources": sources}
    if mutate:
        mutate(tables)
    _write(directory / "institutions.csv",
           ["institution_id", "institution_name", "region", "institution_type"], INSTITUTIONS)
    _write(directory / "majors.csv", ["major_id", "major_name", "major_family"], MAJORS)
    _write(directory / "roles.csv", ["role_id", "job_family", "role_name"], ROLES)
    _write(directory / "organizations.csv",
           ["organization_id", "organization_name", "industry", "company_size_band"], ORGS)
    _write(directory / "persons.csv",
           ["person_id", "user_stage", "data_layer", "source_ref", "source_type"], persons)
    _write(directory / "educations.csv",
           ["education_id", "person_id", "institution_id", "major_id", "graduation_year",
            "degree_type", "data_layer", "source_ref", "source_type"], educations)
    _write(directory / "work_events.csv",
           ["work_event_id", "person_id", "event_type", "organization_id", "role_id",
            "start_date", "end_date", "is_current", "data_layer", "source_ref", "source_type"],
           events)
    _write(directory / "work_event_sources.csv",
           ["work_event_source_id", "work_event_id", "source_ref", "source_type",
            "supported_fields", "evidence_confidence", "is_primary"], sources)
    return directory


@pytest.fixture(scope="session")
def imported(engine, tmp_path_factory):
    from hellomyme.domain.aggregation import run_aggregation
    from hellomyme.importer.preseed import run_import

    pkg = build_package(tmp_path_factory.mktemp("pkg"))
    report = run_import(engine, pkg, as_of=AS_OF, dataset_version="test")
    run_aggregation(engine, as_of=AS_OF)
    return {"dir": pkg, "report": report}
