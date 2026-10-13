"""A Slack message to the team when a new member signs up (docs/10 §가입 알림).

Sent when a new member's first answers are linked at login (the funnel's "로그인 완료"), after
the response, so a slow or failing Slack never touches the login. Counts and the marketing
channel only: no name, contact, school or account id leaves the service. The team's own
browsers (?internal=1) are left out, like everywhere else in the statistics.
"""
from __future__ import annotations

import logging
import re
from typing import Protocol

import httpx
from sqlalchemy import Connection, text

from hellomyme.config import Settings

log = logging.getLogger(__name__)

USER_TYPES = {"STUDENT": "학생", "JOB_SEEKER": "취준생", "PROFESSIONAL": "직장인"}


class Notifier(Protocol):
    def post(self, message: str) -> None: ...


class SlackWebhook:
    def __init__(self, url: str):
        self.url = url

    def post(self, message: str) -> None:
        try:
            r = httpx.post(self.url, json={"text": message}, timeout=5.0)
        except httpx.HTTPError as exc:
            log.warning("signup alert not sent: %s", type(exc).__name__)  # never the URL
            return
        if r.status_code != 200:
            log.warning("signup alert not sent: HTTP %s", r.status_code)


def get_notifier(settings: Settings) -> Notifier | None:
    url = settings.slack_signup_webhook_url
    return SlackWebhook(url.get_secret_value()) if url else None


def _plain(value: object, limit: int = 40) -> str | None:
    """A visitor-supplied value (utm, referrer) as inert text: no Slack markup, links or mentions."""
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[<>&*_~`|@!\s]+", " ", value).strip()[:limit]
    return cleaned or None


def signup_message(conn: Connection, draft_id: str, anonymous_session: str,
                   web_url: str) -> str | None:
    """The alert for the member who just claimed this draft, or None for the team's own sign-ups."""
    draft = conn.execute(text(
        """SELECT internal, user_type, payload_json->>'import_attempt_id' IS NOT NULL AS imported
           FROM anonymous_draft WHERE draft_id = CAST(:d AS uuid)"""), {"d": draft_id}).first()
    if draft is None or draft.internal:
        return None
    # First touch of this browser (track.ts sends it with every event).
    touch = conn.execute(text(
        """SELECT properties FROM analytics.event WHERE anonymous_session_id = :s
           ORDER BY occurred_at LIMIT 1"""), {"s": anonymous_session}).scalar() or {}
    if touch.get("internal") is True:
        return None
    counts = conn.execute(text(
        """WITH members AS (
               SELECT a.account_id, a.created_at FROM account a
               WHERE a.status = 'ACTIVE' AND EXISTS (
                   SELECT 1 FROM anonymous_draft d
                   WHERE d.claimed_account_id = a.account_id AND NOT d.internal))
           SELECT count(*) FILTER (WHERE (created_at AT TIME ZONE 'Asia/Seoul')::date
                                         = (now() AT TIME ZONE 'Asia/Seoul')::date) AS today,
                  count(*) AS total
           FROM members""")).one()

    source = _plain(touch.get("utm_source")) or _plain(touch.get("in_app")) \
        or _plain(touch.get("referrer")) or "직접 방문"
    channel = [f"유입 `{source}`"]
    if campaign := _plain(touch.get("utm_campaign")):
        channel.append(f"캠페인 `{campaign}`")
    if draft.imported:
        channel.append("이력서로 시작")
    return "\n".join([
        f":tada: *nextpath 회원가입* — {USER_TYPES.get(draft.user_type, draft.user_type)}",
        " · ".join(channel),
        f"오늘 {counts.today}번째 · 누적 {counts.total:,}명",
        f"<{web_url.rstrip('/')}/admin|대시보드에서 보기>",
    ])


def safe_message(conn: Connection, draft_id: str, anonymous_session: str, web_url: str) -> str | None:
    """signup_message inside a savepoint: an alert problem never fails or rolls back the login."""
    try:
        with conn.begin_nested():
            return signup_message(conn, draft_id, anonymous_session, web_url)
    except Exception:  # noqa: BLE001 - the alert is optional, the login is not
        log.warning("signup alert skipped", exc_info=True)
        return None
