import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from hellomyme.domain import ledger
from hellomyme.main import create_app


@pytest.fixture(scope="module")
def client(imported):
    return TestClient(create_app())


def taxonomy(client, kind, name):
    return next(x["id"] for x in client.get(f"/taxonomy/{kind}").json() if x["name"] == name)


def login(client, subject: str) -> dict:
    r = client.post("/auth/login", json={"provider": "DEV", "token": f"dev:{subject}"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['session_token']}"}


def draft_payload(client, current=True):
    return {
        "user_type": "PROFESSIONAL",
        "education": {"institution_id": taxonomy(client, "institutions", "테스트대학교"),
                      "major_id": taxonomy(client, "majors", "경영학과"),
                      "graduation_year": 2018},
        "career_events": [
            {"event_type": "EMPLOYMENT", "organization_name": "테스트전자",
             "role_name": "브랜드 마케터", "start_date": "2018-03-01", "end_date": "2020-03-01",
             "is_current": False},
            {"event_type": "EMPLOYMENT", "organization_name": "아직 없는 회사",
             "role_name": "데이터 애널리스트", "start_date": "2020-04-01",
             "is_current": current},
        ],
    }


def onboard(client, subject: str):
    anon = {"X-Anonymous-Session": uuid.uuid4().hex}
    draft = client.post("/career/draft", headers=anon,
                        json={"payload": draft_payload(client)}).json()
    auth = login(client, subject)
    merged = client.post("/auth/merge-draft", json={"draft_id": draft["draft_id"]},
                         headers={**auth, **anon, "Idempotency-Key": uuid.uuid4().hex})
    assert merged.status_code == 200, merged.text
    return auth, anon, draft["draft_id"], merged.json()


def test_anonymous_teaser_has_no_distributions(client):
    anon = {"X-Anonymous-Session": uuid.uuid4().hex}
    draft = client.post("/career/draft", headers=anon, json={"payload": draft_payload(client)})
    assert draft.status_code == 200
    teaser = client.post("/career/draft/query", headers=anon,
                         json={"draft_id": draft.json()["draft_id"]}).json()
    assert teaser["available"] is True
    assert teaser["data_basis"] == "SIMULATION" and teaser["notice"]
    assert "next_job_family" not in teaser
    # Another anonymous session cannot read this draft.
    other = client.post("/career/draft/query", headers={"X-Anonymous-Session": uuid.uuid4().hex},
                        json={"draft_id": draft.json()["draft_id"]})
    assert other.status_code == 404


def test_login_wall_merge_is_idempotent_and_rewards_once(client, engine):
    auth, anon, draft_id, first = onboard(client, "merge-user")
    assert first["merged"] is True
    assert sum(r["amount"] for r in first["rewards"]) > 0
    again = client.post("/auth/merge-draft", json={"draft_id": draft_id},
                        headers={**auth, **anon, "Idempotency-Key": uuid.uuid4().hex}).json()
    assert again == {"person_id": first["person_id"], "merged": False, "rewards": []}

    with engine.begin() as conn:
        person = conn.execute(text(
            "SELECT origin_layer FROM person WHERE person_id = :p"),
            {"p": first["person_id"]}).scalar()
        events = conn.execute(text(
            """SELECT w.verification_level, w.normalization_status, w.organization_raw,
                      s.supported_fields, r.source_type
               FROM work_event w JOIN work_event_source s USING (work_event_id)
               JOIN source_record r USING (source_id)
               WHERE w.person_id = :p ORDER BY w.start_date"""),
            {"p": first["person_id"]}).all()
        rewards = conn.execute(text(
            "SELECT count(*) FROM credit_ledger l JOIN account_identity i USING (account_id) "
            "WHERE i.provider_subject = 'merge-user' AND l.reason_type = 'REWARD'")).scalar()
    assert person == "VERIFIED"
    assert [e.verification_level for e in events] == ["SELF_REPORTED", "SELF_REPORTED"]
    # Unknown company kept as raw text, not invented or forced into the taxonomy.
    assert events[1].normalization_status == "PARTIAL"
    assert events[1].organization_raw == "아직 없는 회사"
    assert "end_date" not in events[1].supported_fields
    assert {e.source_type for e in events} == {"MANUAL_INPUT"}
    # SIGNUP + EDUCATION + CURRENT_ROLE + PREVIOUS_CAREER, each exactly once.
    assert rewards == 4

    # A second login does not pay SIGNUP again.
    login(client, "merge-user")
    with engine.begin() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM credit_ledger l JOIN account_identity i USING (account_id) "
            "WHERE i.provider_subject = 'merge-user' AND l.reason_type = 'REWARD'")).scalar() == 4


