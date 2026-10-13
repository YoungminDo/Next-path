"""Every Korean university and junior college as a reference institution (public data).

Source: 공공데이터포털 '전국대학및전문대학정보표준데이터' (교육부·대학알리미), fetched 2026-05-21;
built into hellomyme/reference/kr_institutions.csv by scripts/build_kr_institutions.py. These are
reference rows (names a person can pick), not career data: a school with no records yet answers
through the cohort's dimension fallback, said in the basis line.

- institution: name_en, school_level (UNIVERSITY / JUNIOR_COLLEGE), school_kind (as published,
  e.g. 교육대학, 기능대학). Existing rows keep their region and type; only empty new columns fill.
- institution_alias: rule-based short names (삼육대학교 -> 삼육대), source_type PUBLIC_DATA.

Revision ID: 0032
Revises: 0031
"""
import csv
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

VERSION = "kr_public_univ_2026_05"
CSV = Path(__file__).resolve().parents[2] / "hellomyme" / "reference" / "kr_institutions.csv"


def _rows() -> list[dict]:
    with open(CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def upgrade() -> None:
    op.execute("""
    ALTER TABLE institution
        ADD COLUMN name_en text,
        ADD COLUMN school_level text CHECK (school_level IN ('UNIVERSITY','JUNIOR_COLLEGE')),
        ADD COLUMN school_kind text;
    """)
    conn = op.get_bind()
    tv = conn.execute(sa.text(
        """INSERT INTO taxonomy_version (taxonomy, version, description)
           VALUES ('INSTITUTION', :v, :d)
           ON CONFLICT (taxonomy, version) DO UPDATE SET description = EXCLUDED.description
           RETURNING taxonomy_version_id"""),
        {"v": VERSION, "d": "공공데이터포털 전국대학및전문대학정보표준데이터 (fetched 2026-05-21)"}).scalar_one()
    rows = _rows()
    conn.execute(sa.text(
        """INSERT INTO institution (name, region, institution_type, taxonomy_version_id, name_en,
               school_level, school_kind)
           VALUES (:name, :region, NULLIF(:institution_type, ''), :tv, NULLIF(:name_en, ''),
                   :school_level, :school_kind)
           ON CONFLICT (name) DO UPDATE SET
               name_en = coalesce(institution.name_en, EXCLUDED.name_en),
               school_level = coalesce(institution.school_level, EXCLUDED.school_level),
               school_kind = coalesce(institution.school_kind, EXCLUDED.school_kind)"""),
        [{**r, "tv": tv} for r in rows])
    aliases = [{"name": r["name"], "alias": a} for r in rows for a in r["aliases"].split("|") if a]
    conn.execute(sa.text(
        """INSERT INTO institution_alias (institution_id, alias_text, source_type)
           SELECT institution_id, :alias, 'PUBLIC_DATA' FROM institution WHERE name = :name
           ON CONFLICT (institution_id, alias_text) DO NOTHING"""), aliases)


def downgrade() -> None:
    op.execute(f"""
    DELETE FROM institution_alias WHERE source_type = 'PUBLIC_DATA';
    DELETE FROM institution i
     USING taxonomy_version tv
     WHERE i.taxonomy_version_id = tv.taxonomy_version_id AND tv.version = '{VERSION}'
       AND NOT EXISTS (SELECT 1 FROM education e WHERE e.institution_id = i.institution_id)
       AND NOT EXISTS (SELECT 1 FROM entity_key_map k WHERE k.entity_id = i.institution_id);
    ALTER TABLE institution DROP COLUMN name_en, DROP COLUMN school_level, DROP COLUMN school_kind;
    """)
