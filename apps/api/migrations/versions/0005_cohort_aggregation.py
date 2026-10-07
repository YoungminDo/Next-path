"""Cohort/transition aggregation + COHORT_POLICY + scoring policies + cohort result audit.

Career transitions are derived from WORK_EVENT by versioned logic (logic_version) and stored
in aggregation tables; they are never edited by hand.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

POLICY_STATUS = "status text NOT NULL CHECK (status IN ('DRAFT','ACTIVE','RETIRED'))"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE cohort_policy (
        cohort_policy_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        version                 text NOT NULL UNIQUE,
        min_exact_n             integer NOT NULL CHECK (min_exact_n > 0),
        graduation_window_years integer NOT NULL CHECK (graduation_window_years >= 0),
        fallback_enabled        boolean NOT NULL,
        similarity_fallback_k   integer NOT NULL CHECK (similarity_fallback_k > 0),
        max_fallback_level      integer NOT NULL CHECK (max_fallback_level BETWEEN 0 AND 3),
        -- Dimensions dropped one at a time at fallback level 2, in this order.
        dimension_fallback_order jsonb NOT NULL,
        -- Minimum persons behind any single disclosed category (cell-level suppression).
        min_cell_n              integer NOT NULL CHECK (min_cell_n > 0),
        effective_from          timestamptz NOT NULL DEFAULT now(),
        effective_to            timestamptz,
        {POLICY_STATUS},
        created_at              timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX cohort_policy_one_active_uq ON cohort_policy ((true))
        WHERE status = 'ACTIVE';

    CREATE TABLE scoring_policy (
        scoring_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        policy_type       text NOT NULL CHECK (policy_type IN ('CAREER_SIMILARITY','MENTOR_RANKING')),
        version           text NOT NULL,
        weights           jsonb NOT NULL,
        params            jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        {POLICY_STATUS},
        created_at        timestamptz NOT NULL DEFAULT now(),
        UNIQUE (policy_type, version)
    );
    CREATE UNIQUE INDEX scoring_policy_one_active_uq ON scoring_policy (policy_type)
        WHERE status = 'ACTIVE';

    -- Default configuration rows (values are data, not application constants).
    INSERT INTO cohort_policy (version, min_exact_n, graduation_window_years, fallback_enabled,
                               similarity_fallback_k, max_fallback_level,
                               dimension_fallback_order, min_cell_n, status)
    VALUES ('cohort_v1', 30, 2, true, 100, 3,
            '["graduation_year", "current_job_family", "institution_id"]', 5, 'ACTIVE');

    INSERT INTO scoring_policy (policy_type, version, weights, params, status) VALUES
    ('CAREER_SIMILARITY', 'similarity_v0',
     '{{"institution": 2.0, "major": 2.0, "graduation_year": 1.0, "current_job_family": 2.0,
       "current_role": 1.5, "current_industry": 1.0, "current_company_size": 0.5,
       "current_event_type": 0.5, "career_sequence": 1.5, "stage": 0.5}}',
     '{{"graduation_year_decay_years": 5, "major_family_partial": 0.5,
       "bucket_thresholds": {{"VERY_SIMILAR": 0.75, "SIMILAR": 0.5}}}}',
     'ACTIVE'),
    ('MENTOR_RANKING', 'mentor_v0',
     '{{"career_similarity": 3.0, "target_path_relevance": 4.0, "recency": 1.0,
       "availability": 1.0, "rating": 1.0, "response_rate": 1.0, "completed_transactions": 0.5}}',
     '{{"recency_half_life_years": 3, "completed_transactions_saturation": 20}}',
     'ACTIVE');

    CREATE TABLE aggregation_run (
        aggregation_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        logic_version      text NOT NULL,
        as_of_date         date NOT NULL,
        status             text NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
        stats              jsonb,
        started_at         timestamptz NOT NULL DEFAULT now(),
        finished_at        timestamptz
    );

    CREATE TABLE career_person_snapshot (
        logic_version            text NOT NULL,
        person_id                uuid NOT NULL REFERENCES person ON DELETE CASCADE,
        origin_layer             text NOT NULL,
        derived_stage            text NOT NULL,
        institution_id           uuid REFERENCES institution,
        major_id                 uuid REFERENCES major,
        major_family             text,
        graduation_year          smallint,
        current_work_event_id    uuid REFERENCES work_event ON DELETE SET NULL,
        current_event_type       text,
        current_role_id          uuid REFERENCES role,
        current_job_family       text,
        current_organization_id  uuid REFERENCES organization,
        current_industry         text,
        current_company_size_band text,
        job_family_sequence      text[] NOT NULL,
        event_type_sequence      text[] NOT NULL,
        primary_event_count      integer NOT NULL,
        parallel_event_count     integer NOT NULL,
        computed_at              timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (logic_version, person_id)
    );
    CREATE INDEX career_person_snapshot_cohort_idx
        ON career_person_snapshot (logic_version, origin_layer, institution_id, major_id,
                                   graduation_year);
    CREATE INDEX career_person_snapshot_family_idx
        ON career_person_snapshot (logic_version, major_family, current_job_family);

    CREATE TABLE career_transition (
        career_transition_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        logic_version          text NOT NULL,
        person_id              uuid NOT NULL REFERENCES person ON DELETE CASCADE,
        origin_layer           text NOT NULL,
        -- NULL from_work_event_id = education -> first career event.
        from_work_event_id     uuid REFERENCES work_event ON DELETE CASCADE,
        to_work_event_id       uuid NOT NULL REFERENCES work_event ON DELETE CASCADE,
        from_event_type        text,
        from_role_id           uuid REFERENCES role,
        from_job_family        text,
        from_organization_id   uuid REFERENCES organization,
        from_industry          text,
        from_company_size_band text,
        to_event_type          text NOT NULL,
        to_role_id             uuid REFERENCES role,
        to_job_family          text,
        to_organization_id     uuid REFERENCES organization,
        to_industry            text,
        to_company_size_band   text,
        to_org_is_placeholder  boolean,
        from_tenure_months     integer,
        gap_months             integer,
        overlap_months         integer,
        years_since_graduation smallint,
        transition_index       integer NOT NULL,
        computed_at            timestamptz NOT NULL DEFAULT now(),
        UNIQUE NULLS NOT DISTINCT (logic_version, person_id, from_work_event_id, to_work_event_id)
    );
    CREATE INDEX career_transition_from_idx
        ON career_transition (logic_version, from_job_family, origin_layer);
    CREATE INDEX career_transition_person_idx ON career_transition (logic_version, person_id);

    -- Every cohort result keeps exact_n / effective_n / fallback_level / policy version.
    CREATE TABLE cohort_result_log (
        cohort_result_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        cohort_policy_id      uuid NOT NULL REFERENCES cohort_policy,
        cohort_policy_version text NOT NULL,
        logic_version         text NOT NULL,
        request_dimensions    jsonb NOT NULL,
        applied_dimensions    jsonb NOT NULL,
        data_layers           text[] NOT NULL,
        fallback_level        integer NOT NULL,
        exact_n               integer NOT NULL,
        effective_n           integer NOT NULL,
        suppressed            boolean NOT NULL,
        account_id            uuid REFERENCES account,
        anonymous_draft_id    uuid,
        created_at            timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX cohort_result_log_created_idx ON cohort_result_log (created_at);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE cohort_result_log;
    DROP TABLE career_transition;
    DROP TABLE career_person_snapshot;
    DROP TABLE aggregation_run;
    DROP TABLE scoring_policy;
    DROP TABLE cohort_policy;
    """)
