"""v1.4 work event role taxonomy + employment type; dated, time-agnostic career transitions.

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    DROP VIEW canonical_work_event;
    ALTER TABLE work_event
        ADD COLUMN role_taxonomy_node_id uuid REFERENCES taxonomy_node,
        ADD COLUMN employment_type text CHECK (employment_type IN
            ('FULL_TIME','PART_TIME','CONTRACT','INTERN','UNKNOWN'));
    CREATE INDEX work_event_role_node_idx ON work_event (role_taxonomy_node_id);
    CREATE INDEX work_event_current_idx ON work_event (person_id) WHERE is_current;
    CREATE TRIGGER work_event_role_type BEFORE INSERT OR UPDATE OF role_taxonomy_node_id
        ON work_event FOR EACH ROW EXECUTE FUNCTION assert_taxonomy_type('role_taxonomy_node_id', 'ROLE');
    CREATE VIEW canonical_work_event AS
        SELECT w.* FROM work_event w
        WHERE w.retracted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM work_event n
                          WHERE n.supersedes_work_event_id = w.work_event_id);

    -- Transitions keep their dates so any as_of/lookback window can be applied at query time.
    ALTER TABLE career_transition
        ADD COLUMN transition_date   date,
        ADD COLUMN from_start_date   date,
        ADD COLUMN from_end_date     date,
        ADD COLUMN to_start_date     date,
        ADD COLUMN from_role_node_id uuid REFERENCES taxonomy_node,
        ADD COLUMN to_role_node_id   uuid REFERENCES taxonomy_node;
    CREATE INDEX career_transition_date_idx ON career_transition (logic_version, transition_date);
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX career_transition_date_idx;
    ALTER TABLE career_transition
        DROP COLUMN transition_date, DROP COLUMN from_start_date, DROP COLUMN from_end_date,
        DROP COLUMN to_start_date, DROP COLUMN from_role_node_id, DROP COLUMN to_role_node_id;
    DROP VIEW canonical_work_event;
    DROP TRIGGER work_event_role_type ON work_event;
    DROP INDEX work_event_current_idx;
    DROP INDEX work_event_role_node_idx;
    ALTER TABLE work_event DROP COLUMN role_taxonomy_node_id, DROP COLUMN employment_type;
    CREATE VIEW canonical_work_event AS
        SELECT w.* FROM work_event w
        WHERE w.retracted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM work_event n
                          WHERE n.supersedes_work_event_id = w.work_event_id);
    """)
