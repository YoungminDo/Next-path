"""The team dashboard reads events by the time the server received them.

Revision ID: 0029
Revises: 0028
"""
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX analytics_event_received_idx ON analytics.event (received_at)")


def downgrade() -> None:
    op.execute("DROP INDEX analytics.analytics_event_received_idx")
