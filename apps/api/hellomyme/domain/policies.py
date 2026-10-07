"""Active policy lookup. Thresholds, windows, weights, rewards and costs live in policy tables."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, text


class PolicyMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class CohortPolicy:
    cohort_policy_id: str
    version: str
    min_exact_n: int
    graduation_window_years: int
    fallback_enabled: bool
    similarity_fallback_k: int
    max_fallback_level: int
    dimension_fallback_order: tuple[str, ...]
    min_cell_n: int


@dataclass(frozen=True)
class ScoringPolicy:
    scoring_policy_id: str
    policy_type: str
    version: str
    weights: dict
    params: dict


def active_cohort_policy(conn: Connection) -> CohortPolicy:
    row = conn.execute(text(
        """SELECT cohort_policy_id::text, version, min_exact_n, graduation_window_years,
                  fallback_enabled, similarity_fallback_k, max_fallback_level,
                  dimension_fallback_order, min_cell_n
           FROM cohort_policy WHERE status = 'ACTIVE'
             AND effective_from <= now() AND (effective_to IS NULL OR effective_to > now())"""
    )).first()
    if row is None:
        raise PolicyMissing("no active cohort_policy")
    data = dict(row._mapping)
    data["dimension_fallback_order"] = tuple(data["dimension_fallback_order"])
    return CohortPolicy(**data)


def active_scoring_policy(conn: Connection, policy_type: str) -> ScoringPolicy:
    row = conn.execute(text(
        """SELECT scoring_policy_id::text, policy_type, version, weights, params
           FROM scoring_policy WHERE status = 'ACTIVE' AND policy_type = :t"""
    ), {"t": policy_type}).first()
    if row is None:
        raise PolicyMissing(f"no active scoring_policy for {policy_type}")
    return ScoringPolicy(**row._mapping)


def active_reward_policy(conn: Connection, action_type: str):
    return conn.execute(text(
        """SELECT reward_policy_id, action_type, reward_tube, max_occurrences, cooldown_seconds,
                  version
           FROM reward_policy WHERE status = 'ACTIVE' AND action_type = :a
             AND effective_from <= now() AND (effective_to IS NULL OR effective_to > now())"""
    ), {"a": action_type}).first()


def active_unlock_policy(conn: Connection, insight_type: str):
    return conn.execute(text(
        """SELECT unlock_policy_id, insight_type, cost_tube, entitlement_days, version
           FROM unlock_policy WHERE status = 'ACTIVE' AND insight_type = :t
             AND effective_from <= now() AND (effective_to IS NULL OR effective_to > now())"""
    ), {"t": insight_type}).first()
