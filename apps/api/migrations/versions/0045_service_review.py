"""Members' own reviews of the /alert service (docs/10 §공고 알림 랜딩, 이용 후기).

- service_review: what a member wrote after using a step (FIT: the first-pass analysis; ALERT: a
  job alert). Kept as written: the team never edits it, it only approves or hides it. Showing it on
  the landing is optional and has its own consent, REVIEW_PUBLISH (purpose: show the text on the
  service page; item: the text and the step it was written after; until withdrawn). The page shows
  no name or account. Deleting it clears the text at once.
- service_review_decision: the team's approve/hide decisions, append-only; the latest one counts.
  Only approved, publish-consented, not-deleted reviews are shown, and only once at least five are.
- analytics.event gains review_viewed, review_submitted, review_deleted.

Revision ID: 0045
Revises: 0044
"""
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

OLD = ("'TERMS','PRIVACY_PROCESSING','CAREER_DATA_AGGREGATION','MENTOR_PUBLIC_PROFILE',"
       "'EXTERNAL_IMPORT','MARKETING','INTERVIEW_CONTACT','JOB_ALERT_CONTACT','COACHING_CONTACT'")
NEW = OLD + ",'REVIEW_PUBLISH'"

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
    "'checkout_viewed','checkout_completed','checkout_cancelled',"
    "'login_consent_missing',"
    "'alert_step_viewed','alert_code_sent','alert_subscribed','alert_skipped','alert_withdrawn',"
    "'fit_step_viewed','fit_requested','coaching_requested','coaching_cancelled'"
)
NEW_EVENTS = OLD_EVENTS + ",'review_viewed','review_submitted','review_deleted'"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE data_consent DROP CONSTRAINT data_consent_consent_type_check;
    ALTER TABLE data_consent ADD CONSTRAINT data_consent_consent_type_check
        CHECK (consent_type IN ({NEW}));
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({NEW_EVENTS}));

    CREATE TABLE service_review (
        review_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id           uuid NOT NULL REFERENCES account ON DELETE CASCADE,
        surface              text NOT NULL CHECK (surface IN ('FIT', 'ALERT')),
        body                 text CHECK (char_length(body) BETWEEN 10 AND 300),
        publish              boolean NOT NULL,
        consent_id           uuid REFERENCES data_consent,
        consent_text_version text,
        created_at           timestamptz NOT NULL DEFAULT now(),
        deleted_at           timestamptz,
        CHECK ((deleted_at IS NULL) = (body IS NOT NULL)),
        CHECK (NOT publish OR (consent_id IS NOT NULL AND consent_text_version IS NOT NULL))
    );
    CREATE INDEX service_review_account_idx ON service_review (account_id, created_at);
    ALTER TABLE service_review ENABLE ROW LEVEL SECURITY;

    CREATE TABLE service_review_decision (
        decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        review_id   uuid NOT NULL REFERENCES service_review ON DELETE CASCADE,
        decision    text NOT NULL CHECK (decision IN ('APPROVED', 'HIDDEN')),
        decided_by  uuid NOT NULL REFERENCES account,
        decided_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX service_review_decision_idx ON service_review_decision (review_id, decided_at);
    ALTER TABLE service_review_decision ENABLE ROW LEVEL SECURITY;
    """)


def downgrade() -> None:
    op.execute(f"""
    DROP TABLE service_review_decision;
    DROP TABLE service_review;
    DELETE FROM analytics.event WHERE event_name IN ('review_viewed','review_submitted',
        'review_deleted');
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({OLD_EVENTS}));
    DELETE FROM data_consent WHERE consent_type = 'REVIEW_PUBLISH';
    ALTER TABLE data_consent DROP CONSTRAINT data_consent_consent_type_check;
    ALTER TABLE data_consent ADD CONSTRAINT data_consent_consent_type_check
        CHECK (consent_type IN ({OLD}));
    """)
