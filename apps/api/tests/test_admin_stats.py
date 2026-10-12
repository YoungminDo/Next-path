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

    with_team = c.get("/admin/stats", headers=auth, params={"range": "today", "with_team": True}).json()
    assert next(s for s in with_team["schools"] if s["name"] == f"대시보드{tag}대학교")["people"] == 2
    week = c.get("/admin/stats", headers=auth, params={"range": "7d"}).json()
    assert len(week["daily"]) == 7  # empty days are zeros, not gaps
    assert c.get("/admin/stats", headers=auth, params={"range": "1y"}).status_code == 422
    assert "phone" not in out.text and visitor not in out.text  # counts only
