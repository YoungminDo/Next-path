from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import Connection, text

from hellomyme.auth.providers import ProviderIdentity
from hellomyme.domain.ledger import grant_reward


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(conn: Connection, identity: ProviderIdentity, ttl_hours: int) -> dict:
    row = conn.execute(text(
        """SELECT a.account_id::text FROM account_identity i JOIN account a USING (account_id)
           WHERE i.auth_provider = :p AND i.provider_subject = :s AND a.status = 'ACTIVE'"""),
        {"p": identity.provider, "s": identity.subject}).first()
    is_new = row is None
    if is_new:
        account_id = conn.execute(text(
            "INSERT INTO account DEFAULT VALUES RETURNING account_id::text")).scalar_one()
        inserted = conn.execute(text(
            """INSERT INTO account_identity (account_id, auth_provider, provider_subject)
               VALUES (:a, :p, :s) ON CONFLICT (auth_provider, provider_subject) DO NOTHING
               RETURNING account_id::text"""),
            {"a": account_id, "p": identity.provider, "s": identity.subject}).scalar()
        if inserted is None:  # concurrent first login won the race
            conn.execute(text("DELETE FROM account WHERE account_id = :a"), {"a": account_id})
            return login(conn, identity, ttl_hours)
        grant_reward(conn, account_id, "SIGNUP", "ACCOUNT", account_id)
    else:
        account_id = row.account_id
    token = secrets.token_urlsafe(32)
    conn.execute(text(
        "INSERT INTO auth_session (account_id, token_hash, expires_at) "
        "VALUES (:a, :h, now() + :ttl)"),
        {"a": account_id, "h": token_hash(token), "ttl": timedelta(hours=ttl_hours)})
    return {"account_id": account_id, "session_token": token, "is_new_account": is_new}


def account_for_token(conn: Connection, token: str) -> str | None:
    return conn.execute(text(
        """SELECT s.account_id::text FROM auth_session s JOIN account a USING (account_id)
           WHERE s.token_hash = :h AND s.revoked_at IS NULL AND s.expires_at > now()
             AND a.status = 'ACTIVE'"""), {"h": token_hash(token)}).scalar()


def logout(conn: Connection, token: str) -> None:
    conn.execute(text("UPDATE auth_session SET revoked_at = now() WHERE token_hash = :h"),
                 {"h": token_hash(token)})
