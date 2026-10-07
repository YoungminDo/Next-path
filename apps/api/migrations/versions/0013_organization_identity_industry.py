"""v1.4 ORGANIZATION as an entity; industry classification through a junction.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE organization
        ADD COLUMN organization_type   text CHECK (organization_type IN
            ('COMPANY','PUBLIC_INSTITUTION','NONPROFIT','SELF','PLACEHOLDER')),
        ADD COLUMN ownership_type      text,
        ADD COLUMN listed_status       text,
        ADD COLUMN country_code        char(2),
        ADD COLUMN employee_count_band text,
        ADD COLUMN b2b_b2c_type        text CHECK (b2b_b2c_type IN ('B2B','B2C','B2B2C','B2G','MIXED')),
        ADD COLUMN founded_year        smallint CHECK (founded_year BETWEEN 1800 AND 2100),
        ADD COLUMN status              text NOT NULL DEFAULT 'ACTIVE'
            CHECK (status IN ('ACTIVE','CLOSED','MERGED'));
    COMMENT ON COLUMN organization.industry IS
        'legacy (pre-v1.4) free-text industry; superseded by organization_industry';

    CREATE TABLE organization_industry (
        organization_industry_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id          uuid NOT NULL REFERENCES organization ON DELETE CASCADE,
        taxonomy_node_id         uuid NOT NULL REFERENCES taxonomy_node,
        is_primary               boolean NOT NULL DEFAULT false,
        valid_from               date,
        valid_to                 date,
        source_id                uuid REFERENCES source_record,
        created_at               timestamptz NOT NULL DEFAULT now(),
        UNIQUE (organization_id, taxonomy_node_id, valid_from)
    );
    CREATE UNIQUE INDEX organization_industry_one_primary_uq
        ON organization_industry (organization_id) WHERE is_primary AND valid_to IS NULL;
    CREATE INDEX organization_industry_node_idx ON organization_industry (taxonomy_node_id);
    CREATE TRIGGER organization_industry_type BEFORE INSERT OR UPDATE ON organization_industry
        FOR EACH ROW EXECUTE FUNCTION assert_taxonomy_type('taxonomy_node_id', 'INDUSTRY');
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE organization_industry;
    COMMENT ON COLUMN organization.industry IS NULL;
    ALTER TABLE organization
        DROP COLUMN organization_type, DROP COLUMN ownership_type, DROP COLUMN listed_status,
        DROP COLUMN country_code, DROP COLUMN employee_count_band, DROP COLUMN b2b_b2c_type,
        DROP COLUMN founded_year, DROP COLUMN status;
    """)
