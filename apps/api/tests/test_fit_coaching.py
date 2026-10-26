"""First-pass fit analysis and coaching requests (/alert, migration 0044): consent first, confirmed
records only, one stored answer per set of records, a daily limit, and coaching with its own
phone consent that cancelling clears."""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from hellomyme.api.acquisition import fit_analyzer
from hellomyme.config import Settings, get_settings
from hellomyme.domain.fit_analysis import FitResult, FitRole, Usage
from hellomyme.main import create_app
from tests.test_acquisition import anon, login, merge, save, student
from tests.test_career_query import ids  # noqa: F401  (module fixture: imports the cohort)

ANSWER = FitResult(
    summary="그로스 쪽이 가장 잘 맞아요",
    fits=[FitRole(role_code="R3", role_name="그로스 마케팅", level="HIGH", reason="3년 했어요"),
          FitRole(role_code="NOT-A-CODE", role_name="CRM", level="HIGH", reason="캠페인 경험이 있어요"),
          FitRole(role_code=None, role_name="PM", level="MEDIUM", reason="실험 설계 경험이 있어요"),
          FitRole(role_code=None, role_name="넷째", level="MEDIUM", reason="잘림")],
    company_types=["핀테크 스타트업", "커머스 플랫폼"],
    gaps=["공백 설명이 없어요", "직무 경험이 1년 미만이에요"])


class Fake:
    model = "fake-analyzer"

    def __init__(self, result=ANSWER, outcome="DONE"):
        self.result, self.outcome, self.calls, self.records = result, outcome, 0, None

    def analyze(self, records, roles):
        self.calls += 1
        self.records = records
        return self.result, self.outcome, Usage(input_tokens=900, output_tokens=200)


def app_with(analyzer, **overrides) -> TestClient:
    app = create_app()
    settings = Settings(**{"env": "test", "auth_providers": ["DEV"], **overrides})
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[fit_analyzer] = lambda: analyzer
    return TestClient(app)


def pro_member(c, ids, subject):  # noqa: F811
    h = anon()
    payload = {**student(ids), "user_type": "PROFESSIONAL",
               "current_job": {"organization_name": "분석회사", "role_node_id": ids["R3"],
                               "start_year": 2021}}
    auth, _ = merge(c, h, save(c, h, payload), subject)
    return auth


def body(**extra):
    return {"consent": True, "consent_text_version": "fit_analysis_v2", **extra}


def test_consent_and_a_profile_come_first(ids):  # noqa: F811
    assert app_with(None).get("/acq/me/fit").status_code == 401
    off = app_with(None)
    auth = pro_member(off, ids, "fit-off")
    assert off.get("/acq/me/fit", headers=auth).json()["enabled"] is False
    assert off.post("/acq/me/fit", headers=auth, json=body()).status_code == 409

    fake = Fake()
    c = app_with(fake)
    assert c.post("/acq/me/fit", headers=login(c, "fit-nobody"), json=body()).status_code == 404
    auth = login(c, "fit-off")
    assert c.post("/acq/me/fit", headers=auth, json={**body(), "consent": False}).status_code == 422
    assert c.post("/acq/me/fit", headers=auth, json=body(consent_text_version="old")).status_code == 409
    assert fake.calls == 0


