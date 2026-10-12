"""User-interview opt-in: a member's phone number, kept only with its own separate consent.

- data_consent gains INTERVIEW_CONTACT (purpose: contact for a user interview; item: mobile
  number; kept until a year after the interview or until withdrawn). Grant and withdrawal are
  both rows, so the history stays.
- interview_contact: one row per account (ACCOUNT, not PERSON). Withdrawal clears the number and
  sets withdrawn_at; the number is never kept after that.
- phone_verification: short-lived SMS code checks. Only a keyed hash of the number and of the
  code is stored, enough for expiry, attempt limits and rate limits.

Revision ID: 0027
Revises: 0026
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

OLD = ("'TERMS','PRIVACY_PROCESSING','CAREER_DATA_AGGREGATION','MENTOR_PUBLIC_PROFILE',"
       "'EXTERNAL_IMPORT','MARKETING'")
NEW = OLD + ",'INTERVIEW_CONTACT'"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE data_consent DROP CONSTRAINT data_consent_consent_type_check;
    ALTER TABLE data_consent ADD CONSTRAINT data_consent_consent_type_check
        CHECK (consent_type IN ({NEW}));

    CREATE TABLE interview_contact (
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
    CREATE TRIGGER interview_contact_updated_at BEFORE UPDATE ON interview_contact
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    ALTER TABLE interview_contact ENABLE ROW LEVEL SECURITY;

    CREATE TABLE phone_verification (
        verification_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id      uuid NOT NULL REFERENCES account ON DELETE CASCADE,
        phone_hash      text NOT NULL,
        code_hash       text NOT NULL,
        expires_at      timestamptz NOT NULL,
        attempts        integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
        verified_at     timestamptz,
        created_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX phone_verification_account_idx ON phone_verification (account_id, created_at);
    CREATE INDEX phone_verification_phone_idx ON phone_verification (phone_hash, created_at);
    ALTER TABLE phone_verification ENABLE ROW LEVEL SECURITY;
    """)


def downgrade() -> None:
    op.execute(f"""
    DROP TABLE phone_verification;
    DROP TABLE interview_contact;
    DELETE FROM data_consent WHERE consent_type = 'INTERVIEW_CONTACT';
    ALTER TABLE data_consent DROP CONSTRAINT data_consent_consent_type_check;
    ALTER TABLE data_consent ADD CONSTRAINT data_consent_consent_type_check
        CHECK (consent_type IN ({OLD}));
    """)
