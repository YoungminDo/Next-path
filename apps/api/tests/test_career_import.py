"""Resume / capture import (migration 0030): read before login into the input form, kept only
through the draft and the login merge; members add ticked jobs; limits and consent first."""
import base64
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from hellomyme.api.acquisition import import_extractor
from hellomyme.config import Settings, get_settings
from hellomyme.db import get_engine
from hellomyme.domain.career_import import (
    ExtractedEducation,
    ExtractedExperience,
    Extraction,
    Usage,
)
from hellomyme.main import create_app
from tests.test_acquisition import anon, login, merge, save, step
from tests.test_career_query import ids  # noqa: F401  (module fixture: imports the cohort)

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


def experience(company, title, sy, sm=None, ey=None, em=None, current=False, kind=None):
    return ExtractedExperience(company=company, title=title, employment_type=kind, start_year=sy,
                               start_month=sm, end_year=ey, end_month=em, is_current=current)


RESUME = Extraction(
    is_career_document=True, source_kind="RESUME",
    experiences=[experience("질의컴퍼니", "브랜드 마케팅", 2022, 3, current=True, kind="FULL_TIME"),
                 experience("목록밖회사", "그로스 해커", 2020, 1, 2022, 2),
                 experience("인턴회사", "데이터 분석", 2019, 7, 2019, 12, kind="INTERN"),
                 experience("거꾸로", "브랜드 마케팅", 2018, 5, 2017, 1)],
    education=[ExtractedEducation(school="질의대학교", major="경영학과", degree="학사",
                                  start_year=2016, end_year=2020)])


class Fake:
    model = "fake-reader"

    def __init__(self, result=RESUME, outcome="PARSED"):
        self.result, self.outcome, self.calls, self.held = result, outcome, 0, []

    def extract(self, files):
        self.calls += 1
        # No connection may be checked out while the model reads (a burst would starve the pool).
        self.held.append(get_engine().pool.checkedout())
        return self.result, self.outcome, Usage(input_tokens=4000, output_tokens=600)


def app_with(extractor, **overrides) -> TestClient:
    app = create_app()
    settings = Settings(**{"env": "test", "auth_providers": ["DEV"], **overrides})
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[import_extractor] = lambda: extractor
    return TestClient(app)


def body(files=None, **extra):
    return {"files": files or [{"media_type": "image/png", "data": PNG}], "consent": True,
            "consent_text_version": "career_import_v1", **extra}


def test_off_without_a_key_and_consent_comes_first(ids):  # noqa: F811
    off = app_with(None)
    h = anon()
    assert off.get("/acq/import", headers=h).json()["enabled"] is False
    assert off.post("/acq/import/parse", headers=h, json=body()).status_code == 409

    fake = Fake()
    c = app_with(fake)
    assert c.post("/acq/import/parse", headers=h, json={**body(), "consent": False}).status_code == 422
    assert c.post("/acq/import/parse", headers=h,
                  json=body(consent_text_version="old")).status_code == 409
    bad = c.post("/acq/import/parse", headers=h,
                 json=body([{"media_type": "text/html", "data": PNG}]))
    assert bad.status_code == 422
    big = base64.b64encode(b"0" * 2_600_000).decode()
    assert c.post("/acq/import/parse", headers=h,
                  json=body([{"media_type": "application/pdf", "data": big}])).status_code == 413
    assert fake.calls == 0  # nothing was sent anywhere


