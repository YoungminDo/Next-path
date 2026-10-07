"""Career input (anonymous draft and member edits): validation, taxonomy normalization, and
writing member-owned VERIFIED career data with provenance."""
from __future__ import annotations

import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Connection, text

from hellomyme.domain.aggregation import Event, build_person
from hellomyme.domain.similarity import Profile

EventType = Literal["EMPLOYMENT", "STARTUP", "SIDE_BUSINESS", "SELF_EMPLOYED", "FREELANCE",
                    "STUDY", "CAREER_BREAK", "MILITARY", "PROJECT", "OTHER"]
UserType = Literal["STUDENT", "JOB_SEEKER", "PROFESSIONAL"]


class EducationInput(BaseModel):
    institution_id: str | None = None
    institution_name: str | None = Field(default=None, max_length=200)
    major_id: str | None = None
    major_name: str | None = Field(default=None, max_length=200)
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)
    degree_type: Literal["ASSOCIATE", "BACHELOR", "MASTER", "DOCTORATE", "OTHER"] | None = None


class CareerEventInput(BaseModel):
    event_type: EventType
    organization_id: str | None = None
    organization_name: str | None = Field(default=None, max_length=200)
    role_id: str | None = None
    role_name: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None

    @model_validator(mode="after")
    def _consistent(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if self.is_current and self.end_date:
            raise ValueError("a current event cannot have an end_date")
        return self


class CareerDraftPayload(BaseModel):
    user_type: UserType
    education: EducationInput | None = None
    interested_role_id: str | None = None
    interested_job_family: str | None = None
    interested_industry: str | None = None
    career_events: list[CareerEventInput] = Field(default_factory=list, max_length=30)


def _lookup(conn: Connection, table: str, id_value: str | None, name: str | None,
            extra: str = "") -> dict | None:
    cols = f"{table}_id::text AS id, name{extra}"
    if id_value:
        row = conn.execute(text(f"SELECT {cols} FROM {table} WHERE {table}_id::text = :v"),
                           {"v": id_value}).first()
        if row:
            return dict(row._mapping)
    if name:
        row = conn.execute(text(f"SELECT {cols} FROM {table} WHERE name = :n"),
                           {"n": name.strip()}).first()
        if row:
            return dict(row._mapping)
    return None


def normalize(conn: Connection, payload: CareerDraftPayload) -> dict:
    """Map raw input to taxonomy. Unmapped values stay NULL with their raw text kept."""
    edu = None
    if payload.education:
        e = payload.education
        inst = _lookup(conn, "institution", e.institution_id, e.institution_name)
        major = _lookup(conn, "major", e.major_id, e.major_name, ", major_family")
        mapped = [x is not None for x, raw in ((inst, e.institution_id or e.institution_name),
                                               (major, e.major_id or e.major_name)) if raw]
        edu = {
            "institution_raw": e.institution_name or (inst and inst["name"]),
            "institution_id": inst and inst["id"],
            "major_raw": e.major_name or (major and major["name"]),
            "major_id": major and major["id"],
            "major_family": major and major["major_family"],
            "graduation_year": e.graduation_year, "degree_type": e.degree_type,
            "normalization_status": _status(mapped),
        }
    events = []
    for ev in payload.career_events:
        org = _lookup(conn, "organization", ev.organization_id, ev.organization_name,
                      ", industry, company_size_band, is_placeholder")
        role = _lookup(conn, "role", ev.role_id, ev.role_name, ", job_family")
        mapped = [x is not None for x, raw in ((org, ev.organization_id or ev.organization_name),
                                               (role, ev.role_id or ev.role_name)) if raw]
        events.append({
            "event_type": ev.event_type,
            "organization_raw": ev.organization_name or (org and org["name"]),
            "organization_id": org and org["id"], "industry": org and org["industry"],
            "company_size_band": org and org["company_size_band"],
            "is_placeholder": org and org["is_placeholder"],
            "role_raw": ev.role_name or (role and role["name"]),
            "role_id": role and role["id"], "job_family": role and role["job_family"],
            "start_date": ev.start_date, "end_date": ev.end_date, "is_current": ev.is_current,
            "normalization_status": _status(mapped),
            "supported_fields": [f for f, v in (
                ("event_type", ev.event_type), ("organization", ev.organization_id or
                                                ev.organization_name),
                ("role", ev.role_id or ev.role_name), ("start_date", ev.start_date),
                ("end_date", ev.end_date), ("is_current", ev.is_current)) if v is not None],
        })
    return {"user_type": payload.user_type, "education": edu, "events": events}


def _status(mapped: list[bool]) -> str:
    if not mapped or all(mapped):
        return "MAPPED"
    return "PARTIAL" if any(mapped) else "UNMAPPED"


def profile_from_normalized(norm: dict, as_of: date, person_id: str | None = None) -> Profile:
    events = [Event(f"input-{i}", e["event_type"], e["start_date"], e["end_date"],
                    e["is_current"], e["role_id"], e["job_family"], e["organization_id"],
                    e["industry"], e["company_size_band"], e["is_placeholder"])
              for i, e in enumerate(norm["events"]) if e["start_date"] and e["start_date"] <= as_of]
    return _to_profile(person_id, norm["education"], events, as_of, norm["user_type"])


def _to_profile(person_id, edu, events, as_of, declared_stage=None) -> Profile:
    snap, _ = build_person({"person_id": person_id, "origin_layer": "VERIFIED"},
                           {"institution_id": edu and edu["institution_id"],
                            "major_id": edu and edu["major_id"],
                            "major_family": edu and edu["major_family"],
                            "graduation_year": edu and edu["graduation_year"]} if edu else None,
                           events, as_of)
    stage = snap["derived_stage"]
    if declared_stage == "STUDENT" and not snap["current_job_family"]:
        stage = "STUDENT"
    return Profile(
        person_id=person_id, institution_id=snap["institution_id"], major_id=snap["major_id"],
        major_family=snap["major_family"], graduation_year=snap["graduation_year"],
        current_job_family=snap["current_job_family"], current_role_id=snap["current_role_id"],
        current_industry=snap["current_industry"],
        current_company_size_band=snap["current_company_size_band"],
        current_event_type=snap["current_event_type"],
        job_family_sequence=tuple(snap["job_family_sequence"]), derived_stage=stage)


def member_person_id(conn: Connection, account_id: str) -> str | None:
    return conn.execute(text(
        "SELECT person_id::text FROM person WHERE account_id = :a AND deleted_at IS NULL"),
        {"a": account_id}).scalar()


def member_profile(conn: Connection, person_id: str, as_of: date) -> Profile:
    edu = conn.execute(text(
        """SELECT e.institution_id::text, e.major_id::text, m.major_family, e.graduation_year
           FROM canonical_education e LEFT JOIN major m USING (major_id)
           WHERE e.person_id = :p ORDER BY e.graduation_year DESC NULLS LAST LIMIT 1"""),
        {"p": person_id}).first()
    events = [Event(r.work_event_id, r.event_type, r.start_date, r.end_date, r.is_current,
                    r.role_id, r.job_family, r.organization_id, r.industry, r.company_size_band,
                    r.is_placeholder)
              for r in conn.execute(text(
                  """SELECT w.work_event_id::text, w.event_type, w.start_date, w.end_date,
                            w.is_current, w.role_id::text, r.job_family, w.organization_id::text,
                            o.industry, o.company_size_band, o.is_placeholder
                     FROM canonical_work_event w LEFT JOIN role r USING (role_id)
                     LEFT JOIN organization o USING (organization_id)
                     WHERE w.person_id = :p AND w.start_date IS NOT NULL
                       AND w.start_date <= :as_of"""), {"p": person_id, "as_of": as_of})]
    declared = conn.execute(text("SELECT declared_stage FROM person WHERE person_id = :p"),
                            {"p": person_id}).scalar()
    return _to_profile(person_id, dict(edu._mapping) if edu else None, events, as_of, declared)


def write_member_career(conn: Connection, account_id: str, norm: dict, source_key: str,
                        raw_payload: dict) -> dict:
    """Create the member's VERIFIED person + SELF_REPORTED education/events with provenance.
    Returns ids so callers can attach rewards to concrete contributions."""
    source_id = conn.execute(text(
        """INSERT INTO source_record (source_type, data_layer, source_system, source_key,
               raw_payload, normalized_payload, legal_basis)
           VALUES ('MANUAL_INPUT', 'VERIFIED', 'HELLOMYME_APP', :k, CAST(:raw AS jsonb),
                   CAST(:norm AS jsonb), 'MEMBER_CONSENT')
           ON CONFLICT (source_system, source_key) DO NOTHING
           RETURNING source_id::text"""),
        {"k": source_key, "raw": json.dumps(raw_payload, default=str, ensure_ascii=False),
         "norm": json.dumps(norm, default=str, ensure_ascii=False)}).scalar()
    if source_id is None:
        raise RuntimeError(f"source {source_key} already written")

    person_id = member_person_id(conn, account_id)
    if person_id is None:
        person_id = conn.execute(text(
            """INSERT INTO person (account_id, origin_layer, declared_stage, primary_source_id,
                   last_verified_at)
               VALUES (:a, 'VERIFIED', :stage, :src, now()) RETURNING person_id::text"""),
            {"a": account_id, "stage": norm["user_type"], "src": source_id}).scalar_one()

    out = {"person_id": person_id, "source_id": source_id, "education_id": None,
           "work_event_ids": [], "current_work_event_ids": []}
    edu = norm["education"]
    if edu:
        out["education_id"] = conn.execute(text(
            """INSERT INTO education (person_id, institution_raw, institution_id, major_raw,
                   major_id, degree_type, graduation_year, data_layer, verification_level,
                   normalization_status, last_verified_at)
               VALUES (:p, :ir, :iid, :mr, :mid, :deg, :gy, 'VERIFIED', 'SELF_REPORTED', :ns,
                       now())
               RETURNING education_id::text"""),
            {"p": person_id, "ir": edu["institution_raw"], "iid": edu["institution_id"],
             "mr": edu["major_raw"], "mid": edu["major_id"], "deg": edu["degree_type"],
             "gy": edu["graduation_year"], "ns": edu["normalization_status"]}).scalar_one()
        fields = [f for f, k in (("institution", "institution_raw"), ("major", "major_raw"),
                                 ("degree_type", "degree_type"),
                                 ("graduation_year", "graduation_year")) if edu[k] is not None]
        if fields:
            conn.execute(text(
                """INSERT INTO education_source (education_id, source_id, supported_fields,
                       is_primary) VALUES (:e, :s, :f, true)"""),
                {"e": out["education_id"], "s": source_id, "f": fields})
        _log(conn, "EDUCATION", out["education_id"], account_id, source_id, fields)

    for ev in norm["events"]:
        weid = conn.execute(text(
            """INSERT INTO work_event (person_id, event_type, organization_raw, organization_id,
                   role_raw, role_id, start_date, start_date_precision, end_date,
                   end_date_precision, is_current, data_layer, verification_level,
                   normalization_status, last_verified_at)
               VALUES (:p, :t, :or, :oid, :rr, :rid, :sd, :sp, :ed, :ep, :cur, 'VERIFIED',
                       'SELF_REPORTED', :ns, now())
               RETURNING work_event_id::text"""),
            {"p": person_id, "t": ev["event_type"], "or": ev["organization_raw"],
             "oid": ev["organization_id"], "rr": ev["role_raw"], "rid": ev["role_id"],
             "sd": ev["start_date"], "sp": "DAY" if ev["start_date"] else None,
             "ed": ev["end_date"], "ep": "DAY" if ev["end_date"] else None,
             "cur": ev["is_current"], "ns": ev["normalization_status"]}).scalar_one()
        conn.execute(text(
            """INSERT INTO work_event_source (work_event_id, source_id, supported_fields,
                   is_primary) VALUES (:w, :s, :f, true)"""),
            {"w": weid, "s": source_id, "f": ev["supported_fields"]})
        _log(conn, "WORK_EVENT", weid, account_id, source_id, ev["supported_fields"])
        out["work_event_ids"].append(weid)
        if ev["is_current"]:
            out["current_work_event_ids"].append(weid)
    return out


def _log(conn, entity_type, entity_id, account_id, source_id, fields) -> None:
    conn.execute(text(
        """INSERT INTO verification_log (entity_type, entity_id, account_id, action,
               verified_fields, source_id, new_level)
           VALUES (:t, :e, :a, 'SELF_REPORTED', :f, :s, 'SELF_REPORTED')"""),
        {"t": entity_type, "e": entity_id, "a": account_id, "f": fields, "s": source_id})


def reconfirm_work_event(conn: Connection, account_id: str, work_event_id: str) -> dict | None:
    """Member reconfirms an event: refresh last_verified_at, keep history in verification_log."""
    row = conn.execute(text(
        """SELECT w.verification_level FROM canonical_work_event w JOIN person p USING (person_id)
           WHERE w.work_event_id = :w AND p.account_id = :a"""),
        {"w": work_event_id, "a": account_id}).first()
    if row is None:
        return None
    conn.execute(text(
        """UPDATE work_event SET verification_level = 'SELF_RECONFIRMED', last_verified_at = now()
           WHERE work_event_id = :w"""), {"w": work_event_id})
    verification_id = conn.execute(text(
        """INSERT INTO verification_log (entity_type, entity_id, account_id, action,
               previous_level, new_level)
           VALUES ('WORK_EVENT', :w, :a, 'SELF_RECONFIRMED', :prev, 'SELF_RECONFIRMED')
           RETURNING verification_id::text"""),
        {"w": work_event_id, "a": account_id, "prev": row.verification_level}).scalar_one()
    return {"work_event_id": work_event_id, "verification_id": verification_id}
