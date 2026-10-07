"""ACCOUNT / PERSON: authentication identity separated from career identity; PII separated.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE account (
        account_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        status     text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUSPENDED','DELETED')),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        deleted_at timestamptz
    );
    CREATE TRIGGER account_updated_at BEFORE UPDATE ON account
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    -- Provider abstraction: Kakao + Google first, Apple later; one account may link several.
    CREATE TABLE account_identity (
        account_identity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id          uuid NOT NULL REFERENCES account ON DELETE CASCADE,
        auth_provider       text NOT NULL CHECK (auth_provider IN ('KAKAO','GOOGLE','APPLE','DEV')),
        provider_subject    text NOT NULL,
        created_at          timestamptz NOT NULL DEFAULT now(),
        UNIQUE (auth_provider, provider_subject)
    );
    CREATE INDEX account_identity_account_idx ON account_identity (account_id);

    CREATE TABLE auth_session (
        session_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id uuid NOT NULL REFERENCES account ON DELETE CASCADE,
        token_hash text NOT NULL UNIQUE,
        created_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz
    );

    -- Career identity root. May exist without an account (PRE_SEED, SEED).
    CREATE TABLE person (
        person_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id         uuid UNIQUE REFERENCES account,
        origin_layer       text NOT NULL CHECK (origin_layer IN ('PRE_SEED','SEED','VERIFIED')),
        -- Stage as declared by the source/user; product logic derives stage from events.
        declared_stage     text CHECK (declared_stage IN ('STUDENT','JOB_SEEKER','PROFESSIONAL')),
        primary_source_id  uuid REFERENCES source_record,
        created_at         timestamptz NOT NULL DEFAULT now(),
        updated_at         timestamptz NOT NULL DEFAULT now(),
        last_verified_at   timestamptz,
        deleted_at         timestamptz,
        CHECK (origin_layer <> 'PRE_SEED' OR account_id IS NULL)
    );
    CREATE INDEX person_origin_layer_idx ON person (origin_layer) WHERE deleted_at IS NULL;
    CREATE TRIGGER person_updated_at BEFORE UPDATE ON person
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE person_pii (
        person_id    uuid PRIMARY KEY REFERENCES person ON DELETE CASCADE,
        display_name text,
        email        text,
        phone        text,
        created_at   timestamptz NOT NULL DEFAULT now(),
        updated_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE TRIGGER person_pii_updated_at BEFORE UPDATE ON person_pii
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE person_pii;
    DROP TABLE person;
    DROP TABLE auth_session;
    DROP TABLE account_identity;
    DROP TABLE account;
    """)
