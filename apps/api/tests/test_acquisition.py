"""Acquisition flows end to end on the synthetic cohort from test_career_query."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hellomyme.main import create_app
from tests.test_career_query import ids  # noqa: F401  (module fixture: imports the cohort)


@pytest.fixture(scope="module")
def client(ids):  # noqa: F811
    return TestClient(create_app())


def anon() -> dict:
    return {"X-Anonymous-Session": uuid.uuid4().hex}


def login(client, subject: str) -> dict:
    r = client.post("/auth/login", json={"provider": "DEV", "token": f"dev:{subject}"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['session_token']}"}


def save(client, headers, payload, draft_id=None):
    r = client.post("/acq/draft", headers=headers, json={"draft_id": draft_id, "payload": payload})
    assert r.status_code == 200, r.text
    return r.json()["draft_id"]


def step(client, headers, draft_id, name):
    r = client.post(f"/acq/draft/{draft_id}/result", headers=headers, json={"step": name})
    assert r.status_code == 200, r.text
    return r.json()


def student(ids):  # noqa: F811
    return {"user_type": "STUDENT", "education": {
        "institution_id": ids["inst"], "major_node_id": ids["M3"],
        "admission_year": 2016, "graduation_year": 2020}}


def test_options_match_aliases(client, ids):  # noqa: F811
    majors = client.get("/acq/options/majors", params={"q": "경영학과"}).json()
    assert any(m["code"] == "M3" and m["matched_alias"] == "경영학과" for m in majors)
    roles = client.get("/acq/options/roles", params={"depth": 2}).json()
    assert {"R2", "R2B"} <= {r["code"] for r in roles}


def merge(client, h, draft, subject):
    auth = login(client, subject)
    hdr = {**auth, **h, "Idempotency-Key": uuid.uuid4().hex}
    body = {"draft_id": draft, "consent_policy_version": "v1"}
    r = client.post("/auth/merge-draft", headers=hdr, json=body)
    assert r.status_code == 200 and r.json()["merged"] is True, r.text
    again = client.post("/auth/merge-draft", headers=hdr, json=body).json()
    assert again["merged"] is False and again["person_id"] == r.json()["person_id"]
    return auth, r.json()["person_id"]


def test_student_sees_only_a_teaser_before_login(client, ids):  # noqa: F811
    h = anon()
    draft = save(client, h, student(ids))
    t = step(client, h, draft, "teaser")
    assert t["locked"] and t["data_basis"] == "SIMULATION"
    assert (t["base"]["exact_n"], t["base"]["effective_n"], t["n_directions"]) == (10, 45, 2)
    assert "cells" not in t["base"] and "result" not in t  # the answer itself stays behind login
    for locked in ("first_roles", "intent_paths"):
        r = client.post(f"/acq/draft/{draft}/result", headers=h, json={"step": locked})
        assert r.status_code == 422


def test_student_flow_after_login(client, engine, ids):  # noqa: F811
    h = anon()
    draft = save(client, h, student(ids))
    auth, person_id = merge(client, h, draft, "acq-student")

    first = client.get("/acq/me/step/first_roles", headers=auth).json()["result"]
    assert [(c["code"], c["n"]) for c in first["cells"]] == [("R2", 30), ("R2B", 15)]

    intent = {"surface": "STUDENT_FIRST_ROLE", "target_kind": "ROLE", "target_node_id": ids["R2B"]}
    r = client.post("/acq/me/intent", headers=auth, json={"intent": intent})
    assert r.status_code == 200 and len(r.json()["intent_event_ids"]) == 1

    with engine.begin() as conn:
        row = conn.execute(text(
            """SELECT i.intent_event_id, i.target_kind, i.source_surface, n.code
               FROM intent_event i JOIN taxonomy_node n ON n.taxonomy_node_id =
                    i.target_taxonomy_node_id WHERE i.person_id = :p"""), {"p": person_id}).one()
        horizons = conn.execute(text(
            "SELECT horizon_months FROM intent_followup WHERE intent_event_id = :i ORDER BY 1"),
            {"i": row.intent_event_id}).scalars().all()
        edu = conn.execute(text(
            """SELECT admission_year, admission_date_precision, verification_level
               FROM education WHERE person_id = :p"""), {"p": person_id}).one()
    assert (row.target_kind, row.source_surface, row.code) == ("ROLE", "STUDENT_FIRST_ROLE", "R2B")
    assert horizons == [6, 12]
    assert tuple(edu) == (2016, "YEAR", "SELF_REPORTED")

    me = client.get("/acq/me", headers=auth).json()
    paths = me["intent_paths"]["paths"]
    assert me["intent_paths"]["target_basis"] == "INTENT"
    assert [([s["label"] for s in x["path"]], x["n"]) for x in paths["paths"]] == [
        (["데이터·AI"], 15), (["마케팅", "데이터·AI"], 10)]
    assert me["deep_dive"]["unlocked"] is False and me["deep_dive"]["content"] is None
    before = me["balance_tube"]

    u = client.post("/acq/me/unlock", headers={**auth, "Idempotency-Key": uuid.uuid4().hex}).json()
    assert u["unlocked"] and u["charged"] and u["balance_tube"] == before - u["cost_tube"]
    assert u["content"]["company_size"][0] == {"key": "LARGE", "label": "LARGE", "n": 25}
    u2 = client.post("/acq/me/unlock", headers={**auth, "Idempotency-Key": uuid.uuid4().hex})
    assert u2.json()["charged"] is False  # already entitled
    assert client.get("/acq/me", headers=auth).json()["deep_dive"]["unlocked"] is True


def test_professional_flow_after_login(client, ids):  # noqa: F811
    h = anon()
    payload = {**student(ids), "user_type": "PROFESSIONAL",
               "current_job": {"organization_name": "어딘가", "role_node_id": ids["R3"],
                               "start_year": 2021}}
    draft = save(client, h, payload)
    assert step(client, h, draft, "teaser")["base"]["effective_n"] == 30
    auth, _ = merge(client, h, draft, "acq-pro")

    nxt = client.get("/acq/me/step/next_roles", headers=auth).json()["result"]
    assert [(c["code"], c["n"]) for c in nxt["cells"]] == [("STAYED", 20), ("R2B", 10)]

    job = {"organization_name": "첫회사", "role_node_id": ids["R3B"], "start_year": 2018,
           "end_year": 2020}
    key = {**auth, "Idempotency-Key": uuid.uuid4().hex}
    added = client.post("/acq/me/jobs", headers=key, json={"job": job}).json()
    assert added["work_event_id"] and added["reward"] is None  # reward_v2: only sign-up pays
    assert client.post("/acq/me/jobs", headers=key, json={"job": job}).json()["replayed"] is True
    similar = client.get("/acq/me/step/similar_paths", headers=auth).json()["result"]
    assert similar["suppressed"]  # nobody went data -> marketing in this cohort

    intent = {"surface": "PROFESSIONAL_NEXT_ROLE", "target_kind": "ROLE",
              "target_node_id": ids["R2B"]}
    client.post("/acq/me/intent", headers=auth, json={"intent": intent})
    p = client.get("/acq/me", headers=auth).json()["intent_paths"]
    # Too few share both steps, so the current-role cohort is used and said so.
    assert p["cohort_basis"] == "CURRENT_ROLE"
    assert (p["paths"]["n_people"], p["paths"]["median_months"]) == (10, 23)


def test_undecided_intent_uses_most_common_destination(client, ids):  # noqa: F811
    h = anon()
    auth, _ = merge(client, h, save(client, h, student(ids)), "acq-undecided")
    client.post("/acq/me/intent", headers=auth, json={"intent": {
        "surface": "STUDENT_FIRST_ROLE", "target_kind": "UNDECIDED"}})
    out = client.get("/acq/me", headers=auth).json()["intent_paths"]
    assert out["target_basis"] == "MOST_COMMON" and out["paths"]["target"]["label"] == "마케팅"


def test_invalid_input_is_rejected(client, ids):  # noqa: F811
    h = anon()
    bad = {**student(ids), "education": {**student(ids)["education"], "admission_year": 2021}}
    assert client.post("/acq/draft", headers=h, json={"payload": bad}).status_code == 422
    # An id that is not in the list is refused when the draft is saved.
    r = client.post("/acq/draft", headers=h, json={"payload": {**student(ids), "education": {
        **student(ids)["education"], "major_node_id": str(uuid.uuid4())}}})
    assert r.status_code == 422
    draft = save(client, h, student(ids))
    other = anon()
    assert client.post(f"/acq/draft/{draft}/result", headers=other,
                       json={"step": "teaser"}).status_code == 404


def test_unlisted_school_or_major_is_typed_in_and_still_answered(client, engine, ids):  # noqa: F811
    """Not in the pick list: the typed name is accepted, the cohort leaves that dimension out,
    the name is kept as typed and queued for standardisation."""
    h = anon()
    payload = {"user_type": "STUDENT", "education": {
        "institution_raw": "  목록밖대학교 ", "major_node_id": ids["M3"],
        "admission_year": 2016, "graduation_year": 2020}}
    draft = save(client, h, payload)
    t = step(client, h, draft, "teaser")
    assert t["base"]["effective_n"] >= 45  # every school with that major and those years
    auth, person_id = merge(client, h, draft, "acq-unlisted")
    with engine.begin() as conn:
        edu = conn.execute(text(
            """SELECT institution_raw, institution_id, major_taxonomy_node_id IS NOT NULL AS major,
                      normalization_status FROM education WHERE person_id = :p"""),
            {"p": person_id}).one()
        assert tuple(edu) == ("목록밖대학교", None, True, "PARTIAL")
        assert conn.execute(text(
            "SELECT occurrences FROM mapping_queue WHERE raw_value = '목록밖대학교'")).scalar() >= 1
    me = client.get("/acq/me", headers=auth)
    assert me.status_code == 200, me.text
    assert client.get("/acq/me/step/first_roles", headers=auth).status_code == 200

    both = {"user_type": "STUDENT", "education": {
        "institution_raw": "목록밖대학교", "major_raw": "목록밖학과",
        "admission_year": 2016, "graduation_year": 2020}}
    h2 = anon()
    assert step(client, h2, save(client, h2, both), "teaser")["locked"]
    neither = {"user_type": "STUDENT", "education": {"admission_year": 2016, "graduation_year": 2020}}
    r = client.post("/acq/draft", headers=anon(), json={"draft_id": None, "payload": neither})
    assert r.status_code == 422


def test_unlisted_names_compare_with_the_nearest_group(client, ids):  # noqa: F811
    """A typed name the list does not know still says something: 경영정보 is close to 경영학, a
    school named after 서울 is a 서울 school. The group is then the one a listed answer gets
    (same size, same widening), not everyone of those years; for students and professionals."""
    h = anon()
    years = {"admission_year": 2016, "graduation_year": 2020}
    listed = step(client, h, save(client, h, student(ids)), "teaser")["base"]
    pro_job = {"current_job": {"organization_name": "어딘가", "role_node_id": ids["R3"],
                               "start_year": 2021}}
    listed_pro = step(client, h, save(client, h, {**student(ids), "user_type": "PROFESSIONAL",
                                                  **pro_job}), "teaser")["base"]
    for edu, similar in (
            ({"institution_id": ids["inst"], "major_raw": "글로벌경영정보학부"}, {"major": "SIMILAR"}),
            ({"institution_raw": "서울목록밖대학교", "major_node_id": ids["M3"]}, {"region": "서울"}),
            ({"institution_raw": "서울목록밖대학교", "major_raw": "경영정보학과"},
             {"region": "서울", "major": "SIMILAR"})):
        for payload, want in (({"user_type": "STUDENT"}, listed),
                              ({"user_type": "PROFESSIONAL", **pro_job}, listed_pro)):
            t = step(client, h, save(client, h, {**payload, "education": {**edu, **years}}),
                     "teaser")
            base = t["base"]
            assert (base["effective_n"], base["fallback_reason"]) == (
                want["effective_n"], want["fallback_reason"]), (edu, payload["user_type"])
            assert base["effective_filters"]["similar"] == similar
            assert base["exact_n"] == 0  # nobody on record has exactly the typed name
            assert t["unlisted"]


def test_similar_major_and_region_rules():
    from hellomyme.domain.acquisition import similar_majors, similar_region
    from hellomyme.domain.career_query import Taxonomy

    def node(label, depth, parent=None):
        return {"code": label, "label": label, "depth": depth, "parent": parent}
    majors = Taxonomy("MAJOR", "t", {
        "F0": node("사회과학", 1), "F1": node("경영·경제", 2, "F0"),
        "F2": node("수학·통계·데이터", 2, "F0"), "F3": node("언어·문학", 2, "F0"),
        "L1": node("경영학과", 3, "F1"), "L2": node("경제학과", 3, "F1"),
        "L3": node("통계학과", 3, "F2"), "L4": node("수학과", 3, "F2"),
        "L5": node("국어국문학과", 3, "F3")})
    assert similar_majors(majors, "글로벌경영학부") == (("L1",), "SIMILAR")
    assert similar_majors(majors, "경영정보학과") == (("L1",), "SIMILAR")
    assert similar_majors(majors, "수학교육과") == (("L4",), "SIMILAR")
    assert similar_majors(majors, "데이터사이언스학과") == (("F2",), "FAMILY")
    assert similar_majors(majors, "독어독문학과") == (("F3",), "FAMILY")
    assert similar_majors(majors, "국어교육과") == (("L5",), "SIMILAR")  # starts the same way
    assert similar_majors(majors, "QA테스트학과") == ((), None)
    assert similar_region("부산목록밖대학교") == "부산"
    assert similar_region("충청남도 목록밖대학") == "충남"
    assert similar_region("수원목록밖대") == "경기"
    assert similar_region("QA테스트대학교") is None


def test_typed_names_the_list_knows_are_matched(client, ids):  # noqa: F811
    """'경영학과' is how people write the major whose list name is 경영학 (an alias): it must
    count as the listed major, not as an unknown one that drops the major from the cohort."""
    h = anon()
    r = client.post("/acq/draft", headers=h, json={"draft_id": None, "payload": {
        "user_type": "STUDENT", "education": {
            "institution_id": ids["inst"], "major_raw": "경영학과",
            "admission_year": 2016, "graduation_year": 2020}}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["payload"]["education"]["major_node_id"] == ids["M3"]
    assert body["payload"]["education"]["major_raw"] == "경영학과"  # typed text kept
    assert body["unlisted"] == []
    t = step(client, h, body["draft_id"], "teaser")
    listed = step(client, h, save(client, h, student(ids)), "teaser")  # picked from the list
    assert t["base"] == listed["base"] and t["unlisted"] == []


def test_bad_ids_are_refused_not_500(client, ids):  # noqa: F811
    for edu in ({"institution_id": "x", "major_node_id": ids["M3"]},
                {"institution_id": "00000000-0000-0000-0000-000000000000", "major_node_id": ids["M3"]},
                {"institution_id": ids["inst"], "major_node_id": "", "major_raw": " "}):
        r = client.post("/acq/draft", headers=anon(), json={"draft_id": None, "payload": {
            "user_type": "STUDENT", "education": {**edu, "admission_year": 2016,
                                                  "graduation_year": 2020}}})
        assert r.status_code == 422, (edu, r.status_code, r.text)


def test_unlock_key_unchanged_for_payloads_without_typed_school(ids):  # noqa: F811
    """Entitlements bought before typed names existed must still match (no second charge)."""
    import hashlib
    import json

    from hellomyme.domain.acquisition import AcquisitionPayload, insight_key
    p = AcquisitionPayload.model_validate(student(ids))
    old_basis = {"schema_version": "acq_v1", "user_type": "STUDENT", "education": {
        "institution_id": ids["inst"], "major_node_id": ids["M3"], "major_raw": None,
        "admission_year": 2016, "graduation_year": 2020}, "current_job": None, "first_job": None,
        "first_job_is_current": False, "gender_code": None}
    old = hashlib.sha256(json.dumps({"p": old_basis, "t": "T"}, sort_keys=True).encode()).hexdigest()
    assert insight_key(p, "T") == old


def test_a_returning_member_sees_what_changes_and_decides(client, engine, ids):  # noqa: F811
    """A student who now works answers again: login shows before/after (nothing applied yet); on
    "이걸로 바꾸기" the new answers become the profile, old records withdrawn, not overwritten."""
    h = anon()
    auth, person_id = merge(client, h, save(client, h, student(ids)), "acq-returning")

    def merge_again(payload):
        h2 = anon()
        d = save(client, h2, payload)
        r = client.post("/auth/merge-draft", json={"draft_id": d, "consent_policy_version": "v1"},
                        headers={**auth, **h2, "Idempotency-Key": uuid.uuid4().hex})
        assert r.status_code == 200 and r.json()["merged"] is False, r.text
        return d, r.json()["changes"]

    pro = {"user_type": "PROFESSIONAL", "education": {
        "institution_raw": "목록밖대학교", "major_node_id": ids["M3"],
        "admission_year": 2017, "graduation_year": 2021},
        "current_job": {"organization_name": "새회사", "role_node_id": ids["R3B"], "start_year": 2023}}
    draft, changes = merge_again(pro)
    assert [c["field"] for c in changes] == ["user_type", "education", "current_job"]
    assert changes[0] == {"field": "user_type", "before": "학생", "after": "직장인"}
    assert changes[1]["after"].startswith("목록밖대학교 · 경영학 · 2017–2021")
    assert changes[2]["before"] is None and changes[2]["after"].startswith("새회사 · 데이터 분석 · 2023~")
    assert client.get("/acq/me", headers=auth).json()["profile"]["user_type"] == "STUDENT"  # not yet

    other = login(client, "acq-returning-other")
    assert client.post("/acq/me/apply-draft", json={"draft_id": draft},
                       headers=other).status_code == 404
    r = client.post("/acq/me/apply-draft", json={"draft_id": draft}, headers=auth)
    assert r.status_code == 200 and r.json()["applied"] == ["current_job", "education", "user_type"]
    assert client.post("/acq/me/apply-draft", json={"draft_id": draft},
                       headers=auth).json()["applied"] == []  # once per draft
    profile = client.get("/acq/me", headers=auth).json()["profile"]
    assert profile["user_type"] == "PROFESSIONAL"
    assert profile["education"]["admission_year"] == 2017
    assert profile["current_job"]["role_node_id"] == ids["R3B"]

    # Same company and start year, another role: a correction (the old job is withdrawn).
    fixed = {**pro, "current_job": {**pro["current_job"], "role_node_id": ids["R3"]}}
    draft2, changes = merge_again(fixed)
    assert [c["field"] for c in changes] == ["current_job"]
    assert client.post("/acq/me/apply-draft", json={"draft_id": draft2},
                       headers=auth).json()["applied"] == ["current_job"]
    _, same = merge_again(fixed)
    assert same == []  # nothing left to change
    with engine.begin() as conn:
        rows = conn.execute(text(
            """SELECT 'edu' AS k, retracted_at IS NOT NULL AS gone FROM education WHERE person_id = :p
               UNION ALL SELECT 'job', retracted_at IS NOT NULL FROM work_event WHERE person_id = :p"""),
            {"p": person_id}).all()
    assert sorted(map(tuple, rows)) == [("edu", False), ("edu", True), ("job", False), ("job", True)]


def test_other_schools_same_major_is_a_paid_comparison(client, engine, ids):  # noqa: F811
    """The member's own school is free; "다른 학교, 같은 과" opens with 튜브, is computed without
    their school, and is never charged when the other schools are too few."""
    from hellomyme.domain import ledger
    from tests.test_career_query import run

    own = run(engine, target_metric="FIRST_ROLE_DISTRIBUTION", major_node_ids=(ids["M3"],),
              graduation_year_from=2020, graduation_year_to=2020)
    others = run(engine, target_metric="FIRST_ROLE_DISTRIBUTION", major_node_ids=(ids["M3"],),
                 graduation_year_from=2020, graduation_year_to=2020,
                 exclude_institution_ids=(ids["inst"],))
    assert own["exact_n"] == 10 and others["exact_n"] == 0  # every fixture person is at that school
    assert own["query_hash"] != others["query_hash"]

    h = anon()
    auth, _ = merge(client, h, save(client, h, student(ids)), "acq-compare")
    me = client.get("/acq/me", headers=auth).json()
    assert me["compare"] == {"available": True, "unlocked": False, "cost_tube": 1, "result": None}
    before = me["balance_tube"]
    r = client.post("/acq/me/unlock/compare", headers={**auth, "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 200 and r.json() == {"unlocked": False, "charged": False}
    assert client.get("/acq/me", headers=auth).json()["balance_tube"] == before

    with engine.begin() as conn:  # the product exists and costs what the policy says
        account = conn.execute(text("SELECT account_id::text FROM account_identity "
                                    "WHERE provider_subject = 'acq-compare'")).scalar_one()
        grant = ledger.unlock(conn, account, "SCHOOL_COMPARE", "k-compare", {}, "idem-compare")
        assert grant["charged"] is True
        assert ledger.balance(conn, account) == before - 1
