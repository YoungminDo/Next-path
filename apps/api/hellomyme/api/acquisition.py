"""Acquisition API: student/professional flows before login, the awaited result after login."""
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from hellomyme.api.deps import (
    Account,
    AnonSession,
    AppSettings,
    AsOf,
    Conn,
    IdempotencyKey,
    OptionalAccount,
    optional_account,
)
from hellomyme.db import get_engine
from hellomyme.domain import acquisition as acq
from hellomyme.domain import career_import, drafts, interview, ledger
from hellomyme.domain.career_input import member_person_id
from hellomyme.domain.career_query import QueryInvalid
from hellomyme.domain.policies import PolicyMissing, active_unlock_policy
from hellomyme.sms import SmsUnavailable, get_sender

router = APIRouter(prefix="/acq", tags=["acquisition"])
# Before login only the teaser is served; every distribution needs a member (login first).
AnonStep = Literal["teaser"]
MemberStep = Literal["first_roles", "next_roles", "similar_paths"]
DEEP_DIVE = "PATH_DEEP_DIVE"
SCHOOL_COMPARE = "SCHOOL_COMPARE"
COMPARE_TARGET = "OTHER_SCHOOLS"  # the entitlement key's target: one comparison per answers


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
    # The team's own browsers (?internal=1): kept, but left out of statistics.
    internal: bool = False


