"""Search ingest planning (docs/12 §4). Each test runs in a transaction that is rolled back."""
import dataclasses
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from hellomyme.ingest.pipeline import accept_pending, approve, receive
from hellomyme.ingest.search_plan import active_policy, demand_candidates, plan

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)


@pytest.fixture
def conn(engine):
    with engine.connect() as c:
        tx = c.begin()
        yield c
        tx.rollback()


def test_seeded_policy_is_the_one_active(conn):
    rows = conn.execute(text(
        """SELECT version, max_queries_per_run, results_per_query, requery_after_days,
                  demand_lookback_days, max_consecutive_errors
           FROM search_ingest_policy WHERE status = 'ACTIVE'""")).all()
    assert [tuple(r) for r in rows] == [("search_v1", 20, 10, 30, 30, 5)]


def _ref(c):
    """Two listed schools and one major node the planner can name."""
    # Other tests commit drafts; mark them internal (rolled back) so demand is ours alone.
    c.execute(text("UPDATE anonymous_draft SET internal = true"))
    tv = c.execute(text(
        """INSERT INTO taxonomy_version (taxonomy, version) VALUES ('INSTITUTION', 'plan-test')
           ON CONFLICT (taxonomy, version) DO UPDATE SET version = EXCLUDED.version
           RETURNING taxonomy_version_id""")).scalar_one()
    a, b = (c.execute(text("INSERT INTO institution (name, taxonomy_version_id) VALUES (:n, :v) "
                           "RETURNING institution_id::text"), {"n": n, "v": tv}).scalar_one()
            for n in ("플랜대학교", "수요대학교"))
    tid = c.execute(text("SELECT taxonomy_id FROM taxonomy WHERE taxonomy_type = 'MAJOR' "
                         "AND status = 'ACTIVE'")).scalar() or c.execute(text(
        """INSERT INTO taxonomy (taxonomy_type, name, version, status)
           VALUES ('MAJOR', 'plan test', 'plan-test', 'ACTIVE') RETURNING taxonomy_id""")).scalar_one()
    m = c.execute(text(
        """INSERT INTO taxonomy_node (taxonomy_id, code, canonical_name, display_name, depth)
           VALUES (:t, 'PLAN_M1', '플랜학과', '플랜학과', 1) RETURNING taxonomy_node_id::text"""),
        {"t": tid}).scalar_one()
    return a, b, m


def _draft(c, inst, major, n=1, internal=False, days_ago=1):
    payload = json.dumps({"schema_version": "acq_v1",
                          "education": {"institution_id": inst, "major_node_id": major}})
    for _ in range(n):
        c.execute(text(
            """INSERT INTO anonymous_draft (session_id, user_type, payload_json, expires_at,
                                            created_at, internal)
               VALUES ('plan-test', 'STUDENT', CAST(:p AS jsonb), now(), :at, :i)"""),
            {"p": payload, "at": NOW - timedelta(days=days_ago), "i": internal})


def _seed_person(c, school):
    """One SEED person at school + 플랜학과, loaded through the real pipeline."""
    doc = {"schema_version": "career_extraction.v1", "submission_id": f"plan-{school}",
           "assets": [{"asset_id": "S1", "page_order": 1}], "person": {"display_name_raw": None},
           "educations": [{"local_id": "E1", "institution_raw": school, "major_raw": "플랜학과",
                           "start": {"value": "2016", "precision": "YEAR"},
                           "end": {"value": "2020", "precision": "YEAR"},
                           "evidence": [{"asset_id": "S1", "text": f"{school} 플랜학과 2016 - 2020"}]}],
           "work_events": []}
    r = receive(c, json.dumps(doc, ensure_ascii=False), collector="plan-test",
                source_type="PUBLIC_PROFILE", permitted_use="AGGREGATE_ONLY", legal_basis="test",
                model_version="t", prompt_version="t", as_of=NOW.date())
    accept_pending(c, r["parse_run_id"])
    approve(c, r["parse_run_id"])


def _operator(c, q, last_run_at=None):
    c.execute(text("INSERT INTO search_query (query_text, origin, last_run_at) "
                   "VALUES (:q, 'OPERATOR', :t)"), {"q": q, "t": last_run_at})


def test_demand_counts_external_recent_drafts_and_skips_filled_cohorts(conn):
    a, b, m = _ref(conn)
    _draft(conn, a, m, n=3)
    _draft(conn, b, m, n=2)
    _draft(conn, b, m, n=5, internal=True)          # the team's own browsers
    _draft(conn, b, m, n=4, days_ago=90)            # outside the window
    _seed_person(conn, "플랜대학교")                  # 플랜대학교 + 플랜학과 now has 1 SEED person
    rows = demand_candidates(conn, NOW - timedelta(days=30), min_n=1)
    assert [(r["institution_name"], r["drafts"], r["supply"]) for r in rows] == [("수요대학교", 2, 0)]


def test_operator_queries_first_then_demand_up_to_the_limit(conn):
    a, b, m = _ref(conn)
    _draft(conn, a, m, n=3)
    _draft(conn, b, m, n=2)
    _operator(conn, "op-old", NOW - timedelta(days=40))
    _operator(conn, "op-new")
    _operator(conn, "op-recent", NOW - timedelta(days=2))   # inside requery_after_days
    out = plan(conn, dataclasses.replace(active_policy(conn), max_queries_per_run=3), NOW)
    assert [q.query_text for q in out] == [
        "op-new", "op-old", 'site:linkedin.com/in "플랜대학교" "플랜학과"']
    origin = conn.execute(text("SELECT origin FROM search_query WHERE query_text = :q"),
                          {"q": out[2].query_text}).scalar_one()
    assert origin == "DEMAND"


def test_a_demand_query_run_recently_is_not_planned_again(conn):
    a, b, m = _ref(conn)
    _draft(conn, a, m, n=3)
    _draft(conn, b, m, n=2)
    conn.execute(text(
        """INSERT INTO search_query (query_text, origin, institution_id, major_node_id, last_run_at)
           VALUES ('site:linkedin.com/in "플랜대학교" "플랜학과"', 'DEMAND', CAST(:a AS uuid),
                   CAST(:m AS uuid), :t)"""), {"a": a, "m": m, "t": NOW - timedelta(days=1)})
    out = plan(conn, active_policy(conn), NOW)
    assert [q.query_text for q in out] == ['site:linkedin.com/in "수요대학교" "플랜학과"']
