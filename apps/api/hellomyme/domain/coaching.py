"""Coaching requests after the fit analysis (/alert, migration 0044; docs/10 §공고 알림 랜딩).

A member picks one of the coaching products (prices in coaching_product) and leaves a mobile
number so the team can call; payment is arranged after that call. The number has its own consent,
COACHING_CONTACT (PIPA §15(2): purpose, item, retention, the right to refuse); the job-alert or
interview numbers are never reused for it. Cancelling clears the number at once; a number is kept
at most a year after the request. The team hears of a request on Slack with the product only.
"""
from __future__ import annotations

from sqlalchemy import Connection, text

from hellomyme.config import Settings
from hellomyme.domain.interview import InterviewError, masked, normalize_phone

RETENTION = "1 year"
_SCOPE = '{"purpose": "coaching_contact", "items": ["mobile_phone"]}'


def purge_expired(conn: Connection) -> None:
    conn.execute(text(
        f"""UPDATE coaching_request SET phone_e164 = NULL, cancelled_at = now()
            WHERE cancelled_at IS NULL AND requested_at < now() - interval '{RETENTION}'"""))


def products(conn: Connection) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(text(
        """SELECT sku, name, amount_krw FROM coaching_product WHERE status = 'ACTIVE'
           ORDER BY sort_order""")).all()]


def status(conn: Connection, settings: Settings, account_id: str) -> dict:
    purge_expired(conn)
    row = conn.execute(text(
        """SELECT r.sku, p.name, r.amount_krw, r.requested_at, r.phone_e164
           FROM coaching_request r JOIN coaching_product p USING (sku)
           WHERE r.account_id = :a AND r.cancelled_at IS NULL
           ORDER BY r.requested_at DESC LIMIT 1"""), {"a": account_id}).first()
    return {
        "enabled": settings.coaching_enabled,
        "consent_text_version": settings.coaching_consent_version,
        "products": products(conn),
        "request": None if row is None else {
            "sku": row.sku, "name": row.name, "amount_krw": row.amount_krw,
            "requested_at": row.requested_at.isoformat(), "phone_masked": masked(row.phone_e164)},
    }


def request(conn: Connection, settings: Settings, account_id: str, sku: str, raw_phone: str,
            consent_text_version: str) -> tuple[dict, str]:
    """Returns the new status and the product name (for the team's Slack line)."""
    if not settings.coaching_enabled:
        raise InterviewError(409, "coaching requests are closed")
    if consent_text_version != settings.coaching_consent_version:
        raise InterviewError(409, "동의 문구가 바뀌었어요. 새로고침 후 다시 동의해 주세요")
    product = conn.execute(text(
        "SELECT name, amount_krw FROM coaching_product WHERE sku = :s AND status = 'ACTIVE'"),
        {"s": sku}).first()
    if product is None:
        raise InterviewError(422, "없는 상품이에요")
    phone = normalize_phone(raw_phone)
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 44))"),
                 {"k": f"coaching:{account_id}"})
    if status(conn, settings, account_id)["request"] is not None:
        raise InterviewError(409, "이미 신청했어요. 곧 연락드릴게요")
    consent_id = conn.execute(text(
        f"""INSERT INTO data_consent (account_id, consent_type, policy_version, status, scope)
            VALUES (:a, 'COACHING_CONTACT', :v, 'GRANTED', '{_SCOPE}'::jsonb)
            RETURNING consent_id::text"""),
        {"a": account_id, "v": consent_text_version}).scalar_one()
    conn.execute(text(
        """INSERT INTO coaching_request (account_id, sku, amount_krw, analysis_id, phone_e164,
               consent_id, consent_text_version)
           VALUES (:a, :s, :amt,
                   (SELECT analysis_id FROM fit_analysis WHERE account_id = :a AND outcome = 'DONE'
                    ORDER BY created_at DESC LIMIT 1),
                   :p, CAST(:c AS uuid), :v)"""),
        {"a": account_id, "s": sku, "amt": product.amount_krw, "p": phone, "c": consent_id,
         "v": consent_text_version})
    return status(conn, settings, account_id), f"{product.name} ({product.amount_krw:,}원)"


def cancel(conn: Connection, settings: Settings, account_id: str) -> dict:
    rows = conn.execute(text(
        """UPDATE coaching_request SET phone_e164 = NULL, cancelled_at = now()
           WHERE account_id = :a AND cancelled_at IS NULL RETURNING consent_text_version"""),
        {"a": account_id}).all()
    for row in rows:
        conn.execute(text(
            f"""INSERT INTO data_consent (account_id, consent_type, policy_version, status,
                   revoked_at, scope)
                VALUES (:a, 'COACHING_CONTACT', :v, 'REVOKED', now(), '{_SCOPE}'::jsonb)"""),
            {"a": account_id, "v": row.consent_text_version})
    return status(conn, settings, account_id)
