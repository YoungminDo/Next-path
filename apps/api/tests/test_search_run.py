"""One search-ingest run (docs/12 §5) with fake providers. Each test rolls back."""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from hellomyme.ingest.search_run import LOCK_KEY, run
from hellomyme.ingest.search_source import Result, SearchError

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)
AS_OF = date(2026, 10, 15)


class S:
    env = "staging"
    public_profile_legal_basis = "test basis"
    public_profile_legal_reviewed = False


def person(slug, org="토스", year="2022"):
    return Result(f"https://kr.linkedin.com/in/{slug}", f"테스트{slug} - 개발자 - {org} | LinkedIn",
                  f"경력: {org} · {org} {year} - 현재")


class Fake:
    def __init__(self, name, pages=None, fail=None):
        self.name = self.model_version = name
        self.pages, self.fail, self.calls = pages or {}, fail, []

    def search(self, query, count):
        self.calls.append(query)
        if self.fail:
            raise SearchError(self.name, self.fail, "fake")
        return self.pages.get(query, [])


@pytest.fixture
def conn(engine):
    with engine.connect() as c:
        tx = c.begin()
        # other test files commit anonymous_draft rows that plan() turns into DEMAND queries
        c.execute(text("UPDATE anonymous_draft SET internal = true"))
        yield c
        tx.rollback()


def _ops(c, *queries):
    for q in queries:
        c.execute(text("INSERT INTO search_query (query_text, origin) VALUES (:q, 'OPERATOR')"), {"q": q})


def go(c, providers, settings=S):
    return run(c, settings=settings, providers=providers, as_of=AS_OF, now=NOW)


def test_alternates_providers_and_receives_each_person_once(conn):
    _ops(conn, "q1", "q2")
    a = Fake("serpapi", {"q1": [person("a"), person("b")]})
    b = Fake("brave", {"q2": [person("a"), person("c", "카카오")]})
    out = go(conn, [a, b])
    assert out["status"] == "DONE"
    assert (a.calls, b.calls) == (["q1"], ["q2"])
    assert (out["received"], out["replayed"], out["results"]) == (3, 1, 4)
    assert out["by_provider"]["brave"]["received"] == 1
    subs = conn.execute(text(
        """SELECT count(*) FROM source_submission s JOIN collector c USING (collector_id)
           WHERE c.name = 'search-cron' AND s.source_type = 'PUBLIC_PROFILE'
             AND s.permitted_use = 'AGGREGATE_ONLY'""")).scalar_one()
    assert subs == 3
    raw = conn.execute(text("SELECT string_agg(raw_output::text, ' ') FROM parse_run")).scalar_one()
    assert "테스트a" not in raw and "linkedin.com" not in raw
    last = conn.execute(text("SELECT query_text, last_provider FROM search_query ORDER BY 1")).all()
    assert [tuple(r) for r in last] == [("q1", "serpapi"), ("q2", "brave")]


def test_a_quota_error_moves_the_rest_of_the_run_to_the_other_provider(conn):
    _ops(conn, "q1", "q2")
    a = Fake("serpapi", fail=429)
    b = Fake("brave", {"q1": [person("a")], "q2": [person("b")]})
    out = go(conn, [a, b])
    assert out["status"] == "DONE" and out["received"] == 2
    assert (a.calls, b.calls) == (["q1"], ["q1", "q2"])
    assert out["by_provider"]["serpapi"]["failed"] == [429]


def test_both_providers_unusable_fails_the_run(conn):
    _ops(conn, "q1")
    out = go(conn, [Fake("serpapi", fail=401), Fake("brave", fail=401)])
    assert out["status"] == "FAILED" and out["reason"].startswith("ALL_PROVIDERS_FAILED")


def test_a_loaded_person_counts_as_already_loaded(conn):
    _ops(conn, "q1")
    go(conn, [Fake("serpapi", {"q1": [person("a")]})])
    conn.execute(text("UPDATE source_submission SET status = 'LOADED'"))
    conn.execute(text("UPDATE search_query SET last_run_at = NULL"))
    out = go(conn, [Fake("serpapi", {"q1": [person("a", year="2023")]})])
    assert (out["already_loaded"], out["received"]) == (1, 0)


