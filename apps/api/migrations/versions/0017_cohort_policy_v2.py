"""v1.4 adaptive cohort engine v2 policy: ordered fallback steps (time widening, taxonomy
broadening, dimension dropping, similarity) and stricter thresholds for demographic filters.

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE cohort_policy
        ADD COLUMN fallback_steps jsonb,
        ADD COLUMN demographic_min_n integer CHECK (demographic_min_n > 0),
        ADD COLUMN demographic_min_cell_n integer CHECK (demographic_min_cell_n > 0),
        ADD COLUMN top_n integer CHECK (top_n > 0);

    UPDATE cohort_policy SET status = 'RETIRED', effective_to = now() WHERE status = 'ACTIVE';
    INSERT INTO cohort_policy (version, min_exact_n, graduation_window_years, fallback_enabled,
                               similarity_fallback_k, max_fallback_level, dimension_fallback_order,
                               min_cell_n, fallback_steps, demographic_min_n,
                               demographic_min_cell_n, top_n, status)
    VALUES ('cohort_v2', 30, 2, true, 100, 3,
            '["graduation_year", "current_job_family", "institution_id"]', 5,
            '[{"step": "widen_time", "dimension": "graduation_year", "by_years": 2},
              {"step": "widen_time", "dimension": "admission_year", "by_years": 2},
              {"step": "broaden_taxonomy", "dimension": "major", "levels": 1},
              {"step": "drop", "dimension": "gender"},
              {"step": "drop", "dimension": "admission_year"},
              {"step": "drop", "dimension": "graduation_year"},
              {"step": "drop", "dimension": "institution"},
              {"step": "similarity_top_k"}]',
            50, 10, 8, 'ACTIVE');
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM cohort_policy WHERE version = 'cohort_v2';
    UPDATE cohort_policy SET status = 'ACTIVE', effective_to = NULL WHERE version = 'cohort_v1';
    ALTER TABLE cohort_policy
        DROP COLUMN fallback_steps, DROP COLUMN demographic_min_n,
        DROP COLUMN demographic_min_cell_n, DROP COLUMN top_n;
    """)
