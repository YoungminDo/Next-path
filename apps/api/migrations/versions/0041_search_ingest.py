"""Search ingest (docs/12): public-profile snippets from search APIs, received for review as SEED.

- search_ingest_policy: how much one run may search; numbers are policy, not code. One ACTIVE.
- search_query: operator queries and the demand-based ones the planner adds (same table).
- search_run: one row per run with its counts; no result text is kept.
Every table enables RLS (migration 0025: nothing is served over the Supabase Data API).

Revision ID: 0041
Revises: 0040
"""
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE search_ingest_policy (
        search_ingest_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        version                 text NOT NULL UNIQUE,
        status                  text NOT NULL CHECK (status IN ('ACTIVE','RETIRED')),
        max_queries_per_run     integer NOT NULL CHECK (max_queries_per_run > 0),
        results_per_query       integer NOT NULL CHECK (results_per_query BETWEEN 1 AND 20),
        requery_after_days      integer NOT NULL CHECK (requery_after_days >= 0),
        demand_lookback_days    integer NOT NULL CHECK (demand_lookback_days > 0),
        max_consecutive_errors  integer NOT NULL CHECK (max_consecutive_errors > 0),
        created_at              timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX search_ingest_policy_one_active_uq ON search_ingest_policy ((true))
        WHERE status = 'ACTIVE';
    INSERT INTO search_ingest_policy (version, status, max_queries_per_run, results_per_query,
        requery_after_days, demand_lookback_days, max_consecutive_errors)
    VALUES ('search_v1', 'ACTIVE', 20, 10, 30, 30, 5);

    CREATE TABLE search_query (
        search_query_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        query_text      text NOT NULL UNIQUE,
        origin          text NOT NULL CHECK (origin IN ('OPERATOR','DEMAND')),
        status          text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','PAUSED')),
        institution_id  uuid REFERENCES institution,
        major_node_id   uuid REFERENCES taxonomy_node,
        last_run_at     timestamptz,
        last_provider   text CHECK (last_provider IN ('serpapi','brave')),
        created_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX search_query_due_idx ON search_query (origin, status, last_run_at);

    CREATE TABLE search_run (
        search_run_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        started_at     timestamptz NOT NULL DEFAULT now(),
        finished_at    timestamptz,
        status         text NOT NULL DEFAULT 'RUNNING'
                           CHECK (status IN ('RUNNING','DONE','FAILED','SKIPPED')),
        reason         text,
        queries        integer NOT NULL DEFAULT 0,
        results        integer NOT NULL DEFAULT 0,
        received       integer NOT NULL DEFAULT 0,
        replayed       integer NOT NULL DEFAULT 0,
        already_loaded integer NOT NULL DEFAULT 0,
        rejected       integer NOT NULL DEFAULT 0,
        empty          integer NOT NULL DEFAULT 0,
        errors         integer NOT NULL DEFAULT 0,
        by_provider    jsonb NOT NULL DEFAULT '{}'
    );

    ALTER TABLE search_ingest_policy ENABLE ROW LEVEL SECURITY;
    ALTER TABLE search_query ENABLE ROW LEVEL SECURITY;
    ALTER TABLE search_run ENABLE ROW LEVEL SECURITY;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE search_run; DROP TABLE search_query; DROP TABLE search_ingest_policy;")