def test_empty_results_and_non_profiles_are_not_received(conn):
    _ops(conn, "q1")
    out = go(conn, [Fake("serpapi", {"q1": [
        Result("https://kr.linkedin.com/in/z", "Z | LinkedIn", "서울"),
        Result("https://www.linkedin.com/company/toss", "Toss | LinkedIn", "회사")]})])
    assert (out["results"], out["empty"], out["received"]) == (1, 1, 0)


def test_production_waits_for_the_legal_review(conn):
    _ops(conn, "q1")
    p = Fake("serpapi", {"q1": [person("a")]})

    class Prod(S):
        env = "production"
    out = go(conn, [p], settings=Prod)
    assert (out["status"], out["reason"], p.calls) == ("SKIPPED", "LEGAL_REVIEW_PENDING", [])


def test_no_active_policy_skips_and_is_logged(conn):
    conn.execute(text("UPDATE search_ingest_policy SET status = 'RETIRED'"))
    out = go(conn, [Fake("serpapi")])
    assert (out["status"], out["reason"]) == ("SKIPPED", "NO_ACTIVE_POLICY")
    row = conn.execute(text("SELECT status, reason FROM search_run")).one()
    assert tuple(row) == ("SKIPPED", "NO_ACTIVE_POLICY")


def test_no_provider_skips(conn):
    assert go(conn, [])["reason"] == "NO_SEARCH_PROVIDER"


def test_a_second_run_at_the_same_time_skips(conn, engine):
    _ops(conn, "q1")
    with engine.connect() as other:
        otx = other.begin()
        other.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
        out = go(conn, [Fake("serpapi", {"q1": [person("a")]})])
        otx.rollback()
    assert (out["status"], out["reason"]) == ("SKIPPED", "ALREADY_RUNNING")


def test_one_failing_person_does_not_stop_the_others(conn, monkeypatch):
    from hellomyme.ingest import search_run as sr
    real = sr.receive

    def flaky(c, raw, **kw):
        if "카카오" in raw:
            raise RuntimeError("boom")
        return real(c, raw, **kw)
    monkeypatch.setattr(sr, "receive", flaky)
    _ops(conn, "q1")
    out = go(conn, [Fake("serpapi", {"q1": [person("a"), person("b", "카카오"), person("c")]})])
    assert (out["status"], out["received"], out["errors"]) == ("DONE", 2, 1)


def test_every_received_field_waits_for_a_person_even_with_a_known_school(conn):
    tv = conn.execute(text(
        """INSERT INTO taxonomy_version (taxonomy, version) VALUES ('INSTITUTION', 'search-run-test')
           ON CONFLICT (taxonomy, version) DO UPDATE SET version = EXCLUDED.version
           RETURNING taxonomy_version_id""")).scalar_one()
    conn.execute(text("INSERT INTO institution (name, taxonomy_version_id) VALUES ('검색대학교', :v)"),
                 {"v": tv})
    _ops(conn, "q1")
    edu = Result("https://kr.linkedin.com/in/e", "테스트e - 학생 | LinkedIn",
                 "학력: 검색대학교 · 검색대학교 컴퓨터학과 2015 - 2019")
    out = go(conn, [Fake("serpapi", {"q1": [edu, person("w")]})])
    assert out["received"] == 2
    rows = conn.execute(text(
        """SELECT p.status, count(*) FILTER (WHERE f.review_status <> 'PENDING'
                                              AND f.raw_value IS NOT NULL)
           FROM parse_run p JOIN extraction_field f USING (parse_run_id) GROUP BY p.parse_run_id, p.status"""
    )).all()
    assert len(rows) == 2 and all(tuple(r) == ("NEEDS_REVIEW", 0) for r in rows)


def test_per_provider_results_count_profiles_only(conn):
    _ops(conn, "q1")
    out = go(conn, [Fake("serpapi", {"q1": [
        person("a"), Result("https://www.linkedin.com/company/toss", "Toss | LinkedIn", "회사")]})])
    assert out["results"] == 1 and out["by_provider"]["serpapi"]["results"] == 1
