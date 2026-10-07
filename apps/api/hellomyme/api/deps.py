from datetime import date
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import Connection

from hellomyme.auth.sessions import account_for_token
from hellomyme.config import Settings, get_settings
from hellomyme.db import get_conn

Conn = Annotated[Connection, Depends(get_conn)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def as_of_today() -> date:
    return date.today()


AsOf = Annotated[date, Depends(as_of_today)]


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def optional_account(conn: Conn, authorization: Annotated[str | None, Header()] = None) -> str | None:
    token = _bearer(authorization)
    return account_for_token(conn, token) if token else None


def require_account(account_id: Annotated[str | None, Depends(optional_account)]) -> str:
    if account_id is None:
        raise HTTPException(401, "login required")
    return account_id


def anonymous_session(x_anonymous_session: Annotated[str | None, Header()] = None) -> str:
    if not x_anonymous_session or len(x_anonymous_session) < 16:
        raise HTTPException(400, "X-Anonymous-Session header (>=16 chars) is required")
    return x_anonymous_session


def idempotency_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    if not idempotency_key or not (8 <= len(idempotency_key) <= 200):
        raise HTTPException(400, "Idempotency-Key header (8-200 chars) is required")
    return idempotency_key


OptionalAccount = Annotated[str | None, Depends(optional_account)]
Account = Annotated[str, Depends(require_account)]
AnonSession = Annotated[str, Depends(anonymous_session)]
IdempotencyKey = Annotated[str, Depends(idempotency_key)]
