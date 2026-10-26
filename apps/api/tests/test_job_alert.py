"""Job-alert opt-in (/alert, migration 0043): its own consent, the interview's phone check, optional
SMS advertising consent, and withdrawal that clears the number and the advertising consent."""
import logging
import re

from sqlalchemy import text

from tests.test_acquisition import login
from tests.test_interview import app_with


def body(phone="010-1234-5678", **extra):
    return {"phone": phone, "consent": True, "consent_text_version": "job_alert_contact_v1", **extra}


def history(engine, subject: str) -> dict:
    with engine.begin() as conn:
        rows = conn.execute(text(
            """SELECT d.consent_type, array_agg(d.status ORDER BY d.consented_at, d.revoked_at) AS h
               FROM data_consent d JOIN account_identity ai USING (account_id)
               WHERE ai.provider_subject = :s AND d.consent_type IN ('JOB_ALERT_CONTACT', 'MARKETING')
               GROUP BY 1"""), {"s": subject}).all()
    return {r.consent_type: r.h for r in rows}


def test_subscribe_without_a_provider_then_withdraw(engine):
    c = app_with()
    auth = login(c, "alert-plain")
    assert c.get("/acq/me/job-alert").status_code == 401  # members only
    s = c.get("/acq/me/job-alert", headers=auth).json()
    assert (s["status"], s["verification_required"], s["marketing"]) == ("NONE", False, False)
    assert c.post("/acq/me/job-alert", headers=auth, json={**body(), "consent": False}).status_code == 422
    assert c.post("/acq/me/job-alert", headers=auth,
                  json=body(consent_text_version="old")).status_code == 409
    r = c.post("/acq/me/job-alert", headers=auth, json=body())
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["phone_masked"], r.json()["marketing"]) == (
        "SUBSCRIBED", "010-****-5678", False)
    # The interview opt-in is a different consent: it stays empty.
    assert c.get("/acq/me/interview", headers=auth).json()["status"] == "NONE"

    w = c.delete("/acq/me/job-alert", headers=auth).json()
    assert (w["status"], w["phone_masked"]) == ("WITHDRAWN", None)
    with engine.begin() as conn:
        phone = conn.execute(text(
            """SELECT j.phone_e164 FROM job_alert_contact j JOIN account_identity ai USING (account_id)
               WHERE ai.provider_subject = 'alert-plain'""")).scalar()
    assert phone is None
    assert history(engine, "alert-plain") == {"JOB_ALERT_CONTACT": ["GRANTED", "REVOKED"]}


def test_marketing_is_its_own_optional_consent_and_goes_with_the_number(engine):
    c = app_with()
    auth = login(c, "alert-marketing")
    s = c.post("/acq/me/job-alert", headers=auth, json=body(marketing=True)).json()
    assert s["marketing"] is True
    again = c.post("/acq/me/job-alert", headers=auth, json=body("01099998888", marketing=True)).json()
    assert again["phone_masked"] == "010-****-8888"
    assert history(engine, "alert-marketing")["MARKETING"] == ["GRANTED"]  # not granted twice
    c.delete("/acq/me/job-alert", headers=auth)
    assert c.get("/acq/me/job-alert", headers=auth).json()["marketing"] is False
    assert history(engine, "alert-marketing")["MARKETING"] == ["GRANTED", "REVOKED"]


def test_with_a_provider_the_code_is_required(engine, caplog):
    c = app_with(sms_provider="log")
    auth = login(c, "alert-sms")
    assert c.post("/acq/me/job-alert", headers=auth, json=body(code="000000")).status_code == 422
    with caplog.at_level(logging.WARNING, logger="hellomyme.sms"):
        sent = c.post("/acq/me/job-alert/code", headers=auth, json={"phone": "010-4444-5555"})
    assert sent.status_code == 200
    code = re.search(r"인증번호 (\d{6})", caplog.text).group(1)
    ok = c.post("/acq/me/job-alert", headers=auth, json=body("010-4444-5555", code=code))
    assert ok.status_code == 200, ok.text
    assert ok.json()["verified"] is True


def test_numbers_past_retention_are_cleared(engine):
    c = app_with()
    auth = login(c, "alert-old")
    assert c.post("/acq/me/job-alert", headers=auth, json=body("01055556666")).status_code == 200
    with engine.begin() as conn:
        conn.execute(text(
            """UPDATE job_alert_contact SET consented_at = now() - interval '13 months'
               WHERE account_id = (SELECT account_id FROM account_identity
                                   WHERE provider_subject = 'alert-old')"""))
    s = c.get("/acq/me/job-alert", headers=auth).json()
    assert s["status"] == "WITHDRAWN" and s["phone_masked"] is None


def test_switched_off_new_subscriptions_are_refused():
    c = app_with(job_alert_enabled=False)
    auth = login(c, "alert-off")
    assert c.get("/acq/me/job-alert", headers=auth).json()["enabled"] is False
    assert c.post("/acq/me/job-alert", headers=auth, json=body()).status_code == 409
    assert c.delete("/acq/me/job-alert", headers=auth).status_code == 200  # withdrawal still works
