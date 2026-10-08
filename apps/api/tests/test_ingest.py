"""Career ingestion: AI JSON -> checks -> field review -> SEED load, standardisation queue,
identity candidates. Synthetic names only; each test runs in a transaction that is rolled back."""
import copy
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from hellomyme.ingest.pipeline import (
    IngestError,
    accept_pending,
    approve,
    receive,
    resolve_mapping,
    review_field,
)
from tests.conftest import AS_OF

INTAKE = {"collector": "ops-test", "source_type": "PUBLIC_PROFILE",
          "permitted_use": "AGGREGATE_ONLY", "legal_basis": "test fixture",
          "model_version": "test-model", "prompt_version": "p1", "as_of": AS_OF}


def ev(asset, line):
    return [{"asset_id": asset, "text": line}]


# One person, four jobs (the Pepsi -> Nivea -> 밀리의서재 -> startup shape), the first job
# repeated on the second screenshot because the captures overlap.
DOC = {
    "schema_version": "career_extraction.v1",
    "submission_id": "SUB-0001",
    "assets": [{"asset_id": "A1", "page_order": 1}, {"asset_id": "A2", "page_order": 2}],
    "person": {"display_name_raw": "김인제", "evidence": ev("A1", "김인제")},
    "educations": [{"local_id": "E1", "institution_raw": "인제스트대학교", "major_raw": "인제스트학과",
                    "degree_raw": "학사", "start": {"value": "2014", "precision": "YEAR"},
                    "end": {"value": "2018", "precision": "YEAR"},
                    "evidence": ev("A1", "인제스트대학교 · 학사, 인제스트학과 2014 - 2018")}],
    "work_events": [
        {"local_id": "W1", "organization_raw": "인제스트컴퍼니", "role_raw": "그로스 해커",
         "employment_type_raw": "정규직", "event_type_hint": "EMPLOYMENT",
         "start": {"value": "2018-03", "precision": "MONTH"},
         "end": {"value": "2020-02", "precision": "MONTH"}, "is_current": False,
         "evidence": ev("A1", "그로스 해커 · 인제스트컴퍼니 정규직 2018년 3월 - 2020년 2월")},
        {"local_id": "W2", "organization_raw": "니베아테스트", "role_raw": "브랜드 매니져",
         "event_type_hint": "EMPLOYMENT", "start": {"value": "2020-03", "precision": "MONTH"},
         "end": {"value": "2022-06", "precision": "MONTH"}, "is_current": False,
         "evidence": ev("A1", "브랜드 매니저 · 니베아테스트 2020년 3월 - 2022년 6월")},
        {"local_id": "W3", "organization_raw": "밀리테스트", "role_raw": "그로스 해커",
         "event_type_hint": "UNKNOWN", "start": {"value": "2022-07", "precision": "MONTH"},
         "end": {"value": "2024-01", "precision": "MONTH"}, "is_current": False,
         "confidence": {"role": 0.5},
         "evidence": ev("A2", "그로스 해커 · 밀리테스트 2022년 7월 - 2024년 1월")},
        {"local_id": "W4", "organization_raw": "인제스타트업", "role_raw": "대표",
         "event_type_hint": "STARTUP", "start": {"value": "2024", "precision": "YEAR"},
         "is_current": True, "evidence": ev("A2", "대표 · 인제스타트업 2024 - 현재")},
        {"local_id": "W1b", "organization_raw": "인제스트컴퍼니", "role_raw": "그로스 해커",
         "employment_type_raw": "정규직", "event_type_hint": "EMPLOYMENT",
         "start": {"value": "2018-03", "precision": "MONTH"},
         "end": {"value": "2020-02", "precision": "MONTH"}, "is_current": False,
         "evidence": ev("A2", "그로스 해커 · 인제스트컴퍼니 2018년 3월 - 2020년 2월")},
    ],
}


@pytest.fixture
def conn(engine):
    with engine.connect() as c:
        tx = c.begin()
        _reference(c)
        yield c
        tx.rollback()


def _taxonomy(c, kind):
    tid = c.execute(text("SELECT taxonomy_id FROM taxonomy WHERE taxonomy_type = :k AND status = 'ACTIVE'"),
                    {"k": kind}).scalar()
    return tid or c.execute(text(
        """INSERT INTO taxonomy (taxonomy_type, name, version, status)
           VALUES (:k, 'ingest test', 'ingest-test', 'ACTIVE') RETURNING taxonomy_id"""),
        {"k": kind}).scalar_one()


