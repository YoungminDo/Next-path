"""Acquisition flows (docs/07_SERVICE_DESIGN.html §5): student and professional, before login.

Anonymous input builds a career profile step by step in anonymous_draft (schema acq_v1). Each
step returns a real, already computed result from the v1.4 query engine, so the login wall can
show proof that the answer exists. On login the draft is written once into PERSON / EDUCATION /
WORK_EVENT / INTENT_EVENT (idempotent) and the awaited result is served from the member's own
records, so nothing is entered twice.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Connection, text

from hellomyme.domain.career_query import (
    FIRST_EMPLOYMENT_RULE,
    STAYED,
    CareerQuery,
    Filters,
    QueryInvalid,
    Taxonomy,
    active_cohort_policy_v2,
    cohort_sql,
    evaluate_with_filters,
    load_taxonomy,
    surface_depth,
)

SCHEMA = "acq_v1"
SURFACE = "ACQUISITION"
INTENT_SIGNAL = "ACQUISITION_INTENT"
PATH_EVENT_EXCLUDED = ("STUDY", "MILITARY", "CAREER_BREAK")
DISCLOSED_GENDERS = ("MALE", "FEMALE", "OTHER")


class AcqEducation(BaseModel):
    institution_id: str
    major_node_id: str
    major_raw: str | None = Field(default=None, max_length=200)
    admission_year: int = Field(ge=1950, le=2100)
    graduation_year: int = Field(ge=1950, le=2100)

    @model_validator(mode="after")
    def _order(self):
        if self.admission_year > self.graduation_year:
            raise ValueError("admission_year must not be after graduation_year")
        return self


class AcqJob(BaseModel):
    organization_id: str | None = None
    organization_name: str | None = Field(default=None, max_length=200)
    role_node_id: str
    role_raw: str | None = Field(default=None, max_length=200)
    start_year: int = Field(ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)


class AcqIntent(BaseModel):
    surface: Literal["STUDENT_FIRST_ROLE", "PROFESSIONAL_NEXT_ROLE"]
    target_kind: Literal["ROLE", "UNDECIDED"]
    target_node_id: str | None = None
    captured_at: datetime | None = None

    @model_validator(mode="after")
    def _target(self):
        if (self.target_kind == "ROLE") != bool(self.target_node_id):
            raise ValueError("ROLE intent needs target_node_id; UNDECIDED must not have one")
        return self


class AcquisitionPayload(BaseModel):
    schema_version: Literal["acq_v1"] = SCHEMA
    user_type: Literal["STUDENT", "JOB_SEEKER", "PROFESSIONAL"]
    education: AcqEducation | None = None
    current_job: AcqJob | None = None
    first_job: AcqJob | None = None
    first_job_is_current: bool = False
    gender_code: Literal["MALE", "FEMALE", "OTHER", "UNDISCLOSED"] | None = None
    intents: list[AcqIntent] = Field(default_factory=list, max_length=10)

    @property
    def is_professional(self) -> bool:
        return self.user_type == "PROFESSIONAL"

    def stamp_intents(self, now: datetime) -> AcquisitionPayload:
        """The server, not the client, says when an intent was captured."""
        for i in self.intents:
            if i.captured_at is None:
                i.captured_at = now
        return self

    def latest_intent(self) -> AcqIntent | None:
        return self.intents[-1] if self.intents else None


def is_acquisition_payload(payload: dict) -> bool:
    return isinstance(payload, dict) and payload.get("schema_version") == SCHEMA


# --- options (autocomplete) ---------------------------------------------------------------

def institutions(conn: Connection) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(text(
        "SELECT institution_id::text AS id, name, region FROM institution WHERE is_active "
        "ORDER BY name"))]


def taxonomy_options(conn: Connection, taxonomy_type: str, q: str | None, depth: int | None,
                     limit: int = 30) -> list[dict]:
    """Nodes of the active taxonomy, matched on display name or alias (raw text seen before)."""
    rows = conn.execute(text(
        """SELECT n.taxonomy_node_id::text AS node_id, n.code, n.display_name AS label, n.depth,
                  p.display_name AS parent_label,
                  (SELECT a.alias_text FROM taxonomy_alias a
                    WHERE a.taxonomy_node_id = n.taxonomy_node_id AND a.status = 'ACTIVE'
                      AND CAST(:q AS text) IS NOT NULL
                      AND a.normalized_alias LIKE '%' || normalize_label(:q) || '%'
                    ORDER BY length(a.alias_text) LIMIT 1) AS matched_alias
           FROM taxonomy t JOIN taxonomy_node n USING (taxonomy_id)
           LEFT JOIN taxonomy_node p ON p.taxonomy_node_id = n.parent_node_id
           WHERE t.taxonomy_type = :t AND t.status = 'ACTIVE' AND n.status = 'ACTIVE'
             AND (CAST(:d AS integer) IS NULL OR n.depth = :d)
           ORDER BY n.sort_order, n.display_name"""),
        {"t": taxonomy_type, "q": q or None, "d": depth}).all()
    out = [dict(r._mapping) for r in rows]
    if q:
        needle = q.strip().lower()
        out = [r for r in out if r["matched_alias"] or needle in r["label"].lower()]
    return out[:limit]


def organizations(conn: Connection, q: str | None, limit: int = 20) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(text(
        """SELECT organization_id::text AS id, name FROM organization
           WHERE is_active AND NOT is_placeholder
             AND (CAST(:q AS text) IS NULL OR name ILIKE '%' || :q || '%')
           ORDER BY name LIMIT :l"""), {"q": q or None, "l": limit})]


# --- results ------------------------------------------------------------------------------

def _gender(p: AcquisitionPayload) -> tuple[str, ...]:
    return (p.gender_code,) if p.gender_code in DISCLOSED_GENDERS else ()


def _surface_node(conn: Connection, roles: Taxonomy, node_id: str) -> str:
    if node_id not in roles.nodes:
        raise QueryInvalid(f"unknown role node {node_id}")
    return roles.ancestor_at(node_id, surface_depth(conn, SURFACE, "ROLE", None))


def _require(p: AcquisitionPayload, *parts: str) -> None:
    missing = [x for x in parts if getattr(p, x) is None]
    if missing:
        raise QueryInvalid(f"missing input: {', '.join(missing)}")


def student_first_roles(conn, p: AcquisitionPayload, *, layers, as_of, exclude=()):
    """S2: what similar seniors did first (FIRST_ROLE at the surface depth)."""
    _require(p, "education")
    e = p.education
    return evaluate_with_filters(conn, CareerQuery(
        as_of_date=as_of, target_metric="FIRST_ROLE_DISTRIBUTION", surface_code=SURFACE,
        institution_ids=(e.institution_id,), major_node_ids=(e.major_node_id,),
        admission_year_from=e.admission_year, admission_year_to=e.admission_year,
        graduation_year_from=e.graduation_year, graduation_year_to=e.graduation_year,
        gender_codes=_gender(p), exclude_person_ids=tuple(exclude)), layers=layers)


def professional_next_roles(conn, p: AcquisitionPayload, *, layers, as_of, exclude=(),
                            with_first_job: bool = False):
    """P2 (current role only) and P4 (same first role and current role): the next choice."""
    _require(p, "education", "current_job")
    roles = load_taxonomy(conn, "ROLE")
    current = _surface_node(conn, roles, p.current_job.role_node_id)
    first: tuple[str, ...] = ()
    if with_first_job:
        if p.first_job_is_current or p.first_job is None:
            raise QueryInvalid("first job is needed for similar paths")
        first = (_surface_node(conn, roles, p.first_job.role_node_id),)
    e = p.education
    return evaluate_with_filters(conn, CareerQuery(
        as_of_date=as_of, target_metric="NEXT_ROLE_DISTRIBUTION", surface_code=SURFACE,
        institution_ids=(e.institution_id,), major_node_ids=(e.major_node_id,),
        graduation_year_from=e.graduation_year, graduation_year_to=e.graduation_year,
        gender_codes=_gender(p), from_role_node_ids=(current,), first_role_node_ids=first,
        exclude_person_ids=tuple(exclude)), layers=layers)


def _months(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def paths_to_target(conn: Connection, f: Filters, target_node: str, *, layers, as_of,
                    from_node: str | None = None) -> dict:
    """People in the cohort who reached target (surface depth), the paths they took (role
    sequence from their first job to the target), and how long it took. Paths below the cell
    minimum are folded; the whole result is suppressed below the cell minimum."""
    policy = active_cohort_policy_v2(conn)
    majors, roles = load_taxonomy(conn, "MAJOR"), load_taxonomy(conn, "ROLE")
    depth = surface_depth(conn, SURFACE, "ROLE", None)
    if target_node not in roles.nodes:
        raise QueryInvalid(f"unknown role node {target_node}")
    target = roles.ancestor_at(target_node, depth)
    min_cell = policy.demographic_min_cell_n if f.demographic else policy.min_cell_n
    cohort, params = cohort_sql(f, majors, roles)
    params.update(layers=layers, as_of=as_of, fe_rule=FIRST_EMPLOYMENT_RULE,
                  target=roles.subtree([target]), excluded=list(PATH_EVENT_EXCLUDED))
    rows = conn.execute(text(f"""
        WITH cohort AS ({cohort})
        SELECT w.person_id::text, w.role_taxonomy_node_id::text AS node, w.start_date,
               o.company_size_band, oi.taxonomy_node_id::text AS industry
        FROM canonical_work_event w JOIN cohort c ON c.person_id = w.person_id
        LEFT JOIN organization o ON o.organization_id = w.organization_id
        LEFT JOIN organization_industry oi ON oi.organization_id = w.organization_id
             AND oi.is_primary AND oi.valid_to IS NULL
        WHERE w.start_date IS NOT NULL AND w.start_date <= :as_of
          AND w.event_type <> ALL(:excluded)
          AND EXISTS (SELECT 1 FROM canonical_work_event t
                      WHERE t.person_id = w.person_id AND t.start_date <= :as_of
                        AND t.role_taxonomy_node_id = ANY(CAST(:target AS uuid[])))
        ORDER BY w.person_id, w.start_date, w.work_event_id"""), params).all()

    by_person = defaultdict(list)
    for r in rows:
        by_person[r.person_id].append(r)
    industries = load_taxonomy(conn, "INDUSTRY")
    paths: Counter = Counter()
    months, sizes, inds = [], Counter(), Counter()
    for events in by_person.values():
        seq: list[tuple[str, date]] = []
        hit = None
        for ev in events:
            node = roles.ancestor_at(ev.node, depth) if ev.node in roles.nodes else None
            if node is None:
                continue
            if not seq or seq[-1][0] != node:
                seq.append((node, ev.start_date))
            if node == target:
                hit = ev
                break
        if hit is None:
            continue
        nodes = [n for n, _ in seq]
        if from_node is not None and (from_node not in nodes[:-1]):
            continue
        start = next(d for n, d in seq if n == from_node) if from_node else seq[0][1]
        paths[tuple(nodes)] += 1
        months.append(_months(start, hit.start_date))
        sizes[hit.company_size_band or "UNKNOWN"] += 1
        if hit.industry in industries.nodes:
            inds[industries.ancestor_at(hit.industry, 1)] += 1
        else:
            inds["UNKNOWN"] += 1

    n_people = sum(paths.values())
    suppressed = n_people < min_cell

    def label(node: str) -> str:
        return roles.nodes[node]["label"]

    shown, other = [], 0
    for path, n in sorted(paths.items(), key=lambda kv: (-kv[1], kv[0])):
        if n < min_cell or len(shown) >= policy.top_n:
            other += n
        else:
            shown.append({"path": [{"node_id": x, "label": label(x)} for x in path], "n": n,
                          "share": round(n / n_people, 4)})

    def folded(counter: Counter, name) -> list[dict]:
        out, rest = [], 0
        for k, n in counter.most_common():
            if n < min_cell or k == "UNKNOWN":
                rest += n
            else:
                out.append({"key": k, "label": name(k), "n": n})
        if rest >= min_cell:
            out.append({"key": "OTHER", "label": None, "n": rest})
        return out

    deep = None
    if not suppressed:
        deep = {"company_size": folded(sizes, lambda k: k),
                "industry": folded(inds, lambda k: industries.nodes[k]["label"]
                                   if k in industries.nodes else k)}
        # Only sell a breakdown that shows at least one real category, not just "other".
        if not any(i["key"] != "OTHER" for part in deep.values() for i in part):
            deep = None

    return {
        "target": {"node_id": target, "label": label(target)},
        "from": from_node and {"node_id": from_node, "label": label(from_node)},
        "suppressed": suppressed, "min_cell_n": min_cell,
        "n_people": None if suppressed else n_people,
        "n_paths": None if suppressed else len(paths),
        "n_paths_shown": None if suppressed else len(shown),
        "median_months": None if suppressed or not months else statistics.median(months),
        "paths": [] if suppressed else shown,
        "other_n": None if suppressed else (other if other >= min_cell else None),
        "deep_dive": deep,
        "cohort_policy_version": policy.version, "taxonomy_version": roles.version,
    }


def _intent_target(base: dict, intent: AcqIntent | None) -> tuple[str | None, str]:
    """Explicit target, or for 'not sure yet' the most common real destination."""
    if intent and intent.target_kind == "ROLE":
        return intent.target_node_id, "INTENT"
    for cell in base["cells"]:
        if cell["key"] != STAYED:
            return cell["key"], "MOST_COMMON"
    return None, "NONE"


def result(conn: Connection, p: AcquisitionPayload, step: str, *, layers, as_of,
           exclude=(), full: bool = False) -> dict:
    """One flow step. Teasers (full=False) never include the paths themselves."""
    if step == "first_roles":
        out, _ = student_first_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude)
        return {"step": step, "result": out}
    if step == "next_roles":
        out, _ = professional_next_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude)
        return {"step": step, "result": out}
    if step == "similar_paths":
        out, _ = professional_next_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude,
                                         with_first_job=True)
        return {"step": step, "result": out}
    if step != "intent_paths":
        raise QueryInvalid(f"unknown step {step}")

    cohort_basis = "EDUCATION"
    if p.is_professional:
        cohort_basis = "CURRENT_ROLE"
        base = None
        if p.first_job is not None and not p.first_job_is_current:
            base, eff = professional_next_roles(conn, p, layers=layers, as_of=as_of,
                                                exclude=exclude, with_first_job=True)
            cohort_basis = "FIRST_AND_CURRENT_ROLE"
        if base is None or base["suppressed"]:
            # Too few people share both steps: say so and use the current-role cohort.
            base, eff = professional_next_roles(conn, p, layers=layers, as_of=as_of,
                                                exclude=exclude)
            cohort_basis = "CURRENT_ROLE"
        roles = load_taxonomy(conn, "ROLE")
        from_node = _surface_node(conn, roles, p.current_job.role_node_id)
    else:
        base, eff = student_first_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude)
        from_node = None
    target, basis = _intent_target(base, p.latest_intent())
    if base["suppressed"] or target is None:
        return {"step": step, "base": _summary(base), "cohort_basis": cohort_basis,
                "target_basis": basis, "paths": None}
    paths = paths_to_target(conn, eff, target, layers=layers, as_of=as_of, from_node=from_node)
    if not full:
        paths = {k: v for k, v in paths.items() if k not in ("paths", "deep_dive")}
    return {"step": step, "base": _summary(base), "cohort_basis": cohort_basis,
            "target_basis": basis, "paths": paths}


def _summary(out: dict) -> dict:
    keep = ("effective_n", "exact_n", "fallback_reason", "effective_filters", "suppressed",
            "time_window", "cohort_policy_version", "taxonomy_version")
    return {k: out[k] for k in keep}


def insight_key(p: AcquisitionPayload, target_node: str | None) -> str:
    """Entitlement key: the cohort inputs plus the target, independent of wording/order."""
    basis = p.model_dump(mode="json", exclude={"intents"})
    return hashlib.sha256(json.dumps({"p": basis, "t": target_node}, sort_keys=True)
                          .encode()).hexdigest()


# --- member profile -> payload (post-login, no re-entry) ----------------------------------

def member_payload(conn: Connection, person_id: str, as_of: date) -> AcquisitionPayload | None:
    person = conn.execute(text(
        "SELECT declared_stage, gender_code FROM person WHERE person_id = :p"),
        {"p": person_id}).first()
    edu = conn.execute(text(
        """SELECT institution_id::text, major_taxonomy_node_id::text AS major, major_raw,
                  admission_year, graduation_year
           FROM canonical_education WHERE person_id = :p AND major_taxonomy_node_id IS NOT NULL
             AND institution_id IS NOT NULL AND admission_year IS NOT NULL
             AND graduation_year IS NOT NULL
           ORDER BY graduation_year DESC LIMIT 1"""), {"p": person_id}).first()
    if person is None or edu is None:
        return None

    def job(row) -> AcqJob | None:
        if row is None or row.role is None or row.start_date is None:
            return None
        return AcqJob(organization_id=row.org, organization_name=row.org_raw,
                      role_node_id=row.role, role_raw=row.role_raw,
                      start_year=row.start_date.year,
                      end_year=row.end_date.year if row.end_date else None)

    cols = """w.work_event_id::text AS id, w.organization_id::text AS org,
              w.organization_raw AS org_raw, w.role_taxonomy_node_id::text AS role,
              w.role_raw, w.start_date, w.end_date"""
    current = conn.execute(text(
        f"""SELECT {cols} FROM canonical_work_event w WHERE w.person_id = :p
             AND w.start_date <= :d AND (w.end_date IS NULL OR w.end_date > :d)
             AND w.role_taxonomy_node_id IS NOT NULL
            ORDER BY w.start_date DESC LIMIT 1"""), {"p": person_id, "d": as_of}).first()
    first = conn.execute(text(
        f"""SELECT {cols} FROM first_employment_all(:r, :d) fe
            JOIN work_event w ON w.work_event_id = fe.work_event_id
            WHERE fe.person_id = :p"""),
        {"p": person_id, "d": as_of, "r": FIRST_EMPLOYMENT_RULE}).first()
    intents = conn.execute(text(
        """SELECT source_surface, target_kind, target_taxonomy_node_id::text AS node, captured_at
           FROM intent_event WHERE person_id = :p AND signal_type = :s
           ORDER BY captured_at NULLS FIRST, created_at"""),
        {"p": person_id, "s": INTENT_SIGNAL}).all()
    stage = person.declared_stage or ("PROFESSIONAL" if current else "STUDENT")
    return AcquisitionPayload(
        user_type=stage,
        education=AcqEducation(institution_id=edu.institution_id, major_node_id=edu.major,
                               major_raw=edu.major_raw, admission_year=edu.admission_year,
                               graduation_year=edu.graduation_year),
        current_job=job(current), first_job=job(first),
        first_job_is_current=bool(current and first and current.id == first.id),
        gender_code=person.gender_code if person.gender_code in (*DISCLOSED_GENDERS,
                                                                   "UNDISCLOSED") else None,
        intents=[AcqIntent(surface=i.source_surface, target_kind=i.target_kind,
                           target_node_id=i.node, captured_at=i.captured_at)
                 for i in intents if i.source_surface in ("STUDENT_FIRST_ROLE",
                                                          "PROFESSIONAL_NEXT_ROLE")])


# --- merge (login) ------------------------------------------------------------------------

def write_acquisition_profile(conn: Connection, account_id: str, p: AcquisitionPayload,
                              draft_id: str, raw_payload: dict) -> dict:
    """Write the draft as the member's own SELF_REPORTED records with one source record.
    Unknown stays NULL: years are stored as 1 Jan with YEAR precision, never a guessed day."""
    roles, majors = load_taxonomy(conn, "ROLE"), load_taxonomy(conn, "MAJOR")
    source_key = f"draft:{draft_id}"
    source_id = conn.execute(text(
        """INSERT INTO source_record (source_type, data_layer, source_system, source_key,
               raw_payload, legal_basis)
           VALUES ('MANUAL_INPUT', 'VERIFIED', 'HELLOMYME_APP', :k, CAST(:raw AS jsonb),
                   'MEMBER_CONSENT')
           ON CONFLICT (source_system, source_key) DO NOTHING RETURNING source_id::text"""),
        {"k": source_key, "raw": json.dumps(raw_payload, ensure_ascii=False, default=str)}
    ).scalar()
    if source_id is None:
        raise RuntimeError(f"source {source_key} already written")

    gender = p.gender_code or "UNKNOWN"
    person_id = conn.execute(text(
        """INSERT INTO person (account_id, origin_layer, declared_stage, primary_source_id,
               gender_code, gender_source_id, last_verified_at)
           VALUES (:a, 'VERIFIED', :stage, :src, :g,
                   CASE WHEN :g = 'UNKNOWN' THEN NULL ELSE CAST(:src AS uuid) END, now())
           RETURNING person_id::text"""),
        {"a": account_id, "stage": p.user_type, "src": source_id, "g": gender}).scalar_one()
    out = {"person_id": person_id, "source_id": source_id, "education_id": None,
           "work_event_ids": [], "current_work_event_ids": [], "intent_event_ids": []}

    if p.education:
        e = p.education
        if e.major_node_id not in majors.nodes:
            raise QueryInvalid(f"unknown major node {e.major_node_id}")
        inst_name = conn.execute(text(
            "SELECT name FROM institution WHERE institution_id::text = :i"),
            {"i": e.institution_id}).scalar()
        out["education_id"] = conn.execute(text(
            """INSERT INTO education (person_id, institution_raw, institution_id, major_raw,
                   major_taxonomy_node_id, admission_year, admission_date_precision,
                   graduation_year, graduation_date_precision, data_layer, verification_level,
                   normalization_status, last_verified_at)
               VALUES (:p, :ir, CAST(:iid AS uuid), :mr, CAST(:m AS uuid), :ay, 'YEAR', :gy,
                       'YEAR', 'VERIFIED', 'SELF_REPORTED', :ns, now())
               RETURNING education_id::text"""),
            {"p": person_id, "ir": inst_name, "iid": e.institution_id if inst_name else None,
             "mr": e.major_raw or majors.nodes[e.major_node_id]["label"], "m": e.major_node_id,
             "ay": e.admission_year, "gy": e.graduation_year,
             "ns": "MAPPED" if inst_name else "PARTIAL"}).scalar_one()
        fields = ["institution", "major", "admission_year", "graduation_year"]
        conn.execute(text(
            """INSERT INTO education_source (education_id, source_id, supported_fields, is_primary)
               VALUES (:e, :s, :f, true)"""),
            {"e": out["education_id"], "s": source_id, "f": fields})
        _log(conn, "EDUCATION", out["education_id"], account_id, source_id, fields)

    jobs: list[tuple[AcqJob, bool]] = []
    if p.first_job and not p.first_job_is_current:
        jobs.append((p.first_job, False))
    if p.current_job:
        jobs.append((p.current_job, True))
    for j, current in jobs:
        if j.role_node_id not in roles.nodes:
            raise QueryInvalid(f"unknown role node {j.role_node_id}")
        org = None
        if j.organization_id:
            org = conn.execute(text(
                "SELECT organization_id::text AS id, name FROM organization "
                "WHERE organization_id::text = :o"), {"o": j.organization_id}).first()
        fields = ["event_type", "role", "start_date", "is_current"]
        if org or j.organization_name:
            fields.append("organization")
        if j.end_year and not current:
            fields.append("end_date")
        weid = conn.execute(text(
            """INSERT INTO work_event (person_id, event_type, organization_raw, organization_id,
                   role_raw, role_taxonomy_node_id, start_date, start_date_precision, end_date,
                   end_date_precision, is_current, data_layer, verification_level,
                   normalization_status, last_verified_at)
               VALUES (:p, 'EMPLOYMENT', :or, CAST(:oid AS uuid), :rr, CAST(:r AS uuid), :sd,
                       'YEAR', :ed, :ep, :cur, 'VERIFIED', 'SELF_REPORTED', :ns, now())
               RETURNING work_event_id::text"""),
            {"p": person_id, "or": j.organization_name or (org and org.name),
             "oid": org and org.id, "rr": j.role_raw or roles.nodes[j.role_node_id]["label"],
             "r": j.role_node_id, "sd": date(j.start_year, 1, 1),
             "ed": date(j.end_year, 1, 1) if (j.end_year and not current) else None,
             "ep": "YEAR" if (j.end_year and not current) else None, "cur": current,
             "ns": "MAPPED" if (org or not j.organization_name) else "PARTIAL"}).scalar_one()
        conn.execute(text(
            """INSERT INTO work_event_source (work_event_id, source_id, supported_fields,
                   is_primary) VALUES (:w, :s, :f, true)"""),
            {"w": weid, "s": source_id, "f": fields})
        _log(conn, "WORK_EVENT", weid, account_id, source_id, fields)
        out["work_event_ids"].append(weid)
        if current:
            out["current_work_event_ids"].append(weid)

    out["intent_event_ids"] = record_intents(conn, person_id, p, draft_id)
    return out


def record_intents(conn: Connection, person_id: str, p: AcquisitionPayload,
                   draft_id: str | None) -> list[str]:
    """One EXPLICIT intent per draft step (replay-safe), each with its outcome follow-ups."""
    ids = []
    for i in p.intents:
        captured = i.captured_at or datetime.now(UTC)
        row = conn.execute(text(
            """INSERT INTO intent_event (person_id, intent_kind, signal_type, target, target_kind,
                   target_taxonomy_node_id, source_surface, anonymous_draft_id, captured_at)
               VALUES (:p, 'EXPLICIT', :s, CAST(:t AS jsonb), :k, CAST(:n AS uuid), :surface,
                       CAST(:d AS uuid), :at)
               ON CONFLICT (anonymous_draft_id, source_surface, signal_type)
                   WHERE anonymous_draft_id IS NOT NULL DO NOTHING
               RETURNING intent_event_id::text"""),
            {"p": person_id, "s": INTENT_SIGNAL,
             "t": json.dumps({"kind": i.target_kind, "node_id": i.target_node_id}),
             "k": i.target_kind, "n": i.target_node_id, "surface": i.surface, "d": draft_id,
             "at": captured}).scalar()
        if row is None:
            continue
        ids.append(row)
        conn.execute(text(
            """INSERT INTO intent_followup (intent_event_id, followup_policy_id, horizon_months,
                   due_at)
               SELECT :i, f.followup_policy_id, h,
                      CAST(:at AS timestamptz) + make_interval(months => h)
               FROM followup_policy f, unnest(f.horizons_months) AS h
               WHERE f.status = 'ACTIVE'
               ON CONFLICT (intent_event_id, horizon_months) DO NOTHING"""),
            {"i": row, "at": captured})
    return ids


def _log(conn, entity_type, entity_id, account_id, source_id, fields) -> None:
    conn.execute(text(
        """INSERT INTO verification_log (entity_type, entity_id, account_id, action,
               verified_fields, source_id, new_level)
           VALUES (:t, :e, :a, 'SELF_REPORTED', :f, :s, 'SELF_REPORTED')"""),
        {"t": entity_type, "e": entity_id, "a": account_id, "f": fields, "s": source_id})