@router.post("/draft")
def save_draft(body: DraftRequest, conn: Conn, settings: AppSettings, anon: AnonSession):
    payload = body.payload
    # A draft may only point at a read this browser made (its rows become that source's records).
    if payload.import_attempt_id and not career_import.attempt_belongs(
            conn, payload.import_attempt_id, None, anon):
        payload = payload.model_copy(update={"import_attempt_id": None})
    payload = _run(lambda: acq.resolve_names(conn, payload.stamp_intents(datetime.now(UTC))))
    try:
        saved = drafts.save_draft(conn, anon, payload, settings.anonymous_draft_ttl_hours,
                                  body.draft_id, internal=body.internal)
    except drafts.DraftNotFound as exc:
        raise HTTPException(404, "draft not found, expired or already claimed") from exc
    drafts.purge_expired(conn.engine, settings.unclaimed_input_retention_days)
    return {**saved, "payload": payload.model_dump(mode="json"), "unlisted": acq.unlisted(payload)}


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
    return {**out, "data_basis": _basis(settings), "locked": True,
            "unlisted": acq.unlisted(payload)}


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
    # Other schools, same major: offered when their own school is listed; computed once opened.
    compare_policy = active_unlock_policy(conn, SCHOOL_COMPARE)
    compare_key = acq.insight_key(payload, COMPARE_TARGET)
    compare_open = ledger.has_entitlement(conn, account_id, SCHOOL_COMPARE, compare_key)
    compare = None
    if compare_open:
        compare = _run(lambda: acq.result(conn, payload, "other_schools", layers=layers,
                                          as_of=as_of, exclude=(person_id,)))["result"]
    return {
        "profile": payload.model_dump(mode="json", exclude={"intents"}),
        "intent": (payload.latest_intent() and
                   payload.latest_intent().model_dump(mode="json")),
        "base": base["result"], "intent_paths": paths,
        "deep_dive": {"unlocked": unlocked, "available": bool(deep) and policy is not None,
                      "cost_tube": policy and policy.cost_tube,
                      "content": deep if unlocked else None},
        "compare": {"available": bool(payload.education and payload.education.institution_id)
                                  and compare_policy is not None,
                     "unlocked": compare_open, "cost_tube": compare_policy and compare_policy.cost_tube,
                     "result": compare},
        "balance_tube": ledger.balance(conn, account_id),
        "data_basis": _basis(settings),
        "unlisted": acq.unlisted(payload),
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


@router.post("/me/unlock/compare")
def unlock_compare(conn: Conn, settings: AppSettings, account_id: Account,
                   key: IdempotencyKey, as_of: AsOf):
    """Open "다른 학교, 같은 과" with 튜브. Never charged when the other schools are too few."""
    person_id, payload = _member(conn, account_id, as_of)
    out = _run(lambda: acq.result(conn, payload, "other_schools",
                                  layers=settings.career_map_data_layers, as_of=as_of,
                                  exclude=(person_id,)))["result"]
    if out is None or out["suppressed"]:
        return {"unlocked": False, "charged": False}
    try:
        grant = ledger.unlock(conn, account_id, SCHOOL_COMPARE,
                              acq.insight_key(payload, COMPARE_TARGET),
                              {"effective_n": out["effective_n"],
                               "fallback_reason": out["fallback_reason"]}, key)
    except ledger.InsufficientCredit as exc:
        raise HTTPException(402, {"message": "튜브가 부족해요", "balance": exc.balance,
                                  "required": exc.required}) from exc
    except ledger.IdempotencyConflict as exc:
        raise HTTPException(422, "Idempotency-Key reused for a different unlock") from exc
    except ledger.PolicyUnavailable as exc:
        raise HTTPException(503, "unlock is not available right now") from exc
    return {"unlocked": True, **grant, "result": out,
            "balance_tube": ledger.balance(conn, account_id), "data_basis": _basis(settings)}


@router.get("/me/step/{step}")
def my_step(step: MemberStep, conn: Conn, settings: AppSettings, account_id: Account, as_of: AsOf):
    person_id, payload = _member(conn, account_id, as_of)
    out = _run(lambda: acq.result(conn, payload, step, layers=settings.career_map_data_layers,
                                  as_of=as_of, exclude=(person_id,)))
    return {**out, "data_basis": _basis(settings), "unlisted": acq.unlisted(payload)}


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


# --- resume / capture import (before or after login; docs/10 §이력서·캡처) -----------------

def import_extractor(settings: AppSettings) -> career_import.Extractor | None:
    return career_import.get_extractor(settings)


Extractor = Annotated[career_import.Extractor | None, Depends(import_extractor)]
MaybeAnon = Annotated[str | None, Header(alias="X-Anonymous-Session")]


def _import(fn):
    try:
        return _run(fn)
    except career_import.ImportFailed as exc:
        raise HTTPException(exc.status, {"message": exc.message}) from exc


@router.get("/import")
def import_status(conn: Conn, settings: AppSettings, account_id: OptionalAccount,
                  extractor: Extractor, anon: MaybeAnon = None):
    return career_import.status(conn, settings, account_id, anon, extractor)


class ImportFile(BaseModel):
    media_type: str = Field(max_length=40)
    data: str = Field(max_length=4_400_000)  # base64


class ParseRequest(BaseModel):
    files: list[ImportFile] = Field(min_length=1, max_length=career_import.MAX_FILES)
    consent: Literal[True]  # the overseas-transfer notice, ticked by the person
    consent_text_version: str = Field(min_length=1, max_length=64)
    # Optional and separate: keep what was read as anonymous statistics input.
    stats_consent: bool = False
    stats_consent_text_version: str | None = Field(default=None, max_length=64)
    internal: bool = False


@router.post("/import/parse")
def import_parse(body: ParseRequest, settings: AppSettings, extractor: Extractor,
                 authorization: Annotated[str | None, Header()] = None, anon: MaybeAnon = None,
                 client_ip: Annotated[str | None, Header(alias="X-Client-IP")] = None):
    """Read the person's own files into rows they check. Before login nothing is kept but the
    attempt: the rows prefill the input form and travel with the draft. No request-wide
    connection (the read takes 10-30 s): only short transactions inside."""
    engine = get_engine()
    with engine.begin() as conn:
        account_id = optional_account(conn, authorization)
    return _import(lambda: career_import.parse(
        engine, settings, account_id, anon, [f.model_dump() for f in body.files],
        body.consent_text_version, extractor, internal=body.internal, client_ip=client_ip,
        stats_consent_text_version=body.stats_consent_text_version if body.stats_consent else None))


class ImportConfirmRequest(BaseModel):
    import_attempt_id: str = Field(pattern=acq.UUID_RE.pattern)
    jobs: list[acq.AcqPastJob] = Field(min_length=1, max_length=career_import.MAX_ITEMS)


@router.post("/me/import/confirm")
def import_confirm(body: ImportConfirmRequest, conn: Conn, account_id: Account,
                   key: IdempotencyKey, as_of: AsOf):
    """A member adds the jobs they ticked (already-saved ones are skipped)."""
    person_id, _ = _member(conn, account_id, as_of)
    return _import(lambda: career_import.confirm(conn, account_id, person_id,
                                                 body.import_attempt_id, body.jobs, key))


class ApplyDraftRequest(BaseModel):
    draft_id: str = Field(min_length=1, max_length=64)


@router.post("/me/apply-draft")
def apply_draft(body: ApplyDraftRequest, conn: Conn, account_id: Account, as_of: AsOf):
    """A returning member chose "이걸로 바꾸기": their new answers (a draft already linked to this
    account at login) become their profile; the old records are withdrawn, not overwritten."""
    person_id, _ = _member(conn, account_id, as_of)
    payload = drafts.claimed_payload(conn, body.draft_id, account_id)
    if payload is None:
        raise HTTPException(404, "draft not found for this account")
    applied = _run(lambda: acq.apply_profile_changes(conn, account_id, person_id, body.draft_id,
                                                     payload, as_of))
    return {"applied": applied}


# --- user-interview opt-in (separate, optional consent; docs/10 §interview) ----------------

def _interview(fn):
    try:
        return fn()
    except interview.InterviewError as exc:
        raise HTTPException(exc.status, {"message": exc.message, **exc.extra}) from exc
    except SmsUnavailable as exc:
        raise HTTPException(503, {"message": "문자를 보내지 못했어요. 잠시 후 다시 시도해 주세요"}) from exc


@router.get("/me/interview")
def interview_status(conn: Conn, settings: AppSettings, account_id: Account):
    return interview.status(conn, settings, account_id, get_sender(settings))


class PhoneRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=20)


@router.post("/me/interview/code")
def interview_code(body: PhoneRequest, conn: Conn, settings: AppSettings, account_id: Account):
    return _interview(lambda: interview.send_code(conn, settings, account_id, body.phone,
                                                  get_sender(settings)))


class InterviewRequest(PhoneRequest):
    code: str | None = Field(default=None, max_length=10)
    consent: Literal[True]  # the separate interview consent, ticked by the member
    consent_text_version: str = Field(min_length=1, max_length=64)


@router.post("/me/interview")
def interview_apply(body: InterviewRequest, conn: Conn, settings: AppSettings, account_id: Account):
    return _interview(lambda: interview.apply(conn, settings, account_id, body.phone, body.code,
                                              body.consent_text_version, get_sender(settings)))


@router.delete("/me/interview")
def interview_withdraw(conn: Conn, settings: AppSettings, account_id: Account):
    return interview.withdraw(conn, settings, account_id, get_sender(settings))


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
