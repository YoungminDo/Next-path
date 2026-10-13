"""Paid cards (migration 0037): a member buys 튜브 through Toss Payments to open a card.

The order (price and 튜브 from the active pricing_policy) is written before the payment window
opens; the payment is confirmed server-side with Toss (secret key, amount checked against the
order) before anything is credited; a paid order credits once (ledger key purchase:<order_id>).
Card numbers never reach this service; only the method, approval time and receipt link are kept.

Payment-intent test (migration 0038): with no Toss key the checkout is our own page. Pressing
"결제하기" charges nothing and asks for no payment details; it is recorded (TEST_COMPLETED) and
gifts 1 튜브 (reward PAYMENT_TEST_GIFT) that opens the card. Retiring that reward turns it off.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from typing import Protocol

import httpx
from sqlalchemy import Connection, text

from hellomyme.config import Settings
from hellomyme.domain import ledger
from hellomyme.domain.acquisition import CARDS
from hellomyme.domain.policies import active_reward_policy

log = logging.getLogger(__name__)

SKU = "CARD_1"
ORDER_NAME = "nextpath 카드 1장"
# The cards that can be opened right after a payment (unlock_policy.insight_type).
PAYABLE = ("SCHOOL_COMPARE", "PATH_DEEP_DIVE", *CARDS)
TEST_GIFT = "PAYMENT_TEST_GIFT"
# What the test checkout offers (nothing is charged whichever is chosen).
TEST_METHODS = ("CARD", "EASY_PAY", "TRANSFER")


class PaymentFailed(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class PaymentProvider(Protocol):
    def confirm(self, payment_key: str, order_id: str, amount: int) -> tuple[int, dict]: ...


class TossPayments:
    """The confirm call of Toss Payments (POST /v1/payments/confirm, Basic auth with the secret
    key). Returns (HTTP status, body)."""

    def __init__(self, settings: Settings):
        secret = settings.toss_secret_key.get_secret_value()
        self.auth = "Basic " + base64.b64encode(f"{secret}:".encode()).decode()
        self.base = settings.toss_api_base.rstrip("/")

    def confirm(self, payment_key: str, order_id: str, amount: int) -> tuple[int, dict]:
        r = httpx.post(f"{self.base}/v1/payments/confirm",
                       json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
                       headers={"Authorization": self.auth, "Idempotency-Key": f"confirm-{order_id}"},
                       timeout=20.0)
        try:
            body = r.json()
        except ValueError:
            body = {}
        return r.status_code, body if isinstance(body, dict) else {}


def get_provider(settings: Settings) -> PaymentProvider | None:
    """None without a secret key: paid cards are off (the button says so)."""
    return TossPayments(settings) if settings.toss_secret_key else None


def mode(conn: Connection, settings: Settings) -> str | None:
    """TOSS with a secret key; TEST (the payment-intent test) without one while its gift reward is
    active; None when cards cannot be bought."""
    if price(conn) is None:
        return None
    if settings.toss_secret_key:
        return "TOSS"
    return "TEST" if active_reward_policy(conn, TEST_GIFT) else None


def price(conn: Connection):
    return conn.execute(text(
        """SELECT pricing_policy_id::text AS id, sku, amount_krw, credit_amount, version
           FROM pricing_policy WHERE status = 'ACTIVE' AND sku = :s
             AND effective_from <= now() AND (effective_to IS NULL OR effective_to > now())
           ORDER BY effective_from DESC LIMIT 1"""), {"s": SKU}).first()


def customer_key(account_id: str) -> str:
    """Toss's buyer id: stable per account, not the account id itself."""
    return "np_" + hashlib.sha256(f"nextpath-customer:{account_id}".encode()).hexdigest()[:40]


def create_order(conn: Connection, account_id: str, insight_type: str, internal: bool = False,
                 provider: str = "TOSS") -> dict:
    if insight_type not in PAYABLE:
        raise PaymentFailed(422, "열 수 없는 카드예요")
    p = price(conn)
    if p is None:
        raise PaymentFailed(409, "지금은 결제할 수 없어요")
    order_id = "np-" + secrets.token_urlsafe(24)[:32]
    conn.execute(text(
        """INSERT INTO payment_order (order_id, account_id, provider, pricing_policy_id, sku,
               amount_krw, credit_amount, insight_type, internal)
           VALUES (:o, :a, :prov, CAST(:pp AS uuid), :s, :amt, :c, :i, :internal)"""),
        {"o": order_id, "a": account_id, "prov": provider, "pp": p.id, "s": p.sku,
         "amt": p.amount_krw, "c": p.credit_amount, "i": insight_type, "internal": internal})
    return {"order_id": order_id, "amount": p.amount_krw, "order_name": ORDER_NAME,
            "customer_key": customer_key(account_id), "insight_type": insight_type,
            "mode": provider}


