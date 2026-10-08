"""Acquisition API: student/professional flows before login, the awaited result after login."""
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from hellomyme.api.deps import Account, AnonSession, AppSettings, AsOf, Conn, IdempotencyKey
from hellomyme.domain import acquisition as acq
from hellomyme.domain import drafts, ledger
from hellomyme.domain.career_input import member_person_id
from hellomyme.domain.career_query import QueryInvalid
from hellomyme.domain.policies import PolicyMissing, active_unlock_policy

router = APIRouter(prefix="/acq", tags=["acquisition"])
# Before login only the teaser is served; every distribution needs a member (login first).
AnonStep = Literal["teaser"]
MemberStep = Literal["first_roles", "next_roles", "similar_paths"]
DEEP_DIVE = "PATH_DEEP_DIVE"


def _basis(settings) -> str:
    return "SIMULATION" if settings.is_simulation else "OBSERVED"


def _run(fn):
    try:
        return fn()
    except QueryInvalid as exc:
        raise HTTPException(422, str(exc)) from exc
    except PolicyMissing as exc:
        raise HTTPException(503, f"not configured: {exc}") from exc


# --- options --------------------------------------------------------------------------------
# Same for every visitor and changed only by an import: let the CDN keep them.
OPTIONS_CACHE = "public, max-age=300, s-maxage=600, stale-while-revalidate=86400"

@router.get("/options/institutions")
def institutions(conn: Conn, response: Response):
    response.headers["Cache-Control"] = OPTIONS_CACHE
    return acq.institutions(conn)


@router.get("/options/majors")
def majors(conn: Conn, response: Response, q: str | None = None, depth: int | None = None):
    response.headers["Cache-Control"] = OPTIONS_CACHE
    return acq.taxonomy_options(conn, "MAJOR", q, depth)


@router.get("/options/roles")
def roles(conn: Conn, response: Response, q: str | None = None, depth: int | None = None):
    response.headers["Cache-Control"] = OPTIONS_CACHE
    return acq.taxonomy_options(conn, "ROLE", q, depth)


@router.get("/options/organizations")
def organizations(conn: Conn, response: Response, q: str | None = None):
    response.headers["Cache-Control"] = OPTIONS_CACHE
    return acq.organizations(conn, q)


# --- anonymous flow -------------------------------------------------------------------------

class DraftRequest(BaseModel):
    draft_id: str | None = None
    payload: acq.AcquisitionPayload


@router.post("/draft")
def save_draft(body: DraftRequest, conn: Conn, settings: AppSettings, anon: AnonSession):
    payload = body.payload.stamp_intents(datetime.now(UTC))
    try:
        saved = drafts.save_draft(conn, anon, payload, settings.anonymous_draft_ttl_hours,
                                  body.draft_id)
    except drafts.DraftNotFound as exc:
        raise HTTPException(404, "draft not found, expired or already claimed") from exc
    return {**saved, "payload": payload.model_dump(mode="json")}


class ResultRequest(BaseModel):
    step: AnonStep = "teaser"


@router.post("/draft/{draft_id}/result")
def draft_result(draft_id: str, body: ResultRequest, conn: Conn, settings: AppSettings,
                 anon: AnonSession, as_of: AsOf):
    try:
        row = drafts.load_draft(conn, draft_id, anon)
    except drafts.DraftNotFound as exc:
        raise HTTPException(404, "draft not found") from exc
    if not acq.is_acquisition_payload(row.payload_json):
        raise HTTPException(422, "not an acquisition draft")
    payload = acq.AcquisitionPayload.model_validate(row.payload_json)
    out = _run(lambda: acq.result(conn, payload, body.step,
                                  layers=settings.career_map_data_layers, as_of=as_of))
    return {**out, "data_basis": _basis(settings), "locked": True}


# --- after login ----------------------------------------------------------------------------

def _member(conn, account_id: str, as_of):
    person_id = member_person_id(conn, account_id)
    payload = person_id and acq.member_payload(conn, person_id, as_of)
    if not payload:
        raise HTTPException(404, "no career profile yet")
    return person_id, payload


