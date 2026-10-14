"""Sign-up alert to the team's Slack: once per new member, counts and channel only, never the
team's own sign-ups, never in the way of the login."""
import re
import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from hellomyme.api.auth import signup_notifier
from hellomyme.config import Settings, get_settings
from hellomyme.domain.signup_alert import SlackWebhook
from hellomyme.main import create_app
from tests.test_acquisition import anon, login, save, student
from tests.test_career_query import ids  # noqa: F401  (module fixture: imports the cohort)


class FakeSlack:
    def __init__(self):
        self.messages: list[str] = []

    def post(self, message: str) -> None:
        self.messages.append(message)


def client_with(slack) -> TestClient:
    app = create_app()
    settings = Settings(env="test", auth_providers=["DEV"])
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[signup_notifier] = lambda: slack
    return TestClient(app)


def touch(c, h, **props):
    r = c.post("/analytics/events", json={
        "event_name": "landing_viewed", "occurred_at": datetime.now(UTC).isoformat(),
        "anonymous_session_id": h["X-Anonymous-Session"], "properties": props})
    assert r.status_code == 202, r.text


def merge(c, h, draft, auth):
    body = {"draft_id": draft, "consent_policy_version": "v1"}
    r = c.post("/auth/merge-draft", headers={**auth, **h, "Idempotency-Key": uuid.uuid4().hex},
               json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_new_member_is_announced_once_with_the_channel_only(ids):  # noqa: F811
    slack = FakeSlack()
    c = client_with(slack)
    h = anon()
    tag = uuid.uuid4().hex[:6]
    touch(c, h, utm_source="insta<!channel>", utm_campaign=f"fall_*promo*{tag}")
    touch(c, anon(), utm_source="insta", utm_campaign=f"fall_*promo*{tag}")  # a visitor who left
    touch(c, anon(), utm_source="insta", utm_campaign=f"fall_*promo*{tag}", utm_medium="paid_social",
          referrer="www.facebook.com")  # Meta's ad review: not a person, not in the rate
    draft = save(c, h, student(ids))
    auth = login(c, "alert-new")
    assert merge(c, h, draft, auth)["merged"] is True
    assert len(slack.messages) == 1
    msg = slack.messages[0]
    assert msg.startswith(":tada: *nextpath 회원가입* — 학생")
    # Visitor-supplied text is inert: no mention, link or bold can be injected.
    assert "유입 `insta !channel`" in msg and f"캠페인 `fall_*promo*{tag}`" in msg
    # Sign-up rate: this campaign's new members over its visiting browsers (1 of 2 came back).
    assert f"캠페인 `fall_*promo*{tag}` 50.0% (1/2명) (누적)" in msg
    assert re.search(r"가입 전환율 · 오늘 \d+\.\d% \(\d+/[\d,]+명\)", msg)
    assert "<!channel>" not in msg and "오늘 " in msg and "누적 " in msg
    assert msg.endswith("<https://nextpath.da-sh.io/admin|대시보드에서 보기>")
    assert draft not in msg and "고려" not in msg  # no ids, no school
    merge(c, h, draft, auth)  # a replay of the same merge
    assert len(slack.messages) == 1


def test_the_team_and_returning_members_are_not_announced(ids):  # noqa: F811
    slack = FakeSlack()
    c = client_with(slack)
    h = anon()
    r = c.post("/acq/draft", headers=h, json={"payload": student(ids), "internal": True})
    merge(c, h, r.json()["draft_id"], login(c, "alert-team"))
    h2 = anon()
    touch(c, h2, internal=True)  # a team browser (?internal=1) that forgot the draft flag
    merge(c, h2, save(c, h2, student(ids)), login(c, "alert-team-2"))
    assert slack.messages == []

    h3 = anon()
    auth = login(c, "alert-returning")
    merge(c, h3, save(c, h3, student(ids)), auth)
    merge(c, h3, save(c, h3, {**student(ids), "user_type": "JOB_SEEKER"}), auth)  # linked, not new
    assert len(slack.messages) == 1 and "직접 방문" in slack.messages[0]


def test_alerts_are_off_without_a_webhook_and_slack_errors_are_swallowed(ids):  # noqa: F811
    c = client_with(None)
    h = anon()
    assert merge(c, h, save(c, h, student(ids)), login(c, "alert-off"))["merged"] is True
    SlackWebhook("http://127.0.0.1:9/hook").post("hello")  # nothing listens: logged, not raised


def test_checkout_events_are_accepted(ids):  # noqa: F811
    client = client_with(None)
    for name in ("checkout_viewed", "checkout_completed", "checkout_cancelled"):
        r = client.post("/analytics/events", json={
            "event_name": name, "occurred_at": datetime.now(UTC).isoformat(), "properties": {}})
        assert r.status_code == 202, (name, r.text)
