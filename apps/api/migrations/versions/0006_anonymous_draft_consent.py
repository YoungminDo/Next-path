"""ANONYMOUS_DRAFT + DATA_CONSENT + EXTERNAL_CONNECTION (Phase 2 ready, provider-neutral).

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE anonymous_draft (
        draft_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        -- SHA-256 of the client-held anonymous session token; the raw token is never stored.
        session_id         text NOT NULL,
        user_type          text NOT NULL CHECK (user_type IN ('STUDENT','JOB_SEEKER','PROFESSIONAL')),
        payload_json       jsonb NOT NULL,
        created_at         timestamptz NOT NULL DEFAULT now(),
        updated_at         timestamptz NOT NULL DEFAULT now(),
        expires_at         timestamptz NOT NULL,
        claimed_account_id uuid REFERENCES account,
        claimed_person_id  uuid REFERENCES person,
        claimed_at         timestamptz,
        CHECK ((claimed_account_id IS NULL) = (claimed_at IS NULL))
    );
    CREATE INDEX anonymous_draft_session_idx ON anonymous_draft (session_id, created_at DESC);
    CREATE INDEX anonymous_draft_expiry_idx ON anonymous_draft (expires_at)
        WHERE claimed_at IS NULL;
    CREATE TRIGGER anonymous_draft_updated_at BEFORE UPDATE ON anonymous_draft
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    ALTER TABLE cohort_result_log
        ADD CONSTRAINT cohort_result_log_draft_fk FOREIGN KEY (anonymous_draft_id)
        REFERENCES anonymous_draft ON DELETE SET NULL;

    CREATE TABLE data_consent (
        consent_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id     uuid NOT NULL REFERENCES account ON DELETE CASCADE,
        consent_type   text NOT NULL CHECK (consent_type IN
                           ('TERMS','PRIVACY_PROCESSING','CAREER_DATA_AGGREGATION',
                            'MENTOR_PUBLIC_PROFILE','EXTERNAL_IMPORT','MARKETING')),
        policy_version text NOT NULL,
        status         text NOT NULL CHECK (status IN ('GRANTED','REVOKED')),
        scope          jsonb NOT NULL DEFAULT '{}'::jsonb,
        consented_at   timestamptz NOT NULL DEFAULT now(),
        revoked_at     timestamptz,
        CHECK ((status = 'REVOKED') = (revoked_at IS NOT NULL))
    );
    CREATE INDEX data_consent_account_idx ON data_consent (account_id, consent_type);

    -- Credentials are never stored here: token_ref points into a secret store.
    CREATE TABLE external_connection (
        connection_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id           uuid NOT NULL REFERENCES account ON DELETE CASCADE,
        provider_type        text NOT NULL CHECK (provider_type IN
                                 ('LINKEDIN_USER_UPLOAD','INSURANCE_API','CAREER_DOCUMENT',
                                  'COMPANY_EMAIL','PARTNER_API')),
        provider_account_ref text,
        token_ref            text,
        consent_id           uuid NOT NULL REFERENCES data_consent,
        consent_status       text NOT NULL CHECK (consent_status IN ('ACTIVE','REVOKED','EXPIRED')),
        consented_at         timestamptz NOT NULL,
        revoked_at           timestamptz,
        last_sync_at         timestamptz,
        created_at           timestamptz NOT NULL DEFAULT now()
    );

    ALTER TABLE source_record
        ADD COLUMN external_connection_id uuid REFERENCES external_connection;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE source_record DROP COLUMN external_connection_id;
    DROP TABLE external_connection;
    DROP TABLE data_consent;
    ALTER TABLE cohort_result_log DROP CONSTRAINT cohort_result_log_draft_fk;
    DROP TABLE anonymous_draft;
    """)
