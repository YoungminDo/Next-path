"""Funnel events for the acquisition demand test: landing view, login click, result step views
and time spent, intent choice, and requests for schools that are not listed yet.

Revision ID: 0024
Revises: 0023
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

OLD = (
    "'career_input_started','career_input_completed','career_query_requested',"
    "'login_wall_viewed','signup_completed','career_map_viewed','filter_applied',"
    "'unlock_viewed','unlock_purchased','credit_purchased','mentor_viewed',"
    "'mentor_contact_clicked','mentor_order_created','career_updated','career_reconfirmed'"
)
NEW = OLD + (",'landing_viewed','login_clicked','result_step_viewed','result_left',"
             "'intent_selected','school_requested'")


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check CHECK (event_name IN ({NEW}));
    CREATE INDEX analytics_event_session_idx ON analytics.event (anonymous_session_id, occurred_at);
    """)


def downgrade() -> None:
    op.execute(f"""
    DROP INDEX analytics.analytics_event_session_idx;
    DELETE FROM analytics.event WHERE event_name NOT IN ({OLD});
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check CHECK (event_name IN ({OLD}));
    """)