def _node(c, kind, code, name, alias, parent=None):
    nid = c.execute(text(
        """INSERT INTO taxonomy_node (taxonomy_id, parent_node_id, code, canonical_name, display_name, depth)
           VALUES (:t, :p, :c, :n, :n, 1) RETURNING taxonomy_node_id::text"""),
        {"t": _taxonomy(c, kind), "p": parent, "c": code, "n": name}).scalar_one()
    if alias:
        c.execute(text("INSERT INTO taxonomy_alias (taxonomy_node_id, alias_text) VALUES (:n, :a)"),
                  {"n": nid, "a": alias})
    return nid


def _reference(c):
    tv = {k: c.execute(text(
        """INSERT INTO taxonomy_version (taxonomy, version) VALUES (:k, 'ingest-test')
           ON CONFLICT (taxonomy, version) DO UPDATE SET version = EXCLUDED.version
           RETURNING taxonomy_version_id"""), {"k": k}).scalar_one()
        for k in ("ORGANIZATION", "INSTITUTION")}
    c.execute(text("INSERT INTO organization (name, taxonomy_version_id) VALUES ('인제스트컴퍼니', :v)"),
              {"v": tv["ORGANIZATION"]})
    c.execute(text("INSERT INTO institution (name, taxonomy_version_id) VALUES ('인제스트대학교', :v)"),
              {"v": tv["INSTITUTION"]})
    root = _node(c, "ROLE", "ING_R1", "인제스트 비즈니스", None)
    _node(c, "ROLE", "ING_R2", "인제스트 그로스", "그로스 해커", parent=root)
    _node(c, "ROLE", "ING_R3", "인제스트 브랜드", None, parent=root)
    _node(c, "MAJOR", "ING_M1", "인제스트학", "인제스트학과")


def _fields(c, run_id, status=None):
    return c.execute(text(
        """SELECT extraction_field_id::text AS id, entity_type, local_id, field_name, raw_value,
                  normalized_ref, review_status
           FROM extraction_field WHERE parse_run_id = CAST(:r AS uuid)
             AND (CAST(:s AS text) IS NULL OR review_status = :s)
           ORDER BY local_id, field_name"""), {"r": run_id, "s": status}).all()


def test_capture_to_seed_person(conn):
    out = receive(conn, json.dumps(DOC, ensure_ascii=False), **INTAKE)
    assert out["status"] == "NEEDS_REVIEW", out
    assert {i["code"] for i in out["issues"]} == {"DUPLICATE_EVENT", "EVENT_TYPE_UNKNOWN"}
    assert {(u["kind"], u["raw"]) for u in out["unmapped"]} == {
        ("ORGANIZATION", "니베아테스트"), ("ORGANIZATION", "밀리테스트"),
        ("ORGANIZATION", "인제스타트업"), ("ROLE", "브랜드 매니져"), ("ROLE", "대표")}
    run = out["parse_run_id"]

    # The same output again is the same run; nothing is duplicated.
    again = receive(conn, json.dumps(DOC, ensure_ascii=False), **INTAKE)
    assert again["replayed"] and again["parse_run_id"] == run

    pending = {(f.local_id, f.field_name): f for f in _fields(conn, run, "PENDING")}
    # Unknown names, a low-confidence reading and an unclassified job wait for a person;
    # the duplicate W1b was dropped, the known names were accepted on their own.
    assert set(pending) == {("W2", "organization"), ("W2", "role"), ("W3", "organization"),
                            ("W3", "role"), ("W3", "event_type"), ("W4", "organization"),
                            ("W4", "role")}
    assert not [f for f in _fields(conn, run) if f.local_id == "W1b"]
    with pytest.raises(IngestError, match="still need review"):
        approve(conn, run)

    # The AI misread the role; the reviewer types what the screenshot shows.
    review_field(conn, pending[("W2", "role")].id, "CORRECTED", corrected_value="브랜드 매니저")
    review_field(conn, pending[("W3", "event_type")].id, "CORRECTED", corrected_value="EMPLOYMENT")
    with pytest.raises(IngestError, match="not a valid start"):
        start = next(f for f in _fields(conn, run) if (f.local_id, f.field_name) == ("W3", "start"))
        review_field(conn, start.id, "CORRECTED", corrected_value="2022년 7월")
    assert accept_pending(conn, run) == 5

    loaded = approve(conn, run)
    assert loaded["loaded"] and len(loaded["work_event_ids"]) == 4
    assert len(loaded["education_ids"]) == 1
    assert approve(conn, run) == {"person_id": loaded["person_id"], "loaded": False}

    # Career order comes from the dates at query time: 1st, 2nd, 3rd job, then the current one.
    jobs = conn.execute(text(
        """SELECT w.organization_raw, w.role_raw, w.organization_id IS NOT NULL AS org_mapped,
                  n.code AS role, w.event_type, w.employment_type, w.start_date::text,
                  w.start_date_precision, w.is_current, w.normalization_status,
                  s.supported_fields, s.evidence_text, a.external_asset_id
           FROM work_event w LEFT JOIN taxonomy_node n ON n.taxonomy_node_id = w.role_taxonomy_node_id
           JOIN work_event_source s USING (work_event_id) JOIN source_asset a USING (source_asset_id)
           WHERE w.person_id = :p ORDER BY w.start_date"""), {"p": loaded["person_id"]}).all()
    assert [(j.organization_raw, j.role_raw) for j in jobs] == [
        ("인제스트컴퍼니", "그로스 해커"), ("니베아테스트", "브랜드 매니저"),
        ("밀리테스트", "그로스 해커"), ("인제스타트업", "대표")]
    first, second, third, last = jobs
    assert (first.org_mapped, first.role, first.employment_type, first.normalization_status) == (
        True, "ING_R2", "FULL_TIME", "MAPPED")
    assert first.external_asset_id == "A1" and "인제스트컴퍼니" in first.evidence_text
    assert second.employment_type is None  # the profile did not say; never assumed full-time
    assert (second.role, second.normalization_status) == (None, "UNMAPPED")
    assert (third.event_type, third.external_asset_id) == ("EMPLOYMENT", "A2")
    assert (last.event_type, last.start_date, last.start_date_precision, last.is_current) == (
        "STARTUP", "2024-01-01", "YEAR", True)
    assert "end_date" not in last.supported_fields

    person = conn.execute(text(
        """SELECT p.origin_layer, pp.display_name, r.data_layer, r.raw_payload, e.admission_year,
                  e.graduation_year, e.degree_type, e.normalization_status
           FROM person p JOIN person_pii pp USING (person_id)
           JOIN source_record r ON r.source_id = p.primary_source_id
           JOIN education e USING (person_id) WHERE p.person_id = :p"""),
        {"p": loaded["person_id"]}).one()
    assert (person.origin_layer, person.display_name, person.data_layer) == ("SEED", "김인제", "SEED")
    assert "김인제" not in json.dumps(person.raw_payload, ensure_ascii=False)  # name only in PII
    assert (person.admission_year, person.graduation_year, person.degree_type,
            person.normalization_status) == (2014, 2018, "BACHELOR", "MAPPED")
    sub = conn.execute(text("SELECT status, loaded_person_id::text FROM source_submission")).one()
    assert tuple(sub) == ("LOADED", loaded["person_id"])


