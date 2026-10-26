"""Job-alert opt-in after login (/alert landing, migration 0043): a mobile number with its own consent,
used to text a member when a matching job posting opens.

Optional: saying no changes nothing else in the product (PIPA §16(3)). The consent names purpose,
item, retention and the right to refuse (PIPA §15(2)). Texts go out 08:00-21:00 only; coaching or
event news is advertising and needs the separate MARKETING consent (정보통신망법 §50). Code checks,
limits and the number format are the interview opt-in's (domain/interview.py). Withdrawal clears
the number at once; a number is kept at most a year after consent.
"""
from __future__ import annotations

from sqlalchemy import Connection, text

from hellomyme.config import Settings
from hellomyme.domain import interview
from hellomyme.domain.interview import InterviewError, masked, normalize_phone
from hellomyme.sms import SmsSender

RETENTION = "1 year"  # from consent; the consent text says the same
_ALERT_SCOPE = '{"purpose": "job_posting_alert", "items": ["mobile_phone"]}'
_MARKETING_SCOPE = '{"purpose": "coaching_event_news", "channel": "sms"}'


def purge_expired(conn: Connection) -> None:
    conn.execute(text(
        f"""UPDATE job_alert_contact SET phone_e164 = NULL, phone_verified_at = NULL,
                withdrawn_at = now()
            WHERE withdrawn_at IS NULL AND consented_at < now() - interval '{RETENTION}'"""))
    interview.purge_expired(conn)


def _marketing_granted(conn: Connection, account_id: str) -> bool:
    latest = conn.execute(text(
        """SELECT status FROM data_consent
           WHERE account_id = :a AND consent_type = 'MARKETING' AND scope->>'channel' = 'sms'
           ORDER BY consented_at DESC, coalesce(revoked_at, consented_at) DESC LIMIT 1"""),
        {"a": account_id}).scalar()
    return latest == "GRANTED"


def status(conn: Connection, settings: Settings, account_id: str, sender: SmsSender | None) -> dict:
    purge_expired(conn)
    row = conn.execute(text(
        """SELECT phone_e164, phone_verified_at, withdrawn_at
           FROM job_alert_contact WHERE account_id = :a"""), {"a": account_id}).first()
    state = "NONE" if row is None else ("WITHDRAWN" if row.withdrawn_at else "SUBSCRIBED")
    return {
        "enabled": settings.job_alert_enabled,
        "status": state,
        "phone_masked": masked(row.phone_e164) if row else None,
        "verified": bool(row and row.phone_verified_at),
        "verification_required": sender is not None,
        "consent_text_version": settings.job_alert_consent_version,
        "marketing": _marketing_granted(conn, account_id),
    }


def send_code(conn: Connection, settings: Settings, account_id: str, raw_phone: str,
              sender: SmsSender | None) -> dict:
    if not settings.job_alert_enabled:
        raise InterviewError(409, "job alerts are closed")
    return interview.send_phone_code(conn, settings, account_id, raw_phone, sender)


def subscribe(conn: Connection, settings: Settings, account_id: str, raw_phone: str,
              code: str | None, consent_text_version: str, marketing: bool,
              sender: SmsSender | None) -> dict:
    if not settings.job_alert_enabled:
        raise InterviewError(409, "job alerts are closed")
    if consent_text_version != settings.job_alert_consent_version:
        raise InterviewError(409, "동의 문구가 바뀌었어요. 새로고침 후 다시 동의해 주세요")
    phone = normalize_phone(raw_phone)
    if sender is not None:
        interview._verify(conn, settings, account_id, phone, code or "")
    consent_id = conn.execute(text(
        f"""INSERT INTO data_consent (account_id, consent_type, policy_version, status, scope)
            VALUES (:a, 'JOB_ALERT_CONTACT', :v, 'GRANTED', '{_ALERT_SCOPE}'::jsonb)
            RETURNING consent_id::text"""),
        {"a": account_id, "v": consent_text_version}).scalar_one()
    conn.execute(text(
        """INSERT INTO job_alert_contact (account_id, phone_e164, phone_verified_at, consent_id,
               consent_text_version, consented_at)
           VALUES (:a, :p, CASE WHEN :ver THEN now() END, CAST(:c AS uuid), :v, now())
           ON CONFLICT (account_id) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164,
               phone_verified_at = EXCLUDED.phone_verified_at, consent_id = EXCLUDED.consent_id,
               consent_text_version = EXCLUDED.consent_text_version,
               consented_at = EXCLUDED.consented_at, withdrawn_at = NULL"""),
        {"a": account_id, "p": phone, "ver": sender is not None, "c": consent_id,
         "v": consent_text_version})
    if marketing and not _marketing_granted(conn, account_id):
        conn.execute(text(
            f"""INSERT INTO data_consent (account_id, consent_type, policy_version, status, scope)
                VALUES (:a, 'MARKETING', :v, 'GRANTED', '{_MARKETING_SCOPE}'::jsonb)"""),
            {"a": account_id, "v": consent_text_version})
    return status(conn, settings, account_id, sender)


def withdraw(conn: Connection, settings: Settings, account_id: str, sender: SmsSender | None) -> dict:
    """Stops the texts: the number is cleared, and SMS advertising consent goes with it."""
    conn.execute(text("DELETE FROM phone_verification WHERE account_id = :a"), {"a": account_id})
    row = conn.execute(text(
        """UPDATE job_alert_contact SET phone_e164 = NULL, phone_verified_at = NULL,
               withdrawn_at = now()
           WHERE account_id = :a AND withdrawn_at IS NULL RETURNING consent_text_version"""),
        {"a": account_id}).first()
    if row is not None:
        conn.execute(text(
            """INSERT INTO data_consent (account_id, consent_type, policy_version, status,
                   revoked_at, scope)
               VALUES (:a, 'JOB_ALERT_CONTACT', :v, 'REVOKED', now(),
                       '{"purpose": "job_posting_alert"}'::jsonb)"""),
            {"a": account_id, "v": row.consent_text_version})
        if _marketing_granted(conn, account_id):
            conn.execute(text(
                f"""INSERT INTO data_consent (account_id, consent_type, policy_version, status,
                       revoked_at, scope)
                    VALUES (:a, 'MARKETING', :v, 'REVOKED', now(), '{_MARKETING_SCOPE}'::jsonb)"""),
                {"a": account_id, "v": row.consent_text_version})
    return status(conn, settings, account_id, sender)
