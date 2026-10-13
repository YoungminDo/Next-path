"""Why a file read failed, for the team (docs/10 §이력서·캡처).

A failed read showed the person one generic line and left only the outcome FAILED, so a broken
key, an empty credit balance or a refused image looked the same. The reason is the reader's own
error (API status, error type and message, or the local error class), at most 300 characters.
Never file contents, names or contact details.

Revision ID: 0035
Revises: 0034
"""
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE import_attempt ADD COLUMN failure_reason text
        CHECK (length(failure_reason) <= 300);
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE import_attempt DROP COLUMN failure_reason;")
