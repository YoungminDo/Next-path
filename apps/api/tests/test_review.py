"""Members' own reviews (/alert, migration 0045): kept as written, shown only with their own publish
consent and the team's approval, nothing shown below the minimum, contacts refused, deleting clears
the text and revokes the consent."""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from hellomyme.config import Settings, get_settings
from hellomyme.main import create_app
from tests.test_acquisition import login

VERSION = "review_publish_v1"


def client(**overrides) -> tuple[TestClient, object]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        **{"env": "test", "auth_providers": ["DEV"], **overrides})
    return TestClient(app), app


def write(c, auth, words, publish=True, **extra):
    return c.post("/acq/me/review", headers=auth, json={
        "surface": "FIT", "body": words, "publish": publish,
        "consent_text_version": VERSION if publish else None, **extra})


def consents(engine, subject: str) -> list[str]:
    with engine.begin() as conn:
        return conn.execute(text(
            """SELECT d.status FROM data_consent d JOIN account_identity ai USING (account_id)
               WHERE ai.provider_subject = :s AND d.consent_type = 'REVIEW_PUBLISH'
               ORDER BY d.consented_at, d.revoked_at NULLS FIRST"""), {"s": subject}).scalars().all()


def test_write_replace_and_delete(engine):
    c, _ = client()
    assert c.get("/acq/me/review").status_code == 401  # members only
    auth = login(c, "review-own")
    assert c.get("/acq/me/review", headers=auth).json()["review"] is None
    assert write(c, auth, "짧아요").status_code == 422
    assert write(c, auth, "연락 주세요 010-1234-5678 으로요").status_code == 422
    assert write(c, auth, "자세한 건 https://example.com 에 있어요").status_code == 422
    assert write(c, auth, "공고를 놓치지 않게 됐어요 정말로요", consent_text_version="old").status_code == 409

    first = write(c, auth, "  공고를   놓치지 않게 됐어요.  ")
    assert first.status_code == 200, first.text
    r = first.json()["review"]
    assert (r["body"], r["publish"], r["state"]) == ("공고를 놓치지 않게 됐어요.", True, "PENDING")
    second = write(c, auth, "분석이 생각보다 구체적이었어요", publish=False).json()["review"]
    assert (second["publish"], second["body"]) == (False, "분석이 생각보다 구체적이었어요")
    assert consents(engine, "review-own") == ["GRANTED", "REVOKED"]  # the first one's consent went

    assert c.delete("/acq/me/review", headers=auth).json()["review"] is None
    with engine.begin() as conn:
        left = conn.execute(text(
            """SELECT count(*) FILTER (WHERE body IS NOT NULL) FROM service_review r
               JOIN account_identity ai USING (account_id) WHERE ai.provider_subject = 'review-own'"""
        )).scalar()
    assert left == 0


def test_only_approved_publish_consented_reviews_show_and_only_from_the_minimum(engine):
    c, app = client()
    tag = uuid.uuid4().hex[:6]
    words = [f"알림 덕분에 마감 전에 지원했어요 {tag} {i}" for i in range(3)]
    for i, w in enumerate(words):
        assert write(c, login(c, f"review-pub-{tag}-{i}"), w).status_code == 200
    private = login(c, f"review-private-{tag}")
    assert write(c, private, f"공개는 원하지 않아요 {tag}", publish=False).status_code == 200

    admin = login(c, f"review-admin-{tag}")
    denied = c.get("/admin/reviews", headers=admin)
    assert denied.status_code == 403
    admin_id = denied.json()["detail"]["account_id"]
    app.dependency_overrides[get_settings] = lambda: Settings(
        env="test", auth_providers=["DEV"], admin_account_ids=[admin_id], review_min_shown=1)
    queue = c.get("/admin/reviews", headers=admin).json()["reviews"]
    mine = {r["body"]: r for r in queue if tag in r["body"]}
    assert len(mine) == 4 and all(r["state"] == "PENDING" for r in mine.values())

    assert not any(tag in r["body"] for r in c.get("/acq/reviews").json()["reviews"])  # none approved
    for w in words[:2]:
        assert c.post(f"/admin/reviews/{mine[w]['review_id']}", headers=admin,
                      json={"decision": "APPROVED"}).status_code == 200
    no_consent = mine[f"공개는 원하지 않아요 {tag}"]["review_id"]
    assert c.post(f"/admin/reviews/{no_consent}", headers=admin,
                  json={"decision": "APPROVED"}).status_code == 409
    assert c.post(f"/admin/reviews/{uuid.uuid4()}", headers=admin,
                  json={"decision": "HIDDEN"}).status_code == 404
    # Approved, then hidden: the latest decision counts.
    c.post(f"/admin/reviews/{mine[words[1]]['review_id']}", headers=admin, json={"decision": "HIDDEN"})

    shown = [r for r in c.get("/acq/reviews").json()["reviews"] if tag in r["body"]]
    assert [r["body"] for r in shown] == [words[0]]
    assert set(shown[0]) == {"surface", "label", "body", "month"}  # no name, account or id
    assert shown[0]["label"] == "1차 분석을 받은 분"

    app.dependency_overrides[get_settings] = lambda: Settings(
        env="test", auth_providers=["DEV"], admin_account_ids=[admin_id], review_min_shown=10_000)
    assert c.get("/acq/reviews").json()["reviews"] == []  # below the minimum nothing is shown


def test_switched_off_new_reviews_are_refused():
    c, _ = client(review_enabled=False)
    auth = login(c, "review-off")
    assert c.get("/acq/me/review", headers=auth).json()["enabled"] is False
    assert write(c, auth, "공고를 놓치지 않게 됐어요 정말로요").status_code == 409
    assert c.delete("/acq/me/review", headers=auth).status_code == 200  # deleting still works
