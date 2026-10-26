"""First-pass fit analysis and coaching requests (/alert, docs/10 §공고 알림 랜딩).

- fit_analysis: one row per run (append-only). What the model said about a member's confirmed
  records: a summary, three fitting roles with a reason each, and what to strengthen. The input is
  the confirmed rows only (no file, no name or contact); sending them to Anthropic is an overseas
  transfer, so the consent wording version is kept on the row (as on import_attempt, 0030).
- coaching_product: the two coaching offers and their prices (prices live in a table, not in code).
- coaching_request: a member asked for coaching; the team contacts them by phone. The number has its
  own consent, COACHING_CONTACT (purpose: coaching contact; item: mobile number; until a year after
  the request or until cancelled). Cancelling clears the number.
- analytics.event gains fit_step_viewed, fit_requested, coaching_requested, coaching_cancelled.

Revision ID: 0044
Revises: 0043
"""
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

OLD = ("'TERMS','PRIVACY_PROCESSING','CAREER_DATA_AGGREGATION','MENTOR_PUBLIC_PROFILE',"
       "'EXTERNAL_IMPORT','MARKETING','INTERVIEW_CONTACT','JOB_ALERT_CONTACT'")
NEW = OLD + ",'COACHING_CONTACT'"

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
    "'alert_step_viewed','alert_code_sent','alert_subscribed','alert_skipped','alert_withdrawn'"
)
NEW_EVENTS = OLD_EVENTS + ",'fit_step_viewed','fit_requested','coaching_requested','coaching_cancelled'"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE data_consent DROP CONSTRAINT data_consent_consent_type_check;
    ALTER TABLE data_consent ADD CONSTRAINT data_consent_consent_type_check
        CHECK (consent_type IN ({NEW}));
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({NEW_EVENTS}));

    CREATE TABLE fit_analysis (
        analysis_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id           uuid NOT NULL REFERENCES account ON DELETE CASCADE,
        consent_text_version text NOT NULL,
        input_hash           text NOT NULL,
        model                text NOT NULL,
        -- PENDING is written before anything is sent (the record of the transfer consent).
        outcome              text NOT NULL CHECK (outcome IN ('PENDING', 'DONE', 'FAILED', 'REFUSED')),
        result               jsonb,
        input_tokens         integer,
        output_tokens        integer,
        failure_reason       text,
        created_at           timestamptz NOT NULL DEFAULT now(),
        CHECK ((outcome = 'DONE') = (result IS NOT NULL))
    );
    CREATE INDEX fit_analysis_account_idx ON fit_analysis (account_id, created_at);
    ALTER TABLE fit_analysis ENABLE ROW LEVEL SECURITY;

    CREATE TABLE coaching_product (
        sku        text PRIMARY KEY,
        name       text NOT NULL,
        amount_krw integer NOT NULL CHECK (amount_krw > 0),
        sort_order integer NOT NULL,
        status     text NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED'))
    );
    INSERT INTO coaching_product (sku, name, amount_krw, sort_order, status) VALUES
        ('COACHING_ONCE', '1회 첨삭', 59000, 1, 'ACTIVE'),
        ('COACHING_UNTIL_DEADLINE', '마감까지 무제한 첨삭', 99000, 2, 'ACTIVE');
    ALTER TABLE coaching_product ENABLE ROW LEVEL SECURITY;

    CREATE TABLE coaching_request (
        request_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id           uuid NOT NULL REFERENCES account ON DELETE CASCADE,
        sku                  text NOT NULL REFERENCES coaching_product,
        amount_krw           integer NOT NULL CHECK (amount_krw > 0),
        analysis_id          uuid REFERENCES fit_analysis,
        phone_e164           text CHECK (phone_e164 ~ '^\\+[1-9][0-9]{{7,14}}$'),
        consent_id           uuid NOT NULL REFERENCES data_consent,
        consent_text_version text NOT NULL,
        requested_at         timestamptz NOT NULL DEFAULT now(),
        cancelled_at         timestamptz,
        CHECK ((cancelled_at IS NULL) = (phone_e164 IS NOT NULL))
    );
    CREATE INDEX coaching_request_account_idx ON coaching_request (account_id, requested_at);
    ALTER TABLE coaching_request ENABLE ROW LEVEL SECURITY;
    """)


def downgrade() -> None:
    op.execute(f"""
    DROP TABLE coaching_request;
    DROP TABLE coaching_product;
    DROP TABLE fit_analysis;
    DELETE FROM analytics.event WHERE event_name IN ('fit_step_viewed','fit_requested',
        'coaching_requested','coaching_cancelled');
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({OLD_EVENTS}));
    DELETE FROM data_consent WHERE consent_type = 'COACHING_CONTACT';
    ALTER TABLE data_consent DROP CONSTRAINT data_consent_consent_type_check;
    ALTER TABLE data_consent ADD CONSTRAINT data_consent_consent_type_check
        CHECK (consent_type IN ({OLD}));
    """)
