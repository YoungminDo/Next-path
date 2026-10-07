from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from hellomyme.api.deps import Account, AnonSession, AppSettings, Conn, IdempotencyKey
from hellomyme.auth import sessions
from hellomyme.auth.providers import AuthError, get_provider
from hellomyme.domain import drafts

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    provider: Literal["KAKAO", "GOOGLE", "APPLE", "DEV"]
    token: str


@router.post("/login")
def login(body: LoginRequest, conn: Conn, settings: AppSettings):
    try:
        identity = get_provider(body.provider, settings).verify(body.token)
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    return sessions.login(conn, identity, settings.session_ttl_hours)


@router.post("/logout", status_code=204)
def logout(conn: Conn, account_id: Account, authorization: str = Header()):
    sessions.logout(conn, authorization[7:].strip())


class MergeDraftRequest(BaseModel):
    draft_id: str


@router.post("/merge-draft")
def merge_draft(body: MergeDraftRequest, conn: Conn, account_id: Account,
                anon: AnonSession, _key: IdempotencyKey):
    # Idempotency comes from the draft itself: a claimed draft returns its first result.
    try:
        return drafts.merge_draft(conn, account_id, body.draft_id, anon)
    except drafts.DraftNotFound as exc:
        raise HTTPException(404, "draft not found or expired") from exc
    except drafts.DraftConflict as exc:
        raise HTTPException(409, str(exc)) from exc
