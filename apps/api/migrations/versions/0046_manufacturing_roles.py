"""Manufacturing roles in the active ROLE taxonomy (owner decision 2026-10-26).

The first member who came in through /alert works in outsourced purchasing at a manufacturer; the role
list (22 roles, office and IT work) had nothing near it, so the read put "운영". This adds a 제조·생산
branch next to the existing ones: 구매·SCM, 생산·품질, 설비·안전, 설계·하드웨어 and eight roles under
them, each with the titles people write in resumes as aliases (the reader's deterministic match).

Additive only: existing nodes are not moved or renamed (a changed structure needs a new taxonomy
version, migration 0012), and records already saved keep the role their person confirmed. The new
roles have no PRE_SEED people, so results for them stay below the small-cohort threshold until SEED
records arrive. Nothing happens when no ROLE taxonomy is active yet (a fresh database). Codes use
their own prefix (ROLE_M..) so a later PRE_SEED version cannot collide with them.

Revision ID: 0046
Revises: 0045
"""
import json

from alembic import op
from sqlalchemy import text

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

SOURCE = "MIGRATION_0046"
ROOT = ("ROLE_M00", "제조·생산")
# (group code, group name, [(role code, role name, aliases)]). No bare "QA" or "유지보수": in
# software they mean testing and maintenance work, and an alias must point one way only.
BRANCHES = [
    ("ROLE_M10", "구매·SCM", [
        ("ROLE_M11", "구매/조달", ["구매", "조달", "구매담당", "구매관리", "외주구매", "협력사 관리",
                                "협력업체 관리", "소싱", "purchasing", "procurement"]),
        ("ROLE_M12", "물류/SCM", ["물류", "SCM", "공급망 관리", "자재관리", "재고관리", "물류관리",
                                "logistics", "supply chain"]),
    ]),
    ("ROLE_M20", "생산·품질", [
        ("ROLE_M21", "생산관리", ["생산관리", "생산계획", "생산 관리자", "production planning",
                              "production manager"]),
        ("ROLE_M22", "품질관리/품질보증", ["품질관리", "품질보증", "품질경영", "QC", "품질 엔지니어",
                                     "quality assurance", "quality control"]),
        ("ROLE_M23", "생산기술/공정", ["생산기술", "공정기술", "공정 엔지니어", "제조기술", "공정개발",
                                  "process engineer"]),
    ]),
    ("ROLE_M30", "설비·안전", [
        ("ROLE_M31", "설비/보전", ["설비", "설비보전", "설비관리", "설비 엔지니어", "maintenance engineer"]),
        ("ROLE_M32", "환경/안전", ["환경안전", "안전관리", "EHS", "HSE", "산업안전", "보건관리", "환경관리"]),
    ]),
    ("ROLE_M40", "설계·하드웨어", [
        ("ROLE_M41", "기구/하드웨어 설계", ["기구설계", "기계설계", "회로설계", "전기설계", "하드웨어 설계",
                                      "하드웨어 엔지니어", "mechanical engineer", "hardware engineer"]),
    ]),
]


def add_roles(conn) -> int:
    """Adds the branch to the active ROLE taxonomy; returns how many nodes were new (0 on a rerun)."""
    taxonomy = conn.execute(text(
        "SELECT taxonomy_id FROM taxonomy WHERE taxonomy_type = 'ROLE' AND status = 'ACTIVE'")).scalar()
    if taxonomy is None:
        return 0
    last = conn.execute(text("SELECT coalesce(max(sort_order), 0) FROM taxonomy_node WHERE taxonomy_id = :t"),
                        {"t": taxonomy}).scalar_one()
    added = 0

    def node(code: str, name: str, parent, order: int):
        nonlocal added
        added += conn.execute(text(
            """INSERT INTO taxonomy_node (taxonomy_id, parent_node_id, code, canonical_name, display_name,
                   depth, sort_order, metadata)
               VALUES (:t, :p, :c, :n, :n, 1, :o, CAST(:m AS jsonb))
               ON CONFLICT (taxonomy_id, code) DO NOTHING"""),
            {"t": taxonomy, "p": parent, "c": code, "n": name, "o": order,
             "m": json.dumps({"source": SOURCE})}).rowcount
        return conn.execute(text("SELECT taxonomy_node_id FROM taxonomy_node WHERE taxonomy_id = :t AND code = :c"),
                            {"t": taxonomy, "c": code}).scalar_one()

    order = last + 1
    root = node(*ROOT, None, order)
    for group_code, group_name, roles in BRANCHES:
        order += 1
        group = node(group_code, group_name, root, order)
        for code, name, aliases in roles:
            order += 1
            leaf = node(code, name, group, order)
            for alias in aliases:
                conn.execute(text(
                    """INSERT INTO taxonomy_alias (taxonomy_node_id, alias_text, source_type)
                       VALUES (:n, :a, :s) ON CONFLICT (taxonomy_node_id, alias_text, locale) DO NOTHING"""),
                    {"n": leaf, "a": alias, "s": SOURCE})
    return added


def upgrade() -> None:
    add_roles(op.get_bind())


def downgrade() -> None:
    # Only while nothing points at the new roles; a saved record keeps them (and stops this).
    op.execute("""
    DELETE FROM taxonomy_alias WHERE source_type = 'MIGRATION_0046';
    DELETE FROM taxonomy_node WHERE metadata->>'source' = 'MIGRATION_0046' AND depth = 3;
    DELETE FROM taxonomy_node WHERE metadata->>'source' = 'MIGRATION_0046' AND depth = 2;
    DELETE FROM taxonomy_node WHERE metadata->>'source' = 'MIGRATION_0046' AND depth = 1;
    """)
