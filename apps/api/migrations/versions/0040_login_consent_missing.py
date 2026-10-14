"""analytics.event: login_consent_missing — the Kakao button pressed before the consent box was
ticked (the button stays pressable and points to the box; docs/10 §로그인 동의).

Revision ID: 0040
Revises: 0039
"""
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

OLD_EVENTS = (
    "'career_input_started','career_input_completed','career_query_requested',"
    "'login_wall_viewed','signup_completed','career_map_viewed','filter_applied',"
    "'unlock_viewed','unlock_purchased','credit_purchased','mentor_viewed',"
    "'mentor_contact_clicked','mentor_order_created','career_updated','career_reconfirmed',"
    "'landing_viewed','login_clicked','result_step_viewed','result_left',"
    "'intent_selected','school_requested',"
    "'desired_role_selected','interview_step_viewed','interview_skipped',"
    "'interview_code_sent','interview_submitted','interview_withdrawn',"
    "'import_viewed','import_uploaded','import_parsed','import_confirmed',"
    "'payment_started','payment_failed',"
    "'checkout_viewed','checkout_completed','checkout_cancelled'"
)
NEW_EVENTS = OLD_EVENTS + ",'login_consent_missing'"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({NEW_EVENTS}));
    """)


def downgrade() -> None:
    op.execute(f"""
    DELETE FROM analytics.event WHERE event_name = 'login_consent_missing';
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({OLD_EVENTS}));
    """)
