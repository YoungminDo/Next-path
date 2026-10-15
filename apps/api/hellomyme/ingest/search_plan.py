"""Which queries one search-ingest run sends (docs/12 §4).

Operator queries come first (never-run first, then the oldest run). The rest of the run's budget
goes to demand: school + major pairs people typed recently (the team's own browsers left out)
whose SEED + VERIFIED people are still fewer than the cohort minimum, most-asked first.
A query run within requery_after_days is not planned again.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Connection, text

# acq_input compares ids as text so one malformed answer never breaks the view; cast only valid ones.
UUID_RE = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


@dataclass(frozen=True)
class Policy:
    version: str
    max_queries_per_run: int
    results_per_query: int
    requery_after_days: int
    demand_lookback_days: int
    max_consecutive_errors: int


@dataclass(frozen=True)
class PlannedQuery:
    search_query_id: str
    query_text: str
    last_provider: str | None


def active_policy(conn: Connection) -> Policy | None:
    row = conn.execute(text(
        """SELECT version, max_queries_per_run, results_per_query, requery_after_days,
                  demand_lookback_days, max_consecutive_errors
           FROM search_ingest_policy WHERE status = 'ACTIVE'""")).first()
    return Policy(*row) if row else None


def demand_candidates(conn: Connection, since: datetime, min_n: int) -> list[dict]:
    rows = conn.execute(text(
        """WITH demand AS (
             SELECT CAST(a.institution_id AS uuid) AS institution_id,
                    CAST(a.major_node_id AS uuid) AS major_node_id,
                    max(a.institution_name) AS institution_name, max(a.major_label) AS major_label,
                    count(*) AS drafts
             FROM analytics.acq_input a
             WHERE NOT a.internal AND a.institution_listed AND a.major_label IS NOT NULL
               AND a.major_node_id ~ :uuid_re AND a.created_at >= :since
             GROUP BY 1, 2),
           supply AS (
             SELECT e.institution_id, e.major_taxonomy_node_id AS major_node_id,
                    count(DISTINCT p.person_id) AS n
             FROM person p JOIN canonical_education e ON e.person_id = p.person_id
             WHERE p.deleted_at IS NULL AND p.origin_layer IN ('SEED','VERIFIED')
             GROUP BY 1, 2)
           SELECT d.institution_id::text AS institution_id, d.major_node_id::text AS major_node_id,
                  d.institution_name, d.major_label, d.drafts, coalesce(s.n, 0) AS supply
           FROM demand d LEFT JOIN supply s USING (institution_id, major_node_id)
           WHERE coalesce(s.n, 0) < :min_n
           ORDER BY d.drafts DESC, d.institution_name, d.major_label"""),
        {"since": since, "min_n": min_n, "uuid_re": UUID_RE}).mappings().all()
    return [dict(r) for r in rows]


def _due(conn: Connection, origin: str, cutoff: datetime, limit: int,
         query_text: str | None = None) -> list[PlannedQuery]:
    rows = conn.execute(text(
        """SELECT search_query_id::text, query_text, last_provider FROM search_query
           WHERE origin = :o AND status = 'ACTIVE' AND (last_run_at IS NULL OR last_run_at < :cut)
             AND (CAST(:q AS text) IS NULL OR query_text = :q)
           ORDER BY last_run_at NULLS FIRST, created_at, query_text LIMIT :n"""),
        {"o": origin, "cut": cutoff, "n": limit, "q": query_text}).all()
    return [PlannedQuery(*r) for r in rows]


def plan(conn: Connection, policy: Policy, now: datetime) -> list[PlannedQuery]:
    cutoff = now - timedelta(days=policy.requery_after_days)
    out = _due(conn, "OPERATOR", cutoff, policy.max_queries_per_run)
    if len(out) >= policy.max_queries_per_run:
        return out
    min_n = conn.execute(text("SELECT min_exact_n FROM cohort_policy WHERE status = 'ACTIVE'")).scalar()
    if not min_n:
        return out
    for c in demand_candidates(conn, now - timedelta(days=policy.demand_lookback_days), min_n):
        q = f'site:linkedin.com/in "{c["institution_name"]}" "{c["major_label"]}"'
        conn.execute(text(
            """INSERT INTO search_query (query_text, origin, institution_id, major_node_id)
               VALUES (:q, 'DEMAND', CAST(:i AS uuid), CAST(:m AS uuid))
               ON CONFLICT (query_text) DO NOTHING"""),
            {"q": q, "i": c["institution_id"], "m": c["major_node_id"]})
        out += _due(conn, "DEMAND", cutoff, 1, query_text=q)
        if len(out) >= policy.max_queries_per_run:
            break
    return out
