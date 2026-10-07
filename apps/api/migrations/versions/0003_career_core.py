"""EDUCATION / WORK_EVENT with multi-source evidence, verification log, identity resolution.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

EVENT_TYPES = (
    "'EMPLOYMENT','STARTUP','SIDE_BUSINESS','SELF_EMPLOYED','FREELANCE','STUDY',"
    "'CAREER_BREAK','MILITARY','PROJECT','OTHER'"
)
LEVELS = "'UNVERIFIED','SELF_REPORTED','SOURCE_VERIFIED','SELF_RECONFIRMED'"
WORK_FIELDS = "'organization','role','event_type','start_date','end_date','is_current','seniority'"
EDU_FIELDS = "'institution','major','degree_type','graduation_year'"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE education (
        education_id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        person_id                uuid NOT NULL REFERENCES person ON DELETE CASCADE,
        institution_raw          text,
        institution_id           uuid REFERENCES institution,
        major_raw                text,
        major_id                 uuid REFERENCES major,
        degree_type              text CHECK (degree_type IN
                                     ('ASSOCIATE','BACHELOR','MASTER','DOCTORATE','OTHER')),
        graduation_year          smallint CHECK (graduation_year BETWEEN 1950 AND 2100),
        data_layer               text NOT NULL CHECK (data_layer IN ('PRE_SEED','SEED','VERIFIED')),
        verification_level       text NOT NULL CHECK (verification_level IN ({LEVELS})),
        normalization_status     text NOT NULL DEFAULT 'MAPPED'
                                     CHECK (normalization_status IN ('MAPPED','PARTIAL','UNMAPPED')),
        normalization_confidence numeric(4,3) CHECK (normalization_confidence BETWEEN 0 AND 1),
        -- Corrections create a new row pointing at the row they replace; nothing is overwritten.
        supersedes_education_id  uuid UNIQUE REFERENCES education,
        created_at               timestamptz NOT NULL DEFAULT now(),
        updated_at               timestamptz NOT NULL DEFAULT now(),
        last_verified_at         timestamptz,
        retracted_at             timestamptz
    );
    CREATE INDEX education_person_idx ON education (person_id);
    CREATE INDEX education_cohort_idx ON education (institution_id, major_id, graduation_year);
    CREATE TRIGGER education_updated_at BEFORE UPDATE ON education
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE education_source (
        education_source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        education_id        uuid NOT NULL REFERENCES education ON DELETE CASCADE,
        source_id           uuid NOT NULL REFERENCES source_record,
        supported_fields    text[] NOT NULL
                                CHECK (cardinality(supported_fields) > 0
                                       AND supported_fields <@ ARRAY[{EDU_FIELDS}]),
        evidence_confidence numeric(4,3) CHECK (evidence_confidence BETWEEN 0 AND 1),
        is_primary          boolean NOT NULL DEFAULT false,
        created_at          timestamptz NOT NULL DEFAULT now(),
        UNIQUE (education_id, source_id)
    );
    CREATE INDEX education_source_source_idx ON education_source (source_id);

    CREATE TABLE work_event (
        work_event_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        person_id                uuid NOT NULL REFERENCES person ON DELETE CASCADE,
        event_type               text NOT NULL CHECK (event_type IN ({EVENT_TYPES})),
        organization_raw         text,
        organization_id          uuid REFERENCES organization,
        role_raw                 text,
        role_id                  uuid REFERENCES role,
        seniority                text CHECK (seniority IN
                                     ('ENTRY','JUNIOR','MID','SENIOR','LEAD','EXEC')),
        start_date               date,
        start_date_precision     text CHECK (start_date_precision IN ('DAY','MONTH','YEAR')),
        end_date                 date,
        end_date_precision       text CHECK (end_date_precision IN ('DAY','MONTH','YEAR')),
        is_current               boolean,
        -- Independent interval per event: parallel events are allowed (no exclusion constraint).
        period                   daterange GENERATED ALWAYS AS (
                                     CASE WHEN start_date IS NULL THEN NULL
                                          ELSE daterange(start_date, end_date, '[)') END
                                 ) STORED,
        data_layer               text NOT NULL CHECK (data_layer IN ('PRE_SEED','SEED','VERIFIED')),
        verification_level       text NOT NULL CHECK (verification_level IN ({LEVELS})),
        normalization_status     text NOT NULL DEFAULT 'MAPPED'
                                     CHECK (normalization_status IN ('MAPPED','PARTIAL','UNMAPPED')),
        normalization_confidence numeric(4,3) CHECK (normalization_confidence BETWEEN 0 AND 1),
        supersedes_work_event_id uuid UNIQUE REFERENCES work_event,
        created_at               timestamptz NOT NULL DEFAULT now(),
        updated_at               timestamptz NOT NULL DEFAULT now(),
        last_verified_at         timestamptz,
        retracted_at             timestamptz,
        CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date),
        CHECK (NOT (is_current IS TRUE AND end_date IS NOT NULL))
    );
    CREATE INDEX work_event_person_idx ON work_event (person_id, start_date);
    CREATE INDEX work_event_period_idx ON work_event USING gist (period);
    CREATE INDEX work_event_role_idx ON work_event (role_id);
    CREATE INDEX work_event_org_idx ON work_event (organization_id);
    CREATE TRIGGER work_event_updated_at BEFORE UPDATE ON work_event
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    -- One canonical WORK_EVENT <- N SOURCE_RECORDs. Field-level evidence scope.
    CREATE TABLE work_event_source (
        work_event_source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        work_event_id        uuid NOT NULL REFERENCES work_event ON DELETE CASCADE,
        source_id            uuid NOT NULL REFERENCES source_record,
        supported_fields     text[] NOT NULL
                                 CHECK (cardinality(supported_fields) > 0
                                        AND supported_fields <@ ARRAY[{WORK_FIELDS}]),
        evidence_confidence  numeric(4,3) CHECK (evidence_confidence BETWEEN 0 AND 1),
        is_primary           boolean NOT NULL DEFAULT false,
        created_at           timestamptz NOT NULL DEFAULT now(),
        UNIQUE (work_event_id, source_id)
    );
    CREATE INDEX work_event_source_source_idx ON work_event_source (source_id);
    CREATE INDEX work_event_source_fields_idx ON work_event_source USING gin (supported_fields);
    CREATE UNIQUE INDEX work_event_source_one_primary_uq
        ON work_event_source (work_event_id) WHERE is_primary;

    -- Canonical value chosen per field, with the rule version and winning evidence.
    CREATE TABLE work_event_field_resolution (
        resolution_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        work_event_id     uuid NOT NULL REFERENCES work_event ON DELETE CASCADE,
        field_name        text NOT NULL CHECK (field_name IN ({WORK_FIELDS})),
        resolved_value    jsonb,
        winning_source_id uuid REFERENCES source_record,
        rule_version      text NOT NULL,
        reason            text,
        resolved_at       timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX work_event_field_resolution_idx
        ON work_event_field_resolution (work_event_id, field_name, resolved_at DESC);

    CREATE TABLE verification_log (
        verification_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        entity_type        text NOT NULL CHECK (entity_type IN ('WORK_EVENT','EDUCATION','PERSON')),
        entity_id          uuid NOT NULL,
        account_id         uuid REFERENCES account,
        action             text NOT NULL CHECK (action IN
                               ('SELF_REPORTED','SELF_RECONFIRMED','SOURCE_VERIFIED',
                                'CORRECTED','RETRACTED')),
        verified_fields    text[],
        source_id          uuid REFERENCES source_record,
        previous_level     text CHECK (previous_level IN ({LEVELS})),
        new_level          text CHECK (new_level IN ({LEVELS})),
        detail             jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        created_at         timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX verification_log_entity_idx ON verification_log (entity_type, entity_id);
    CREATE TRIGGER verification_log_append_only BEFORE UPDATE OR DELETE ON verification_log
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

    -- Identity resolution: CANDIDATE -> IN_REVIEW -> MERGED | NOT_SAME. Never auto-merged.
    CREATE TABLE identity_match (
        match_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        candidate_person_id uuid NOT NULL REFERENCES person,
        target_person_id    uuid NOT NULL REFERENCES person,
        evidence            jsonb NOT NULL,
        confidence          numeric(4,3) CHECK (confidence BETWEEN 0 AND 1),
        status              text NOT NULL DEFAULT 'CANDIDATE'
                                CHECK (status IN ('CANDIDATE','IN_REVIEW','MERGED','NOT_SAME')),
        reviewed_by         uuid REFERENCES account,
        reviewed_at         timestamptz,
        created_at          timestamptz NOT NULL DEFAULT now(),
        CHECK (candidate_person_id <> target_person_id),
        UNIQUE (candidate_person_id, target_person_id)
    );

    -- PRE_SEED persons are generated, never real people: they cannot be identity-matched.
    CREATE FUNCTION identity_match_forbid_preseed() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF EXISTS (SELECT 1 FROM person
                   WHERE person_id IN (NEW.candidate_person_id, NEW.target_person_id)
                     AND origin_layer = 'PRE_SEED') THEN
            RAISE EXCEPTION 'PRE_SEED persons cannot take part in identity resolution'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER identity_match_no_preseed BEFORE INSERT OR UPDATE ON identity_match
        FOR EACH ROW EXECUTE FUNCTION identity_match_forbid_preseed();

    CREATE TABLE identity_merge_log (
        merge_log_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        match_id     uuid NOT NULL REFERENCES identity_match,
        decision     text NOT NULL CHECK (decision IN ('MERGED','NOT_SAME')),
        decided_by   uuid REFERENCES account,
        detail       jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        created_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE TRIGGER identity_merge_log_append_only BEFORE UPDATE OR DELETE ON identity_merge_log
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

    -- Canonical (non-superseded, non-retracted) views used by every read path.
    CREATE VIEW canonical_work_event AS
        SELECT w.* FROM work_event w
        WHERE w.retracted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM work_event n
                          WHERE n.supersedes_work_event_id = w.work_event_id);
    CREATE VIEW canonical_education AS
        SELECT e.* FROM education e
        WHERE e.retracted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM education n
                          WHERE n.supersedes_education_id = e.education_id);
    """)


def downgrade() -> None:
    op.execute("""
    DROP VIEW canonical_education;
    DROP VIEW canonical_work_event;
    DROP TABLE identity_merge_log;
    DROP TRIGGER identity_match_no_preseed ON identity_match;
    DROP FUNCTION identity_match_forbid_preseed();
    DROP TABLE identity_match;
    DROP TABLE verification_log;
    DROP TABLE work_event_field_resolution;
    DROP TABLE work_event_source;
    DROP TABLE work_event;
    DROP TABLE education_source;
    DROP TABLE education;
    """)
