"""Team dashboard (/admin/stats): admins only, team sessions left out, counts only."""
import uuid

from fastapi.testclient import TestClient

from hellomyme.config import Settings, get_settings
from hellomyme.main import create_app
from tests.test_acquisition import login, student
from tests.test_career_query import ids  # noqa: F401


def event(c, name, sid, **props):
    r = c.post("/analytics/events", json={"event_name": name, "occurred_at": "2026-10-12T00:00:00Z",
                                          "anonymous_session_id": sid, "properties": props})
    assert r.status_code == 202


def test_only_listed_accounts_see_the_numbers(engine, ids):  # noqa: F811
    app = create_app()
    settings = Settings(env="test", auth_providers=["DEV"])
    app.dependency_overrides[get_settings] = lambda: settings
    c = TestClient(app)
    assert c.get("/admin/stats").status_code == 401
    auth = login(c, f"admin-{uuid.uuid4().hex[:6]}")
    denied = c.get("/admin/stats", headers=auth)
    assert denied.status_code == 403
    account_id = denied.json()["detail"]["account_id"]  # told to the member, to ask for access

    tag = uuid.uuid4().hex[:6]
    visitor, team = uuid.uuid4().hex, uuid.uuid4().hex
    for sid, extra in ((visitor, {}), (team, {"internal": True})):
        event(c, "landing_viewed", sid, utm_source=f"insta{tag}", **extra)
        event(c, "career_input_completed", sid, **extra)
        event(c, "login_consent_missing", sid, **extra)  # pressed Kakao before ticking consent
        payload = {**student(ids), "education": {**student(ids)["education"], "institution_id": None,
                                                 "institution_raw": f"대시보드{tag}대학교"},
                   "desired_role_status": "NONE"}
        assert c.post("/acq/draft", headers={"X-Anonymous-Session": sid},
                      json={"draft_id": None, "payload": payload}).status_code == 200

    app.dependency_overrides[get_settings] = lambda: Settings(env="test", auth_providers=["DEV"],
                                                             admin_account_ids=[account_id])
    out = c.get("/admin/stats", headers=auth, params={"range": "today"})
    assert out.status_code == 200, out.text
    assert out.headers["cache-control"] == "no-store"
    body = out.json()
    funnel = {f["key"]: f["people"] for f in body["funnel"]}
    channel = next(ch for ch in body["channels"] if ch["channel"] == f"insta{tag}")
    school = next(s for s in body["schools"] if s["name"] == f"대시보드{tag}대학교")
    assert (channel["landing"], channel["input_completed"]) == (1, 1)  # the team's visit is left out
    assert school == {"name": f"대시보드{tag}대학교", "listed": False, "people": 1}
    assert funnel["landing"] >= 1 and len(body["daily"]) == 1
    assert any(s["status"] == "NONE" for s in body["desired_status"])
    assert body["gate"]["consent_missing"] >= 1 and "then_clicked" in body["gate"]

    with_team = c.get("/admin/stats", headers=auth, params={"range": "today", "with_team": True}).json()
    assert next(s for s in with_team["schools"] if s["name"] == f"대시보드{tag}대학교")["people"] == 2
    week = c.get("/admin/stats", headers=auth, params={"range": "7d"}).json()
    assert len(week["daily"]) == 7  # empty days are zeros, not gaps
    assert c.get("/admin/stats", headers=auth, params={"range": "1y"}).status_code == 422
    assert "phone" not in out.text and visitor not in out.text  # counts only


def test_campaigns_count_visits_inputs_and_new_members(engine, ids):  # noqa: F811
    from tests.test_acquisition import merge, save

    app = create_app()
    c = TestClient(app)
    admin = login(c, f"admin-{uuid.uuid4().hex[:6]}")
    account_id = c.get("/admin/stats", headers=admin).json()["detail"]["account_id"]
    tag = f"np_{uuid.uuid4().hex[:6]}_student"
    joiner, looker, team, clicker, review, bot, split, direct, handed = (uuid.uuid4().hex for _ in range(9))
    paid = {"utm_medium": "paid_social"}
    for sid, extra in ((joiner, {}), (looker, {}), (team, {"internal": True}),
                       (clicker, {**paid, "fbclid": "1"}),    # a real ad click: counted
                       (review, {**paid, "referrer": "m.facebook.com"}),  # Meta's ad review: not a person
                       (bot, {"bot": True})):                  # an automated browser
        event(c, "landing_viewed", sid, utm_source="meta", utm_campaign=tag, **extra)
    camp = {"utm_source": "meta", "utm_campaign": tag}
    # 방문 = the first event is an arrival (docs/10 §방문): a later landing step first is the same person
    # under a second id (Instagram's preloaded landing), and the phone's browser an in-app browser handed
    # the answers to is the same person too; /start opened directly is a visit.
    event(c, "career_input_started", split, path="/", **camp)
    event(c, "landing_viewed", split, path="/", **camp)
    event(c, "career_input_started", direct, path="/start", **camp)
    event(c, "career_input_started", handed, path="/start", handoff="1", **camp)
    event(c, "career_input_completed", joiner, utm_source="meta", utm_campaign=tag)
    event(c, "login_clicked", joiner, utm_source="meta", utm_campaign=tag)
    h = {"X-Anonymous-Session": joiner}
    merge(c, h, save(c, h, student(ids)), f"camp-{tag}")  # a new member from the campaign

    app.dependency_overrides[get_settings] = lambda: Settings(env="test", auth_providers=["DEV"],
                                                             admin_account_ids=[account_id])
    rows = c.get("/admin/stats", headers=admin, params={"range": "today"}).json()["campaigns"]
    row = next(r for r in rows if r["campaign"] == tag)
    assert {k: row[k] for k in ("source", "visits", "inputs", "login_clicks", "new_members")} == {
        "source": "meta", "visits": 4, "inputs": 1, "login_clicks": 1, "new_members": 1}
