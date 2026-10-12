"""User-interview opt-in (migration 0027): optional, its own consent, a keyed-hash code check,
limits, and withdrawal that clears the number."""
import logging
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hellomyme.config import Settings, get_settings
from hellomyme.domain.interview import InterviewError, masked, normalize_phone
from hellomyme.main import create_app
from tests.test_acquisition import login


def app_with(**overrides) -> TestClient:
    app = create_app()
    settings = Settings(**{"env": "test", "auth_providers": ["DEV"], **overrides})
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def body(phone="010-1234-5678", **extra):
    return {"phone": phone, "consent": True, "consent_text_version": "interview_contact_v1", **extra}


def test_phone_numbers_are_normalised_to_e164():
    for raw in ("010-1234-5678", "01012345678", "+82 10 1234 5678", "82-10-1234-5678"):
        assert normalize_phone(raw) == "+821012345678"
    assert normalize_phone("011-234-5678") == "+82112345678"
    assert masked("+821012345678") == "010-****-5678"
    for bad in ("02-123-4567", "1234", "010-12-34", "+1 415 555 0100"):
        with pytest.raises(InterviewError):
            normalize_phone(bad)


def test_without_a_provider_the_number_is_kept_unverified_and_can_be_withdrawn(engine):
    c = app_with()
    auth = login(c, "interview-plain")
    assert c.get("/acq/me/interview").status_code == 401  # members only
    s = c.get("/acq/me/interview", headers=auth).json()
    assert (s["status"], s["verification_required"], s["reward_text"]) == ("NONE", False, None)
    assert c.post("/acq/me/interview/code", headers=auth, json={"phone": "01012345678"}).status_code == 409
    assert c.post("/acq/me/interview", headers=auth,
                  json={**body(), "consent": False}).status_code == 422  # consent must be ticked
    assert c.post("/acq/me/interview", headers=auth,
                  json=body(consent_text_version="old")).status_code == 409
    r = c.post("/acq/me/interview", headers=auth, json=body())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPLIED" and r.json()["phone_masked"] == "010-****-5678"
    assert r.json()["verified"] is False

    w = c.delete("/acq/me/interview", headers=auth).json()
    assert w["status"] == "WITHDRAWN" and w["phone_masked"] is None
    with engine.begin() as conn:
        row = conn.execute(text(
            """SELECT ic.phone_e164, ic.withdrawn_at IS NOT NULL AS gone,
                      (SELECT array_agg(status ORDER BY consented_at) FROM data_consent d
                        WHERE d.account_id = ic.account_id AND consent_type = 'INTERVIEW_CONTACT')
                          AS history
               FROM interview_contact ic JOIN account_identity ai USING (account_id)
               WHERE ai.provider_subject = 'interview-plain'""")).one()
    assert (row.phone_e164, row.gone, row.history) == (None, True, ["GRANTED", "REVOKED"])
    again = c.post("/acq/me/interview", headers=auth, json=body("01099998888")).json()
    assert again["status"] == "APPLIED" and again["phone_masked"] == "010-****-8888"


def test_with_a_provider_the_code_is_required_limited_and_never_stored(engine, caplog):
    c = app_with(sms_provider="log")
    auth = login(c, "interview-sms")
    assert c.get("/acq/me/interview", headers=auth).json()["verification_required"] is True
    assert c.post("/acq/me/interview", headers=auth, json=body(code="000000")).status_code == 422

    with caplog.at_level(logging.WARNING, logger="hellomyme.sms"):
        sent = c.post("/acq/me/interview/code", headers=auth, json={"phone": "010-2222-3333"})
    assert sent.status_code == 200 and sent.json()["expires_in"] == 180
    code = re.search(r"인증번호 (\d{6})", caplog.text).group(1)
    assert "2222" not in caplog.text  # only the last four digits are ever logged
    assert c.post("/acq/me/interview/code", headers=auth,
                  json={"phone": "010-2222-3333"}).status_code == 429  # resend too soon

    wrong = c.post("/acq/me/interview", headers=auth, json=body("010-2222-3333", code="999999"))
    assert wrong.status_code == 422 and wrong.json()["detail"]["attempts_left"] == 4
    ok = c.post("/acq/me/interview", headers=auth, json=body("010-2222-3333", code=code))
    assert ok.status_code == 200, ok.text
    assert ok.json()["verified"] is True
    with engine.begin() as conn:
        stored = conn.execute(text(
            "SELECT phone_hash, code_hash, attempts FROM phone_verification ORDER BY created_at DESC"
        )).first()
    assert "2222" not in stored.phone_hash and code not in stored.code_hash and stored.attempts == 2

    # Withdrawal removes the number and every code check derived from it.
    assert c.delete("/acq/me/interview", headers=auth).json()["status"] == "WITHDRAWN"
    with engine.begin() as conn:
        left = conn.execute(text(
            """SELECT count(*) FROM phone_verification v JOIN account_identity ai USING (account_id)
               WHERE ai.provider_subject = 'interview-sms'""")).scalar()
    assert left == 0


