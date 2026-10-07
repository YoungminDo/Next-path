"""Longitudinal moat: HISTORY -> INTENT -> DECISION -> OUTCOME (Decision 1:N Outcome).

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE intent_event (
        intent_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        person_id       uuid NOT NULL REFERENCES person ON DELETE CASCADE,
        -- BEHAVIORAL = inferred from product behaviour (viewed/unlocked a path);
        -- EXPLICIT   = the member stated it.
        intent_kind     text NOT NULL CHECK (intent_kind IN ('BEHAVIORAL','EXPLICIT')),
        signal_type     text NOT NULL,
        target          jsonb NOT NULL,
        created_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX intent_event_person_idx ON intent_event (person_id, created_at);

    CREATE TABLE decision_event (
        decision_event_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        person_id             uuid NOT NULL REFERENCES person ON DELETE CASCADE,
        decision_type         text NOT NULL CHECK (decision_type IN
                                  ('JOB_CHANGE','ROLE_CHANGE','START_STARTUP','START_SIDE_BUSINESS',
                                   'STUDY','CAREER_BREAK','STAY','OTHER')),
        chosen_target         jsonb,
        reasons               text[],
        reason_text           text,
        related_work_event_id uuid REFERENCES work_event ON DELETE SET NULL,
        helped_by_mentor_profile_id uuid,
        decided_at            date,
        created_at            timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX decision_event_person_idx ON decision_event (person_id);

    CREATE TABLE outcome (
        outcome_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        decision_event_id uuid NOT NULL REFERENCES decision_event ON DELETE CASCADE,
        horizon_months    smallint NOT NULL CHECK (horizon_months > 0),
        measured_at       timestamptz NOT NULL DEFAULT now(),
        status            text CHECK (status IN ('STAYED','MOVED_ON','REVERSED','IN_PROGRESS')),
        satisfaction      smallint CHECK (satisfaction BETWEEN 1 AND 5),
        payload           jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at        timestamptz NOT NULL DEFAULT now(),
        UNIQUE (decision_event_id, horizon_months)
    );
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE outcome;
    DROP TABLE decision_event;
    DROP TABLE intent_event;
    """)
