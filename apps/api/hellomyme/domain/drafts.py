"""Anonymous draft: persist pre-login input, merge into the member's person after login so the
user never re-enters it. Merge is idempotent: replaying it returns the first result."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from pydantic import BaseModel
from sqlalchemy import Connection, text

from hellomyme.domain import ledger
from hellomyme.domain.acquisition import (
    AcquisitionPayload,
    is_acquisition_payload,
    write_acquisition_profile,
)
from hellomyme.domain.career_input import (
    CareerDraftPayload,
    member_person_id,
    normalize,
    write_member_career,
)


class DraftNotFound(Exception):
    pass


class DraftConflict(Exception):
    pass


def session_hash(anonymous_session: str) -> str:
    return hashlib.sha256(anonymous_session.encode()).hexdigest()


def save_draft(conn: Connection, anonymous_session: str,
               payload: CareerDraftPayload | AcquisitionPayload | BaseModel,
               ttl_hours: int, draft_id: str | None = None) -> dict:
    sid = session_hash(anonymous_session)
    data = payload.model_dump(mode="json")
    if draft_id:
        row = conn.execute(text(
            """UPDATE anonymous_draft SET payload_json = CAST(:p AS jsonb), user_type = :u,
                   expires_at = now() + :ttl
               WHERE draft_id = CAST(:d AS uuid) AND session_id = :s AND claimed_at IS NULL
               RETURNING draft_id::text, expires_at"""),
            {"p": json.dumps(data), "u": payload.user_type, "ttl": timedelta(hours=ttl_hours),
             "d": draft_id, "s": sid}).first()
        if row is None:
            raise DraftNotFound(draft_id)
    else:
        row = conn.execute(text(
            """INSERT INTO anonymous_draft (session_id, user_type, payload_json, expires_at)
               VALUES (:s, :u, CAST(:p AS jsonb), now() + :ttl)
               RETURNING draft_id::text, expires_at"""),
            {"s": sid, "u": payload.user_type, "p": json.dumps(data),
             "ttl": timedelta(hours=ttl_hours)}).first()
    return {"draft_id": row.draft_id, "expires_at": row.expires_at.isoformat()}


def load_draft(conn: Connection, draft_id: str, anonymous_session: str | None = None,
               for_update: bool = False):
    sql = """SELECT draft_id::text, session_id, payload_json, expires_at > now() AS live,
                    claimed_account_id::text, claimed_person_id::text
             FROM anonymous_draft WHERE draft_id = CAST(:d AS uuid)"""
    if for_update:
        sql += " FOR UPDATE"
    row = conn.execute(text(sql), {"d": draft_id}).first()
    if row is None or (anonymous_session is not None
                       and row.session_id != session_hash(anonymous_session)):
        raise DraftNotFound(draft_id)
    return row


CAREER_CONSENTS = ("PRIVACY_PROCESSING", "CAREER_DATA_AGGREGATION")


def merge_draft(conn: Connection, account_id: str, draft_id: str, anonymous_session: str,
                consent_policy_version: str) -> dict:
    row = load_draft(conn, draft_id, anonymous_session, for_update=True)
    if row.claimed_account_id:
        if row.claimed_account_id != account_id:
            raise DraftConflict("draft already claimed by another account")
        return {"person_id": row.claimed_person_id, "merged": False, "rewards": []}
    if not row.live:
        raise DraftNotFound(draft_id)
    if member_person_id(conn, account_id):
        raise DraftConflict("account already has a career profile; edit it instead")

    for consent_type in CAREER_CONSENTS:
        conn.execute(text(
            """INSERT INTO data_consent (account_id, consent_type, policy_version, status, scope)
               VALUES (:a, :t, :v, 'GRANTED', CAST(:scope AS jsonb))"""),
            {"a": account_id, "t": consent_type, "v": consent_policy_version,
             "scope": json.dumps({"granted_at_step": "merge_draft", "draft_id": draft_id})})

    if is_acquisition_payload(row.payload_json):
        written = write_acquisition_profile(
            conn, account_id, AcquisitionPayload.model_validate(row.payload_json), draft_id,
            row.payload_json)
    else:
        payload = CareerDraftPayload.model_validate(row.payload_json)
        norm = normalize(conn, payload)
        written = write_member_career(conn, account_id, norm, f"draft:{draft_id}",
                                      row.payload_json)
    conn.execute(text(
        """UPDATE anonymous_draft SET claimed_account_id = :a, claimed_person_id = :p,
               claimed_at = now() WHERE draft_id = CAST(:d AS uuid)"""),
        {"a": account_id, "p": written["person_id"], "d": draft_id})

    rewards = []
    if written["education_id"]:
        rewards.append(ledger.grant_reward(conn, account_id, "EDUCATION_ADDED", "EDUCATION",
                                           written["education_id"]))
    for weid in written["work_event_ids"]:
        action = ("CURRENT_ROLE_ADDED" if weid in written["current_work_event_ids"]
                  else "PREVIOUS_CAREER_ADDED")
        rewards.append(ledger.grant_reward(conn, account_id, action, "WORK_EVENT", weid))
    return {"person_id": written["person_id"], "merged": True,
            "rewards": [{"ledger_id": r.ledger_id, "amount": r.amount} for r in rewards if r]}