def test_mapping_queue_standardises_without_touching_raw(conn):
    run = receive(conn, json.dumps(DOC, ensure_ascii=False), **INTAKE)["parse_run_id"]
    accept_pending(conn, run)
    person = approve(conn, run)["person_id"]
    q = conn.execute(text(
        """SELECT mapping_queue_id::text FROM mapping_queue
           WHERE entity_kind = 'ORGANIZATION' AND raw_value = '니베아테스트'""")).scalar_one()
    with pytest.raises(IngestError, match="exactly one"):
        resolve_mapping(conn, q)
    res = resolve_mapping(conn, q, new_name="니베아테스트코리아")
    assert (res["status"], res["rows_filled"]) == ("NEW_ENTITY", 1)
    row = conn.execute(text(
        """SELECT w.organization_raw, o.name, w.normalization_status FROM work_event w
           JOIN organization o USING (organization_id)
           WHERE w.person_id = :p AND w.organization_raw = '니베아테스트'"""), {"p": person}).one()
    assert tuple(row) == ("니베아테스트", "니베아테스트코리아", "PARTIAL")  # role still unmapped

    # Role mapped to an existing node through the queue: the next capture maps on its own.
    role_q = conn.execute(text(
        "SELECT mapping_queue_id::text FROM mapping_queue WHERE raw_value = '대표'")).scalar_one()
    brand = conn.execute(text(
        "SELECT taxonomy_node_id::text FROM taxonomy_node WHERE code = 'ING_R3'")).scalar_one()
    with pytest.raises(IngestError, match="not a ROLE node"):
        major = conn.execute(text(
            "SELECT taxonomy_node_id::text FROM taxonomy_node WHERE code = 'ING_M1'")).scalar_one()
        resolve_mapping(conn, role_q, resolved_ref=major)
    assert resolve_mapping(conn, role_q, resolved_ref=brand)["rows_filled"] == 1

    doc = copy.deepcopy(DOC)
    doc["submission_id"] = "SUB-0002"
    doc["person"] = {"display_name_raw": "박인제", "evidence": ev("A1", "박인제")}
    out = receive(conn, json.dumps(doc, ensure_ascii=False), **INTAKE)
    refs = {(f.local_id, f.field_name): f for f in _fields(conn, out["parse_run_id"])}
    assert refs[("W2", "organization")].normalized_ref is not None
    assert refs[("W2", "organization")].review_status == "AUTO_ACCEPTED"
    assert refs[("W4", "role")].normalized_ref is not None
    occurrences = conn.execute(text(
        "SELECT occurrences FROM mapping_queue WHERE raw_value = '밀리테스트'")).scalar_one()
    assert occurrences == 2


