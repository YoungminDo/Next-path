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
    assert added["work_event_id"] and added["reward"]
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
    draft = save(client, h, {**student(ids), "education": {
        **student(ids)["education"], "major_node_id": str(uuid.uuid4())}})
    r = client.post(f"/acq/draft/{draft}/result", headers=h, json={"step": "teaser"})
    assert r.status_code == 422
    other = anon()
    assert client.post(f"/acq/draft/{draft}/result", headers=other,
                       json={"step": "teaser"}).status_code == 404
