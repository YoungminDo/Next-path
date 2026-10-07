"""Adaptive Cohort Engine.

Fallback order (COHORT_POLICY decides thresholds, window, order and maximum level):
  0 exact cohort            all provided dimensions match exactly
  1 time window             graduation_year -> graduation_year +/- window
  2 dimension fallback      drop dimensions one at a time in dimension_fallback_order
  3 similarity top-K        K most similar journeys (weighted similarity v0)
Every result keeps exact_n, effective_n, fallback_level and cohort_policy_version. A result
whose best level still has fewer than min_exact_n unique persons is suppressed.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from hellomyme.domain.aggregation import LOGIC_VERSION
from hellomyme.domain.policies import CohortPolicy, ScoringPolicy
from hellomyme.domain.similarity import Profile, score

# Dimensions a cohort can be defined on, mapped to Profile attributes.
DIMENSIONS = ("institution_id", "major_id", "graduation_year", "current_job_family",
              "major_family")


@dataclass
class CohortResult:
    fallback_level: int
    applied_dimensions: dict
    exact_n: int
    effective_n: int
    cohort_policy_version: str
    suppressed: bool
    person_ids: list[str] = field(default_factory=list, repr=False)
    similarity: dict[str, float] = field(default_factory=dict, repr=False)
    cohort_result_id: str | None = None

    def audit(self) -> dict:
        return {"exact_n": self.exact_n, "effective_n": self.effective_n,
                "fallback_level": self.fallback_level,
                "cohort_policy_version": self.cohort_policy_version,
                "applied_dimensions": self.applied_dimensions, "suppressed": self.suppressed}


class Population:
    """Snapshot rows for the configured data layers, cached per aggregation run."""

    _lock = threading.Lock()
    _cache: dict[tuple, list[Profile]] = {}

    @classmethod
    def load(cls, conn: Connection, layers: list[str],
             logic_version: str = LOGIC_VERSION) -> list[Profile]:
        run_id = conn.execute(text(
            "SELECT max(finished_at)::text FROM aggregation_run "
            "WHERE logic_version = :v AND status = 'COMPLETED'"), {"v": logic_version}).scalar()
        key = (logic_version, tuple(sorted(layers)), run_id)
        with cls._lock:
            if key in cls._cache:
                return cls._cache[key]
        rows = conn.execute(text(
            """SELECT person_id::text, institution_id::text, major_id::text, major_family,
                      graduation_year, current_job_family, current_role_id::text,
                      current_industry, current_company_size_band, current_event_type,
                      job_family_sequence, derived_stage
               FROM career_person_snapshot
               WHERE logic_version = :v AND origin_layer = ANY(:layers)"""),
            {"v": logic_version, "layers": layers})
        profiles = [Profile(**{**r._mapping,
                               "job_family_sequence": tuple(r.job_family_sequence)})
                    for r in rows]
        with cls._lock:
            cls._cache = {k: v for k, v in cls._cache.items() if k[:2] != key[:2]}
            cls._cache[key] = profiles
        return profiles


def _matches(p: Profile, dims: dict, window: int | None) -> bool:
    for name, value in dims.items():
        actual = getattr(p, name)
        if name == "graduation_year" and window is not None:
            if actual is None or abs(actual - value) > window:
                return False
        elif actual != value:
            return False
    return True


def build_cohort(query: Profile, population: list[Profile], policy: CohortPolicy,
                 similarity_policy: ScoringPolicy) -> CohortResult:
    others = [p for p in population if p.person_id != query.person_id]
    dims = {d: getattr(query, d) for d in DIMENSIONS
            if d != "major_family" and getattr(query, d) is not None}
    min_n = policy.min_exact_n

    def members(d: dict, window: int | None = None) -> list[str]:
        return [p.person_id for p in others if _matches(p, d, window)]

    exact = members(dims) if dims else []
    exact_n = len(exact)

    def result(level, applied, ids, sims=None, suppressed=False):
        return CohortResult(level, applied, exact_n, len(ids), policy.version, suppressed,
                            [] if suppressed else ids, sims or {})

    best: tuple[int, dict, list[str]] = (0, dims, exact)
    if dims and exact_n >= min_n:
        return result(0, dims, exact)
    can = policy.fallback_enabled

    if can and policy.max_fallback_level >= 1 and "graduation_year" in dims:
        ids = members(dims, policy.graduation_window_years)
        applied = {**dims, "graduation_window_years": policy.graduation_window_years}
        if len(ids) >= min_n:
            return result(1, applied, ids)
        best = max(best, (1, applied, ids), key=lambda b: len(b[2]))

    if can and policy.max_fallback_level >= 2:
        remaining = dict(dims)
        for dim in policy.dimension_fallback_order:
            if dim not in remaining:
                continue
            remaining.pop(dim)
            if not remaining:
                break
            ids = members(remaining)
            if len(ids) >= min_n:
                return result(2, dict(remaining), ids)
            best = max(best, (2, dict(remaining), ids), key=lambda b: len(b[2]))

    if can and policy.max_fallback_level >= 3:
        scored = []
        for p in others:
            s, _ = score(query, p, similarity_policy)
            if s > 0:
                scored.append((s, p.person_id))
        scored.sort(reverse=True)
        top = scored[: policy.similarity_fallback_k]
        ids = [pid for _, pid in top]
        applied = {"similarity_policy_version": similarity_policy.version,
                   "k": policy.similarity_fallback_k}
        if len(ids) >= min_n:
            return result(3, applied, ids, {pid: s for s, pid in top})
        best = max(best, (3, applied, ids), key=lambda b: len(b[2]))

    level, applied, ids = best
    return result(level, applied, ids, suppressed=True)


def log_result(conn: Connection, res: CohortResult, policy: CohortPolicy, query: Profile,
               layers: list[str], account_id: str | None = None,
               draft_id: str | None = None) -> str:
    request = {d: getattr(query, d) for d in DIMENSIONS if getattr(query, d) is not None}
    rid = conn.execute(text(
        """INSERT INTO cohort_result_log (cohort_policy_id, cohort_policy_version, logic_version,
               request_dimensions, applied_dimensions, data_layers, fallback_level, exact_n,
               effective_n, suppressed, account_id, anonymous_draft_id)
           VALUES (:pid, :pv, :lv, CAST(:req AS jsonb), CAST(:app AS jsonb), :layers, :lvl,
                   :en, :eff, :sup, :acc, :draft)
           RETURNING cohort_result_id::text"""),
        {"pid": policy.cohort_policy_id, "pv": policy.version, "lv": LOGIC_VERSION,
         "req": json.dumps(request), "app": json.dumps(res.applied_dimensions),
         "layers": layers, "lvl": res.fallback_level, "en": res.exact_n,
         "eff": res.effective_n, "sup": res.suppressed, "acc": account_id, "draft": draft_id},
    ).scalar_one()
    res.cohort_result_id = rid
    return rid