@pytest.mark.parametrize("mutate, code", [
    (lambda d: d["work_events"][0].update(end={"value": "2017-01", "precision": "MONTH"}),
     "END_BEFORE_START"),
    (lambda d: d["work_events"][0].update(evidence=ev("A9", "?")), "EVIDENCE_ASSET_UNKNOWN"),
    (lambda d: d["work_events"][0].update(start={"value": "2018-03", "precision": "YEAR"}),
     "PRECISION_MISMATCH"),
    (lambda d: d["work_events"][3].update(end={"value": "2025", "precision": "YEAR"}),
     "CURRENT_WITH_END_DATE"),
    (lambda d: d["work_events"][3].update(start={"value": "2027", "precision": "YEAR"}),
     "START_AFTER_AS_OF"),
    (lambda d: d["work_events"][0].pop("evidence"), "SCHEMA"),
    (lambda d: d["work_events"][0].update(organization_id="ORG1"), "SCHEMA"),  # no canonical ids
])
def test_blocking_rules_reject_the_run(conn, mutate, code):
    doc = copy.deepcopy(DOC)
    mutate(doc)
    out = receive(conn, json.dumps(doc, ensure_ascii=False), **INTAKE)
    assert out["status"] == "REJECTED"
    assert code in {i["code"] for i in out["issues"] if i["severity"] == "BLOCK"}
    assert not _fields(conn, out["parse_run_id"])
    with pytest.raises(IngestError, match="REJECTED"):
        approve(conn, out["parse_run_id"])
    # The verbatim output is still kept for the record.
    assert conn.execute(text("SELECT raw_output IS NOT NULL FROM parse_run WHERE parse_run_id = :r"),
                        {"r": out["parse_run_id"]}).scalar_one()


def test_not_json_is_refused(conn):
    with pytest.raises(IngestError, match="not JSON"):
        receive(conn, "Sure! Here is the JSON: {", **INTAKE)


def test_parse_output_is_immutable_and_reparse_supersedes(conn):
    first = receive(conn, json.dumps(DOC, ensure_ascii=False), **INTAKE)["parse_run_id"]
    with pytest.raises(DBAPIError, match="immutable"), conn.begin_nested():
        conn.execute(text("UPDATE parse_run SET raw_output = '{}'::jsonb WHERE parse_run_id = :r"),
                     {"r": first})
    doc = copy.deepcopy(DOC)
    doc["work_events"][1]["role_raw"] = "브랜드 매니저"  # a better prompt reads it right
    second = receive(conn, json.dumps(doc, ensure_ascii=False), **{**INTAKE, "prompt_version": "p2"})
    states = dict(conn.execute(text("SELECT parse_run_id::text, status FROM parse_run")).all())
    assert states[first] == "SUPERSEDED" and states[second["parse_run_id"]] == "NEEDS_REVIEW"
    with pytest.raises(IngestError, match="SUPERSEDED"):
        approve(conn, first)


def test_same_person_twice_becomes_a_candidate_never_a_merge(conn):
    runs = []
    for collector in ("ops-a", "ops-b"):
        run = receive(conn, json.dumps(DOC, ensure_ascii=False),
                      **{**INTAKE, "collector": collector})["parse_run_id"]
        accept_pending(conn, run)
        runs.append(approve(conn, run))
    assert runs[0]["identity_candidates"] == 0 and runs[1]["identity_candidates"] == 1
    match = conn.execute(text(
        "SELECT candidate_person_id::text, target_person_id::text, status FROM identity_match")).one()
    assert tuple(match) == (runs[1]["person_id"], runs[0]["person_id"], "CANDIDATE")
    assert conn.execute(text("SELECT count(*) FROM person WHERE person_id IN (:a, :b)"),
                        {"a": runs[0]["person_id"], "b": runs[1]["person_id"]}).scalar_one() == 2


def test_ambiguous_name_is_queued_not_guessed(conn):
    # Two equally specific roles share the alias: the pipeline must not pick one.
    for code in ("ING_X1", "ING_X2"):
        _node(conn, "ROLE", code, f"인제스트 {code}", "애매한 직무")
    doc = copy.deepcopy(DOC)
    doc["work_events"] = [{**DOC["work_events"][0], "role_raw": "애매한 직무"}]
    out = receive(conn, json.dumps(doc, ensure_ascii=False), **INTAKE)
    role = next(f for f in _fields(conn, out["parse_run_id"]) if f.field_name == "role")
    assert (role.normalized_ref, role.review_status) == (None, "PENDING")
    assert {"kind": "ROLE", "raw": "애매한 직무"} in out["unmapped"]
