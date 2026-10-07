"""v1.4 person gender + reported first employment year; education admission year, precisions,
major taxonomy node and education role.

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    -- UNKNOWN = the source has no value; UNDISCLOSED = the person chose not to disclose.
    -- Never inferred from name, photo, school or anything else.
    ALTER TABLE person
        ADD COLUMN gender_code text NOT NULL DEFAULT 'UNKNOWN'
            CHECK (gender_code IN ('MALE','FEMALE','OTHER','UNDISCLOSED','UNKNOWN')),
        ADD COLUMN gender_source_id uuid REFERENCES source_record,
        -- Only for sources that know the first-employment year without the underlying event.
        -- The value derived from canonical WORK_EVENTs always wins.
        ADD COLUMN reported_first_employment_year smallint
            CHECK (reported_first_employment_year BETWEEN 1950 AND 2100),
        ADD COLUMN reported_first_employment_source_id uuid REFERENCES source_record;
    CREATE INDEX person_layer_gender_idx ON person (origin_layer, gender_code)
        WHERE deleted_at IS NULL;

    -- canonical_education is SELECT e.*: columns are fixed at view creation, so rebuild it.
    DROP VIEW canonical_education;
    ALTER TABLE education
        ADD COLUMN admission_year smallint CHECK (admission_year BETWEEN 1950 AND 2100),
        ADD COLUMN admission_date_precision text CHECK (admission_date_precision IN ('DAY','MONTH','YEAR')),
        ADD COLUMN graduation_date_precision text CHECK (graduation_date_precision IN ('DAY','MONTH','YEAR')),
        ADD COLUMN major_taxonomy_node_id uuid REFERENCES taxonomy_node,
        ADD COLUMN education_role text CHECK (education_role IN ('MAJOR','DOUBLE_MAJOR','MINOR')),
        ADD CONSTRAINT education_admission_before_graduation
            CHECK (admission_year IS NULL OR graduation_year IS NULL OR admission_year <= graduation_year);
    CREATE INDEX education_institution_idx ON education (institution_id);
    CREATE INDEX education_major_node_idx ON education (major_taxonomy_node_id);
    CREATE INDEX education_admission_idx ON education (admission_year);
    CREATE INDEX education_graduation_idx ON education (graduation_year);
    CREATE TRIGGER education_major_type BEFORE INSERT OR UPDATE OF major_taxonomy_node_id
        ON education FOR EACH ROW EXECUTE FUNCTION assert_taxonomy_type('major_taxonomy_node_id', 'MAJOR');
    CREATE VIEW canonical_education AS
        SELECT e.* FROM education e
        WHERE e.retracted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM education n
                          WHERE n.supersedes_education_id = e.education_id);
    """)


def downgrade() -> None:
    op.execute("""
    DROP VIEW canonical_education;
    DROP TRIGGER education_major_type ON education;
    DROP INDEX education_graduation_idx;
    DROP INDEX education_admission_idx;
    DROP INDEX education_major_node_idx;
    DROP INDEX education_institution_idx;
    ALTER TABLE education
        DROP CONSTRAINT education_admission_before_graduation,
        DROP COLUMN admission_year, DROP COLUMN admission_date_precision,
        DROP COLUMN graduation_date_precision, DROP COLUMN major_taxonomy_node_id,
        DROP COLUMN education_role;
    CREATE VIEW canonical_education AS
        SELECT e.* FROM education e
        WHERE e.retracted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM education n
                          WHERE n.supersedes_education_id = e.education_id);
    DROP INDEX person_layer_gender_idx;
    ALTER TABLE person
        DROP COLUMN gender_code, DROP COLUMN gender_source_id,
        DROP COLUMN reported_first_employment_year, DROP COLUMN reported_first_employment_source_id;
    """)
