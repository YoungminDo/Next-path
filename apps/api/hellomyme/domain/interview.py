"""User-interview opt-in after login: a mobile number with its own consent (migration 0027).

Optional by law and by design: saying no changes nothing else in the product (PIPA §16(3)). The
consent names purpose, item, retention and the right to refuse (PIPA §15(2)); it covers contact
for interviews only, not promotional messages (those would need their own consent, 정보통신망법
§50). Withdrawal clears the number at once; a number is kept at most a year after consent.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from sqlalchemy import Connection, text

from hellomyme.config import Settings
from hellomyme.sms import SmsSender

CODE_TTL = timedelta(minutes=3)
MAX_ATTEMPTS = 5
RESEND_AFTER = timedelta(seconds=30)
PER_HOUR = 5  # codes per account and per number
PER_DAY = 10  # codes per account and per number
RETENTION = "1 year"  # from consent; the consent text says the same

# Korean mobile numbers: 010-1234-5678, 01012345678, +82 10 1234 5678, 82-10-...
_MOBILE = re.compile(r"^(?:\+?82)?0?(1[016789])(\d{7,8})$")


class InterviewError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"[\s\-().]", "", raw or "")
    m = _MOBILE.match(digits)
    if not m:
        raise InterviewError(422, "휴대전화번호를 다시 확인해 주세요")
    return f"+82{m.group(1)}{m.group(2)}"


def masked(phone_e164: str | None) -> str | None:
    if not phone_e164:
        return None
    national = "0" + phone_e164[3:]
    return f"{national[:3]}-****-{national[-4:]}"


def _hash(settings: Settings, value: str) -> str:
    key = settings.phone_hash_secret.get_secret_value().encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def purge_expired(conn: Connection) -> None:
    """Numbers past the retention promised in the consent are cleared, and code checks older than
    a day (only needed for expiry and rate limits) are deleted. Run on every interview request."""
    conn.execute(text(
        f"""UPDATE interview_contact SET phone_e164 = NULL, phone_verified_at = NULL,
                withdrawn_at = now()
            WHERE withdrawn_at IS NULL AND consented_at < now() - interval '{RETENTION}'"""))
    conn.execute(text(
        "DELETE FROM phone_verification WHERE created_at < now() - interval '1 day'"))


def status(conn: Connection, settings: Settings, account_id: str, sender: SmsSender | None) -> dict:
    purge_expired(conn)
    row = conn.execute(text(
        """SELECT phone_e164, phone_verified_at, withdrawn_at, consent_text_version
           FROM interview_contact WHERE account_id = :a"""), {"a": account_id}).first()
    state = "NONE" if row is None else ("WITHDRAWN" if row.withdrawn_at else "APPLIED")
    return {
        "enabled": settings.interview_enabled,
        "status": state,
        "phone_masked": masked(row.phone_e164) if row else None,
        "verified": bool(row and row.phone_verified_at),
        "verification_required": sender is not None,
        "consent_text_version": settings.interview_consent_version,
        "reward_text": settings.interview_reward_text,
    }


def send_code(conn: Connection, settings: Settings, account_id: str, raw_phone: str,
              sender: SmsSender | None) -> dict:
    if not settings.interview_enabled:
        raise InterviewError(409, "interview applications are closed")
    if sender is None:
        raise InterviewError(409, "verification is not required")
    phone = normalize_phone(raw_phone)
    ph = _hash(settings, phone)
    # Its own transaction, serialised per account and per number: parallel requests cannot all
    # pass the same count, and a code counts against the limits even if sending then fails.
    with conn.engine.begin() as own:
        code, vid = _new_code(own, settings, account_id, ph)
    sender.send(phone, f"[nextpath] 인증번호 {code} (3분 안에 입력해 주세요)")
    return {"sent": True, "expires_in": int(CODE_TTL.total_seconds()),
            "phone_masked": masked(phone)}


def _new_code(conn: Connection, settings: Settings, account_id: str, ph: str) -> tuple[str, str]:
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 27))"),
                 {"k": f"phone-account:{account_id}"})
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 27))"),
                 {"k": f"phone-number:{ph}"})
    recent = conn.execute(text(
        """SELECT count(*) FILTER (WHERE account_id = :a AND created_at > now() - interval '1 hour')
                      AS account_hour,
                  count(*) FILTER (WHERE phone_hash = :h AND created_at > now() - interval '1 hour')
                      AS phone_hour,
                  count(*) FILTER (WHERE phone_hash = :h) AS phone_day,
                  count(*) FILTER (WHERE account_id = :a) AS account_day,
                  max(created_at) FILTER (WHERE account_id = :a) > now() - :wait AS too_soon
           FROM phone_verification
           WHERE (account_id = :a OR phone_hash = :h) AND created_at > now() - interval '1 day'"""),
        {"a": account_id, "h": ph, "wait": RESEND_AFTER}).one()
    if recent.too_soon:
        raise InterviewError(429, "잠시 후 다시 요청해 주세요", retry_after=int(RESEND_AFTER.seconds))
    if (recent.account_hour >= PER_HOUR or recent.phone_hour >= PER_HOUR
            or recent.phone_day >= PER_DAY or recent.account_day >= PER_DAY):
        raise InterviewError(429, "인증번호 요청이 너무 많아요. 나중에 다시 시도해 주세요")
    code = f"{secrets.randbelow(10**6):06d}"
    vid = conn.execute(text(
        """INSERT INTO phone_verification (account_id, phone_hash, code_hash, expires_at)
           VALUES (:a, :h, '', now() + :ttl) RETURNING verification_id::text"""),
        {"a": account_id, "h": ph, "ttl": CODE_TTL}).scalar_one()
    conn.execute(text("UPDATE phone_verification SET code_hash = :c WHERE verification_id = :v"),
                 {"c": _hash(settings, f"{vid}:{code}"), "v": vid})
    return code, vid


def _verify(conn: Connection, settings: Settings, account_id: str, phone: str, code: str) -> None:
    # Its own short transaction: a wrong code must count as an attempt even though the request
    # then fails (and the request's own transaction is rolled back).
    with conn.engine.begin() as own:
        row = own.execute(text(
            """SELECT verification_id::text AS id, code_hash, attempts, expires_at > now() AS live
               FROM phone_verification
               WHERE account_id = :a AND phone_hash = :h AND verified_at IS NULL
               ORDER BY created_at DESC LIMIT 1 FOR UPDATE"""),
            {"a": account_id, "h": _hash(settings, phone)}).first()
        if row is None or not row.live:
            raise InterviewError(422, "인증번호가 만료됐어요. 다시 받아 주세요", expired=True)
        if row.attempts >= MAX_ATTEMPTS:
            raise InterviewError(422, "입력 횟수를 넘었어요. 인증번호를 다시 받아 주세요",
                                 expired=True)
        ok = hmac.compare_digest(row.code_hash,
                                 _hash(settings, f"{row.id}:{(code or '').strip()}"))
        own.execute(text(
            """UPDATE phone_verification
               SET attempts = attempts + 1, verified_at = CASE WHEN :ok THEN now() END
               WHERE verification_id = :v"""), {"v": row.id, "ok": ok})
    if not ok:
        raise InterviewError(422, "인증번호가 맞지 않아요",
                             attempts_left=MAX_ATTEMPTS - row.attempts - 1)


def apply(conn: Connection, settings: Settings, account_id: str, raw_phone: str,
          code: str | None, consent_text_version: str, sender: SmsSender | None) -> dict:
    if not settings.interview_enabled:
        raise InterviewError(409, "interview applications are closed")
    if consent_text_version != settings.interview_consent_version:
        raise InterviewError(409, "동의 문구가 바뀌었어요. 새로고침 후 다시 동의해 주세요")
    phone = normalize_phone(raw_phone)
    if sender is not None:
        _verify(conn, settings, account_id, phone, code or "")
    consent_id = conn.execute(text(
        """INSERT INTO data_consent (account_id, consent_type, policy_version, status, scope)
           VALUES (:a, 'INTERVIEW_CONTACT', :v, 'GRANTED',
                   '{"purpose": "user_interview_contact", "items": ["mobile_phone"]}'::jsonb)
           RETURNING consent_id::text"""),
        {"a": account_id, "v": consent_text_version}).scalar_one()
    conn.execute(text(
        """INSERT INTO interview_contact (account_id, phone_e164, phone_verified_at, consent_id,
               consent_text_version, consented_at)
           VALUES (:a, :p, CASE WHEN :ver THEN now() END, CAST(:c AS uuid), :v, now())
           ON CONFLICT (account_id) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164,
               phone_verified_at = EXCLUDED.phone_verified_at, consent_id = EXCLUDED.consent_id,
               consent_text_version = EXCLUDED.consent_text_version,
               consented_at = EXCLUDED.consented_at, withdrawn_at = NULL"""),
        {"a": account_id, "p": phone, "ver": sender is not None, "c": consent_id,
         "v": consent_text_version})
    return status(conn, settings, account_id, sender)


def withdraw(conn: Connection, settings: Settings, account_id: str, sender: SmsSender | None) -> dict:
    # Everything derived from the number goes too, including code checks that never led to consent.
    conn.execute(text("DELETE FROM phone_verification WHERE account_id = :a"), {"a": account_id})
    row = conn.execute(text(
        """UPDATE interview_contact SET phone_e164 = NULL, phone_verified_at = NULL,
               withdrawn_at = now()
           WHERE account_id = :a AND withdrawn_at IS NULL RETURNING consent_text_version"""),
        {"a": account_id}).first()
    if row is not None:
        conn.execute(text(
            """INSERT INTO data_consent (account_id, consent_type, policy_version, status,
                   revoked_at, scope)
               VALUES (:a, 'INTERVIEW_CONTACT', :v, 'REVOKED', now(),
                       '{"purpose": "user_interview_contact"}'::jsonb)"""),
            {"a": account_id, "v": row.consent_text_version})
    return status(conn, settings, account_id, sender)