def test_career_map_unlock_flow(client, engine):
    auth, *_ = onboard(client, "map-user")
    balance = client.get("/credits", headers=auth).json()["balance_tube"]
    assert balance > 0

    career = client.get("/career/map", headers=auth).json()
    assert career["data_basis"] == "SIMULATION"
    cohort = career["cohort"]
    for key in ("exact_n", "effective_n", "fallback_level", "cohort_policy_version"):
        assert key in cohort
    assert career["anchor"] in ("FROM_CURRENT_JOB_FAMILY", "ANY_NEXT_MOVE")
    # The fixture is sparse at school+major level, so the engine must fall back to level 3.
    assert cohort["fallback_level"] == 3 and career["similarity_label"]
    assert career["suppressed"] is False and career["basis_n"] >= 30
    assert all(c["n"] >= 5 for c in career["next_job_family"])

    key = uuid.uuid4().hex
    r1 = client.post("/career/unlock", headers={**auth, "Idempotency-Key": key},
                     json={"insight_type": "TIMING_TENURE"}).json()
    assert r1["unlocked"] is True and r1["charged"] is True
    r2 = client.post("/career/unlock", headers={**auth, "Idempotency-Key": key},
                     json={"insight_type": "TIMING_TENURE"}).json()
    r3 = client.post("/career/unlock", headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
                     json={"insight_type": "TIMING_TENURE"}).json()
    assert r2["charged"] is False and r3["charged"] is False
    assert client.get("/credits", headers=auth).json()["balance_tube"] == balance - r1["cost_tube"]

    reused = client.post("/career/unlock", headers={**auth, "Idempotency-Key": key},
                         json={"insight_type": "PATH_DEEP_DIVE"})
    assert reused.status_code == 422

    entries = client.get("/credits/ledger", headers=auth).json()
    assert sum(1 for e in entries if e["reason_type"] == "UNLOCK") == 1
    unlocked = client.get("/career/map", headers=auth).json()["unlocks"]
    assert any(u["insight_type"] == "TIMING_TENURE" and u["unlocked"] for u in unlocked)


def test_insufficient_credit_is_rejected_without_writes(client, engine):
    auth, *_ = onboard(client, "poor-user")
    with engine.begin() as conn:
        account = conn.execute(text(
            "SELECT account_id::text FROM account_identity WHERE provider_subject = 'poor-user'"
        )).scalar()
        bal = ledger.balance(conn, account)
        ledger.spend(conn, account, bal, reason_type="ADJUSTMENT", reference_type="TEST",
                     reference_id="drain", key=f"drain:{account}")
    r = client.post("/career/unlock", headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
                    json={"insight_type": "PATH_DEEP_DIVE"})
    assert r.status_code == 402
    with engine.begin() as conn:
        assert ledger.balance(conn, account) == 0
        assert conn.execute(text("SELECT count(*) FROM unlock_event WHERE account_id = :a"),
                            {"a": account}).scalar() == 0


def test_ledger_is_immutable_and_corrected_by_reversal(engine, client):
    auth, *_ = onboard(client, "ledger-user")
    with engine.begin() as conn:
        account = conn.execute(text(
            "SELECT account_id::text FROM account_identity WHERE provider_subject = 'ledger-user'"
        )).scalar()
        entry_id = conn.execute(text(
            "SELECT ledger_id::text FROM credit_ledger WHERE account_id = :a LIMIT 1"),
            {"a": account}).scalar()
        before = ledger.balance(conn, account)
    for sql in ("UPDATE credit_ledger SET amount = 999", "DELETE FROM credit_ledger"):
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(text(sql))
    with engine.begin() as conn:
        rev = ledger.reverse(conn, entry_id, reason="test correction")
        again = ledger.reverse(conn, entry_id, reason="test correction")
        assert rev.created and not again.created
        assert ledger.balance(conn, account) < before