def test_one_answer_per_set_of_records(engine, ids):  # noqa: F811
    fake = Fake()
    c = app_with(fake)
    auth = pro_member(c, ids, "fit-pro")
    r = c.post("/acq/me/fit", headers=auth, json=body())
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["summary"] == ANSWER.summary and len(out["fits"]) == 3 and len(out["gaps"]) == 2
    assert out["company_types"] == ["핀테크 스타트업", "커머스 플랫폼"]
    assert [f["role_code"] for f in out["fits"]] == ["R3", None, None]  # unknown codes dropped
    assert "분석회사" in fake.records and "2021.01~지금" in fake.records
    assert "fit-pro" not in fake.records  # no account or login name goes out

    again = c.post("/acq/me/fit", headers=auth, json=body()).json()
    assert again["analysis_id"] == out["analysis_id"] and fake.calls == 1
    assert c.get("/acq/me/fit", headers=auth).json()["latest"]["analysis_id"] == out["analysis_id"]
    with engine.begin() as conn:
        row = conn.execute(text(
            """SELECT f.outcome, f.consent_text_version, f.input_tokens FROM fit_analysis f
               WHERE f.analysis_id = CAST(:i AS uuid)"""), {"i": out["analysis_id"]}).one()
    assert tuple(row) == ("DONE", "fit_analysis_v2", 900)

    # New records are a new run; the daily limit counts runs that reached the model.
    job = {"organization_name": "예전회사", "role_node_id": ids["R3B"], "start_year": 2018, "end_year": 2020}
    added = c.post("/acq/me/jobs", headers={**auth, "Idempotency-Key": uuid.uuid4().hex}, json={"job": job})
    assert added.status_code == 200, added.text
    limited = app_with(fake, fit_analysis_daily_limit=1)
    assert limited.post("/acq/me/fit", headers=auth, json=body()).status_code == 429
    assert c.post("/acq/me/fit", headers=auth, json=body()).json()["analysis_id"] != out["analysis_id"]
    assert "예전회사" in fake.records and fake.calls == 2


def test_a_failed_run_is_kept_but_never_shown(engine, ids):  # noqa: F811
    c = app_with(Fake(result=None, outcome="FAILED"))
    auth = pro_member(c, ids, "fit-fail")
    assert c.post("/acq/me/fit", headers=auth, json=body()).status_code == 503
    assert c.get("/acq/me/fit", headers=auth).json()["latest"] is None
    with engine.begin() as conn:
        outcome = conn.execute(text(
            """SELECT f.outcome FROM fit_analysis f JOIN account_identity ai USING (account_id)
               WHERE ai.provider_subject = 'fit-fail'""")).scalar()
    assert outcome == "FAILED"


def coaching_body(**extra):
    return {"sku": "COACHING_UNTIL_DEADLINE", "phone": "010-7777-8888", "consent": True,
            "consent_text_version": "coaching_contact_v2", **extra}


def test_coaching_request_has_its_own_consent_and_cancel_clears_the_number(engine, ids):  # noqa: F811
    c = app_with(Fake())
    auth = pro_member(c, ids, "coach-me")
    s = c.get("/acq/me/coaching", headers=auth).json()
    assert [(p["sku"], p["amount_krw"]) for p in s["products"]] == [
        ("COACHING_ONCE", 59000), ("COACHING_UNTIL_DEADLINE", 99000)]
    assert s["request"] is None
    assert c.post("/acq/me/coaching", headers=auth, json=coaching_body(sku="NOPE")).status_code == 422
    assert c.post("/acq/me/coaching", headers=auth,
                  json=coaching_body(consent_text_version="old")).status_code == 409
    unticked = {**coaching_body(), "consent": False}
    assert c.post("/acq/me/coaching", headers=auth, json=unticked).status_code == 422

    r = c.post("/acq/me/coaching", headers=auth, json=coaching_body())
    assert r.status_code == 200, r.text
    req = r.json()["request"]
    assert (req["sku"], req["amount_krw"], req["phone_masked"]) == ("COACHING_UNTIL_DEADLINE", 99000,
                                                                    "010-****-8888")
    assert c.post("/acq/me/coaching", headers=auth, json=coaching_body()).status_code == 409
    # The job-alert opt-in is a different consent: it stays empty.
    assert c.get("/acq/me/job-alert", headers=auth).json()["status"] == "NONE"

    assert c.delete("/acq/me/coaching", headers=auth).json()["request"] is None
    with engine.begin() as conn:
        row = conn.execute(text(
            """SELECT r.phone_e164, r.cancelled_at IS NOT NULL AS gone,
                      (SELECT array_agg(status ORDER BY consented_at, revoked_at) FROM data_consent d
                        WHERE d.account_id = r.account_id AND consent_type = 'COACHING_CONTACT') AS h
               FROM coaching_request r JOIN account_identity ai USING (account_id)
               WHERE ai.provider_subject = 'coach-me'""")).one()
    assert (row.phone_e164, row.gone, row.h) == (None, True, ["GRANTED", "REVOKED"])