def test_numbers_past_retention_are_cleared(engine):
    c = app_with()
    auth = login(c, "interview-old")
    assert c.post("/acq/me/interview", headers=auth, json=body("01055556666")).status_code == 200
    with engine.begin() as conn:
        conn.execute(text(
            """UPDATE interview_contact SET consented_at = now() - interval '13 months'
               WHERE account_id = (SELECT account_id FROM account_identity
                                   WHERE provider_subject = 'interview-old')"""))
    s = c.get("/acq/me/interview", headers=auth).json()
    assert s["status"] == "WITHDRAWN" and s["phone_masked"] is None


def test_real_deployments_refuse_the_log_provider_and_the_public_hash_key():
    solapi = {"sms_provider": "solapi", "solapi_api_key": "k", "solapi_api_secret": "s",
              "sms_sender_number": "0212345678"}
    for env in ("staging", "production"):  # the live demand test runs as staging
        layers = ["PRE_SEED", "SEED"] if env == "staging" else ["SEED", "VERIFIED"]
        with pytest.raises(ValueError):
            Settings(env=env, career_map_data_layers=layers, auth_providers=["HMM_ID"],
                     sms_provider="log", phone_hash_secret="x")
        with pytest.raises(ValueError):  # codes would be hashed with the key that is in the repo
            Settings(env=env, career_map_data_layers=layers, auth_providers=["HMM_ID"], **solapi)
        Settings(env=env, career_map_data_layers=layers, auth_providers=["HMM_ID"],
                 phone_hash_secret="real-secret", **solapi)
        Settings(env=env, career_map_data_layers=layers, auth_providers=["HMM_ID"])  # no SMS: fine
    with pytest.raises(ValueError):
        Settings(env="test", sms_provider="solapi")  # keys and sender number are required


def test_solapi_request_is_signed_and_uses_the_national_number():
    import hashlib
    import hmac

    import httpx

    from hellomyme.sms import SmsUnavailable, SolapiSender

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"statusCode": "2000"})

    s = Settings(env="test", sms_provider="solapi", solapi_api_key="KEY", solapi_api_secret="SECRET",
                 sms_sender_number="0212345678")
    SolapiSender(s, httpx.Client(transport=httpx.MockTransport(handler))).send("+821012345678", "hi")
    fields = dict(p.split("=", 1) for p in seen["auth"].removeprefix("HMAC-SHA256 ").split(", "))
    assert fields["apiKey"] == "KEY"
    expected = hmac.new(b"SECRET", (fields["date"] + fields["salt"]).encode(), hashlib.sha256)
    assert fields["signature"] == expected.hexdigest()
    assert '"to":"01012345678"' in seen["body"].replace(" ", "")
    refuse = SolapiSender(s, httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"errorCode": "x"}))))
    with pytest.raises(SmsUnavailable):
        refuse.send("+821012345678", "hi")


def test_switched_off_the_invitation_is_hidden_and_applications_refused():
    c = app_with(interview_enabled=False)
    auth = login(c, "interview-off")
    assert c.get("/acq/me/interview", headers=auth).json()["enabled"] is False
    assert c.post("/acq/me/interview", headers=auth, json=body()).status_code == 409
    assert c.delete("/acq/me/interview", headers=auth).status_code == 200  # withdrawal still works
