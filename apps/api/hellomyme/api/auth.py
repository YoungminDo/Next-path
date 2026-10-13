from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from hellomyme.api.deps import Account, AnonSession, AppSettings, AsOf, Conn, IdempotencyKey
from hellomyme.auth import sessions
from hellomyme.auth.providers import AuthError, AuthUnavailable, get_provider
from hellomyme.domain import drafts, signup_alert

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    provider: Literal["HMM_ID", "GOOGLE", "APPLE", "DEV"]
    token: str = Field(min_length=1, max_length=4096)


@router.post("/login")
def login(body: LoginRequest, conn: Conn, settings: AppSettings):
    try:
        identity = get_provider(body.provider, settings).verify(body.token)
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    except AuthUnavailable as exc:
        raise HTTPException(503, "login provider is temporarily unavailable") from exc
    return sessions.login(conn, identity, settings.session_ttl_hours)


@router.post("/logout", status_code=204)
def logout(conn: Conn, account_id: Account, authorization: str = Header()):
    sessions.logout(conn, authorization[7:].strip())


class MergeDraftRequest(BaseModel):
    draft_id: str
    # HMM ID identity is combined with career data here, which needs the member's own consent
    # (hmm-id docking protocol: "사용자 데이터 결합 시 사용자 별도 동의").
    consent_policy_version: str = Field(min_length=1, max_length=64)


def signup_notifier(settings: AppSettings) -> signup_alert.Notifier | None:
    return signup_alert.get_notifier(settings)


Notifier = Annotated[signup_alert.Notifier | None, Depends(signup_notifier)]


@router.post("/merge-draft")
def merge_draft(body: MergeDraftRequest, conn: Conn, settings: AppSettings, account_id: Account,
                anon: AnonSession, _key: IdempotencyKey, as_of: AsOf, background: BackgroundTasks,
                notifier: Notifier):
    # Idempotency comes from the draft itself: a claimed draft returns its first result.
    try:
        out = drafts.merge_draft(conn, account_id, body.draft_id, anon,
                                 body.consent_policy_version, as_of=as_of)
    except drafts.DraftNotFound as exc:
        raise HTTPException(404, "draft not found or expired") from exc
    except drafts.DraftConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    # A new member (their first profile, written once): tell the team, after the response.
    if out["merged"] and notifier is not None:
        message = signup_alert.safe_message(conn, body.draft_id, anon, settings.public_web_url)
        if message:
            background.add_task(notifier.post, message)
    return out
