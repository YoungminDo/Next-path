"""Similarity Engine v0: configurable weighted feature similarity (no ML).

The score is internal. Users only see a bucket label plus the matching features; no
uncalibrated "accuracy %" is ever exposed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hellomyme.domain.policies import ScoringPolicy


@dataclass(frozen=True)
class Profile:
    person_id: str | None = None
    institution_id: str | None = None
    major_id: str | None = None
    major_family: str | None = None
    graduation_year: int | None = None
    current_job_family: str | None = None
    current_role_id: str | None = None
    current_industry: str | None = None
    current_company_size_band: str | None = None
    current_event_type: str | None = None
    job_family_sequence: tuple[str, ...] = field(default_factory=tuple)
    derived_stage: str | None = None


def _edit_distance(a: tuple, b: tuple) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def feature_similarities(q: Profile, c: Profile, params: dict) -> dict[str, float]:
    """Similarity per feature in [0, 1], only for features the query actually has."""
    out: dict[str, float] = {}

    def exact(name: str, a, b):
        if a is not None:
            out[name] = 1.0 if a == b else 0.0

    exact("institution", q.institution_id, c.institution_id)
    if q.major_id is not None:
        if q.major_id == c.major_id:
            out["major"] = 1.0
        elif q.major_family is not None and q.major_family == c.major_family:
            out["major"] = float(params["major_family_partial"])
        else:
            out["major"] = 0.0
    if q.graduation_year is not None:
        decay = float(params["graduation_year_decay_years"])
        if c.graduation_year is None:
            out["graduation_year"] = 0.0
        else:
            out["graduation_year"] = max(0.0, 1 - abs(q.graduation_year - c.graduation_year) / decay)
    exact("current_job_family", q.current_job_family, c.current_job_family)
    exact("current_role", q.current_role_id, c.current_role_id)
    exact("current_industry", q.current_industry, c.current_industry)
    exact("current_company_size", q.current_company_size_band, c.current_company_size_band)
    exact("current_event_type", q.current_event_type, c.current_event_type)
    if q.job_family_sequence:
        a, b = tuple(q.job_family_sequence), tuple(c.job_family_sequence)
        out["career_sequence"] = 1 - _edit_distance(a, b) / max(len(a), len(b))
    exact("stage", q.derived_stage, c.derived_stage)
    return out


def score(q: Profile, c: Profile, policy: ScoringPolicy) -> tuple[float, dict[str, float]]:
    sims = feature_similarities(q, c, policy.params)
    weights = {k: float(policy.weights.get(k, 0)) for k in sims}
    total = sum(weights.values())
    if total == 0:
        return 0.0, sims
    return sum(sims[k] * w for k, w in weights.items()) / total, sims


def bucket(value: float, policy: ScoringPolicy) -> str:
    thresholds = policy.params["bucket_thresholds"]
    if value >= float(thresholds["VERY_SIMILAR"]):
        return "VERY_SIMILAR"
    if value >= float(thresholds["SIMILAR"]):
        return "SIMILAR"
    return "RELATED"
