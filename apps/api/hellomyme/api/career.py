from dataclasses import replace
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from hellomyme.api.deps import Account, AnonSession, AppSettings, AsOf, Conn, IdempotencyKey
from hellomyme.domain import career_map, drafts, ledger
from hellomyme.domain.career_input import (
    CareerDraftPayload,
    CareerEventInput,
    member_person_id,
    member_profile,
    normalize,
    profile_from_normalized,
    reconfirm_work_event,
    write_member_career,
)
from hellomyme.domain.cohort import Population, log_result
from hellomyme.domain.policies import (
    active_cohort_policy,
    active_scoring_policy,
    active_unlock_policy,
)
from hellomyme.domain.similarity import Profile, bucket

router = APIRouter(tags=["career"])


def _resolve(conn, settings, query: Profile):
    cp = active_cohort_policy(conn)
    sp = active_scoring_policy(conn, "CAREER_SIMILARITY")
    layers = settings.career_map_data_layers
    population = Population.load(conn, layers)
    resolved = career_map.resolve(conn, query, population, cp, sp, layers)
    return cp, sp, layers, resolved


def _similarity_label(resolved, sp) -> str | None:
    if resolved.cohort.fallback_level != 3 or not resolved.cohort.similarity:
        return None
    scores = sorted(resolved.cohort.similarity.values())
    return bucket(scores[len(scores) // 2], sp)


# --- anonymous draft ------------------------------------------------------------------------

class DraftRequest(BaseModel):
    draft_id: str | None = None
    payload: CareerDraftPayload


@router.post("/career/draft")
def save_draft(body: DraftRequest, conn: Conn, settings: AppSettings, anon: AnonSession):
    try:
        return drafts.save_draft(conn, anon, body.payload, settings.anonymous_draft_ttl_hours,
                                 body.draft_id)
    except drafts.DraftNotFound as exc:
        raise HTTPException(404, "draft not found, expired or already claimed") from exc


class DraftQueryRequest(BaseModel):
    draft_id: str


@router.post("/career/draft/query")
def query_draft(body: DraftQueryRequest, conn: Conn, settings: AppSettings, anon: AnonSession,
                as_of: AsOf):
    try:
        row = drafts.load_draft(conn, body.draft_id, anon)
    except drafts.DraftNotFound as exc:
        raise HTTPException(404, "draft not found") from exc
    payload = CareerDraftPayload.model_validate(row.payload_json)
    query = profile_from_normalized(normalize(conn, payload), as_of)
    cp, _, layers, resolved = _resolve(conn, settings, query)
    log_result(conn, resolved.cohort, cp, query, layers, draft_id=body.draft_id)
    return career_map.teaser(resolved, cp, settings.is_simulation)


# --- member career --------------------------------------------------------------------------

def _member_query(conn, account_id: str, as_of) -> Profile:
    person_id = member_person_id(conn, account_id)
    if person_id is None:
        raise HTTPException(404, "no career profile yet; save a draft and merge it first")
    return member_profile(conn, person_id, as_of)


class MapQuery(BaseModel):
    """Optional overrides to explore 'what if' cohorts from the member's own profile."""
    institution_id: str | None = None
    major_id: str | None = None
    graduation_year: int | None = None
    current_job_family: str | None = None


@router.get("/career/map")
def get_map(conn: Conn, settings: AppSettings, account_id: Account, as_of: AsOf):
    return _map(conn, settings, account_id, _member_query(conn, account_id, as_of))


@router.post("/career/map/query")
def query_map(body: MapQuery, conn: Conn, settings: AppSettings, account_id: Account,
              as_of: AsOf):
    base = _member_query(conn, account_id, as_of)
    overrides = body.model_dump(exclude_none=True)
    if "major_id" in overrides:
        family = conn.execute(text("SELECT major_family FROM major WHERE major_id::text = :m"),
                              {"m": overrides["major_id"]}).scalar()
        overrides["major_family"] = family
    query = replace(base, **overrides)
    conn.execute(text(
        "INSERT INTO analytics.filter_event (account_id, filters) VALUES (:a, CAST(:f AS jsonb))"),
        {"a": account_id, "f": body.model_dump_json(exclude_none=True)})
    return _map(conn, settings, account_id, query)


def _map(conn, settings, account_id, query: Profile) -> dict:
    cp, sp, layers, resolved = _resolve(conn, settings, query)
    log_result(conn, resolved.cohort, cp, query, layers, account_id=account_id)
    out = career_map.base_map(resolved, cp, settings.is_simulation)
    out["similarity_label"] = _similarity_label(resolved, sp)
    out["unlocks"] = []
    for t in career_map.INSIGHT_TYPES:
        policy = active_unlock_policy(conn, t)
        ikey = career_map.insight_key(t, query, None)
        out["unlocks"].append({
            "insight_type": t, "insight_key": ikey,
            "available": policy is not None, "cost_tube": policy and policy.cost_tube,
            "unlocked": ledger.has_entitlement(conn, account_id, t, ikey)})
    return out


class UnlockRequest(BaseModel):
    insight_type: Literal["PATH_DEEP_DIVE", "COMPANY_BREAKDOWN", "REPRESENTATIVE_PATHS",
                          "TIMING_TENURE"]
    target_job_family: str | None = None


@router.post("/career/unlock")
def unlock(body: UnlockRequest, conn: Conn, settings: AppSettings, account_id: Account,
           key: IdempotencyKey, as_of: AsOf):
    query = _member_query(conn, account_id, as_of)
    cp, _, layers, resolved = _resolve(conn, settings, query)
    insight = career_map.unlocked_insight(conn, body.insight_type, resolved, cp,
                                          body.target_job_family)
    if insight.get("suppressed"):
        # Never charge for an insight the sample cannot support.
        return {"unlocked": False, "charged": False, "insight": insight}
    ikey = career_map.insight_key(body.insight_type, query, body.target_job_family)
    try:
        grant = ledger.unlock(conn, account_id, body.insight_type, ikey,
                              {"target_job_family": body.target_job_family,
                               "cohort": resolved.cohort.audit()}, key)
    except ledger.InsufficientCredit as exc:
        raise HTTPException(402, {"message": "not enough 튜브", "balance": exc.balance,
                                  "required": exc.required}) from exc
    except ledger.IdempotencyConflict as exc:
        raise HTTPException(422, "Idempotency-Key reused for a different unlock") from exc
    except ledger.PolicyUnavailable as exc:
        raise HTTPException(503, "unlock is not available right now") from exc
    log_result(conn, resolved.cohort, cp, query, layers, account_id=account_id)
    return {"unlocked": True, **grant, "insight": insight,
            "data_basis": "SIMULATION" if settings.is_simulation else "OBSERVED"}


class AddEventsRequest(BaseModel):
    career_events: list[CareerEventInput]


@router.post("/career/events")
def add_events(body: AddEventsRequest, conn: Conn, account_id: Account, key: IdempotencyKey):
    if member_person_id(conn, account_id) is None:
        raise HTTPException(404, "no career profile yet")
    stage = conn.execute(text("SELECT declared_stage FROM person WHERE account_id = :a"),
                         {"a": account_id}).scalar() or "PROFESSIONAL"
    payload = CareerDraftPayload(user_type=stage, career_events=body.career_events)
    norm = normalize(conn, payload)
    source_key = f"member:{account_id}:{key}"
    exists = conn.execute(text(
        "SELECT 1 FROM source_record WHERE source_system = 'HELLOMYME_APP' AND source_key = :k"),
        {"k": source_key}).first()
    if exists:
        return {"replayed": True}
    written = write_member_career(conn, account_id, norm, source_key, payload.model_dump(mode="json"))
    rewards = []
    for weid in written["work_event_ids"]:
        action = ("CURRENT_ROLE_ADDED" if weid in written["current_work_event_ids"]
                  else "PREVIOUS_CAREER_ADDED")
        if r := ledger.grant_reward(conn, account_id, action, "WORK_EVENT", weid):
            rewards.append({"ledger_id": r.ledger_id, "amount": r.amount})
    return {"work_event_ids": written["work_event_ids"], "rewards": rewards}


@router.post("/career/events/{work_event_id}/reconfirm")
def reconfirm(work_event_id: str, conn: Conn, account_id: Account):
    result = reconfirm_work_event(conn, account_id, work_event_id)
    if result is None:
        raise HTTPException(404, "event not found")
    reward = ledger.grant_reward(conn, account_id, "CAREER_RECONFIRMED", "VERIFICATION",
                                 result["verification_id"])
    return {**result, "reward": reward and {"ledger_id": reward.ledger_id, "amount": reward.amount}}


# --- taxonomy -------------------------------------------------------------------------------

TAXONOMY = {
    "institutions": "SELECT institution_id::text AS id, name, region FROM institution "
                    "WHERE is_active ORDER BY name",
    "majors": "SELECT major_id::text AS id, name, major_family FROM major WHERE is_active "
              "ORDER BY name",
    "roles": "SELECT role_id::text AS id, name, job_family FROM role WHERE is_active ORDER BY name",
    "organizations": "SELECT organization_id::text AS id, name, industry, company_size_band "
                     "FROM organization WHERE is_active AND NOT is_placeholder ORDER BY name",
}


@router.get("/taxonomy/{kind}")
def taxonomy(kind: Literal["institutions", "majors", "roles", "organizations"], conn: Conn):
    return [dict(r._mapping) for r in conn.execute(text(TAXONOMY[kind]))]
