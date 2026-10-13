"""Paid cards (migration 0037): sign-up gives one 튜브; a card past that is bought for 990원
through Toss Payments, confirmed server-side, credited once, then opened. Without a Toss key the
payment-intent test (0038) runs instead: our own checkout, nothing charged, a 튜브 gifted."""
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
    key = {"toss_secret_key": "test_sk_x"} if provider else {}
    settings = Settings(env="test", auth_providers=["DEV"], **key)
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
    assert me["payments"] == {"enabled": True, "mode": "TOSS", "price_krw": 990}

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


def test_without_a_key_the_checkout_is_a_test_that_gifts_the_tube(engine, ids):  # noqa: F811
    c = app_with(None)
    auth = member(c, ids, "pay-test")
    me = c.get("/acq/me", headers=auth).json()
    assert me["payments"] == {"enabled": True, "mode": "TEST", "price_krw": 990}
    order = c.post("/acq/me/payments", headers=auth, json={"insight_type": "FIRST_COMPANY_SIZE"})
    assert order.status_code == 200, order.text
    order = order.json()
    assert order["mode"] == "TEST" and order["amount"] == 990
    shown = c.get(f"/acq/me/payments/{order['order_id']}", headers=auth).json()
    assert (shown["status"], shown["amount"], shown["insight_type"]) == (
        "CREATED", 990, "FIRST_COMPANY_SIZE")
    # Never the real confirm: there is no provider.
    assert c.post("/acq/me/payments/confirm", headers=auth, json={
        "order_id": order["order_id"], "payment_key": "pk", "amount": 990}).status_code == 409
    assert c.post("/acq/me/payments/test-complete", headers=auth,
                  json={"order_id": order["order_id"], "method": "BITCOIN"}).status_code == 422

    body = {"order_id": order["order_id"], "method": "EASY_PAY"}
    done = c.post("/acq/me/payments/test-complete", headers=auth, json=body)
    assert done.status_code == 200, done.text
    out = done.json()
    # 1 (sign-up) + 1 (gift) - 1 (the card it opened) = 1, the sign-up gift is still there.
    assert (out["completed"], out["gifted"], out["opened"], out["balance_tube"]) == (True, True, True, 1)
    again = c.post("/acq/me/payments/test-complete", headers=auth, json=body).json()
    assert (again["gifted"], again["balance_tube"]) == (True, 1)  # once per order
    card = next(x for x in c.get("/acq/me", headers=auth).json()["cards"]
                if x["type"] == "FIRST_COMPANY_SIZE")
    assert card["unlocked"] and card["result"]["cells"][0]["key"] == "LARGE"
    with engine.begin() as conn:
        row = conn.execute(text(
            """SELECT provider, status, method, ledger_id IS NOT NULL AS gifted, payment_key
               FROM payment_order WHERE order_id = :o"""), {"o": order["order_id"]}).one()
    assert tuple(row) == ("TEST", "TEST_COMPLETED", "EASY_PAY", True, None)
    stranger = login(c, "pay-test-stranger")
    assert c.post("/acq/me/payments/test-complete", headers=stranger, json=body).status_code == 404


def test_paid_cards_are_off_with_no_key_and_no_test_gift(engine, ids):  # noqa: F811
    c = app_with(None)
    auth = member(c, ids, "pay-off")
    with engine.begin() as conn:
        conn.execute(text("UPDATE reward_policy SET status = 'RETIRED' "
                          "WHERE action_type = 'PAYMENT_TEST_GIFT' AND status = 'ACTIVE'"))
    try:
        assert c.get("/acq/me", headers=auth).json()["payments"]["enabled"] is False
        r = c.post("/acq/me/payments", headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
                   json={"insight_type": "SCHOOL_COMPARE"})
        assert r.status_code == 409
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE reward_policy SET status = 'ACTIVE' "
                              "WHERE action_type = 'PAYMENT_TEST_GIFT' AND version = 'reward_v2'"))


def test_cards_open_with_a_tube_and_never_charge_twice(engine, ids):  # noqa: F811
    c = app_with(None)
    auth = member(c, ids, "cards-student")
    cards = c.get("/acq/me", headers=auth).json()["cards"]
    assert [(x["type"], x["available"], x["unlocked"], x["cost_tube"], x["result"]) for x in cards] == [
        ("FIRST_COMPANY_SIZE", True, False, 1, None), ("FIRST_JOB_TENURE", True, False, 1, None),
        ("ROLE_NOW", True, False, 1, None)]
    hdr = {**auth, "Idempotency-Key": uuid.uuid4().hex}
    opened = c.post("/acq/me/cards/FIRST_JOB_TENURE/unlock", headers=hdr)
    assert opened.status_code == 200, opened.text
    out = opened.json()
    assert out["unlocked"] and out["charged"] and out["balance_tube"] == 0
    # Bands in their own order with their labels (other tests' members may join the cohort).
    cells = {x["key"]: x["label"] for x in out["result"]["cells"]}
    assert {"Y1_2": "1~2년", "STAYED": "아직 다니는 중"}.items() <= cells.items()
    order = ["LT_1Y", "Y1_2", "Y2_3", "GE_3Y", "STAYED"]
    assert list(cells) == sorted(cells, key=order.index)
    again = c.post("/acq/me/cards/FIRST_JOB_TENURE/unlock", headers=hdr).json()
    assert again["charged"] is False and again["balance_tube"] == 0
    broke = c.post("/acq/me/cards/ROLE_NOW/unlock",
                   headers={**auth, "Idempotency-Key": uuid.uuid4().hex})
    assert broke.status_code == 402
    # A professional's card is not part of a student's result.
    assert c.post("/acq/me/cards/ROLE_TENURE/unlock",
                  headers={**auth, "Idempotency-Key": uuid.uuid4().hex}).status_code == 422


def test_a_professional_gets_the_professional_cards(ids):  # noqa: F811
    c = app_with(None)
    h = anon()
    pro = {**student(ids), "user_type": "PROFESSIONAL",
           "current_job": {"organization_name": "어딘가", "role_node_id": ids["R3"], "start_year": 2021}}
    auth, _ = merge(c, h, save(c, h, pro), "cards-pro")
    cards = c.get("/acq/me", headers=auth).json()["cards"]
    assert [x["type"] for x in cards] == ["NEXT_COMPANY_SIZE", "ROLE_TENURE"]
    out = c.post("/acq/me/cards/ROLE_TENURE/unlock",
                 headers={**auth, "Idempotency-Key": uuid.uuid4().hex}).json()
    assert out["unlocked"] and {"Y1_2", "STAYED"} <= {x["key"] for x in out["result"]["cells"]}
    # Only the ~10 who moved on count for the next company: too few, so nothing is charged.
    moved = c.post("/acq/me/cards/NEXT_COMPANY_SIZE/unlock",
                   headers={**auth, "Idempotency-Key": uuid.uuid4().hex}).json()
    assert moved == {"unlocked": False, "charged": False}
