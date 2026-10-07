"""Data moat (docs/08_DATA_MOAT.md): intent follow-up (A), decision rationale (B),
help feedback on connections (D), and the reward actions that collect them.

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

POLICY_COLS = """
        version        text NOT NULL,
        effective_from timestamptz NOT NULL DEFAULT now(),
        effective_to   timestamptz,
        status         text NOT NULL CHECK (status IN ('DRAFT','ACTIVE','RETIRED')),
        created_at     timestamptz NOT NULL DEFAULT now()
"""

OLD_ACTIONS = (
    "'SIGNUP','EDUCATION_ADDED','CURRENT_ROLE_ADDED','PREVIOUS_CAREER_ADDED',"
    "'DECISION_RECORDED','CAREER_RECONFIRMED','OUTCOME_REPORTED'"
)
NEW_ACTIONS = (
    OLD_ACTIONS
    + ",'INTENT_FOLLOWUP_ANSWERED','DECISION_RATIONALE_ADDED','HELP_COMPLETED','HELP_RATED'"
)


def upgrade() -> None:
    op.execute(f"""
    -- A. When to ask "결국 어떻게 됐어요?" after an intent. Horizons are policy, not code.
    CREATE TABLE followup_policy (
        followup_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        horizons_months    smallint[] NOT NULL CHECK (cardinality(horizons_months) > 0
                               AND 0 < ALL (horizons_months)),
        {POLICY_COLS},
        UNIQUE (version)
    );
    CREATE UNIQUE INDEX followup_policy_one_active_uq ON followup_policy ((true))
        WHERE status = 'ACTIVE';
    INSERT INTO followup_policy (horizons_months, version, status)
    VALUES ('{{6,12}}', 'fu_v1', 'ACTIVE');

    CREATE TABLE intent_followup (
        intent_followup_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        intent_event_id    uuid NOT NULL REFERENCES intent_event ON DELETE CASCADE,
        followup_policy_id uuid NOT NULL REFERENCES followup_policy,
        horizon_months     smallint NOT NULL CHECK (horizon_months > 0),
        due_at             timestamptz NOT NULL,
        status             text NOT NULL DEFAULT 'SCHEDULED' CHECK (status IN
                               ('SCHEDULED','SENT','ANSWERED','SKIPPED','EXPIRED')),
        -- What happened to the intent: went there, on the way, picked another target,
        -- stayed put, still deciding, gave up.
        resolution         text CHECK (resolution IN
                               ('PURSUED','PURSUING','CHANGED_TARGET','STAYED',
                                'STILL_EXPLORING','DROPPED')),
        decision_event_id  uuid REFERENCES decision_event ON DELETE SET NULL,
        answered_at        timestamptz,
        created_at         timestamptz NOT NULL DEFAULT now(),
        UNIQUE (intent_event_id, horizon_months),
        CHECK ((status = 'ANSWERED') = (resolution IS NOT NULL AND answered_at IS NOT NULL))
    );
    CREATE INDEX intent_followup_due_idx ON intent_followup (status, due_at);

    -- An answer is a source record of what the member said at that time: never rewritten.
    CREATE FUNCTION intent_followup_freeze_answer() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.status = 'ANSWERED' THEN
            RAISE EXCEPTION 'answered intent_followup is immutable'
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER intent_followup_freeze BEFORE UPDATE ON intent_followup
        FOR EACH ROW EXECUTE FUNCTION intent_followup_freeze_answer();

    -- B. Why the choice was made, what else was on the table, would they choose it again.
    ALTER TABLE decision_event
        ADD COLUMN intent_event_id uuid REFERENCES intent_event ON DELETE SET NULL,
        ADD COLUMN considered_targets jsonb NOT NULL DEFAULT '[]'::jsonb
            CHECK (jsonb_typeof(considered_targets) = 'array'),
        ADD COLUMN would_choose_again text CHECK (would_choose_again IN ('YES','NO','UNSURE')),
        ADD COLUMN source_surface text;
    CREATE INDEX decision_event_intent_idx ON decision_event (intent_event_id);

    -- D. Connections: what the question was about, which intent led to it, and whether it helped.
    ALTER TABLE orders
        ADD COLUMN topic_taxonomy_node_id uuid REFERENCES taxonomy_node,
        ADD COLUMN intent_event_id uuid REFERENCES intent_event ON DELETE SET NULL;

    CREATE TABLE help_feedback (
        help_feedback_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        order_id         uuid NOT NULL UNIQUE REFERENCES orders ON DELETE CASCADE,
        rater_account_id uuid NOT NULL REFERENCES account,
        helpfulness      smallint NOT NULL CHECK (helpfulness BETWEEN 1 AND 5),
        decision_effect  text CHECK (decision_effect IN
                             ('CHANGED','CONFIRMED','NO_EFFECT','TOO_EARLY')),
        comment          text,
        created_at       timestamptz NOT NULL DEFAULT now()
    );

    ALTER TABLE reward_policy DROP CONSTRAINT reward_policy_action_type_check;
    ALTER TABLE reward_policy ADD CONSTRAINT reward_policy_action_type_check
        CHECK (action_type IN ({NEW_ACTIONS}));
    """)


def downgrade() -> None:
    op.execute(f"""
    ALTER TABLE reward_policy DROP CONSTRAINT reward_policy_action_type_check;
    ALTER TABLE reward_policy ADD CONSTRAINT reward_policy_action_type_check
        CHECK (action_type IN ({OLD_ACTIONS}));
    DROP TABLE help_feedback;
    ALTER TABLE orders DROP COLUMN topic_taxonomy_node_id, DROP COLUMN intent_event_id;
    DROP INDEX decision_event_intent_idx;
    ALTER TABLE decision_event
        DROP COLUMN intent_event_id, DROP COLUMN considered_targets,
        DROP COLUMN would_choose_again, DROP COLUMN source_surface;
    DROP TRIGGER intent_followup_freeze ON intent_followup;
    DROP FUNCTION intent_followup_freeze_answer();
    DROP TABLE intent_followup;
    DROP TABLE followup_policy;
    """)
