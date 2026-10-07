"""v1.4 acquisition intent: what a user wants next, captured before login and kept as
explicit INTENT_EVENTs after the anonymous draft is merged.

Revision ID: 0018
Revises: 0017
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE intent_event
        ADD COLUMN target_kind text CHECK (target_kind IN
            ('ROLE','INDUSTRY','ORGANIZATION','EVENT_TYPE','UNDECIDED')),
        ADD COLUMN target_taxonomy_node_id uuid REFERENCES taxonomy_node,
        ADD COLUMN target_organization_id uuid REFERENCES organization,
        ADD COLUMN target_event_type text,
        ADD COLUMN source_surface text,
        ADD COLUMN anonymous_draft_id uuid REFERENCES anonymous_draft ON DELETE SET NULL,
        ADD COLUMN captured_at timestamptz;
    -- One explicit intent per draft step: replaying the merge never duplicates it.
    CREATE UNIQUE INDEX intent_event_draft_step_uq
        ON intent_event (anonymous_draft_id, source_surface, signal_type)
        WHERE anonymous_draft_id IS NOT NULL;
    CREATE INDEX intent_event_target_node_idx ON intent_event (target_taxonomy_node_id);

    COMMENT ON TABLE career_person_snapshot IS
        'deprecated in v1.4: pinned to one as-of date; superseded by query-time evaluation';
    """)


def downgrade() -> None:
    op.execute("""
    COMMENT ON TABLE career_person_snapshot IS NULL;
    DROP INDEX intent_event_target_node_idx;
    DROP INDEX intent_event_draft_step_uq;
    ALTER TABLE intent_event
        DROP COLUMN target_kind, DROP COLUMN target_taxonomy_node_id,
        DROP COLUMN target_organization_id, DROP COLUMN target_event_type,
        DROP COLUMN source_surface, DROP COLUMN anonymous_draft_id, DROP COLUMN captured_at;
    """)