def test_reconfirm_reward_respects_cooldown(client, engine):
    auth, *_ = onboard(client, "reconfirm-user")
    with engine.begin() as conn:
        weid = conn.execute(text(
            """SELECT w.work_event_id::text FROM work_event w JOIN person p USING (person_id)
               JOIN account_identity i ON i.account_id = p.account_id
               WHERE i.provider_subject = 'reconfirm-user' AND w.is_current""")).scalar()
    first = client.post(f"/career/events/{weid}/reconfirm", headers=auth).json()
    second = client.post(f"/career/events/{weid}/reconfirm", headers=auth).json()
    assert first["reward"] is not None and second["reward"] is None
    with engine.begin() as conn:
        levels = conn.execute(text(
            "SELECT action FROM verification_log WHERE entity_id = :w ORDER BY created_at"),
            {"w": weid}).scalars().all()
    assert levels == ["SELF_REPORTED", "SELF_RECONFIRMED", "SELF_RECONFIRMED"]


def test_mentor_opt_in_matching_and_order(client, engine):
    mentor_auth, *_ = onboard(client, "mentor-user")
    assert client.post("/mentors/profile", headers=mentor_auth, json={
        "headline": "마케터에서 데이터 애널리스트로", "consent_policy_version": "mentor_terms_v1",
    }).status_code == 200
    offer = client.post("/mentors/offers", headers=mentor_auth, json={
        "offer_type": "QNA", "title": "직무 전환 Q&A", "price_tube": 1}).json()
    bad = client.post("/mentors/offers", headers=mentor_auth, json={
        "offer_type": "LECTURE", "title": "강의"})
    assert bad.status_code == 422  # outside MVP scope

    seeker_auth, *_ = onboard(client, "seeker-user")
    matches = client.get("/mentors/matches", headers=seeker_auth,
                         params={"target_job_family": "DATA"}).json()
    ids = [m["mentor_profile_id"] for m in matches]
    assert ids, "the opted-in senior who walked the DATA path should be found"
    assert all("person_id" not in m for m in matches)
    with engine.begin() as conn:
        layers = conn.execute(text(
            "SELECT DISTINCT p.origin_layer FROM mentor_profile m JOIN person p USING (person_id)"
        )).scalars().all()
    assert layers == ["VERIFIED"]

    key = uuid.uuid4().hex
    order = client.post("/orders", headers={**seeker_auth, "Idempotency-Key": key},
                        json={"offer_id": offer["offer_id"], "question_text": "어떻게 준비했나요?"})
    assert order.status_code == 200, order.text
    replay = client.post("/orders", headers={**seeker_auth, "Idempotency-Key": key},
                         json={"offer_id": offer["offer_id"], "question_text": "어떻게 준비했나요?"})
    assert replay.json()["replayed"] is True
    own = client.post("/orders", headers={**mentor_auth, "Idempotency-Key": uuid.uuid4().hex},
                      json={"offer_id": offer["offer_id"], "question_text": "?"})
    assert own.status_code == 422


def test_analytics_events_are_separate_from_career_data(client, engine):
    r = client.post("/analytics/events", json={
        "event_name": "login_wall_viewed", "occurred_at": datetime.now(UTC).isoformat(),
        "anonymous_session_id": "abc", "properties": {"step": "teaser"}})
    assert r.status_code == 202
    assert client.post("/analytics/events", json={
        "event_name": "not_an_event", "occurred_at": datetime.now(UTC).isoformat()}
    ).status_code == 422
    with engine.begin() as conn:
        assert conn.execute(text(
            "SELECT properties->>'step' FROM analytics.event WHERE event_name = 'login_wall_viewed'"
        )).scalar() == "teaser"


def test_suppressed_insight_is_never_charged(client):
    auth, *_ = onboard(client, "target-user")
    before = client.get("/credits", headers=auth).json()["balance_tube"]
    r = client.post("/career/unlock", headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
                    json={"insight_type": "PATH_DEEP_DIVE", "target_job_family": "NO_SUCH_FAMILY"})
    assert r.json() == {"unlocked": False, "charged": False,
                        "insight": {"suppressed": True, "reason": "LOW_SAMPLE_FOR_TARGET",
                                    "basis_n": 0}}
    assert client.get("/credits", headers=auth).json()["balance_tube"] == before


def test_endpoints_require_login_and_idempotency_key(client):
    assert client.get("/career/map").status_code == 401
    auth = login(client, "plain-user")
    assert client.post("/career/unlock", headers=auth,
                       json={"insight_type": "PATH_DEEP_DIVE"}).status_code == 400
