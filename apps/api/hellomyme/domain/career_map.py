"""Career Map aggregation over a cohort: "what did similar people actually do next?".

All counts are unique persons. Any category backed by fewer than min_cell_n persons is folded
into OTHER; a map whose cohort is suppressed returns no distributions at all.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, replace
from statistics import mean, median

from sqlalchemy import Connection, text

from hellomyme.domain.aggregation import LOGIC_VERSION
from hellomyme.domain.cohort import CohortResult, build_cohort
from hellomyme.domain.policies import CohortPolicy, ScoringPolicy
from hellomyme.domain.similarity import Profile

INSIGHT_TYPES = ("PATH_DEEP_DIVE", "COMPANY_BREAKDOWN", "REPRESENTATIVE_PATHS", "TIMING_TENURE")

COHORT_LABELS = {
    0: "같은 학교·학과·졸업년도",
    1: "같은 학교·학과, 비슷한 졸업 시기",
    2: "더 넓은 비교 그룹",
    3: "비슷한 경력 여정을 가진 사람들 (정확히 같은 조건은 아님)",
}
SIMULATION_NOTICE = ("개발·UX 검증용 시뮬레이션 데이터입니다. 실제 사람들의 경력 선택 통계가 "
                     "아닙니다.")


@dataclass
class Resolved:
    anchor: str
    cohort: CohortResult
    moves: list[dict]


def insight_key(insight_type: str, query: Profile, target_job_family: str | None) -> str:
    basis = {"type": insight_type, "target": target_job_family,
             "institution_id": query.institution_id, "major_id": query.major_id,
             "graduation_year": query.graduation_year,
             "current_job_family": query.current_job_family}
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:32]


def distribution(values: list, min_cell_n: int, top: int | None = None) -> list[dict]:
    counts = Counter(v for v in values if v is not None)
    total = sum(counts.values())
    if total == 0:
        return []
    shown, other = [], 0
    for value, n in counts.most_common():
        if n >= min_cell_n and (top is None or len(shown) < top):
            shown.append({"value": value, "n": n})
        else:
            other += n
    if other:
        shown.append({"value": "OTHER", "n": other})
    for item in shown:
        item["share_pct"] = round(100 * item["n"] / total)
    return shown


def _stat(values: list[int], min_cell_n: int) -> dict | None:
    values = [v for v in values if v is not None]
    if len(values) < min_cell_n:
        return None
    return {"n": len(values), "mean": round(mean(values), 1), "median": median(values)}


def _transitions(conn: Connection, person_ids: list[str]) -> list[dict]:
    rows = conn.execute(text(
        """SELECT t.person_id::text, t.from_work_event_id IS NULL AS is_entry, t.from_job_family,
                  t.to_job_family, t.to_event_type, t.to_industry, t.to_company_size_band,
                  t.to_org_is_placeholder, o.name AS to_organization, r.name AS to_role,
                  t.from_tenure_months, t.gap_months, t.years_since_graduation,
                  t.transition_index
           FROM career_transition t
           LEFT JOIN organization o ON o.organization_id = t.to_organization_id
           LEFT JOIN role r ON r.role_id = t.to_role_id
           WHERE t.logic_version = :v AND t.person_id = ANY(CAST(:ids AS uuid[]))
           ORDER BY t.person_id, t.transition_index"""),
        {"v": LOGIC_VERSION, "ids": person_ids})
    return [dict(r._mapping) for r in rows]


def _eligible(conn: Connection, layers: list[str], from_job_family: str | None,
              entry: bool) -> set[str]:
    sql = ("SELECT DISTINCT person_id::text FROM career_transition "
           "WHERE logic_version = :v AND origin_layer = ANY(:layers) AND ")
    if entry:
        sql += "from_work_event_id IS NULL"
    elif from_job_family is None:
        sql += "from_work_event_id IS NOT NULL"
    else:
        sql += "from_work_event_id IS NOT NULL AND from_job_family = :fam"
    return set(conn.execute(text(sql), {"v": LOGIC_VERSION, "layers": layers,
                                        "fam": from_job_family}).scalars())


def _first_per_person(rows) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        if r["person_id"] not in seen:
            seen.add(r["person_id"])
            out.append(r)
    return out


def resolve(conn: Connection, query: Profile, population: list[Profile], policy: CohortPolicy,
            similarity_policy: ScoringPolicy, layers: list[str]) -> Resolved:
    """Pick the anchor, then build the cohort among persons who actually made that move, so the
    sample threshold applies to the analysed basis and not just to cohort membership."""
    candidates = []
    if query.current_job_family:
        candidates.append(("FROM_CURRENT_JOB_FAMILY",
                           _eligible(conn, layers, query.current_job_family, entry=False),
                           replace(query, current_job_family=None)))
        candidates.append(("ANY_NEXT_MOVE", _eligible(conn, layers, None, entry=False), query))
    else:
        candidates.append(("FIRST_DESTINATION", _eligible(conn, layers, None, entry=True), query))

    resolved = None
    for anchor, eligible, cohort_query in candidates:
        pool = [p for p in population if p.person_id in eligible]
        cohort = build_cohort(cohort_query, pool, policy, similarity_policy)
        resolved = Resolved(anchor, cohort, [])
        if not cohort.suppressed:
            break
    rows = _transitions(conn, resolved.cohort.person_ids) if not resolved.cohort.suppressed else []
    if resolved.anchor == "FROM_CURRENT_JOB_FAMILY":
        rows = [r for r in rows if not r["is_entry"]
                and r["from_job_family"] == query.current_job_family]
    elif resolved.anchor == "ANY_NEXT_MOVE":
        rows = [r for r in rows if not r["is_entry"]]
    else:
        rows = [r for r in rows if r["is_entry"]]
    resolved.moves = _first_per_person(rows)
    return resolved


def base_map(resolved: Resolved, policy: CohortPolicy, simulation: bool) -> dict:
    cohort = resolved.cohort
    out = {
        "cohort": {
            "label": COHORT_LABELS[cohort.fallback_level],
            "is_exact": cohort.fallback_level == 0,
            **cohort.audit(),
        },
        "data_basis": "SIMULATION" if simulation else "OBSERVED",
        "notice": SIMULATION_NOTICE if simulation else None,
    }
    if cohort.suppressed:
        out.update({"suppressed": True, "reason": "LOW_SAMPLE",
                    "message": "아직 비교할 수 있는 사람이 충분하지 않아요."})
        return out
    moves = resolved.moves
    n = len(moves)
    out.update({"suppressed": n < policy.min_exact_n, "anchor": resolved.anchor, "basis_n": n})
    if n < policy.min_exact_n:
        out["reason"] = "LOW_SAMPLE_FOR_NEXT_MOVE"
        return out
    out["next_job_family"] = distribution([m["to_job_family"] for m in moves], policy.min_cell_n)
    out["next_event_type"] = distribution([m["to_event_type"] for m in moves], policy.min_cell_n)
    out["next_industry"] = distribution([m["to_industry"] for m in moves], policy.min_cell_n)
    out["next_company_size"] = distribution(
        [m["to_company_size_band"] for m in moves], policy.min_cell_n)
    out["locked_insights"] = list(INSIGHT_TYPES)
    return out


def teaser(resolved: Resolved, policy: CohortPolicy, simulation: bool) -> dict:
    """Pre-login: no distributions, only that an answer exists and how broad it is."""
    cohort = resolved.cohort
    if cohort.suppressed:
        size = None
    elif cohort.effective_n >= 10 * policy.min_exact_n:
        size = f"{10 * policy.min_exact_n}+"
    else:
        size = f"{policy.min_exact_n}+"
    return {
        "available": not cohort.suppressed,
        "cohort_label": COHORT_LABELS[cohort.fallback_level],
        "cohort_size_band": size,
        "data_basis": "SIMULATION" if simulation else "OBSERVED",
        "notice": SIMULATION_NOTICE if simulation else None,
        "login_required_for": ["next_job_family", "next_industry", "next_company_size",
                               *INSIGHT_TYPES],
    }


def unlocked_insight(conn: Connection, insight_type: str, resolved: Resolved,
                     policy: CohortPolicy, target_job_family: str | None) -> dict:
    if resolved.cohort.suppressed:
        return {"suppressed": True, "reason": "LOW_SAMPLE"}
    moves = resolved.moves
    if target_job_family:
        moves = [m for m in moves if m["to_job_family"] == target_job_family]
    if len(moves) < policy.min_exact_n:
        return {"suppressed": True, "reason": "LOW_SAMPLE_FOR_TARGET", "basis_n": len(moves)}
    k = policy.min_cell_n
    base = {"suppressed": False, "basis_n": len(moves), "target_job_family": target_job_family}
    if insight_type == "PATH_DEEP_DIVE":
        return {**base,
                "next_role": distribution([m["to_role"] for m in moves], k),
                "next_industry": distribution([m["to_industry"] for m in moves], k),
                "next_company_size": distribution([m["to_company_size_band"] for m in moves], k),
                "tenure_before_move_months": _stat([m["from_tenure_months"] for m in moves], k)}
    if insight_type == "COMPANY_BREAKDOWN":
        named = [m["to_organization"] for m in moves if not m["to_org_is_placeholder"]]
        return {**base, "named_company_basis_n": len(named),
                "next_company": distribution(named, k, top=10)}
    if insight_type == "TIMING_TENURE":
        return {**base,
                "tenure_before_move_months": _stat([m["from_tenure_months"] for m in moves], k),
                "gap_months": _stat([m["gap_months"] for m in moves], k),
                "years_since_graduation": distribution(
                    [m["years_since_graduation"] for m in moves], k)}
    if insight_type == "REPRESENTATIVE_PATHS":
        seqs = conn.execute(text(
            """SELECT job_family_sequence FROM career_person_snapshot
               WHERE logic_version = :v AND person_id = ANY(CAST(:ids AS uuid[]))"""),
            {"v": LOGIC_VERSION, "ids": [m["person_id"] for m in moves]}).scalars()
        paths = [" → ".join(s[:3]) for s in seqs if s]
        return {**base, "paths": distribution(paths, k, top=5)}
    raise ValueError(insight_type)
