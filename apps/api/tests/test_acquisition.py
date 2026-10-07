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


def test_student_flow_login_merge_and_awaited_result(client, engine, ids):  # noqa: F811
    h = anon()
    draft = save(client, h, student(ids))
    first = step(client, h, draft, "first_roles")["result"]
    assert (first["exact_n"], first["effective_n"]) == (10, 45)
    assert [(c["code"], c["n"]) for c in first["cells"]] == [("R2", 30), ("R2B", 15)]

    payload = {**student(ids), "intents": [
        {"surface": "STUDENT_FIRST_ROLE", "target_kind": "ROLE", "target_node_id": ids["R2B"]}]}
    save(client, h, payload, draft)
    teaser = step(client, h, draft, "intent_paths")
    assert teaser["locked"] and teaser["data_basis"] == "SIMULATION"
    p = teaser["paths"]
    assert (p["n_people"], p["n_paths"], p["target"]["label"]) == (25, 2, "데이터·AI")
    assert "paths" not in p and "deep_dive" not in p  # proof only, details stay behind login

    auth = login(client, "acq-student")
    merge = {"draft_id": draft, "consent_policy_version": "v1"}
    hdr = {**auth, **h, "Idempotency-Key": uuid.uuid4().hex}
    r = client.post("/auth/merge-draft", headers=hdr, json=merge)
    assert r.status_code == 200 and r.json()["merged"] is True, r.text
    again = client.post("/auth/merge-draft", headers=hdr, json=merge).json()
    assert again["merged"] is False and again["person_id"] == r.json()["person_id"]

    with engine.begin() as conn:
        intent = conn.execute(text(
            """SELECT i.intent_event_id, i.target_kind, i.source_surface, n.code
               FROM intent_event i JOIN taxonomy_node n ON n.taxonomy_node_id =
                    i.target_taxonomy_node_id WHERE i.person_id = :p"""),
            {"p": r.json()["person_id"]}).one()
        horizons = conn.execute(text(
            "SELECT horizon_months FROM intent_followup WHERE intent_event_id = :i ORDER BY 1"),
            {"i": intent.intent_event_id}).scalars().all()
        edu = conn.execute(text(
            """SELECT admission_year, admission_date_precision, verification_level
               FROM education WHERE person_id = :p"""), {"p": r.json()["person_id"]}).one()
    assert (intent.target_kind, intent.source_surface, intent.code) == (
        "ROLE", "STUDENT_FIRST_ROLE", "R2B")
    assert horizons == [6, 12]
    assert tuple(edu) == (2016, "YEAR", "SELF_REPORTED")

    me = client.get("/acq/me", headers=auth).json()
    paths = me["intent_paths"]["paths"]
    assert [([s["label"] for s in x["path"]], x["n"]) for x in paths["paths"]] == [
        (["데이터·AI"], 15), (["마케팅", "데이터·AI"], 10)]
    assert me["deep_dive"]["unlocked"] is False and me["deep_dive"]["content"] is None
    before = me["balance_tube"]

    key = {**auth, "Idempotency-Key": uuid.uuid4().hex}
    u = client.post("/acq/me/unlock", headers=key).json()
    assert u["unlocked"] and u["charged"] and u["balance_tube"] == before - u["cost_tube"]
    assert u["content"]["company_size"][0] == {"key": "LARGE", "label": "LARGE", "n": 25}
    u2 = client.post("/acq/me/unlock", headers={**auth, "Idempotency-Key": uuid.uuid4().hex})
    assert u2.json()["charged"] is False  # already entitled
    assert client.get("/acq/me", headers=auth).json()["deep_dive"]["unlocked"] is True


def test_professional_next_and_intent_paths(client, ids):  # noqa: F811
    h = anon()
    payload = {**student(ids), "user_type": "PROFESSIONAL",
               "current_job": {"organization_name": "어딘가", "role_node_id": ids["R3"],
                               "start_year": 2021},
               "first_job_is_current": True}
    draft = save(client, h, payload)
    nxt = step(client, h, draft, "next_roles")["result"]
    assert [(c["code"], c["n"]) for c in nxt["cells"]] == [("STAYED", 20), ("R2B", 10)]
    payload["intents"] = [{"surface": "PROFESSIONAL_NEXT_ROLE", "target_kind": "ROLE",
                           "target_node_id": ids["R2B"]}]
    save(client, h, payload, draft)
    p = step(client, h, draft, "intent_paths")
    assert p["cohort_basis"] == "CURRENT_ROLE"
    # 10 moved marketing -> data, 2021-03 to 2023-02.
    assert (p["paths"]["n_people"], p["paths"]["median_months"]) == (10, 23)


def test_undecided_intent_uses_most_common_destination(client, ids):  # noqa: F811
    h = anon()
    draft = save(client, h, {**student(ids), "intents": [
        {"surface": "STUDENT_FIRST_ROLE", "target_kind": "UNDECIDED"}]})
    out = step(client, h, draft, "intent_paths")
    assert out["target_basis"] == "MOST_COMMON" and out["paths"]["target"]["label"] == "마케팅"


def test_invalid_input_is_rejected(client, ids):  # noqa: F811
    h = anon()
    bad = {**student(ids), "education": {**student(ids)["education"], "admission_year": 2021}}
    assert client.post("/acq/draft", headers=h, json={"payload": bad}).status_code == 422
    draft = save(client, h, {**student(ids), "education": {
        **student(ids)["education"], "major_node_id": str(uuid.uuid4())}})
    r = client.post(f"/acq/draft/{draft}/result", headers=h, json={"step": "first_roles"})
    assert r.status_code == 422
    other = anon()
    assert client.post(f"/acq/draft/{draft}/result", headers=other,
                       json={"step": "first_roles"}).status_code == 404
