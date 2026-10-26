"""Migration 0046: the manufacturing branch joins the active ROLE taxonomy once, under its own codes,
and resume titles reach the new roles through their aliases."""
import importlib.util

from sqlalchemy import text

from hellomyme.ingest.pipeline import _lookup
from tests.conftest import API_DIR
from tests.test_career_query import ids  # noqa: F401  (module fixture: an active ROLE taxonomy)

spec = importlib.util.spec_from_file_location(
    "m0046", API_DIR / "migrations" / "versions" / "0046_manufacturing_roles.py")
m0046 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m0046)


def test_branch_is_added_once_and_titles_find_it(engine, ids):  # noqa: F811
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            assert m0046.add_roles(conn) == 13  # 1 branch, 4 groups, 8 roles
            assert m0046.add_roles(conn) == 0  # a rerun changes nothing
            rows = conn.execute(text(
                """SELECT n.code, n.depth, p.code AS parent FROM taxonomy_node n
                   JOIN taxonomy t USING (taxonomy_id)
                   LEFT JOIN taxonomy_node p ON p.taxonomy_node_id = n.parent_node_id
                   WHERE t.taxonomy_type = 'ROLE' AND t.status = 'ACTIVE' AND n.code LIKE 'ROLE_M%'""")).all()
            by_code = {r.code: (r.depth, r.parent) for r in rows}
            assert by_code["ROLE_M00"] == (1, None)
            assert by_code["ROLE_M10"] == (2, "ROLE_M00") and by_code["ROLE_M11"] == (3, "ROLE_M10")
            assert sum(1 for d, _ in by_code.values() if d == 3) == 8

            leaf = conn.execute(text(
                "SELECT taxonomy_node_id::text FROM taxonomy_node WHERE code = 'ROLE_M11'")).scalar()
            assert _lookup(conn, "ROLE", "외주구매") == leaf
            assert _lookup(conn, "ROLE", "협력업체관리") == leaf  # spacing does not matter
            assert _lookup(conn, "ROLE", "QA") is None  # software testing stays unclaimed
        finally:
            tx.rollback()


def test_nothing_without_an_active_role_taxonomy(engine, ids):  # noqa: F811
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("UPDATE taxonomy SET status = 'DRAFT' WHERE taxonomy_type = 'ROLE'"))
            assert m0046.add_roles(conn) == 0
        finally:
            tx.rollback()
