"""Mentor matching: seniors who actually walked the target path, ranked by MENTOR_RANKING policy.

Only explicit opt-in mentors with a member-owned (VERIFIED) person are ever returned; PRE_SEED
and SEED persons are never presented as people.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, text

from hellomyme.domain.career_input import member_profile
from hellomyme.domain.policies import ScoringPolicy
from hellomyme.domain.similarity import Profile, score

MVP_OFFER_TYPES = ("QNA", "15_MIN_CHAT")


def _path_relevance(conn, person_id: str, target_job_family: str, as_of: date):
    rows = conn.execute(text(
        """SELECT w.start_date, w.is_current FROM canonical_work_event w
           JOIN role r USING (role_id)
           WHERE w.person_id = :p AND r.job_family = :f AND w.start_date IS NOT NULL
           ORDER BY w.start_date DESC"""), {"p": person_id, "f": target_job_family}).all()
    if not rows:
        return None, None
    relevance = 1.0 if any(r.is_current for r in rows) else 0.8
    years_ago = (as_of - rows[0].start_date).days / 365.25
    return relevance, years_ago


def match(conn: Connection, requester: Profile, target_job_family: str, policy: ScoringPolicy,
          similarity_policy: ScoringPolicy, as_of: date, limit: int = 20) -> list[dict]:
    mentors = conn.execute(text(
        """SELECT m.mentor_profile_id::text, m.person_id::text, m.headline, m.is_accepting,
                  m.rating_avg, m.rating_count, m.response_rate, m.completed_count
           FROM mentor_profile m JOIN person p USING (person_id)
           WHERE m.status = 'ACTIVE' AND p.origin_layer = 'VERIFIED' AND p.deleted_at IS NULL
             AND (CAST(:pid AS uuid) IS NULL OR m.person_id <> CAST(:pid AS uuid))"""),
        {"pid": requester.person_id}).all()
    w, params = policy.weights, policy.params
    results = []
    for m in mentors:
        relevance, years_ago = _path_relevance(conn, m.person_id, target_job_family, as_of)
        if relevance is None:
            continue  # has not walked the target path
        mentor = member_profile(conn, m.person_id, as_of)
        sim, sims = score(requester, mentor, similarity_policy)
        features = {
            "career_similarity": sim,
            "target_path_relevance": relevance,
            "recency": 0.5 ** (years_ago / float(params["recency_half_life_years"])),
            "availability": 1.0 if m.is_accepting else 0.0,
            "completed_transactions": min(
                1.0, m.completed_count / float(params["completed_transactions_saturation"])),
        }
        if m.rating_count:  # unknown rating/response rate are left out, not scored as zero
            features["rating"] = float(m.rating_avg) / 5
        if m.response_rate is not None:
            features["response_rate"] = float(m.response_rate)
        total_w = sum(float(w.get(k, 0)) for k in features)
        rank = sum(v * float(w.get(k, 0)) for k, v in features.items()) / total_w
        offers = conn.execute(text(
            """SELECT offer_id::text, offer_type, title, duration_minutes, price_my
               FROM mentor_offer WHERE mentor_profile_id = :m AND status = 'ACTIVE'
                 AND offer_type = ANY(:types)"""),
            {"m": m.mentor_profile_id, "types": list(MVP_OFFER_TYPES)}).all()
        results.append({
            "mentor_profile_id": m.mentor_profile_id, "headline": m.headline,
            "_rank": rank,
            "match_reasons": [k for k, v in sims.items() if v >= 1.0],
            "path": {"target_job_family": target_job_family,
                     "is_current": relevance == 1.0, "years_since_start": round(years_ago, 1)},
            "is_accepting": m.is_accepting,
            "offers": [dict(o._mapping) for o in offers],
        })
    results.sort(key=lambda r: r["_rank"], reverse=True)
    for r in results:
        r.pop("_rank")
    return results[:limit]
