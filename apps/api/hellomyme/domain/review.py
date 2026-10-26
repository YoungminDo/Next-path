"""Members' own reviews of /alert (migration 0045; docs/10 §공고 알림 랜딩, 이용 후기).

A member writes a few lines after using a step (FIT: the first-pass analysis; ALERT: a job alert).
Showing it on the landing is optional and has its own consent, REVIEW_PUBLISH (PIPA §15(2): purpose,
item, retention until deleted, the right to refuse). The text is kept as written: the team approves
or hides it (append-only decisions, the latest counts) and never edits it, so the landing never
shows words a member did not write (표시광고법 §3). The page shows no name or account, only the step
and the month. Nothing is shown until at least `review_min_shown` reviews are approved, the same
small-number rule as every other count on the page. Contacts and links are refused in the text so a
public review cannot carry them. Deleting a review clears the text at once.
"""
from __future__ import annotations

import re
from typing import Literal

from sqlalchemy import Connection, text

from hellomyme.config import Settings
from hellomyme.domain.interview import InterviewError

Surface = Literal["FIT", "ALERT"]
Decision = Literal["APPROVED", "HIDDEN"]
SURFACE_LABELS = {"FIT": "1차 분석을 받은 분", "ALERT": "공고 알림을 받은 분"}
MIN_LEN, MAX_LEN = 10, 300
_SCOPE = '{"purpose": "review_publish", "items": ["review_text", "surface"]}'
# A phone number (also with spaces or dots), any long run of digits, an e-mail address or a link.
_CONTACT = re.compile(r"01[016789][\s.-]?\d{3,4}[\s.-]?\d{4}|\d{8,}|[\w.+-]+@[\w-]+\.[\w.]+"
                      r"|https?://|www\.", re.IGNORECASE)

# The latest decision per review; none yet = PENDING.
_STATE = """coalesce((SELECT d.decision FROM service_review_decision d
                      WHERE d.review_id = r.review_id
                      ORDER BY d.decided_at DESC, d.decision_id DESC LIMIT 1), 'PENDING')"""


def _revoke(conn: Connection, account_id: str, versions: list[str]) -> None:
    for v in versions:
        conn.execute(text(
            f"""INSERT INTO data_consent (account_id, consent_type, policy_version, status,
                   revoked_at, scope)
                VALUES (:a, 'REVIEW_PUBLISH', :v, 'REVOKED', now(), '{_SCOPE}'::jsonb)"""),
            {"a": account_id, "v": v})


def _clear(conn: Connection, account_id: str) -> None:
    """Deletes the member's current review: the text goes, the publish consent is revoked."""
    rows = conn.execute(text(
        """UPDATE service_review SET body = NULL, deleted_at = now()
           WHERE account_id = :a AND deleted_at IS NULL
           RETURNING publish, consent_text_version"""), {"a": account_id}).all()
    _revoke(conn, account_id, [r.consent_text_version for r in rows if r.publish])


def status(conn: Connection, settings: Settings, account_id: str) -> dict:
    row = conn.execute(text(
        f"""SELECT r.surface, r.body, r.publish, r.created_at, {_STATE} AS state
            FROM service_review r WHERE r.account_id = :a AND r.deleted_at IS NULL
            ORDER BY r.created_at DESC LIMIT 1"""), {"a": account_id}).first()
    return {
        "enabled": settings.review_enabled,
        "consent_text_version": settings.review_consent_version,
        "review": None if row is None else {
            "surface": row.surface, "body": row.body, "publish": row.publish,
            "created_at": row.created_at.isoformat(), "state": row.state},
    }


def submit(conn: Connection, settings: Settings, account_id: str, surface: Surface, body: str,
           publish: bool, consent_text_version: str | None) -> dict:
    """A new review replaces the member's earlier one (which goes, text and consent)."""
    if not settings.review_enabled:
        raise InterviewError(409, "reviews are closed")
    body = re.sub(r"\s+", " ", body).strip()
    if not MIN_LEN <= len(body) <= MAX_LEN:
        raise InterviewError(422, f"{MIN_LEN}~{MAX_LEN}자로 써 주세요")
    if _CONTACT.search(body):
        raise InterviewError(422, "연락처나 링크는 빼고 써 주세요")
    if publish and consent_text_version != settings.review_consent_version:
        raise InterviewError(409, "동의 문구가 바뀌었어요. 새로고침 후 다시 동의해 주세요")
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 45))"),
                 {"k": f"review:{account_id}"})
    _clear(conn, account_id)
    consent_id = None
    if publish:
        consent_id = conn.execute(text(
            f"""INSERT INTO data_consent (account_id, consent_type, policy_version, status, scope)
                VALUES (:a, 'REVIEW_PUBLISH', :v, 'GRANTED', '{_SCOPE}'::jsonb)
                RETURNING consent_id::text"""),
            {"a": account_id, "v": consent_text_version}).scalar_one()
    conn.execute(text(
        """INSERT INTO service_review (account_id, surface, body, publish, consent_id,
               consent_text_version)
           VALUES (:a, :s, :b, :p, CAST(:c AS uuid), :v)"""),
        {"a": account_id, "s": surface, "b": body, "p": publish, "c": consent_id,
         "v": consent_text_version if publish else None})
    return status(conn, settings, account_id)


def delete(conn: Connection, settings: Settings, account_id: str) -> dict:
    _clear(conn, account_id)
    return status(conn, settings, account_id)


def public(conn: Connection, settings: Settings, limit: int = 20) -> dict:
    """What the landing may show: approved, publish-consented, not deleted; nothing below the minimum."""
    rows = conn.execute(text(
        f"""SELECT r.surface, r.body, r.created_at FROM service_review r
            WHERE r.publish AND r.deleted_at IS NULL AND {_STATE} = 'APPROVED'
            ORDER BY r.created_at DESC""")).all()
    if len(rows) < settings.review_min_shown:
        return {"reviews": []}
    return {"reviews": [
        {"surface": r.surface, "label": SURFACE_LABELS[r.surface], "body": r.body,
         "month": r.created_at.strftime("%Y-%m")} for r in rows[:limit]]}


def for_review(conn: Connection) -> dict:
    """The team's queue (/admin): every current review, publish-consented ones first."""
    rows = conn.execute(text(
        f"""SELECT r.review_id::text, r.surface, r.body, r.publish, r.created_at, {_STATE} AS state
            FROM service_review r WHERE r.deleted_at IS NULL
            ORDER BY (r.publish AND {_STATE} = 'PENDING') DESC, r.created_at DESC
            LIMIT 200""")).all()
    return {"reviews": [
        {"review_id": r.review_id, "surface": r.surface, "body": r.body, "publish": r.publish,
         "created_at": r.created_at.isoformat(), "state": r.state} for r in rows]}


def decide(conn: Connection, review_id: str, decision: Decision, admin_account_id: str) -> dict:
    row = conn.execute(text(
        "SELECT publish FROM service_review WHERE review_id = CAST(:r AS uuid) AND deleted_at IS NULL"),
        {"r": review_id}).first()
    if row is None:
        raise InterviewError(404, "없는 후기예요")
    if decision == "APPROVED" and not row.publish:
        raise InterviewError(409, "공개에 동의하지 않은 후기예요")
    conn.execute(text(
        """INSERT INTO service_review_decision (review_id, decision, decided_by)
           VALUES (CAST(:r AS uuid), :d, CAST(:a AS uuid))"""),
        {"r": review_id, "d": decision, "a": admin_account_id})
    return for_review(conn)