@router.get("/me")
def my_result(conn: Conn, settings: AppSettings, account_id: Account, as_of: AsOf):
    """The result the member was waiting for at the login wall, from their own records."""
    person_id, payload = _member(conn, account_id, as_of)
    layers = settings.career_map_data_layers
    base_step = "next_roles" if payload.is_professional else "first_roles"
    base = _run(lambda: acq.result(conn, payload, base_step, layers=layers, as_of=as_of,
                                   exclude=(person_id,)))
    paths = _run(lambda: acq.result(conn, payload, "intent_paths", layers=layers, as_of=as_of,
                                    exclude=(person_id,), full=True))
    target = (paths.get("paths") or {}).get("target", {}).get("node_id")
    key = acq.insight_key(payload, target)
    unlocked = ledger.has_entitlement(conn, account_id, DEEP_DIVE, key)
    deep = (paths.get("paths") or {}).pop("deep_dive", None)
    policy = active_unlock_policy(conn, DEEP_DIVE)
    return {
        "profile": payload.model_dump(mode="json", exclude={"intents"}),
        "intent": (payload.latest_intent() and
                   payload.latest_intent().model_dump(mode="json")),
        "base": base["result"], "intent_paths": paths,
        "deep_dive": {"unlocked": unlocked, "available": bool(deep) and policy is not None,
                      "cost_tube": policy and policy.cost_tube,
                      "content": deep if unlocked else None},
        "balance_tube": ledger.balance(conn, account_id),
        "data_basis": _basis(settings),
    }


@router.post("/me/unlock")
def unlock_deep_dive(conn: Conn, settings: AppSettings, account_id: Account,
                     key: IdempotencyKey, as_of: AsOf):
    person_id, payload = _member(conn, account_id, as_of)
    paths = _run(lambda: acq.result(conn, payload, "intent_paths",
                                    layers=settings.career_map_data_layers, as_of=as_of,
                                    exclude=(person_id,), full=True))
    p = paths.get("paths")
    if not p or p["suppressed"] or not p.get("deep_dive"):
        # Never charge for an insight the sample cannot support.
        return {"unlocked": False, "charged": False}
    ikey = acq.insight_key(payload, p["target"]["node_id"])
    try:
        grant = ledger.unlock(conn, account_id, DEEP_DIVE, ikey,
                              {"target": p["target"], "cohort": paths["base"]}, key)
    except ledger.InsufficientCredit as exc:
        raise HTTPException(402, {"message": "튜브가 부족해요", "balance": exc.balance,
                                  "required": exc.required}) from exc
    except ledger.IdempotencyConflict as exc:
        raise HTTPException(422, "Idempotency-Key reused for a different unlock") from exc
    except ledger.PolicyUnavailable as exc:
        raise HTTPException(503, "unlock is not available right now") from exc
    return {"unlocked": True, **grant, "content": p["deep_dive"],
            "balance_tube": ledger.balance(conn, account_id), "data_basis": _basis(settings)}


@router.get("/me/step/{step}")
def my_step(step: MemberStep, conn: Conn, settings: AppSettings, account_id: Account, as_of: AsOf):
    person_id, payload = _member(conn, account_id, as_of)
    out = _run(lambda: acq.result(conn, payload, step, layers=settings.career_map_data_layers,
                                  as_of=as_of, exclude=(person_id,)))
    return {**out, "data_basis": _basis(settings)}


class JobRequest(BaseModel):
    job: acq.AcqJob


@router.post("/me/jobs")
def add_job(body: JobRequest, conn: Conn, account_id: Account, key: IdempotencyKey, as_of: AsOf):
    """Professional flow P3: the first job, added after login (no re-entry of anything else)."""
    person_id, _ = _member(conn, account_id, as_of)
    written = _run(lambda: acq.add_member_job(conn, account_id, person_id, body.job, key))
    reward = None
    if written["work_event_id"]:
        r = ledger.grant_reward(conn, account_id, "PREVIOUS_CAREER_ADDED", "WORK_EVENT",
                                written["work_event_id"])
        reward = r and {"ledger_id": r.ledger_id, "amount": r.amount}
    return {**written, "reward": reward}


class IntentRequest(BaseModel):
    intent: acq.AcqIntent


@router.post("/me/intent")
def change_intent(body: IntentRequest, conn: Conn, account_id: Account, as_of: AsOf):
    """A member changes what they want to see next: a new, time-stamped intent (history kept)."""
    person_id, payload = _member(conn, account_id, as_of)
    intent = body.intent.model_copy(update={"captured_at": datetime.now(UTC)})
    ids = acq.record_intents(conn, person_id, payload.model_copy(update={"intents": [intent]}),
                             None)
    return {"intent_event_ids": ids}