def order(conn: Connection, account_id: str, order_id: str) -> dict:
    """What the checkout page shows for one of the member's own orders."""
    row = conn.execute(text(
        """SELECT order_id, provider, status, amount_krw, credit_amount, insight_type
           FROM payment_order WHERE order_id = :o AND account_id = CAST(:a AS uuid)"""),
        {"o": order_id, "a": account_id}).first()
    if row is None:
        raise PaymentFailed(404, "주문을 찾지 못했어요")
    return {"order_id": row.order_id, "mode": row.provider, "status": row.status,
            "amount": row.amount_krw, "credit_amount": row.credit_amount,
            "order_name": ORDER_NAME, "insight_type": row.insight_type}


def test_complete(conn: Connection, account_id: str, order_id: str, method: str) -> dict:
    """The test checkout's "결제하기" was pressed: record it (nothing is charged) and gift the 튜브
    once per order. A replay returns the same answer; the gift stops at the reward's cap."""
    row = conn.execute(text(
        """SELECT order_id, status, insight_type, ledger_id::text AS ledger_id
           FROM payment_order
           WHERE order_id = :o AND account_id = CAST(:a AS uuid) AND provider = 'TEST'
           FOR UPDATE"""), {"o": order_id, "a": account_id}).first()
    if row is None:
        raise PaymentFailed(404, "주문을 찾지 못했어요")
    if row.status == "TEST_COMPLETED":
        return {"completed": True, "order_id": order_id, "insight_type": row.insight_type,
                "gifted": row.ledger_id is not None}
    if row.status != "CREATED":
        raise PaymentFailed(409, "이미 끝난 주문이에요")
    gift = ledger.grant_reward(conn, account_id, TEST_GIFT, "PAYMENT_ORDER", order_id)
    conn.execute(text(
        """UPDATE payment_order SET status = 'TEST_COMPLETED', method = :m,
               ledger_id = CAST(:l AS uuid), updated_at = now()
           WHERE order_id = :o"""),
        {"m": method, "l": gift and gift.ledger_id, "o": order_id})
    return {"completed": True, "order_id": order_id, "insight_type": row.insight_type,
            "gifted": gift is not None}


def confirm(conn: Connection, account_id: str, order_id: str, payment_key: str, amount: int,
            provider: PaymentProvider) -> dict:
    """Confirm with Toss and credit the 튜브 once. A replay of a paid order returns it again.
    A failure is returned (not raised) so that it is recorded with the request's transaction."""
    order = conn.execute(text(
        """SELECT o.order_id, o.status, o.amount_krw, o.credit_amount, o.insight_type,
                  o.pricing_policy_id::text AS pp, p.version
           FROM payment_order o JOIN pricing_policy p USING (pricing_policy_id)
           WHERE o.order_id = :o AND o.account_id = CAST(:a AS uuid) FOR UPDATE OF o"""),
        {"o": order_id, "a": account_id}).first()
    if order is None:
        raise PaymentFailed(404, "주문을 찾지 못했어요")
    if order.status == "PAID":
        return {"paid": True, "order_id": order_id, "insight_type": order.insight_type}
    if order.status == "FAILED":
        return {"paid": False, "order_id": order_id, "message": "이미 실패한 결제예요. 다시 시도해 주세요"}
    if amount != order.amount_krw:
        _fail(conn, order_id, "AMOUNT_MISMATCH", "결제 금액이 주문과 달라요")
        return {"paid": False, "order_id": order_id, "message": "결제 금액이 주문과 달라요"}
    status, body = provider.confirm(payment_key, order_id, amount)
    if status != 200 or body.get("status") != "DONE" or body.get("totalAmount") != amount \
            or body.get("orderId") != order_id:
        code = str(body.get("code") or f"HTTP_{status}")
        message = str(body.get("message") or "결제를 확인하지 못했어요")
        log.warning("payment confirm failed: %s %s (order %s)", code, message, order_id)
        _fail(conn, order_id, code, message)
        return {"paid": False, "order_id": order_id, "message": message}
    entry = ledger.purchase(conn, account_id, order.credit_amount, order_id,
                            policy_id=order.pp, policy_version=order.version)
    conn.execute(text(
        """UPDATE payment_order SET status = 'PAID', payment_key = :k, method = :m,
               approved_at = CAST(:at AS timestamptz), receipt_url = :r, ledger_id = CAST(:l AS uuid),
               updated_at = now()
           WHERE order_id = :o"""),
        {"k": payment_key, "m": body.get("method"), "at": body.get("approvedAt"),
         "r": (body.get("receipt") or {}).get("url"), "l": entry.ledger_id, "o": order_id})
    return {"paid": True, "order_id": order_id, "insight_type": order.insight_type}


def _fail(conn: Connection, order_id: str, code: str, message: str) -> None:
    conn.execute(text(
        """UPDATE payment_order SET status = 'FAILED', failure_code = :c, failure_message = :m,
               updated_at = now() WHERE order_id = :o AND status = 'CREATED'"""),
        {"c": code[:100], "m": message[:300], "o": order_id})
