"""Career ingestion pipeline (docs/09_INGESTION_PIPELINE.md): capture images -> AI JSON ->
automatic checks -> human review -> DB.

One submission groups the screenshots of one person. Every AI output is kept verbatim per parse
run; field-level review decisions are rows, never edits to the output. Raw company/role names are
never overwritten: standardisation lives in alias tables and a mapping queue.

Revision ID: 0022
Revises: 0021
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

SOURCE_TYPES = "'PUBLIC_PROFILE','LINKEDIN_USER_UPLOAD','CAREER_DOCUMENT','MANUAL_RESEARCH'"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE source_submission (
        source_submission_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        collector_id           uuid NOT NULL REFERENCES collector,
        collection_batch_id    uuid REFERENCES collection_batch,
        external_submission_id text NOT NULL,
        source_type            text NOT NULL CHECK (source_type IN ({SOURCE_TYPES})),
        -- What the data may be used for, e.g. AGGREGATE_ONLY. Lets a whole source be excluded later.
        permitted_use          text NOT NULL,
        legal_basis            text NOT NULL,
        status                 text NOT NULL DEFAULT 'RECEIVED' CHECK (status IN
                                   ('RECEIVED','IN_REVIEW','LOADED','REJECTED','WITHDRAWN')),
        source_id              uuid REFERENCES source_record,
        loaded_person_id       uuid REFERENCES person ON DELETE SET NULL,
        received_at            timestamptz NOT NULL DEFAULT now(),
        updated_at             timestamptz NOT NULL DEFAULT now(),
        UNIQUE (collector_id, external_submission_id)
    );
    CREATE TRIGGER source_submission_updated_at BEFORE UPDATE ON source_submission
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    -- Image files live in access-controlled object storage; only the reference and hash are here.
    CREATE TABLE source_asset (
        source_asset_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source_submission_id uuid NOT NULL REFERENCES source_submission ON DELETE CASCADE,
        external_asset_id    text NOT NULL,
        page_order           smallint NOT NULL CHECK (page_order >= 1),
        sha256               text CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
        storage_ref          text,
        captured_at          timestamptz,
        created_at           timestamptz NOT NULL DEFAULT now(),
        UNIQUE (source_submission_id, external_asset_id)
    );

    CREATE TABLE parse_run (
        parse_run_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source_submission_id uuid NOT NULL REFERENCES source_submission ON DELETE CASCADE,
        model_version        text NOT NULL,
        prompt_version       text NOT NULL,
        schema_version       text NOT NULL,
        rule_version         text NOT NULL,
        raw_output           jsonb NOT NULL,
        output_sha256        text NOT NULL,
        schema_valid         boolean NOT NULL,
        issues               jsonb NOT NULL DEFAULT '[]'::jsonb,
        status               text NOT NULL CHECK (status IN
                                 ('REJECTED','NEEDS_REVIEW','READY','LOADED','SUPERSEDED')),
        reviewed_by          uuid REFERENCES account,
        reviewed_at          timestamptz,
        created_at           timestamptz NOT NULL DEFAULT now(),
        -- The same output received twice is the same run (idempotent intake).
        UNIQUE (source_submission_id, output_sha256)
    );
    CREATE INDEX parse_run_status_idx ON parse_run (status, created_at);
    CREATE FUNCTION parse_run_output_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.raw_output IS DISTINCT FROM OLD.raw_output
           OR NEW.output_sha256 IS DISTINCT FROM OLD.output_sha256 THEN
            RAISE EXCEPTION 'parse_run.raw_output is immutable; record a new parse run'
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER parse_run_output_immutable BEFORE UPDATE ON parse_run
        FOR EACH ROW EXECUTE FUNCTION parse_run_output_frozen();

    -- One row per extracted field: what the AI read, what the rules made of it, what a person decided.
    CREATE TABLE extraction_field (
        extraction_field_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        parse_run_id        uuid NOT NULL REFERENCES parse_run ON DELETE CASCADE,
        entity_type         text NOT NULL CHECK (entity_type IN ('PERSON','EDUCATION','WORK_EVENT')),
        local_id            text NOT NULL,
        field_name          text NOT NULL,
        raw_value           text,
        normalized_value    text,
        normalized_ref      uuid,
        confidence          numeric(4,3) CHECK (confidence BETWEEN 0 AND 1),
        source_asset_id     uuid REFERENCES source_asset,
        evidence_text       text,
        review_status       text NOT NULL DEFAULT 'PENDING' CHECK (review_status IN
                                ('PENDING','AUTO_ACCEPTED','ACCEPTED','CORRECTED','REJECTED')),
        corrected_value     text,
        reviewer_account_id uuid REFERENCES account,
        reviewed_at         timestamptz,
        created_at          timestamptz NOT NULL DEFAULT now(),
        UNIQUE (parse_run_id, entity_type, local_id, field_name),
        CHECK ((review_status = 'CORRECTED') = (corrected_value IS NOT NULL))
    );

    -- Organisation names seen in sources -> canonical organisation (raw text stays on the event).
    CREATE TABLE organization_alias (
        organization_alias_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id       uuid NOT NULL REFERENCES organization ON DELETE CASCADE,
        alias_text            text NOT NULL,
        normalized_alias      text GENERATED ALWAYS AS (normalize_label(alias_text)) STORED,
        source_type           text,
        status                text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','RETIRED')),
        created_at            timestamptz NOT NULL DEFAULT now(),
        UNIQUE (organization_id, alias_text)
    );
    CREATE INDEX organization_alias_lookup_idx ON organization_alias (normalized_alias);

    -- Names no alias matched. One row per distinct normalised name, counted across submissions.
    CREATE TABLE mapping_queue (
        mapping_queue_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        entity_kind      text NOT NULL CHECK (entity_kind IN
                             ('ORGANIZATION','ROLE','MAJOR','INSTITUTION')),
        raw_value        text NOT NULL,
        normalized_key   text GENERATED ALWAYS AS (normalize_label(raw_value)) STORED,
        occurrences      integer NOT NULL DEFAULT 1 CHECK (occurrences > 0),
        proposed_ref     uuid,
        proposed_by      text,
        status           text NOT NULL DEFAULT 'PENDING' CHECK (status IN
                             ('PENDING','APPROVED','NEW_ENTITY','REJECTED')),
        resolved_ref     uuid,
        reviewer_account_id uuid REFERENCES account,
        resolved_at      timestamptz,
        created_at       timestamptz NOT NULL DEFAULT now(),
        CHECK ((status IN ('APPROVED','NEW_ENTITY')) = (resolved_ref IS NOT NULL))
    );
    CREATE UNIQUE INDEX mapping_queue_key_uq ON mapping_queue (entity_kind, normalized_key);

    -- Which screenshot (and which line of it) supports a loaded event.
    ALTER TABLE work_event_source
        ADD COLUMN source_asset_id uuid REFERENCES source_asset,
        ADD COLUMN evidence_text text;
    ALTER TABLE education_source
        ADD COLUMN source_asset_id uuid REFERENCES source_asset,
        ADD COLUMN evidence_text text;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE education_source DROP COLUMN source_asset_id, DROP COLUMN evidence_text;
    ALTER TABLE work_event_source DROP COLUMN source_asset_id, DROP COLUMN evidence_text;
    DROP TABLE mapping_queue;
    DROP TABLE organization_alias;
    DROP TABLE extraction_field;
    DROP TRIGGER parse_run_output_immutable ON parse_run;
    DROP FUNCTION parse_run_output_frozen();
    DROP TABLE parse_run;
    DROP TABLE source_asset;
    DROP TABLE source_submission;
    """)