def test_read_before_login_prefills_and_the_merge_keeps_it_as_a_resume_source(engine, ids):  # noqa: F811
    fake = Fake()
    c = app_with(fake)
    h = anon()
    r = c.post("/acq/import/parse", headers=h, json=body(internal=True))
    assert r.status_code == 200, r.text
    assert fake.held == [0]
    read = r.json()
    cur, growth, intern, backwards = read["experiences"]
    assert cur["suggested_role_node_id"] == ids["R3"] and cur["start_month"] == 3
    assert growth["suggested_role_node_id"] is None and growth["already_saved"] is False
    assert intern["employment_type"] == "INTERN" and intern["suggested_role_node_id"] == ids["R3B"]
    assert (backwards["end_year"], backwards["end_month"]) == (None, None)  # misread end: unknown
    edu = read["education"][0]
    assert (edu["suggested_institution_id"], edu["suggested_major_node_id"]) == (ids["inst"], ids["M3"])

    # What the form sends after the person checked it (the first job without a role stays a
    # past job with its title as written).
    payload = {
        "user_type": "PROFESSIONAL", "import_attempt_id": read["import_attempt_id"],
        "education": {"institution_id": ids["inst"], "major_node_id": ids["M3"],
                      "admission_year": 2016, "graduation_year": 2020},
        "current_job": {"organization_name": "질의컴퍼니", "role_node_id": ids["R3"],
                        "role_raw": "브랜드 마케팅", "start_year": 2022, "start_month": 3,
                        "employment_type": "FULL_TIME"},
        "other_jobs": [
            {"organization_name": "목록밖회사", "role_raw": "그로스 해커", "start_year": 2020,
             "start_month": 1, "end_year": 2022, "end_month": 2},
            {"organization_name": "인턴회사", "role_raw": "데이터 분석", "role_node_id": ids["R3B"],
             "start_year": 2019, "start_month": 7, "end_year": 2019, "end_month": 12,
             "employment_type": "INTERN"}]}
    # Another browser cannot claim this read for its draft.
    other = anon()
    stolen = c.post("/acq/draft", headers=other, json={"payload": payload}).json()
    assert stolen["payload"]["import_attempt_id"] is None

    draft = save(c, h, payload)
    assert step(c, h, draft, "teaser")["base"]["effective_n"] > 0
    auth, person_id = merge(c, h, draft, "import-anon")
    assert c.get("/acq/me", headers=auth).status_code == 200
    with engine.begin() as conn:
        rows = conn.execute(text(
            """SELECT w.organization_raw, w.role_raw, w.role_taxonomy_node_id::text AS role,
                      w.employment_type, w.start_date, w.start_date_precision, w.end_date,
                      w.end_date_precision, w.is_current, w.normalization_status, s.source_type
               FROM work_event w JOIN work_event_source ws USING (work_event_id)
               JOIN source_record s ON s.source_id = ws.source_id
               WHERE w.person_id = :p ORDER BY w.start_date"""), {"p": person_id}).all()
        queued = set(conn.execute(text(
            """SELECT entity_kind, raw_value FROM mapping_queue
               WHERE raw_value IN ('그로스 해커', '목록밖회사', '인턴회사')""")).all())
        attempt = conn.execute(text(
            "SELECT outcome, source_kind, internal, input_tokens FROM import_attempt "
            "WHERE import_attempt_id = CAST(:i AS uuid)"), {"i": read["import_attempt_id"]}).one()
    assert {r.source_type for r in rows} == {"CAREER_DOCUMENT"}
    intern_row, growth_row, cur_row = rows
    assert (intern_row.employment_type, intern_row.start_date_precision) == ("INTERN", "MONTH")
    assert (growth_row.role, growth_row.role_raw, growth_row.normalization_status) == (
        None, "그로스 해커", "UNMAPPED")
    assert str(growth_row.end_date) == "2022-02-01" and growth_row.end_date_precision == "MONTH"
    assert cur_row.is_current and str(cur_row.start_date) == "2022-03-01"
    assert {("ROLE", "그로스 해커"), ("ORGANIZATION", "목록밖회사"), ("ORGANIZATION", "인턴회사")} <= queued
    assert tuple(attempt) == ("PARSED", "RESUME", True, 4000)


