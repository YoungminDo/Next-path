import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from hellomyme.importer.preseed import ImportAborted, load_package, run_import, validate
from tests.conftest import AS_OF, build_package


def count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_import_report_counts(imported):
    report = imported["report"]
    assert report["status"] == "COMPLETED"
    assert report["imported"]["persons"] == 160
    assert report["imported"]["work_events"] == 320
    assert report["imported"]["work_event_sources"] == 320
    assert report["rejected_total"] == 0
    assert all(c["pass"] for c in report["integrity_checks"].values())
    rules = {r["rule"] for r in report["issues_by_rule"]}
    assert "PLACEHOLDER_ORGANIZATION" in rules


def test_reimport_is_idempotent(engine, imported):
    tables = ["person", "education", "work_event", "work_event_source", "source_record",
              "import_batch", "entity_key_map"]
    with engine.begin() as conn:
        before = {t: count(conn, t) for t in tables}
    again = run_import(engine, imported["dir"], as_of=AS_OF, dataset_version="test")
    assert again["status"] == "ALREADY_IMPORTED"
    with engine.begin() as conn:
        assert {t: count(conn, t) for t in tables} == before


def test_one_event_many_sources_model(engine, imported):
    with engine.begin() as conn:
        row = conn.execute(text(
            """SELECT s.supported_fields, r.source_type, r.data_layer
               FROM work_event_source s JOIN source_record r USING (source_id) LIMIT 1""")).first()
    assert set(row.supported_fields) == {"organization", "role", "start_date", "end_date",
                                         "is_current", "event_type"}
    assert (row.source_type, row.data_layer) == ("PRE_SEED_FILE", "PRE_SEED")


def test_record_level_rules_reject_without_repair(tmp_path):
    def mutate(t):
        t["work_events"][0][5], t["work_events"][0][6] = "2020-05-01", "2020-01-01"  # end<start
        t["work_events"][3][5] = "2027-01-01"  # current job starting after as-of
        t["persons"][0][1] = "JOB_SEEKER"  # has a current employment

    v = validate(load_package(build_package(tmp_path, per_group=5, mutate=mutate)), AS_OF)
    rules = {(i.severity, i.rule_code) for i in v.issues}
    assert ("REJECT", "END_BEFORE_START") in rules
    assert ("REJECT", "START_AFTER_AS_OF") in rules
    assert ("WARNING", "JOB_SEEKER_WITH_CURRENT_EMPLOYMENT") in rules
    # Rejected events are dropped together with their evidence rows, nothing is "fixed".
    assert len(v.work_events) == 40 - 2
    assert len(v.sources) == 40 - 2
    assert not v.critical()


def test_critical_violation_aborts_whole_import(engine, tmp_path):
    def mutate(t):
        t["work_events"].append(list(t["work_events"][0]))  # duplicate work_event_id

    pkg = build_package(tmp_path, per_group=3, mutate=mutate)
    with engine.begin() as conn:
        batches = count(conn, "import_batch")
    with pytest.raises(ImportAborted) as exc:
        run_import(engine, pkg, as_of=AS_OF, dataset_version="dup")
    assert exc.value.report["status"] == "ABORTED"
    with engine.begin() as conn:
        assert count(conn, "import_batch") == batches


def test_source_record_is_append_only(engine, imported):
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(text("UPDATE source_record SET metadata = '{}'::jsonb"))
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(text("DELETE FROM source_record"))


def test_preseed_persons_cannot_be_identity_matched(engine, imported):
    with pytest.raises(DBAPIError), engine.begin() as conn:
        ids = conn.execute(text("SELECT person_id FROM person LIMIT 2")).scalars().all()
        conn.execute(text(
            "INSERT INTO identity_match (candidate_person_id, target_person_id, evidence) "
            "VALUES (:a, :b, '{}'::jsonb)"), {"a": ids[0], "b": ids[1]})


def test_dataset_versions_reusing_ids_stay_distinct(engine, tmp_path):
    # v1.1 and v1.2 both use PSP00001 for *different* generated people.
    pkg = build_package(tmp_path, per_group=2)
    with engine.begin() as conn:
        before = count(conn, "person")
    report = run_import(engine, pkg, as_of=AS_OF, dataset_version="test-other-version")
    assert report["imported"]["persons"] == 8
    with engine.begin() as conn:
        assert count(conn, "person") == before + 8
