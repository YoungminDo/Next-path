"""Job-alert opt-in (/alert, docs/10 §공고 알림 랜딩): a member's phone number for posting alerts,
kept only with its own consent.

- data_consent gains JOB_ALERT_CONTACT (purpose: a text when a matching job posting opens; item:
  mobile number; kept until a year after consent or until withdrawn). Grant and withdrawal are both
  rows, so the history stays. Coaching or event news is advertising and stays under MARKETING, a
  separate optional consent (정보통신망법 §50).
- job_alert_contact: one row per account (ACCOUNT, not PERSON), the same shape as interview_contact.
  Withdrawal clears the number and sets withdrawn_at. Code checks reuse phone_verification (0027).
- analytics.event gains alert_step_viewed, alert_code_sent, alert_subscribed, alert_skipped,
  alert_withdrawn.

Revision ID: 0043
Revises: 0042
"""
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

OLD = ("'TERMS','PRIVACY_PROCESSING','CAREER_DATA_AGGREGATION','MENTOR_PUBLIC_PROFILE',"
       "'EXTERNAL_IMPORT','MARKETING','INTERVIEW_CONTACT'")
NEW = OLD + ",'JOB_ALERT_CONTACT'"

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
    "'login_consent_missing'"
)
NEW_EVENTS = (OLD_EVENTS + ",'alert_step_viewed','alert_code_sent','alert_subscribed',"
              "'alert_skipped','alert_withdrawn'")


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE data_consent DROP CONSTRAINT data_consent_consent_type_check;
    ALTER TABLE data_consent ADD CONSTRAINT data_consent_consent_type_check
        CHECK (consent_type IN ({NEW}));
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({NEW_EVENTS}));

    CREATE TABLE job_alert_contact (
        account_id           uuid PRIMARY KEY REFERENCES account ON DELETE CASCADE,
        phone_e164           text CHECK (phone_e164 ~ '^\\+[1-9][0-9]{{7,14}}$'),
        phone_verified_at    timestamptz,
        consent_id           uuid NOT NULL REFERENCES data_consent,
        consent_text_version text NOT NULL,
        consented_at         timestamptz NOT NULL,
        withdrawn_at         timestamptz,
        created_at           timestamptz NOT NULL DEFAULT now(),
        updated_at           timestamptz NOT NULL DEFAULT now(),
        CHECK ((withdrawn_at IS NULL) = (phone_e164 IS NOT NULL)),
        CHECK (phone_verified_at IS NULL OR phone_e164 IS NOT NULL)
    );
    CREATE TRIGGER job_alert_contact_updated_at BEFORE UPDATE ON job_alert_contact
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    ALTER TABLE job_alert_contact ENABLE ROW LEVEL SECURITY;
    """)


def downgrade() -> None:
    op.execute(f"""
    DROP TABLE job_alert_contact;
    DELETE FROM analytics.event WHERE event_name IN ('alert_step_viewed','alert_code_sent',
        'alert_subscribed','alert_skipped','alert_withdrawn');
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({OLD_EVENTS}));
    DELETE FROM data_consent WHERE consent_type = 'JOB_ALERT_CONTACT';
    ALTER TABLE data_consent DROP CONSTRAINT data_consent_consent_type_check;
    ALTER TABLE data_consent ADD CONSTRAINT data_consent_consent_type_check
        CHECK (consent_type IN ({OLD}));
    """)
