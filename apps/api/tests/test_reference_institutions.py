"""Migration 0032: every Korean university and junior college (public data) can be picked, and
a short name the reference list derives (삼육대) finds its school."""
from fastapi.testclient import TestClient
from sqlalchemy import text

from hellomyme.ingest.pipeline import _lookup
from hellomyme.main import create_app


def test_public_school_list_is_loaded_with_short_names(engine):
    with engine.begin() as conn:
        n, levels = conn.execute(text(
            """SELECT count(*), count(DISTINCT school_level) FROM institution
               WHERE school_level IS NOT NULL""")).one()
        sahmyook = conn.execute(text(
            """SELECT institution_id::text, region, school_level FROM institution
               WHERE name = '삼육대학교'""")).one()
        assert _lookup(conn, "INSTITUTION", "삼육대") == sahmyook.institution_id
        assert _lookup(conn, "INSTITUTION", "고려대 (세종)") != _lookup(conn, "INSTITUTION", "고려대")
    assert n >= 400 and levels == 2
    assert (sahmyook.region, sahmyook.school_level) == ("서울", "UNIVERSITY")

    listed = TestClient(create_app()).get("/acq/options/institutions").json()
    row = next(i for i in listed if i["name"] == "삼육대학교")
    assert "삼육대" in row["aliases"]
