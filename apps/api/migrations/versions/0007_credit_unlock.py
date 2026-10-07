"""튜브 (Tube) credit: immutable ledger, REWARD/UNLOCK/PRICING policies, unlock events, entitlements.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

POLICY_COLS = """
        version        text NOT NULL,
        effective_from timestamptz NOT NULL DEFAULT now(),
        effective_to   timestamptz,
        status         text NOT NULL CHECK (status IN ('DRAFT','ACTIVE','RETIRED')),
        created_at     timestamptz NOT NULL DEFAULT now()
"""


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE reward_policy (
        reward_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        action_type      text NOT NULL CHECK (action_type IN
                             ('SIGNUP','EDUCATION_ADDED','CURRENT_ROLE_ADDED',
                              'PREVIOUS_CAREER_ADDED','DECISION_RECORDED','CAREER_RECONFIRMED',
                              'OUTCOME_REPORTED')),
        reward_tube        integer NOT NULL CHECK (reward_tube > 0),
        max_occurrences  integer CHECK (max_occurrences > 0),
        cooldown_seconds integer CHECK (cooldown_seconds >= 0),
        {POLICY_COLS},
        UNIQUE (action_type, version)
    );
    CREATE UNIQUE INDEX reward_policy_one_active_uq ON reward_policy (action_type)
        WHERE status = 'ACTIVE';

    CREATE TABLE unlock_policy (
        unlock_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        insight_type     text NOT NULL CHECK (insight_type IN
                             ('PATH_DEEP_DIVE','COMPANY_BREAKDOWN','REPRESENTATIVE_PATHS',
                              'TIMING_TENURE')),
        cost_tube          integer NOT NULL CHECK (cost_tube > 0),
        entitlement_days integer CHECK (entitlement_days > 0),
        {POLICY_COLS},
        UNIQUE (insight_type, version)
    );
    CREATE UNIQUE INDEX unlock_policy_one_active_uq ON unlock_policy (insight_type)
        WHERE status = 'ACTIVE';

    -- Future paid 튜브 packages. Phase 1: schema only, rows stay inactive (decision Q3).
    CREATE TABLE pricing_policy (
        pricing_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        sku               text NOT NULL,
        amount_krw        integer NOT NULL CHECK (amount_krw > 0),
        credit_amount     integer NOT NULL CHECK (credit_amount > 0),
        {POLICY_COLS},
        UNIQUE (sku, version)
    );

    INSERT INTO reward_policy (action_type, reward_tube, max_occurrences, cooldown_seconds,
                               version, status) VALUES
        ('SIGNUP',                3, 1,    NULL,     'reward_v1', 'ACTIVE'),
        ('EDUCATION_ADDED',       1, 1,    NULL,     'reward_v1', 'ACTIVE'),
        ('CURRENT_ROLE_ADDED',    2, 1,    NULL,     'reward_v1', 'ACTIVE'),
        ('PREVIOUS_CAREER_ADDED', 1, 5,    NULL,     'reward_v1', 'ACTIVE'),
        ('DECISION_RECORDED',     1, NULL, 86400,    'reward_v1', 'ACTIVE'),
        ('CAREER_RECONFIRMED',    1, NULL, 7776000,  'reward_v1', 'ACTIVE'),
        ('OUTCOME_REPORTED',      2, NULL, 86400,    'reward_v1', 'ACTIVE');

    INSERT INTO unlock_policy (insight_type, cost_tube, entitlement_days, version, status) VALUES
        ('PATH_DEEP_DIVE',       1, NULL, 'unlock_v1', 'ACTIVE'),
        ('COMPANY_BREAKDOWN',    1, NULL, 'unlock_v1', 'ACTIVE'),
        ('REPRESENTATIVE_PATHS', 1, NULL, 'unlock_v1', 'ACTIVE'),
        ('TIMING_TENURE',        1, NULL, 'unlock_v1', 'ACTIVE');

    -- Source of truth for 튜브 balances. INSERT only; corrections are reversal entries.
    CREATE TABLE credit_ledger (
        ledger_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id         uuid NOT NULL REFERENCES account,
        amount             bigint NOT NULL CHECK (amount > 0),
        direction          text NOT NULL CHECK (direction IN ('CREDIT','DEBIT')),
        reason_type        text NOT NULL CHECK (reason_type IN
                               ('REWARD','UNLOCK','PURCHASE','ORDER','REFUND','REVERSAL',
                                'ADJUSTMENT','EXPIRY')),
        reference_type     text NOT NULL,
        reference_id       text NOT NULL,
        idempotency_key    text NOT NULL UNIQUE,
        policy_type        text,
        policy_id          uuid,
        policy_version     text,
        reverses_ledger_id uuid UNIQUE REFERENCES credit_ledger,
        created_at         timestamptz NOT NULL DEFAULT now(),
        CHECK ((reason_type = 'REVERSAL') = (reverses_ledger_id IS NOT NULL))
    );
    CREATE INDEX credit_ledger_account_idx ON credit_ledger (account_id, created_at);
    CREATE INDEX credit_ledger_reason_idx ON credit_ledger (account_id, reason_type, reference_type);

    CREATE FUNCTION credit_ledger_forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'credit_ledger is immutable (% rejected); write a REVERSAL entry', TG_OP
            USING ERRCODE = 'restrict_violation';
    END $$;
    CREATE TRIGGER credit_ledger_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON credit_ledger
        FOR EACH STATEMENT EXECUTE FUNCTION credit_ledger_forbid_mutation();

    CREATE VIEW credit_balance AS
        SELECT account_id,
               SUM(CASE direction WHEN 'CREDIT' THEN amount ELSE -amount END)::bigint AS balance
        FROM credit_ledger GROUP BY account_id;

    CREATE TABLE unlock_event (
        unlock_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id       uuid NOT NULL REFERENCES account,
        unlock_policy_id uuid NOT NULL REFERENCES unlock_policy,
        insight_type     text NOT NULL,
        insight_key      text NOT NULL,
        insight_params   jsonb NOT NULL,
        cost_tube          integer NOT NULL,
        ledger_id        uuid NOT NULL UNIQUE REFERENCES credit_ledger,
        idempotency_key  text NOT NULL UNIQUE,
        created_at       timestamptz NOT NULL DEFAULT now()
    );
    CREATE TRIGGER unlock_event_append_only BEFORE UPDATE OR DELETE ON unlock_event
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

    CREATE TABLE entitlement (
        entitlement_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id     uuid NOT NULL REFERENCES account,
        insight_type   text NOT NULL,
        insight_key    text NOT NULL,
        unlock_id      uuid NOT NULL REFERENCES unlock_event,
        granted_at     timestamptz NOT NULL DEFAULT now(),
        expires_at     timestamptz,
        revoked_at     timestamptz,
        UNIQUE (account_id, insight_type, insight_key)
    );
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE entitlement;
    DROP TABLE unlock_event;
    DROP VIEW credit_balance;
    DROP TABLE credit_ledger;
    DROP FUNCTION credit_ledger_forbid_mutation();
    DROP TABLE pricing_policy;
    DROP TABLE unlock_policy;
    DROP TABLE reward_policy;
    """)
