"""Taxonomy + provenance: taxonomy tables, import batches, immutable source records.

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Enumerations are TEXT + CHECK rather than native ENUM types: CHECK constraints can be
# replaced in a forward migration and removed again on rollback, ALTER TYPE ... ADD VALUE
# cannot be undone.


def upgrade() -> None:
    op.execute("""
    CREATE EXTENSION IF NOT EXISTS pgcrypto;

    -- Shared helpers ---------------------------------------------------------------
    CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at := now();
        RETURN NEW;
    END $$;

    -- Append-only guard. Erasure (privacy deletion) is the single exception and must be
    -- requested explicitly per transaction: SET LOCAL hellomyme.erasure = 'on'.
    CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' AND current_setting('hellomyme.erasure', true) = 'on' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION '% is append-only (% rejected)', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'restrict_violation';
    END $$;

    -- Taxonomy -----------------------------------------------------------------------
    CREATE TABLE taxonomy_version (
        taxonomy_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        taxonomy    text NOT NULL CHECK (taxonomy IN
                        ('INSTITUTION','MAJOR','ORGANIZATION','ROLE','INDUSTRY',
                         'JOB_FAMILY','SENIORITY','CAREER_EVENT_TYPE')),
        version     text NOT NULL,
        description text,
        created_at  timestamptz NOT NULL DEFAULT now(),
        UNIQUE (taxonomy, version)
    );

    CREATE TABLE institution (
        institution_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name                text NOT NULL UNIQUE,
        region              text,
        institution_type    text,
        taxonomy_version_id uuid NOT NULL REFERENCES taxonomy_version,
        is_active           boolean NOT NULL DEFAULT true,
        created_at          timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE major (
        major_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name                text NOT NULL UNIQUE,
        major_family        text,
        taxonomy_version_id uuid NOT NULL REFERENCES taxonomy_version,
        is_active           boolean NOT NULL DEFAULT true,
        created_at          timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE organization (
        organization_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name                text NOT NULL UNIQUE,
        industry            text,
        company_size_band   text CHECK (company_size_band IN
                                ('MICRO','SMALL','MID','LARGE','ENTERPRISE')),
        company_stage       text,
        -- Category placeholders ("스타트업 A", "창업/자영업") are not real employers:
        -- excluded from company-level statistics.
        is_placeholder      boolean NOT NULL DEFAULT false,
        taxonomy_version_id uuid NOT NULL REFERENCES taxonomy_version,
        is_active           boolean NOT NULL DEFAULT true,
        created_at          timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE role (
        role_id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name                text NOT NULL UNIQUE,
        job_family          text NOT NULL,
        taxonomy_version_id uuid NOT NULL REFERENCES taxonomy_version,
        is_active           boolean NOT NULL DEFAULT true,
        created_at          timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX role_job_family_idx ON role (job_family);

    -- Provenance ---------------------------------------------------------------------
    CREATE TABLE import_batch (
        import_batch_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        dataset_name     text NOT NULL,
        dataset_version  text NOT NULL,
        source_system    text NOT NULL,
        source_type      text NOT NULL,
        data_layer       text NOT NULL CHECK (data_layer IN ('PRE_SEED','SEED','VERIFIED')),
        file_manifest    jsonb NOT NULL,
        manifest_sha256  text NOT NULL,
        validation_rule_version text NOT NULL,
        status           text NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
        report           jsonb,
        started_at       timestamptz NOT NULL DEFAULT now(),
        finished_at      timestamptz
    );
    -- Same files re-imported => same batch (idempotent import).
    CREATE UNIQUE INDEX import_batch_completed_manifest_uq
        ON import_batch (manifest_sha256) WHERE status = 'COMPLETED';

    CREATE TABLE source_record (
        source_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source_type        text NOT NULL CHECK (source_type IN
                               ('MANUAL_INPUT','PRE_SEED_FILE','PUBLIC_PROFILE','MANUAL_RESEARCH',
                                'PARTNER_DATA','INSTITUTION_DATA','LINKEDIN_USER_UPLOAD',
                                'INSURANCE_API','CAREER_DOCUMENT','COMPANY_EMAIL','PARTNER_API',
                                'OTHER_APPROVED_SOURCE')),
        data_layer         text NOT NULL CHECK (data_layer IN ('PRE_SEED','SEED','VERIFIED')),
        source_system      text NOT NULL,
        source_key         text NOT NULL,
        import_batch_id    uuid REFERENCES import_batch,
        -- Phase 2: screenshot/document/provider payload lives in object storage.
        raw_payload_ref    text,
        raw_payload        jsonb,
        normalized_payload jsonb,
        metadata           jsonb NOT NULL DEFAULT '{}'::jsonb,
        legal_basis        text,
        collected_at       timestamptz NOT NULL DEFAULT now(),
        created_at         timestamptz NOT NULL DEFAULT now(),
        UNIQUE (source_system, source_key)
    );
    CREATE TRIGGER source_record_append_only BEFORE UPDATE OR DELETE ON source_record
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

    -- Maps external identifiers (e.g. PSP00001) to canonical UUIDs per source system.
    CREATE TABLE entity_key_map (
        source_system   text NOT NULL,
        entity_type     text NOT NULL,
        source_key      text NOT NULL,
        entity_id       uuid NOT NULL,
        import_batch_id uuid REFERENCES import_batch,
        created_at      timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (source_system, entity_type, source_key)
    );
    CREATE INDEX entity_key_map_entity_idx ON entity_key_map (entity_id);

    CREATE TABLE import_issue (
        import_issue_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        import_batch_id uuid NOT NULL REFERENCES import_batch ON DELETE CASCADE,
        severity        text NOT NULL CHECK (severity IN ('REJECT','WARNING')),
        entity_type     text NOT NULL,
        source_key      text,
        row_number      integer,
        rule_code       text NOT NULL,
        detail          jsonb NOT NULL DEFAULT '{}'::jsonb,
        raw_row         jsonb,
        created_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX import_issue_batch_idx ON import_issue (import_batch_id, severity, rule_code);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE import_issue;
    DROP TABLE entity_key_map;
    DROP TABLE source_record;
    DROP TABLE import_batch;
    DROP TABLE role;
    DROP TABLE organization;
    DROP TABLE major;
    DROP TABLE institution;
    DROP TABLE taxonomy_version;
    DROP FUNCTION forbid_mutation();
    DROP FUNCTION set_updated_at();
    """)