def test_reads_are_limited_and_every_attempt_is_recorded(engine, ids):  # noqa: F811
    with engine.begin() as conn:
        before = conn.execute(text(
            "SELECT count(*) FROM import_attempt WHERE account_id IS NULL "
            "AND created_at > now() - interval '1 day'")).scalar_one()
    c = app_with(Fake(), career_import_session_limit=2, career_import_anonymous_daily_limit=before + 3)
    h = anon()
    assert c.get("/acq/import", headers=h).json()["remaining_today"] == 2
    assert c.post("/acq/import/parse", headers=h, json=body()).status_code == 200
    assert c.post("/acq/import/parse", headers=h, json=body()).status_code == 200
    assert c.post("/acq/import/parse", headers=h, json=body()).status_code == 429  # this session
    other = anon()
    assert c.post("/acq/import/parse", headers=other, json=body()).status_code == 200
    # The ceiling for everyone before login (the cost cap) is reached now.
    assert c.post("/acq/import/parse", headers=anon(), json=body()).status_code == 429
    assert c.get("/acq/import", headers=anon()).json()["remaining_today"] == 0

    not_cv = app_with(Fake(Extraction(is_career_document=False, source_kind="OTHER",
                                      experiences=[], education=[]), "NOT_CAREER"))
    h2 = anon()
    r = not_cv.post("/acq/import/parse", headers={**h2, **login(not_cv, "import-notcv")}, json=body())
    assert r.status_code == 422
    failed = app_with(Fake(None, "FAILED"))
    assert failed.post("/acq/import/parse", headers={**anon(), **login(failed, "import-fail")},
                       json=body()).status_code == 502
    with engine.begin() as conn:
        outcomes = conn.execute(text(
            """SELECT a.outcome FROM import_attempt a JOIN account_identity ai USING (account_id)
               WHERE ai.provider_subject IN ('import-notcv', 'import-fail')
               ORDER BY a.created_at""")).scalars().all()
    assert outcomes == ["NOT_CAREER", "FAILED"]


def test_a_member_adds_the_jobs_they_tick_once(engine, ids):  # noqa: F811
    c = app_with(Fake())
    h = anon()
    payload = {"user_type": "PROFESSIONAL",
               "education": {"institution_id": ids["inst"], "major_node_id": ids["M3"],
                             "admission_year": 2016, "graduation_year": 2020},
               "current_job": {"organization_name": "질의컴퍼니", "role_node_id": ids["R3"],
                               "start_year": 2022}}
    auth, person_id = merge(c, h, save(c, h, payload), "import-member")
    read = c.post("/acq/import/parse", headers={**h, **auth}, json=body()).json()
    assert [x["already_saved"] for x in read["experiences"]] == [True, False, False, False]

    jobs = [{"organization_name": "질의컴퍼니", "role_node_id": ids["R3"], "start_year": 2022,
             "is_current": True},
            {"organization_name": "목록밖회사", "role_raw": "그로스 해커", "start_year": 2020,
             "end_year": 2022}]
    key = {**auth, "Idempotency-Key": uuid.uuid4().hex}
    confirm = {"import_attempt_id": read["import_attempt_id"], "jobs": jobs}
    done = c.post("/acq/me/import/confirm", headers=key, json=confirm).json()
    assert (done["added"], done["skipped"], done["replayed"]) == (1, 1, False)
    assert done["rewards"]
    assert c.post("/acq/me/import/confirm", headers=key, json=confirm).json()["replayed"] is True

    stranger = {**login(c, "import-stranger"), "Idempotency-Key": uuid.uuid4().hex}
    assert c.post("/acq/me/import/confirm", headers=stranger, json=confirm).status_code == 404
    with engine.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM work_event WHERE person_id = :p"),
                         {"p": person_id}).scalar_one()
    assert n == 2


def test_unlock_key_unchanged_by_months_and_resume_fields(ids):  # noqa: F811
    """A professional's key from before months/other jobs existed still matches."""
    from hellomyme.domain.acquisition import AcquisitionPayload, insight_key
    base = {"user_type": "PROFESSIONAL",
            "education": {"institution_id": ids["inst"], "major_node_id": ids["M3"],
                          "admission_year": 2016, "graduation_year": 2020},
            "current_job": {"organization_name": "질의컴퍼니", "role_node_id": ids["R3"],
                            "start_year": 2022}}
    richer = {**base, "current_job": {**base["current_job"], "start_month": 3,
                                      "employment_type": "FULL_TIME"},
              "other_jobs": [{"role_raw": "그로스 해커", "start_year": 2020}]}
    assert insight_key(AcquisitionPayload.model_validate(base), "T") == insight_key(
        AcquisitionPayload.model_validate(richer), "T")
