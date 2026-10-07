import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from hellomyme.api.deps import Account, AsOf, Conn, IdempotencyKey, OptionalAccount
from hellomyme.domain import ledger, mentors
from hellomyme.domain.career_input import member_person_id, member_profile
from hellomyme.domain.policies import active_scoring_policy
from hellomyme.domain.similarity import Profile

router = APIRouter(tags=["credit", "mentor", "order"])


# --- credits --------------------------------------------------------------------------------

@router.get("/credits")
def credits(conn: Conn, account_id: Account):
    return {"account_id": account_id, "balance_tube": ledger.balance(conn, account_id)}


@router.get("/credits/ledger")
def credit_ledger(conn: Conn, account_id: Account, limit: int = Query(50, le=200)):
    rows = conn.execute(text(
        """SELECT ledger_id::text, amount, direction, reason_type, reference_type, reference_id,
                  policy_version, reverses_ledger_id::text, created_at
           FROM credit_ledger WHERE account_id = :a ORDER BY created_at DESC LIMIT :n"""),
        {"a": account_id, "n": limit})
    return [dict(r._mapping) for r in rows]


# --- mentors --------------------------------------------------------------------------------

class MentorProfileRequest(BaseModel):
    headline: str = Field(max_length=120)
    bio: str | None = Field(default=None, max_length=2000)
    visibility: Literal["PUBLIC", "MATCH_ONLY"] = "MATCH_ONLY"
    consent_policy_version: str


@router.post("/mentors/profile")
def opt_in(body: MentorProfileRequest, conn: Conn, account_id: Account):
    person_id = member_person_id(conn, account_id)
    if person_id is None:
        raise HTTPException(404, "add your career before becoming a mentor")
    conn.execute(text(
        """INSERT INTO data_consent (account_id, consent_type, policy_version, status)
           VALUES (:a, 'MENTOR_PUBLIC_PROFILE', :v, 'GRANTED')"""),
        {"a": account_id, "v": body.consent_policy_version})
    mid = conn.execute(text(
        """INSERT INTO mentor_profile (person_id, account_id, headline, bio, visibility)
           VALUES (:p, :a, :h, :b, :vis)
           ON CONFLICT (person_id) DO UPDATE SET headline = EXCLUDED.headline,
               bio = EXCLUDED.bio, visibility = EXCLUDED.visibility, status = 'ACTIVE'
           RETURNING mentor_profile_id::text"""),
        {"p": person_id, "a": account_id, "h": body.headline, "b": body.bio,
         "vis": body.visibility}).scalar_one()
    return {"mentor_profile_id": mid}


class OfferRequest(BaseModel):
    offer_type: Literal["QNA", "15_MIN_CHAT"]  # MVP: Q&A and short sessions only
    title: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    duration_minutes: int | None = Field(default=None, gt=0, le=60)
    price_tube: int = Field(default=0, ge=0)


@router.post("/mentors/offers")
def create_offer(body: OfferRequest, conn: Conn, account_id: Account):
    mid = conn.execute(text(
        "SELECT mentor_profile_id::text FROM mentor_profile WHERE account_id = :a "
        "AND status = 'ACTIVE'"), {"a": account_id}).scalar()
    if mid is None:
        raise HTTPException(404, "opt in as a mentor first")
    oid = conn.execute(text(
        """INSERT INTO mentor_offer (mentor_profile_id, offer_type, title, description,
               duration_minutes, price_tube)
           VALUES (:m, :t, :ti, :d, :dur, :p) RETURNING offer_id::text"""),
        {"m": mid, "t": body.offer_type, "ti": body.title, "d": body.description,
         "dur": body.duration_minutes, "p": body.price_tube}).scalar_one()
    return {"offer_id": oid}


@router.get("/mentors/matches")
def mentor_matches(conn: Conn, account_id: OptionalAccount, as_of: AsOf,
                   target_job_family: str = Query(min_length=1)):
    person_id = member_person_id(conn, account_id) if account_id else None
    requester = member_profile(conn, person_id, as_of) if person_id else Profile()
    return mentors.match(conn, requester, target_job_family,
                         active_scoring_policy(conn, "MENTOR_RANKING"),
                         active_scoring_policy(conn, "CAREER_SIMILARITY"), as_of)


