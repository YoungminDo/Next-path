"""Paid cards (migration 0037): sign-up gives one 튜브; a card past that is bought for 990원
through Toss Payments, confirmed server-side, credited once, then opened."""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from hellomyme.api.acquisition import payment_provider
from hellomyme.config import Settings, get_settings
from hellomyme.main import create_app
from tests.test_acquisition import anon, login, merge, save, student
from tests.test_career_query import ids  # noqa: F401  (module fixture: imports the cohort)


class FakeToss:
    """Answers like POST /v1/payments/confirm: DONE with the amount, or an error body."""

    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def confirm(self, payment_key, order_id, amount):
        self.calls.append((payment_key, order_id, amount))
        if not self.ok:
            return 400, {"code": "REJECT_CARD_COMPANY", "message": "카드사에서 거절했어요"}
        return 200, {"status": "DONE", "orderId": order_id, "totalAmount": amount, "method": "카드",
                     "approvedAt": "2026-10-13T19:00:00+09:00",
                     "receipt": {"url": "https://example.test/receipt"}}


def app_with(provider) -> TestClient:
    app = create_app()
    settings = Settings(env="test", auth_providers=["DEV"], toss_secret_key="test_sk_x")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[payment_provider] = lambda: provider
    return TestClient(app)


def member(c, ids, subject):  # noqa: F811
    h = anon()
    auth, _ = merge(c, h, save(c, h, student(ids)), subject)
    return auth


def test_a_card_bought_for_990_is_confirmed_credited_once_and_opened(engine, ids):  # noqa: F811
    toss = FakeToss()
    c = app_with(toss)
    auth = member(c, ids, "pay-buyer")
    me = c.get("/acq/me", headers=auth).json()
    assert me["balance_tube"] == 1  # the sign-up gift only
    assert me["payments"] == {"enabled": True, "price_krw": 990}

    order = c.post("/acq/me/payments", headers=auth, json={"insight_type": "PATH_DEEP_DIVE"}).json()
    assert order["amount"] == 990 and order["order_name"] == "nextpath 카드 1장"
    assert order["customer_key"].startswith("np_") and len(order["order_id"]) >= 6
    body = {"order_id": order["order_id"], "payment_key": "pk_1", "amount": 990}
    paid = c.post("/acq/me/payments/confirm", headers=auth, json=body)
    assert paid.status_code == 200, paid.text
    out = paid.json()
    assert out["paid"] is True and out["insight_type"] == "PATH_DEEP_DIVE"
    # Bought and spent on the card at once (opened), or kept when the sample is too small.
    assert out["balance_tube"] == (1 if out["opened"] else 2)
    again = c.post("/acq/me/payments/confirm", headers=auth, json=body).json()
    assert again["paid"] is True and again["balance_tube"] == out["balance_tube"]  # credited once
    assert len(toss.calls) == 1  # a replay never asks Toss again
    with engine.begin() as conn:
        row = conn.execute(text(
            """SELECT status, method, receipt_url, ledger_id IS NOT NULL AS credited
               FROM payment_order WHERE order_id = :o"""), {"o": order["order_id"]}).one()
    assert tuple(row) == ("PAID", "카드", "https://example.test/receipt", True)

    stranger = login(c, "pay-stranger")
    assert c.post("/acq/me/payments/confirm", headers=stranger, json=body).status_code == 404


def test_wrong_amount_and_declines_are_recorded_and_never_credited(engine, ids):  # noqa: F811
    c = app_with(FakeToss())
    auth = member(c, ids, "pay-mismatch")
    order = c.post("/acq/me/payments", headers=auth, json={"insight_type": "SCHOOL_COMPARE"}).json()
    bad = c.post("/acq/me/payments/confirm", headers=auth,
                 json={"order_id": order["order_id"], "payment_key": "pk_2", "amount": 10})
    assert bad.status_code == 402 and bad.json()["detail"]["message"] == "결제 금액이 주문과 달라요"

    declined = app_with(FakeToss(ok=False))
    auth2 = member(declined, ids, "pay-declined")
    order2 = declined.post("/acq/me/payments", headers=auth2,
                           json={"insight_type": "SCHOOL_COMPARE"}).json()
    r = declined.post("/acq/me/payments/confirm", headers=auth2,
                      json={"order_id": order2["order_id"], "payment_key": "pk_3", "amount": 990})
    assert r.status_code == 402 and r.json()["detail"]["message"] == "카드사에서 거절했어요"
    assert declined.get("/acq/me", headers=auth2).json()["balance_tube"] == 1
    with engine.begin() as conn:
        rows = dict(conn.execute(text(
            "SELECT order_id, failure_code FROM payment_order WHERE order_id IN (:a, :b)"),
            {"a": order["order_id"], "b": order2["order_id"]}).all())
    assert rows == {order["order_id"]: "AMOUNT_MISMATCH", order2["order_id"]: "REJECT_CARD_COMPANY"}


def test_paid_cards_are_off_without_a_key(ids):  # noqa: F811
    app = create_app()
    settings = Settings(env="test", auth_providers=["DEV"])
    app.dependency_overrides[get_settings] = lambda: settings
    c = TestClient(app)
    h = anon()
    auth, _ = merge(c, h, save(c, h, student(ids)), "pay-off")
    assert c.get("/acq/me", headers=auth).json()["payments"]["enabled"] is False
    r = c.post("/acq/me/payments", headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
               json={"insight_type": "SCHOOL_COMPARE"})
    assert r.status_code == 409
