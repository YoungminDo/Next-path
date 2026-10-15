"""search_run.in_review (docs/12 §5): people skipped because their earlier run is still under
review (NEEDS_REVIEW) or reviewed (READY). A changed snippet never supersedes that run, so a
reviewer's work is not thrown away.

Revision ID: 0042
Revises: 0041
"""
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE search_run ADD COLUMN in_review integer NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE search_run DROP COLUMN in_review")