@router.get("/mentors/{mentor_profile_id}")
def mentor_detail(mentor_profile_id: str, conn: Conn):
    row = conn.execute(text(
        """SELECT m.mentor_profile_id::text, m.headline, m.bio, m.is_accepting, m.rating_avg,
                  m.rating_count, m.completed_count
           FROM mentor_profile m JOIN person p USING (person_id)
           WHERE m.mentor_profile_id::text = :m AND m.status = 'ACTIVE'
             AND p.origin_layer = 'VERIFIED'"""), {"m": mentor_profile_id}).first()
    if row is None:
        raise HTTPException(404, "mentor not found")
    offers = conn.execute(text(
        """SELECT offer_id::text, offer_type, title, description, duration_minutes, price_tube
           FROM mentor_offer WHERE mentor_profile_id = :m AND status = 'ACTIVE'"""),
        {"m": mentor_profile_id})
    return {**row._mapping, "offers": [dict(o._mapping) for o in offers]}


# --- orders ---------------------------------------------------------------------------------

class OrderRequest(BaseModel):
    offer_id: str
    question_text: str = Field(min_length=1, max_length=4000)


@router.post("/orders")
def create_order(body: OrderRequest, conn: Conn, account_id: Account, key: IdempotencyKey):
    okey = f"order:{account_id}:{key}"
    existing = conn.execute(text(
        "SELECT order_id::text, status, offer_id::text FROM orders WHERE idempotency_key = :k"),
        {"k": okey}).first()
    if existing:
        if existing.offer_id != body.offer_id:
            raise HTTPException(422, "Idempotency-Key reused for a different order")
        return {"order_id": existing.order_id, "status": existing.status, "replayed": True}
    offer = conn.execute(text(
        """SELECT o.offer_id::text, o.price_tube, o.price_krw, m.account_id::text AS mentor_account
           FROM mentor_offer o JOIN mentor_profile m USING (mentor_profile_id)
           WHERE o.offer_id::text = :o AND o.status = 'ACTIVE' AND m.status = 'ACTIVE'
             AND m.is_accepting"""), {"o": body.offer_id}).first()
    if offer is None:
        raise HTTPException(404, "offer not available")
    if offer.mentor_account == account_id:
        raise HTTPException(422, "cannot order your own offer")
    if offer.price_krw:
        raise HTTPException(422, "paid (KRW) offers are not available in Phase 1")
    price = offer.price_tube or 0
    status = "PAID" if price > 0 else "CREATED"
    order_id = conn.execute(text(
        """INSERT INTO orders (buyer_account_id, offer_id, status, question_text, price_tube,
               idempotency_key)
           VALUES (:a, :o, :s, :q, :p, :k) RETURNING order_id::text"""),
        {"a": account_id, "o": body.offer_id, "s": status, "q": body.question_text, "p": price,
         "k": okey}).scalar_one()
    if price > 0:
        try:
            entry = ledger.spend(conn, account_id, price, reason_type="ORDER",
                                 reference_type="ORDER", reference_id=order_id,
                                 key=f"order-charge:{order_id}")
        except ledger.InsufficientCredit as exc:
            raise HTTPException(402, {"message": "not enough 튜브", "balance": exc.balance,
                                      "required": exc.required}) from exc
        conn.execute(text(
            """INSERT INTO transaction (order_id, kind, method, amount_tube, ledger_id, status)
               VALUES (:o, 'CHARGE', 'TUBE_CREDIT', :p, :l, 'SUCCEEDED')"""),
            {"o": order_id, "p": price, "l": entry.ledger_id})
    return {"order_id": order_id, "status": status, "price_tube": price}


# --- analytics ------------------------------------------------------------------------------

EventName = Literal[
    "career_input_started", "career_input_completed", "career_query_requested",
    "login_wall_viewed", "signup_completed", "career_map_viewed", "filter_applied",
    "unlock_viewed", "unlock_purchased", "credit_purchased", "mentor_viewed",
    "mentor_contact_clicked", "mentor_order_created", "career_updated", "career_reconfirmed",
]


class AnalyticsEvent(BaseModel):
    event_name: EventName
    occurred_at: datetime
    anonymous_session_id: str | None = Field(default=None, max_length=200)
    properties: dict = Field(default_factory=dict)


@router.post("/analytics/events", status_code=202)
def track(body: AnalyticsEvent, conn: Conn, account_id: OptionalAccount):
    conn.execute(text(
        """INSERT INTO analytics.event (event_name, account_id, anonymous_session_id, properties,
               occurred_at)
           VALUES (:n, :a, :s, CAST(:p AS jsonb), :t)"""),
        {"n": body.event_name, "a": account_id, "s": body.anonymous_session_id,
         "p": json.dumps(body.properties, default=str),
         "t": body.occurred_at})
    return {"accepted": True}
