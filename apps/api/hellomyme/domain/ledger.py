"""MY credit ledger. credit_ledger is append-only; balance = SUM(entries).

Concurrency: every balance-dependent write locks the account row first, so two concurrent
unlocks cannot both spend the same MY.
Idempotency: every entry carries a unique idempotency_key; replaying a request returns the
entry that already exists instead of writing a second one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Connection, text

from hellomyme.domain.policies import active_reward_policy, active_unlock_policy


class InsufficientCredit(Exception):
    def __init__(self, balance: int, required: int):
        super().__init__(f"balance {balance} < required {required}")
        self.balance, self.required = balance, required


class PolicyUnavailable(Exception):
    pass


class IdempotencyConflict(Exception):
    """The same Idempotency-Key was reused for a different request."""


@dataclass
class LedgerEntry:
    ledger_id: str
    amount: int
    direction: str
    created: bool


def lock_account(conn: Connection, account_id: str) -> None:
    conn.execute(text("SELECT 1 FROM account WHERE account_id = :a FOR UPDATE"), {"a": account_id})


def balance(conn: Connection, account_id: str) -> int:
    return int(conn.execute(text(
        "SELECT COALESCE(balance, 0) FROM credit_balance WHERE account_id = :a"),
        {"a": account_id}).scalar() or 0)


def _existing(conn: Connection, key: str) -> LedgerEntry | None:
    row = conn.execute(text(
        "SELECT ledger_id::text, amount, direction FROM credit_ledger WHERE idempotency_key = :k"),
        {"k": key}).first()
    return LedgerEntry(row.ledger_id, row.amount, row.direction, False) if row else None


def _insert(conn: Connection, *, account_id, amount, direction, reason_type, reference_type,
            reference_id, key, policy_type=None, policy_id=None, policy_version=None,
            reverses=None) -> LedgerEntry:
    ledger_id = conn.execute(text(
        """INSERT INTO credit_ledger (account_id, amount, direction, reason_type, reference_type,
               reference_id, idempotency_key, policy_type, policy_id, policy_version,
               reverses_ledger_id)
           VALUES (:a, :amt, :dir, :reason, :rt, :rid, :key, :pt, :pid, :pv, :rev)
           ON CONFLICT (idempotency_key) DO NOTHING
           RETURNING ledger_id::text"""),
        {"a": account_id, "amt": amount, "dir": direction, "reason": reason_type,
         "rt": reference_type, "rid": str(reference_id), "key": key, "pt": policy_type,
         "pid": policy_id, "pv": policy_version, "rev": reverses}).scalar()
    if ledger_id is None:  # lost a race on the same key
        return _existing(conn, key)
    return LedgerEntry(ledger_id, amount, direction, True)


def grant_reward(conn: Connection, account_id: str, action_type: str, reference_type: str,
                 reference_id: str) -> LedgerEntry | None:
    """Reward a data contribution. The key deliberately excludes the policy version, so a
    policy change never pays the same contribution twice; the version is stored on the row."""
    key = f"reward:{account_id}:{action_type}:{reference_type}:{reference_id}"
    lock_account(conn, account_id)
    if existing := _existing(conn, key):
        return existing
    policy = active_reward_policy(conn, action_type)
    if policy is None:
        return None
    prior = conn.execute(text(
        """SELECT count(*) AS n, max(l.created_at) AS last_at
           FROM credit_ledger l JOIN reward_policy p ON p.reward_policy_id = l.policy_id
           WHERE l.account_id = :a AND l.reason_type = 'REWARD' AND p.action_type = :act
             AND NOT EXISTS (SELECT 1 FROM credit_ledger r WHERE r.reverses_ledger_id = l.ledger_id)
        """), {"a": account_id, "act": action_type}).first()
    if policy.max_occurrences is not None and prior.n >= policy.max_occurrences:
        return None
    if policy.cooldown_seconds and prior.last_at is not None:
        within = conn.execute(text("SELECT now() - :t < :cd"),
                              {"t": prior.last_at,
                               "cd": timedelta(seconds=policy.cooldown_seconds)}).scalar()
        if within:
            return None
    return _insert(conn, account_id=account_id, amount=policy.reward_my, direction="CREDIT",
                   reason_type="REWARD", reference_type=reference_type, reference_id=reference_id,
                   key=key, policy_type="REWARD_POLICY", policy_id=policy.reward_policy_id,
                   policy_version=policy.version)


def spend(conn: Connection, account_id: str, amount: int, *, reason_type: str,
          reference_type: str, reference_id: str, key: str, policy_type=None, policy_id=None,
          policy_version=None) -> LedgerEntry:
    lock_account(conn, account_id)
    if existing := _existing(conn, key):
        return existing
    current = balance(conn, account_id)
    if current < amount:
        raise InsufficientCredit(current, amount)
    return _insert(conn, account_id=account_id, amount=amount, direction="DEBIT",
                   reason_type=reason_type, reference_type=reference_type,
                   reference_id=reference_id, key=key, policy_type=policy_type,
                   policy_id=policy_id, policy_version=policy_version)


def reverse(conn: Connection, ledger_id: str, *, reason: str) -> LedgerEntry:
    """Correction = opposite entry linked to the original. The original row is untouched."""
    row = conn.execute(text(
        """SELECT account_id::text, amount, direction, reference_type, reference_id
           FROM credit_ledger WHERE ledger_id = :id"""), {"id": ledger_id}).first()
    if row is None:
        raise KeyError(ledger_id)
    lock_account(conn, row.account_id)
    return _insert(conn, account_id=row.account_id, amount=row.amount,
                   direction="CREDIT" if row.direction == "DEBIT" else "DEBIT",
                   reason_type="REVERSAL", reference_type=row.reference_type,
                   reference_id=row.reference_id, key=f"reversal:{ledger_id}",
                   policy_type="CORRECTION", policy_version=reason, reverses=ledger_id)


def unlock(conn: Connection, account_id: str, insight_type: str, insight_key: str,
           params: dict, idempotency_key: str) -> dict:
    """Spend MY for an insight and grant the entitlement. Already-entitled => no charge."""
    lock_account(conn, account_id)
    key = f"unlock:{account_id}:{idempotency_key}"
    prior = conn.execute(text(
        "SELECT insight_type, insight_key FROM unlock_event WHERE idempotency_key = :k"),
        {"k": key}).first()
    if prior and (prior.insight_type, prior.insight_key) != (insight_type, insight_key):
        raise IdempotencyConflict(idempotency_key)
    ent = conn.execute(text(
        """SELECT entitlement_id::text, unlock_id::text FROM entitlement
           WHERE account_id = :a AND insight_type = :t AND insight_key = :k
             AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())"""),
        {"a": account_id, "t": insight_type, "k": insight_key}).first()
    if ent:
        return {"entitlement_id": ent.entitlement_id, "unlock_id": ent.unlock_id,
                "charged": False}
    policy = active_unlock_policy(conn, insight_type)
    if policy is None:
        raise PolicyUnavailable(insight_type)
    entry = spend(conn, account_id, policy.cost_my, reason_type="UNLOCK",
                  reference_type="INSIGHT", reference_id=f"{insight_type}:{insight_key}", key=key,
                  policy_type="UNLOCK_POLICY", policy_id=policy.unlock_policy_id,
                  policy_version=policy.version)
    unlock_id = conn.execute(text(
        """INSERT INTO unlock_event (account_id, unlock_policy_id, insight_type, insight_key,
               insight_params, cost_my, ledger_id, idempotency_key)
           VALUES (:a, :p, :t, :k, CAST(:params AS jsonb), :c, :l, :key)
           ON CONFLICT (idempotency_key) DO NOTHING RETURNING unlock_id::text"""),
        {"a": account_id, "p": policy.unlock_policy_id, "t": insight_type, "k": insight_key,
         "params": json.dumps(params), "c": policy.cost_my, "l": entry.ledger_id,
         "key": key}).scalar()
    if unlock_id is None:
        unlock_id = conn.execute(text(
            "SELECT unlock_id::text FROM unlock_event WHERE idempotency_key = :k"),
            {"k": key}).scalar_one()
    entitlement_id = conn.execute(text(
        """INSERT INTO entitlement (account_id, insight_type, insight_key, unlock_id, expires_at)
           VALUES (:a, :t, :k, :u,
                   CASE WHEN CAST(:days AS integer) IS NULL THEN NULL
                        ELSE now() + make_interval(days => CAST(:days AS integer)) END)
           ON CONFLICT (account_id, insight_type, insight_key) DO UPDATE
               SET unlock_id = EXCLUDED.unlock_id, granted_at = now(),
                   expires_at = EXCLUDED.expires_at, revoked_at = NULL
           RETURNING entitlement_id::text"""),
        {"a": account_id, "t": insight_type, "k": insight_key, "u": unlock_id,
         "days": policy.entitlement_days}).scalar_one()
    return {"entitlement_id": entitlement_id, "unlock_id": unlock_id, "charged": entry.created,
            "cost_my": policy.cost_my, "policy_version": policy.version}


def has_entitlement(conn: Connection, account_id: str, insight_type: str, insight_key: str) -> bool:
    return conn.execute(text(
        """SELECT EXISTS (SELECT 1 FROM entitlement WHERE account_id = :a AND insight_type = :t
               AND insight_key = :k AND revoked_at IS NULL
               AND (expires_at IS NULL OR expires_at > now()))"""),
        {"a": account_id, "t": insight_type, "k": insight_key}).scalar()
