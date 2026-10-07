"""Retire a superseded PRE_SEED import batch (its generated rows are erased, the batch row and
its report stay as provenance), and allow admission_year as an education evidence field.

Revision ID: 0020
Revises: 0019
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE import_batch DROP CONSTRAINT import_batch_status_check;
    ALTER TABLE import_batch ADD CONSTRAINT import_batch_status_check
        CHECK (status IN ('RUNNING','COMPLETED','FAILED','RETIRED'));
    ALTER TABLE import_batch
        ADD COLUMN retired_at timestamptz,
        ADD COLUMN retired_reason text,
        ADD CONSTRAINT import_batch_retired_consistent
            CHECK ((status = 'RETIRED') = (retired_at IS NOT NULL));
    ALTER TABLE education_source DROP CONSTRAINT education_source_supported_fields_check;
    ALTER TABLE education_source ADD CONSTRAINT education_source_supported_fields_check
        CHECK (cardinality(supported_fields) > 0 AND supported_fields <@
               ARRAY['institution','major','degree_type','admission_year','graduation_year']);
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE education_source DROP CONSTRAINT education_source_supported_fields_check;
    ALTER TABLE education_source ADD CONSTRAINT education_source_supported_fields_check
        CHECK (cardinality(supported_fields) > 0 AND supported_fields <@
               ARRAY['institution','major','degree_type','graduation_year']);
    ALTER TABLE import_batch DROP CONSTRAINT import_batch_retired_consistent;
    ALTER TABLE import_batch DROP COLUMN retired_at, DROP COLUMN retired_reason;
    ALTER TABLE import_batch DROP CONSTRAINT import_batch_status_check;
    ALTER TABLE import_batch ADD CONSTRAINT import_batch_status_check
        CHECK (status IN ('RUNNING','COMPLETED','FAILED'));
    """)
