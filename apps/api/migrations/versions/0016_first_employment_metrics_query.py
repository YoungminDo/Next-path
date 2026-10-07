"""v1.4 versioned first-employment rule, target metric registry, reusable career query.

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

METRICS = [
    # code, anchor, result_kind, result_taxonomy_type, status
    ("FIRST_ROLE_DISTRIBUTION", "FIRST_EMPLOYMENT_START", "TAXONOMY_NODE", "ROLE", "ACTIVE"),
    ("FIRST_INDUSTRY_DISTRIBUTION", "FIRST_EMPLOYMENT_START", "TAXONOMY_NODE", "INDUSTRY", "ACTIVE"),
    ("CURRENT_ROLE_DISTRIBUTION", "ACTIVE_AT_AS_OF", "TAXONOMY_NODE", "ROLE", "ACTIVE"),
    ("CURRENT_INDUSTRY_DISTRIBUTION", "ACTIVE_AT_AS_OF", "TAXONOMY_NODE", "INDUSTRY", "ACTIVE"),
    ("TIME_TO_FIRST_JOB", "FIRST_EMPLOYMENT_START", "NUMERIC_BUCKET", None, "ACTIVE"),
    ("ROLE_DISTRIBUTION", "EVENT_START", "TAXONOMY_NODE", "ROLE", "DRAFT"),
    ("ORGANIZATION_DISTRIBUTION", "EVENT_START", "ORGANIZATION", None, "DRAFT"),
    ("NEXT_ROLE_DISTRIBUTION", "TRANSITION_DATE", "TAXONOMY_NODE", "ROLE", "DRAFT"),
    ("NEXT_ORGANIZATION_DISTRIBUTION", "TRANSITION_DATE", "ORGANIZATION", None, "DRAFT"),
    ("ROLE_TRANSITION", "TRANSITION_DATE", "TRANSITION", "ROLE", "DRAFT"),
    ("INDUSTRY_TRANSITION", "TRANSITION_DATE", "TRANSITION", "INDUSTRY", "DRAFT"),
    ("TENURE_DISTRIBUTION", "EVENT_END", "NUMERIC_BUCKET", None, "DRAFT"),
    ("CAREER_PATH", "ACTIVE_AT_AS_OF", "PATH", "ROLE", "DRAFT"),
]


def upgrade() -> None:
    metric_rows = ",\n".join(
        f"('{c}', '{a}', '{k}', {('NULL' if t is None else repr(t))}, 'metric_v1', '{s}')"
        for c, a, k, t, s in METRICS
    )
    op.execute(f"""
    CREATE TABLE first_employment_rule (
        first_employment_rule_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        version                  text NOT NULL UNIQUE,
        included_event_types     text[] NOT NULL,
        excluded_employment_types text[] NOT NULL DEFAULT '{{}}',
        -- NULL = no constraint. Offset is from 1 Jan of the latest graduation year; persons
        -- without a graduation year are not excluded by it (unknown is not evidence).
        min_start_offset_months_from_graduation integer,
        description              text,
        status                   text NOT NULL CHECK (status IN ('DRAFT','ACTIVE','RETIRED')),
        created_at               timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX first_employment_rule_one_active_uq ON first_employment_rule ((true))
        WHERE status = 'ACTIVE';
    INSERT INTO first_employment_rule (version, included_event_types, excluded_employment_types,
                                       description, status)
    VALUES ('fe_v1', ARRAY['EMPLOYMENT'], ARRAY['INTERN'],
            'Earliest canonical EMPLOYMENT event that is not an internship. Startup, freelance, '
            'side business, project, military and study events never qualify.', 'ACTIVE');

    -- The single definition of "first qualifying employment" (spec §15). Every metric uses it.
    CREATE FUNCTION first_employment_all(p_rule text, p_as_of date)
    RETURNS TABLE (person_id uuid, work_event_id uuid, start_date date, basis text,
                   rule_version text)
    LANGUAGE sql STABLE AS $$
        WITH r AS (SELECT * FROM first_employment_rule WHERE version = p_rule),
        grad AS (SELECT e.person_id, max(e.graduation_year) AS gy
                   FROM canonical_education e GROUP BY e.person_id),
        derived AS (
            SELECT DISTINCT ON (w.person_id) w.person_id, w.work_event_id, w.start_date
              FROM canonical_work_event w
              CROSS JOIN r
              LEFT JOIN grad g ON g.person_id = w.person_id
             WHERE w.event_type = ANY (r.included_event_types)
               AND (w.employment_type IS NULL
                    OR NOT (w.employment_type = ANY (r.excluded_employment_types)))
               AND w.start_date IS NOT NULL AND w.start_date <= p_as_of
               AND (r.min_start_offset_months_from_graduation IS NULL OR g.gy IS NULL
                    OR w.start_date >= (make_date(g.gy, 1, 1)
                       + make_interval(months => r.min_start_offset_months_from_graduation))::date)
             ORDER BY w.person_id, w.start_date, w.work_event_id)
        SELECT d.person_id, d.work_event_id, d.start_date, 'DERIVED'::text, p_rule FROM derived d
        UNION ALL
        SELECT p.person_id, NULL::uuid, make_date(p.reported_first_employment_year, 1, 1),
               'REPORTED'::text, p_rule
          FROM person p
         WHERE p.reported_first_employment_year IS NOT NULL AND p.deleted_at IS NULL
           AND make_date(p.reported_first_employment_year, 1, 1) <= p_as_of
           AND NOT EXISTS (SELECT 1 FROM derived d WHERE d.person_id = p.person_id)
           AND EXISTS (SELECT 1 FROM r)
    $$;

    CREATE TABLE metric_definition (
        metric_code            text PRIMARY KEY,
        anchor                 text NOT NULL CHECK (anchor IN
                                   ('FIRST_EMPLOYMENT_START','ACTIVE_AT_AS_OF','EVENT_START',
                                    'EVENT_END','TRANSITION_DATE')),
        result_kind            text NOT NULL CHECK (result_kind IN
                                   ('TAXONOMY_NODE','ORGANIZATION','NUMERIC_BUCKET','TRANSITION','PATH')),
        result_taxonomy_type   text CHECK (result_taxonomy_type IN ('ROLE','INDUSTRY','MAJOR')),
        implementation_version text NOT NULL,
        status                 text NOT NULL CHECK (status IN ('DRAFT','ACTIVE','RETIRED')),
        created_at             timestamptz NOT NULL DEFAULT now()
    );
    INSERT INTO metric_definition (metric_code, anchor, result_kind, result_taxonomy_type,
                                   implementation_version, status) VALUES
    {metric_rows};

    -- Persisted only when useful: unlock entitlement keys, saved views, sharing, analytics.
    CREATE TABLE career_query (
        career_query_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        requester_account_id  uuid REFERENCES account,
        query_hash            text NOT NULL,
        query                 jsonb NOT NULL,
        target_metric         text NOT NULL REFERENCES metric_definition,
        as_of_date            date NOT NULL,
        lookback              text NOT NULL,
        taxonomy_version      text,
        cohort_policy_version text,
        purpose               text NOT NULL CHECK (purpose IN ('UNLOCK','SAVED_VIEW','SHARE','ANALYTICS')),
        created_at            timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX career_query_hash_idx ON career_query (query_hash);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE career_query;
    DROP TABLE metric_definition;
    DROP FUNCTION first_employment_all(text, date);
    DROP TABLE first_employment_rule;
    """)
