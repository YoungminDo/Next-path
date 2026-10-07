"""Seed collection staging + QA. Research operators never write canonical tables directly.

RAW COLLECTION -> VALIDATION -> NORMALIZATION -> QA -> APPROVED -> CANONICAL DB

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

QA_STATUS = "'PENDING','APPROVED','NEEDS_FIX','REJECTED'"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE collector (
        collector_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name         text NOT NULL,
        account_id   uuid REFERENCES account,
        status       text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
        created_at   timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE collection_batch (
        collection_batch_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        collector_id        uuid NOT NULL REFERENCES collector,
        source_type         text NOT NULL,
        legal_basis         text NOT NULL,
        description         text,
        status              text NOT NULL DEFAULT 'OPEN'
                                CHECK (status IN ('OPEN','SUBMITTED','IMPORTED','CLOSED')),
        import_batch_id     uuid REFERENCES import_batch,
        created_at          timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE seed_staging_record (
        staging_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        collection_batch_id uuid NOT NULL REFERENCES collection_batch,
        entity_type         text NOT NULL CHECK (entity_type IN ('PERSON','EDUCATION','WORK_EVENT')),
        external_ref        text,
        raw_payload         jsonb NOT NULL,
        normalized_payload  jsonb,
        validation_errors   jsonb NOT NULL DEFAULT '[]'::jsonb,
        normalization_version text,
        qa_status           text NOT NULL DEFAULT 'PENDING' CHECK (qa_status IN ({QA_STATUS})),
        created_at          timestamptz NOT NULL DEFAULT now(),
        updated_at          timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX seed_staging_batch_idx ON seed_staging_record (collection_batch_id, qa_status);
    CREATE TRIGGER seed_staging_updated_at BEFORE UPDATE ON seed_staging_record
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE qa_review (
        qa_review_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        staging_id   uuid NOT NULL REFERENCES seed_staging_record,
        reviewer_account_id uuid REFERENCES account,
        decision     text NOT NULL CHECK (decision IN ({QA_STATUS})),
        notes        text,
        created_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE TRIGGER qa_review_append_only BEFORE UPDATE OR DELETE ON qa_review
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE qa_review;
    DROP TABLE seed_staging_record;
    DROP TABLE collection_batch;
    DROP TABLE collector;
    """)
