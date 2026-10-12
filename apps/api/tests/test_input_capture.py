"""Every answer is kept (migration 0026): draft history, desired roles, the statistics views,
and linking on login without duplicates."""
import uuid

from sqlalchemy import text

from tests.test_acquisition import anon, client, login, save, student  # noqa: F401
from tests.test_career_query import ids  # noqa: F401


def post(client, h, payload, draft_id=None, internal=False):  # noqa: F811
    r = client.post("/acq/draft", headers=h,
                    json={"draft_id": draft_id, "payload": payload, "internal": internal})
    return r


def merge(client, h, draft, subject):  # noqa: F811
    auth = login(client, subject)
    r = client.post("/auth/merge-draft", headers={**auth, **h, "Idempotency-Key": uuid.uuid4().hex},
                    json={"draft_id": draft, "consent_policy_version": "career_terms_v1"})
    assert r.status_code == 200, r.text
    return auth, r.json()


def test_edits_are_new_revisions_and_nothing_is_overwritten(client, engine, ids):  # noqa: F811
    h = anon()
    first = post(client, h, student(ids), internal=True).json()
    assert first["revision"] == 1
    same = post(client, h, student(ids), first["draft_id"]).json()
    assert same["revision"] == 1  # the same answer again is not a new version
    changed = {**student(ids), "education": {**student(ids)["education"], "graduation_year": 2021}}
    assert post(client, h, changed, first["draft_id"]).json()["revision"] == 2
    with engine.begin() as conn:
        revs = conn.execute(text(
            """SELECT revision, (payload_json->'education'->>'graduation_year')::int
               FROM anonymous_draft_revision WHERE draft_id = :d ORDER BY 1"""),
            {"d": first["draft_id"]}).all()
        row = conn.execute(text(
            "SELECT internal, graduation_year FROM analytics.acq_input WHERE draft_id = :d"),
            {"d": first["draft_id"]}).one()
    assert [tuple(r) for r in revs] == [(1, 2020), (2, 2021)]
    assert tuple(row) == (True, 2021)  # internal sticks once set


def test_desired_roles_listed_typed_none_and_skipped(client, engine, ids):  # noqa: F811
    h = anon()
    chosen = {**student(ids), "desired_roles": [
        {"role_node_id": ids["R2B"]}, {"role_raw": "마케팅"}, {"role_raw": " 우주비행사 "},
        {"role_node_id": ids["R2B"]}]}
    assert post(client, h, chosen).status_code == 422  # at most three
    chosen["desired_roles"] = chosen["desired_roles"][:3]
    body = post(client, h, chosen).json()
    assert body["payload"]["desired_role_status"] == "CHOSEN"
    roles = body["payload"]["desired_roles"]
    assert [r["role_node_id"] for r in roles] == [ids["R2B"], ids["R2"], None]  # typed name matched
    assert roles[1]["role_raw"] == "마케팅" and roles[2]["role_raw"] == "우주비행사"

    none = post(client, anon(), {**student(ids), "desired_role_status": "NONE"}).json()
    skipped = post(client, anon(), student(ids)).json()
    assert skipped["payload"]["desired_role_status"] is None  # skipped is not "none"
    for bad in ({"desired_role_status": "KEEP_CURRENT"},  # only for professionals
                {"desired_role_status": "NONE", "desired_roles": [{"role_raw": "x"}]},
                {"desired_role_status": "CHOSEN"},
                {"desired_roles": [{"role_node_id": "00000000-0000-0000-0000-000000000000"}]}):
        assert post(client, anon(), {**student(ids), **bad}).status_code == 422, bad

    with engine.begin() as conn:
        listed = conn.execute(text(
            """SELECT rank, role_listed, role_raw FROM analytics.acq_desired_role
               WHERE draft_id = :d ORDER BY rank"""), {"d": body["draft_id"]}).all()
        status = dict(conn.execute(text(
            """SELECT draft_id::text, desired_role_status FROM analytics.acq_input
               WHERE draft_id IN (:a, :b)"""),
            {"a": none["draft_id"], "b": skipped["draft_id"]}).all())
    assert [tuple(r) for r in listed] == [(1, True, None), (2, True, "마케팅"), (3, False, "우주비행사")]
    assert status == {none["draft_id"]: "NONE", skipped["draft_id"]: None}


def test_unlisted_names_are_counted_by_people_and_spelling(client, engine, ids):  # noqa: F811
    tag = uuid.uuid4().hex[:6]
    for spelling in (f"백로그{tag}대학교", f"백로그{tag}대", f" 백로그{tag} 대학교"):
        edu = {**student(ids)["education"], "institution_id": None, "institution_raw": spelling}
        assert post(client, anon(), {"user_type": "STUDENT", "education": edu}).status_code == 200
    edu = {**student(ids)["education"], "institution_id": None, "institution_raw": f"백로그{tag}대"}
    post(client, anon(), {"user_type": "STUDENT", "education": edu}, internal=True)  # the team
    with engine.begin() as conn:
        row = conn.execute(text(
            """SELECT people, cardinality(spellings) FROM analytics.acq_unlisted_backlog
               WHERE kind = 'INSTITUTION' AND key = :k"""), {"k": f"백로그{tag}"}).one()
    assert tuple(row) == (3, 3)


def test_login_links_the_draft_once_and_a_returning_member_gets_no_second_profile(
        client, engine, ids):  # noqa: F811
    h = anon()
    first = post(client, h, {**student(ids), "desired_roles": [{"role_node_id": ids["R2B"]}]}).json()
    auth, merged = merge(client, h, first["draft_id"], "capture-member")
    assert merged["merged"] is True
    _, again = merge(client, h, first["draft_id"], "capture-member")  # replayed login
    assert again["merged"] is False and again["person_id"] == merged["person_id"]

    # Back later on another browser with new answers: linked to the same person, nothing doubled.
    h2 = anon()
    later = post(client, h2, {**student(ids), "desired_role_status": "NONE"}).json()
    _, linked = merge(client, h2, later["draft_id"], "capture-member")
    assert linked == {"person_id": merged["person_id"], "merged": False, "linked": True,
                      "rewards": []}
    abandoned = post(client, anon(), student(ids)).json()  # never logs in

    with engine.begin() as conn:
        persons = conn.execute(text("SELECT count(*) FROM person WHERE account_id = "
                                    "(SELECT claimed_account_id FROM anonymous_draft "
                                    " WHERE draft_id = :d)"), {"d": first["draft_id"]}).scalar()
        desired = conn.execute(text(
            """SELECT status, rank FROM desired_role WHERE person_id = :p
               ORDER BY captured_at, rank"""), {"p": merged["person_id"]}).all()
        claims = dict(conn.execute(text(
            """SELECT draft_id::text, claimed_person_id::text FROM anonymous_draft
               WHERE draft_id IN (:a, :b, :c)"""),
            {"a": first["draft_id"], "b": later["draft_id"], "c": abandoned["draft_id"]}).all())
        consents = conn.execute(text(
            """SELECT count(*) FROM data_consent WHERE account_id =
                   (SELECT claimed_account_id FROM anonymous_draft WHERE draft_id = :d)
                 AND policy_version = 'career_terms_v1' AND status = 'GRANTED'"""),
            {"d": first["draft_id"]}).scalar()
    assert persons == 1
    assert [tuple(r) for r in desired] == [("CHOSEN", 1), ("NONE", 1)]
    assert claims == {first["draft_id"]: merged["person_id"], later["draft_id"]: merged["person_id"],
                      abandoned["draft_id"]: None}
    assert consents == 4  # two consents for each linked draft
    assert client.get("/acq/me", headers=auth).status_code == 200
