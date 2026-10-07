"""Analytics (separate schema from canonical career data) + privacy/audit hardening.

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

EVENT_NAMES = (
    "'career_input_started','career_input_completed','career_query_requested',"
    "'login_wall_viewed','signup_completed','career_map_viewed','filter_applied',"
    "'unlock_viewed','unlock_purchased','credit_purchased','mentor_viewed',"
    "'mentor_contact_clicked','mentor_order_created','career_updated','career_reconfirmed'"
)


def upgrade() -> None:
    op.execute(f"""
    CREATE SCHEMA analytics;

    CREATE TABLE analytics.event (
        event_id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        event_name           text NOT NULL CHECK (event_name IN ({EVENT_NAMES})),
        account_id           uuid,
        anonymous_session_id text,
        properties           jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        occurred_at          timestamptz NOT NULL,
        received_at          timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX analytics_event_name_idx ON analytics.event (event_name, occurred_at);

    CREATE TABLE analytics.filter_event (
        filter_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id      uuid,
        filters         jsonb NOT NULL,
        cohort_result_id uuid,
        created_at      timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE deletion_request (
        deletion_request_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id          uuid NOT NULL REFERENCES account,
        status              text NOT NULL CHECK (status IN ('REQUESTED','COMPLETED','REJECTED')),
        requested_at        timestamptz NOT NULL DEFAULT now(),
        completed_at        timestamptz,
        detail              jsonb NOT NULL DEFAULT '{{}}'::jsonb
    );

    CREATE TABLE audit_log (
        audit_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        actor_account_id uuid,
        action           text NOT NULL,
        entity_type      text NOT NULL,
        entity_id        text,
        detail           jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        created_at       timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX audit_log_entity_idx ON audit_log (entity_type, entity_id);
    CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE audit_log;
    DROP TABLE deletion_request;
    DROP SCHEMA analytics CASCADE;
    """)
