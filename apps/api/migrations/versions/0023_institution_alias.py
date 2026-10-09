"""Institution aliases ("고려대" / "Korea University" -> 고려대학교), same shape as organization_alias.
Filled from the ingestion workbook's 05_INSTITUTION sheet and from the mapping queue.

Revision ID: 0023
Revises: 0022
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE institution_alias (
        institution_alias_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        institution_id       uuid NOT NULL REFERENCES institution ON DELETE CASCADE,
        alias_text           text NOT NULL,
        normalized_alias     text GENERATED ALWAYS AS (normalize_label(alias_text)) STORED,
        source_type          text,
        status               text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','RETIRED')),
        created_at           timestamptz NOT NULL DEFAULT now(),
        UNIQUE (institution_id, alias_text)
    );
    CREATE INDEX institution_alias_lookup_idx ON institution_alias (normalized_alias);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE institution_alias;")
