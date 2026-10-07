"""Login through HMM ID (company IdP) instead of calling Kakao directly.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE account_identity DROP CONSTRAINT account_identity_auth_provider_check;
    ALTER TABLE account_identity ADD CONSTRAINT account_identity_auth_provider_check
        CHECK (auth_provider IN ('HMM_ID','KAKAO','GOOGLE','APPLE','DEV'));
    COMMENT ON COLUMN account_identity.provider_subject IS
        'HMM_ID: dash_user_id from id.da-sh.io /api/v1/auth/me (e.g. kakao_12345)';
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM account_identity WHERE auth_provider = 'HMM_ID';
    ALTER TABLE account_identity DROP CONSTRAINT account_identity_auth_provider_check;
    ALTER TABLE account_identity ADD CONSTRAINT account_identity_auth_provider_check
        CHECK (auth_provider IN ('KAKAO','GOOGLE','APPLE','DEV'));
    COMMENT ON COLUMN account_identity.provider_subject IS NULL;
    """)
