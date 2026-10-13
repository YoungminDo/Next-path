"""first_employment_for: the same first-employment rule as first_employment_all, for given people.

first_employment_all computes everyone's first job; a cohort query only needs its own people,
and the fallback steps ask up to eight times per request. With 50k people that was ~300 ms a
call. This variant takes the person ids and is otherwise the identical definition (one rule,
one definition: change both together).

Revision ID: 0034
Revises: 0033
"""
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION first_employment_for(p_rule text, p_as_of date, p_people uuid[])
    RETURNS TABLE (person_id uuid, work_event_id uuid, start_date date, basis text,
                   rule_version text)
    LANGUAGE sql STABLE AS $$
        WITH r AS (SELECT * FROM first_employment_rule WHERE version = p_rule),
        grad AS (SELECT e.person_id, max(e.graduation_year) AS gy
                   FROM canonical_education e WHERE e.person_id = ANY (p_people)
                  GROUP BY e.person_id),
        derived AS (
            SELECT DISTINCT ON (w.person_id) w.person_id, w.work_event_id, w.start_date
              FROM canonical_work_event w
              CROSS JOIN r
              LEFT JOIN grad g ON g.person_id = w.person_id
             WHERE w.person_id = ANY (p_people)
               AND w.event_type = ANY (r.included_event_types)
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
         WHERE p.person_id = ANY (p_people)
           AND p.reported_first_employment_year IS NOT NULL AND p.deleted_at IS NULL
           AND make_date(p.reported_first_employment_year, 1, 1) <= p_as_of
           AND NOT EXISTS (SELECT 1 FROM derived d WHERE d.person_id = p.person_id)
           AND EXISTS (SELECT 1 FROM r)
    $$;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION first_employment_for(text, date, uuid[])")
