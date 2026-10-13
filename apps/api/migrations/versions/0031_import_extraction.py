"""Keep what a file read showed, also when the person never signs up (docs/10 §이력서·캡처).

Only with the person's own optional consent (career_import_stats_v1), asked separately from the
overseas-transfer notice (PIPA §22①; refusing it never blocks the read, §16③/§22⑤). Stored as the
reader saw it, as anonymous statistics input: no file, no name or contact details, linked only to
the attempt (session hash or account). Unknown stays NULL. Kept 3 years from the read, then
removed by the import API.

- import_attempt.stats_consent_version: the wording version agreed to (NULL: not agreed).
- import_experience / import_education: one row per position / school, in the order read.

Revision ID: 0031
Revises: 0030
"""
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE import_attempt ADD COLUMN stats_consent_version text;

    CREATE TABLE import_experience (
        import_experience_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        import_attempt_id      uuid NOT NULL REFERENCES import_attempt ON DELETE CASCADE,
        ordinal                integer NOT NULL CHECK (ordinal >= 1),
        company_raw            text,
        title_raw              text,
        employment_type        text CHECK (employment_type IN ('FULL_TIME','PART_TIME','CONTRACT','INTERN')),
        start_year             integer,
        start_month            integer CHECK (start_month BETWEEN 1 AND 12),
        end_year               integer,
        end_month              integer CHECK (end_month BETWEEN 1 AND 12),
        is_current             boolean NOT NULL,
        -- What the lists matched at read time (a suggestion, not a decision).
        role_taxonomy_node_id  uuid REFERENCES taxonomy_node,
        organization_id        uuid REFERENCES organization,
        created_at             timestamptz NOT NULL DEFAULT now(),
        UNIQUE (import_attempt_id, ordinal)
    );
    CREATE TABLE import_education (
        import_education_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        import_attempt_id      uuid NOT NULL REFERENCES import_attempt ON DELETE CASCADE,
        ordinal                integer NOT NULL CHECK (ordinal >= 1),
        school_raw             text,
        major_raw              text,
        degree_raw             text,
        start_year             integer,
        end_year               integer,
        institution_id         uuid REFERENCES institution,
        major_taxonomy_node_id uuid REFERENCES taxonomy_node,
        created_at             timestamptz NOT NULL DEFAULT now(),
        UNIQUE (import_attempt_id, ordinal)
    );
    CREATE INDEX import_experience_created_idx ON import_experience (created_at);
    CREATE INDEX import_education_created_idx ON import_education (created_at);
    ALTER TABLE import_experience ENABLE ROW LEVEL SECURITY;
    ALTER TABLE import_education ENABLE ROW LEVEL SECURITY;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE import_education;
    DROP TABLE import_experience;
    ALTER TABLE import_attempt DROP COLUMN stats_consent_version;
    """)
