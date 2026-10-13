"""Paid cards (owner decision 2026-10-13): one card free, one 튜브 as a sign-up gift, then
990원 a card through Toss Payments (docs/10 §결과 카드와 결제).

- reward_policy: reward_v1 retired; reward_v2 gives SIGNUP 1 튜브 and nothing else.
- pricing_policy: CARD_1 = 990원 for 1 튜브 (the first active price row).
- payment_order: one row per checkout. Amount and 튜브 are fixed when the order is made, the
  payment is confirmed server-side with Toss before anything is credited, and a paid order
  credits once (ledger key purchase:<order_id>). No card numbers are stored.
- analytics.event: payment_started, payment_failed ('credit_purchased' marks the paid ones).

Revision ID: 0037
Revises: 0036
"""
from alembic import op

revision = "0037"
down_revision = "0036"
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
    "'import_viewed','import_uploaded','import_parsed','import_confirmed'"
)
NEW_EVENTS = OLD_EVENTS + ",'payment_started','payment_failed'"


def upgrade() -> None:
    op.execute(f"""
    UPDATE reward_policy SET status = 'RETIRED', effective_to = now()
     WHERE version = 'reward_v1' AND status = 'ACTIVE';
    INSERT INTO reward_policy (action_type, reward_tube, max_occurrences, cooldown_seconds,
                               version, status)
    VALUES ('SIGNUP', 1, 1, NULL, 'reward_v2', 'ACTIVE');

    INSERT INTO pricing_policy (sku, amount_krw, credit_amount, version, status)
    VALUES ('CARD_1', 990, 1, 'pricing_v1', 'ACTIVE');

    CREATE TABLE payment_order (
        order_id          text PRIMARY KEY CHECK (order_id ~ '^[A-Za-z0-9_=-]{{6,64}}$'),
        account_id        uuid NOT NULL REFERENCES account,
        provider          text NOT NULL DEFAULT 'TOSS' CHECK (provider IN ('TOSS')),
        pricing_policy_id uuid NOT NULL REFERENCES pricing_policy,
        sku               text NOT NULL,
        amount_krw        integer NOT NULL CHECK (amount_krw > 0),
        credit_amount     integer NOT NULL CHECK (credit_amount > 0),
        -- The card the person was opening; it opens right after the payment is confirmed.
        insight_type      text,
        status            text NOT NULL DEFAULT 'CREATED'
                              CHECK (status IN ('CREATED','PAID','FAILED')),
        payment_key       text UNIQUE,
        method            text,
        approved_at       timestamptz,
        receipt_url       text,
        failure_code      text,
        failure_message   text CHECK (length(failure_message) <= 300),
        ledger_id         uuid REFERENCES credit_ledger,
        internal          boolean NOT NULL DEFAULT false,
        created_at        timestamptz NOT NULL DEFAULT now(),
        updated_at        timestamptz NOT NULL DEFAULT now(),
        CHECK ((status = 'PAID') = (ledger_id IS NOT NULL AND payment_key IS NOT NULL))
    );
    CREATE INDEX payment_order_account_idx ON payment_order (account_id, created_at);
    ALTER TABLE payment_order ENABLE ROW LEVEL SECURITY;

    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({NEW_EVENTS}));
    """)


def downgrade() -> None:
    op.execute(f"""
    DELETE FROM analytics.event WHERE event_name IN ('payment_started','payment_failed');
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({OLD_EVENTS}));
    DROP TABLE payment_order;
    DELETE FROM pricing_policy WHERE sku = 'CARD_1' AND version = 'pricing_v1';
    UPDATE reward_policy SET status = 'RETIRED', effective_to = now() WHERE version = 'reward_v2';
    DELETE FROM reward_policy WHERE version = 'reward_v2'
       AND NOT EXISTS (SELECT 1 FROM credit_ledger l WHERE l.policy_id = reward_policy.reward_policy_id);
    UPDATE reward_policy SET status = 'ACTIVE', effective_to = NULL WHERE version = 'reward_v1';
    """)
