"""Search ingest planning (docs/12 §4). Each test runs in a transaction that is rolled back."""
import pytest
from sqlalchemy import text


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
