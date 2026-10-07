"""NEXT_ROLE_DISTRIBUTION is implemented by the v1.4 query engine (professional acquisition).

Revision ID: 0021
Revises: 0020
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE metric_definition SET status = 'ACTIVE' "
               "WHERE metric_code = 'NEXT_ROLE_DISTRIBUTION'")


def downgrade() -> None:
    op.execute("UPDATE metric_definition SET status = 'DRAFT' "
               "WHERE metric_code = 'NEXT_ROLE_DISTRIBUTION'")
