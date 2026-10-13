"""More result cards, and a payment-intent test while real payments are not connected
(owner decision 2026-10-13; docs/10 §결과 카드와 결제).

- unlock_policy: five more cards at 1 튜브 each. Students: the first job's company size, how long
  the first job lasted, what the cohort does now. Professionals: the company size after the role,
  how long people stayed in the role.
- reward_policy PAYMENT_TEST_GIFT: with no payment provider configured, the checkout is our own
  page and charges nothing; pressing "결제하기" is recorded and gifts 1 튜브 that opens the card
  (at most 10 per account). Retiring this row turns the test off; a Toss key replaces it.
- payment_order: provider TEST and status TEST_COMPLETED (the button was pressed, nothing charged).
- analytics.event: checkout_viewed, checkout_completed, checkout_cancelled.

Revision ID: 0038
Revises: 0037
"""
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

OLD_INSIGHTS = "'PATH_DEEP_DIVE','COMPANY_BREAKDOWN','REPRESENTATIVE_PATHS','TIMING_TENURE','SCHOOL_COMPARE'"
CARDS = ("FIRST_COMPANY_SIZE", "FIRST_JOB_TENURE", "ROLE_NOW", "NEXT_COMPANY_SIZE", "ROLE_TENURE")
NEW_INSIGHTS = OLD_INSIGHTS + "," + ",".join(f"'{c}'" for c in CARDS)

OLD_ACTIONS = (
    "'SIGNUP','EDUCATION_ADDED','CURRENT_ROLE_ADDED','PREVIOUS_CAREER_ADDED',"
    "'DECISION_RECORDED','CAREER_RECONFIRMED','OUTCOME_REPORTED',"
    "'INTENT_FOLLOWUP_ANSWERED','DECISION_RATIONALE_ADDED','HELP_COMPLETED','HELP_RATED'"
)
NEW_ACTIONS = OLD_ACTIONS + ",'PAYMENT_TEST_GIFT'"

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
    "'payment_started','payment_failed'"
)
NEW_EVENTS = OLD_EVENTS + ",'checkout_viewed','checkout_completed','checkout_cancelled'"


def upgrade() -> None:
    cards = ",\n        ".join(f"('{c}', 1, NULL, 'unlock_v1', 'ACTIVE')" for c in CARDS)
    op.execute(f"""
    ALTER TABLE unlock_policy DROP CONSTRAINT unlock_policy_insight_type_check;
    ALTER TABLE unlock_policy ADD CONSTRAINT unlock_policy_insight_type_check
        CHECK (insight_type IN ({NEW_INSIGHTS}));
    INSERT INTO unlock_policy (insight_type, cost_tube, entitlement_days, version, status) VALUES
        {cards};

    ALTER TABLE reward_policy DROP CONSTRAINT reward_policy_action_type_check;
    ALTER TABLE reward_policy ADD CONSTRAINT reward_policy_action_type_check
        CHECK (action_type IN ({NEW_ACTIONS}));
    INSERT INTO reward_policy (action_type, reward_tube, max_occurrences, cooldown_seconds,
                               version, status)
    VALUES ('PAYMENT_TEST_GIFT', 1, 10, NULL, 'reward_v2', 'ACTIVE');

    ALTER TABLE payment_order DROP CONSTRAINT payment_order_provider_check;
    ALTER TABLE payment_order ADD CONSTRAINT payment_order_provider_check
        CHECK (provider IN ('TOSS','TEST'));
    ALTER TABLE payment_order DROP CONSTRAINT payment_order_status_check;
    ALTER TABLE payment_order ADD CONSTRAINT payment_order_status_check
        CHECK (status IN ('CREATED','PAID','FAILED','TEST_COMPLETED'));
    ALTER TABLE payment_order ADD CONSTRAINT payment_order_test_check
        CHECK ((status = 'TEST_COMPLETED') <= (provider = 'TEST')
               AND (status = 'PAID') <= (provider = 'TOSS'));

    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({NEW_EVENTS}));
    """)


def downgrade() -> None:
    names = ",".join(f"'{c}'" for c in CARDS)
    op.execute(f"""
    DELETE FROM analytics.event
     WHERE event_name IN ('checkout_viewed','checkout_completed','checkout_cancelled');
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({OLD_EVENTS}));

    DELETE FROM payment_order WHERE provider = 'TEST';
    ALTER TABLE payment_order DROP CONSTRAINT payment_order_test_check;
    ALTER TABLE payment_order DROP CONSTRAINT payment_order_status_check;
    ALTER TABLE payment_order ADD CONSTRAINT payment_order_status_check
        CHECK (status IN ('CREATED','PAID','FAILED'));
    ALTER TABLE payment_order DROP CONSTRAINT payment_order_provider_check;
    ALTER TABLE payment_order ADD CONSTRAINT payment_order_provider_check
        CHECK (provider IN ('TOSS'));

    UPDATE reward_policy SET status = 'RETIRED', effective_to = now()
     WHERE action_type = 'PAYMENT_TEST_GIFT';
    DELETE FROM reward_policy p WHERE action_type = 'PAYMENT_TEST_GIFT'
       AND NOT EXISTS (SELECT 1 FROM credit_ledger l WHERE l.policy_id = p.reward_policy_id);

    UPDATE unlock_policy SET status = 'RETIRED', effective_to = now() WHERE insight_type IN ({names});
    DELETE FROM unlock_policy p WHERE insight_type IN ({names})
       AND NOT EXISTS (SELECT 1 FROM unlock_event e WHERE e.unlock_policy_id = p.unlock_policy_id);
    """)
