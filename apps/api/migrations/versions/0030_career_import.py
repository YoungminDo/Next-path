"""Career import from a person's own resume or LinkedIn screenshots (docs/10 §이력서·캡처).

- import_attempt: one row per read, before login (anonymous session) or after (account). The
  files are never stored: they go to the model once and are dropped. The row is the record of
  the overseas-transfer consent (which wording, when, by which session or account) and keeps how
  many files, which model, the tokens used and how it ended, for the limits and for cost. What
  the person confirms becomes their own SELF_REPORTED records: through the draft and the login
  merge, or added to a member's profile, under a LINKEDIN_USER_UPLOAD or CAREER_DOCUMENT source.
- Funnel events for the upload path.

Revision ID: 0030
Revises: 0029
"""
from alembic import op

revision = "0030"
down_revision = "0029"
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
    "'interview_code_sent','interview_submitted','interview_withdrawn'"
)
NEW_EVENTS = OLD_EVENTS + ",'import_viewed','import_uploaded','import_parsed','import_confirmed'"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE import_attempt (
        import_attempt_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id           uuid REFERENCES account ON DELETE CASCADE,
        session_hash         text,  -- sha256 of the anonymous session, as anonymous_draft.session_id
        client_hash          text,  -- sha256 of the day and the client address (limits only)
        internal             boolean NOT NULL DEFAULT false,
        files                integer NOT NULL CHECK (files BETWEEN 1 AND 10),
        consent_text_version text NOT NULL,
        model                text NOT NULL,
        outcome              text NOT NULL DEFAULT 'STARTED' CHECK (outcome IN
                                 ('STARTED','PARSED','NOT_CAREER','REFUSED','FAILED')),
        source_kind          text CHECK (source_kind IN ('LINKEDIN','RESUME','OTHER')),
        input_tokens         integer,
        output_tokens        integer,
        experiences          integer,
        created_at           timestamptz NOT NULL DEFAULT now(),
        finished_at          timestamptz,
        CHECK (account_id IS NOT NULL OR session_hash IS NOT NULL)
    );
    CREATE INDEX import_attempt_account_idx ON import_attempt (account_id, created_at)
        WHERE account_id IS NOT NULL;
    CREATE INDEX import_attempt_session_idx ON import_attempt (session_hash, created_at)
        WHERE session_hash IS NOT NULL;
    CREATE INDEX import_attempt_created_idx ON import_attempt (created_at);
    CREATE INDEX import_attempt_client_idx ON import_attempt (client_hash, created_at)
        WHERE client_hash IS NOT NULL;
    ALTER TABLE import_attempt ENABLE ROW LEVEL SECURITY;

    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({NEW_EVENTS}));
    """)


def downgrade() -> None:
    op.execute(f"""
    DELETE FROM analytics.event WHERE event_name NOT IN ({OLD_EVENTS});
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({OLD_EVENTS}));
    DROP TABLE import_attempt;
    """)
