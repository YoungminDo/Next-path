"""One search-ingest run (docs/12 §5): plan -> search -> snippet -> receive(), counted in search_run.

Runs on the caller's connection and transaction (the CLI commits, or rolls back for --dry-run).
One savepoint per person, so one bad result never loses the others. The job only receives:
every field waits for a person (docs/09 §3), and nothing is shown as a person (docs/09 §8).

Providers alternate per query: a query run before starts with the provider it did not use last
time, a never-run query takes the next one in rotation. 401/403/429 removes a provider for the
rest of the run and the query is retried once on the other.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import Connection, text

from hellomyme.ingest.pipeline import IngestError, receive
from hellomyme.ingest.search_plan import active_policy, plan
from hellomyme.ingest.search_source import SearchError
from hellomyme.ingest.snippet import PROMPT_VERSION, profile_key, to_extraction

COLLECTOR = "search-cron"
LOCK_KEY = 120041  # transaction-scoped advisory lock: one run at a time
COUNTS = ("queries", "results", "received", "replayed", "already_loaded", "rejected", "empty", "errors")


class _Stop(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _finish(conn: Connection, run_id: str, status: str, reason: str | None, counts: dict,
            by_provider: dict) -> dict:
    conn.execute(text(
        f"""UPDATE search_run SET status = :st, reason = :r, finished_at = now(),
                {", ".join(f"{k} = :{k}" for k in COUNTS)}, by_provider = CAST(:bp AS jsonb)
            WHERE search_run_id = CAST(:id AS uuid)"""),
        {"st": status, "r": reason, "id": run_id, "bp": json.dumps(by_provider), **counts})
    return {"search_run_id": run_id, "status": status, "reason": reason, **counts,
            "by_provider": by_provider}


def _precondition(conn: Connection, settings, providers: list, policy) -> str | None:
    if policy is None:
        return "NO_ACTIVE_POLICY"
    if not providers:
        return "NO_SEARCH_PROVIDER"
    if not settings.public_profile_legal_basis:
        return "NO_LEGAL_BASIS"
    if settings.env == "production" and not settings.public_profile_legal_reviewed:
        return "LEGAL_REVIEW_PENDING"
    if not conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}).scalar():
        return "ALREADY_RUNNING"
    return None


def run(conn: Connection, *, settings, providers: list, as_of: date, now: datetime) -> dict:
    run_id = conn.execute(text("INSERT INTO search_run DEFAULT VALUES RETURNING search_run_id::text")
                          ).scalar_one()
    counts = dict.fromkeys(COUNTS, 0)
    by_provider = {p.name: {"queries": 0, "results": 0, "received": 0, "failed": []} for p in providers}
    policy = active_policy(conn)
    reason = _precondition(conn, settings, providers, policy)
    if reason:
        return _finish(conn, run_id, "SKIPPED", reason, counts, by_provider)

    usable, seen = list(providers), set()
    streak = rot = 0

    def take(person, provider) -> None:
        nonlocal streak
        key = profile_key(person.url)
        if key is None:  # a company or post page, not a person
            return
        counts["results"] += 1
        if key in seen:
            counts["replayed"] += 1
            return
        seen.add(key)
        doc = to_extraction(person.title, person.snippet, key)
        if doc is None:
            counts["empty"] += 1
            return
        sp = conn.begin_nested()
        try:
            r = receive(conn, json.dumps(doc, ensure_ascii=False), collector=COLLECTOR,
                        source_type="PUBLIC_PROFILE", permitted_use="AGGREGATE_ONLY",
                        legal_basis=settings.public_profile_legal_basis,
                        model_version=provider.model_version, prompt_version=PROMPT_VERSION,
                        as_of=as_of)
            sp.commit()
        except IngestError:  # already LOADED or WITHDRAWN: nothing to do
            sp.rollback()
            counts["already_loaded"] += 1
            return
        except Exception:
            sp.rollback()
            counts["errors"] += 1
            streak += 1
            if streak >= policy.max_consecutive_errors:
                raise _Stop("TOO_MANY_ERRORS") from None
            return
        streak = 0
        if r.get("replayed"):
            counts["replayed"] += 1
        elif r["status"] == "REJECTED":
            counts["rejected"] += 1
        else:
            counts["received"] += 1
            by_provider[provider.name]["received"] += 1

    try:
        for q in plan(conn, policy, now):
            counts["queries"] += 1
            if q.last_provider:
                order = sorted(usable, key=lambda p: p.name == q.last_provider)
            else:
                i = rot % len(usable)
                order, rot = usable[i:] + usable[:i], rot + 1
            for provider in order:
                if provider not in usable:
                    continue
                by_provider[provider.name]["queries"] += 1
                try:
                    page = provider.search(q.query_text, policy.results_per_query)
                except SearchError as exc:
                    if not exc.fatal:
                        counts["errors"] += 1
                        break
                    by_provider[provider.name]["failed"].append(exc.status)
                    usable.remove(provider)
                    if not usable:
                        raise _Stop("ALL_PROVIDERS_FAILED:" + ",".join(
                            f"{n}={v['failed']}" for n, v in by_provider.items())) from None
                    continue  # retry this query once on the other provider
                by_provider[provider.name]["results"] += len(page)
                for person in page:
                    take(person, provider)
                conn.execute(text(
                    """UPDATE search_query SET last_run_at = :now, last_provider = :p
                       WHERE search_query_id = CAST(:id AS uuid)"""),
                    {"now": now, "p": provider.name, "id": q.search_query_id})
                break
    except _Stop as stop:
        return _finish(conn, run_id, "FAILED", stop.reason, counts, by_provider)
    return _finish(conn, run_id, "DONE", None, counts, by_provider)
