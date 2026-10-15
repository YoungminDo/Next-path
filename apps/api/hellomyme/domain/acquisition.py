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
import re
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


UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class AcqEducation(BaseModel):
    """A school or major that is not in the pick list comes as typed text (``*_raw`` without an
    id): the cohort then leaves that dimension out, and the name is kept and queued for
    standardisation."""
    institution_id: str | None = None
    institution_raw: str | None = Field(default=None, max_length=100)
    major_node_id: str | None = None
    major_raw: str | None = Field(default=None, max_length=200)
    admission_year: int = Field(ge=1950, le=2100)
    graduation_year: int = Field(ge=1950, le=2100)

    @model_validator(mode="after")
    def _order(self):
        if self.admission_year > self.graduation_year:
            raise ValueError("admission_year must not be after graduation_year")
        for raw in ("institution_raw", "major_raw"):
            if getattr(self, raw) is not None:
                setattr(self, raw, getattr(self, raw).strip() or None)
        for ref in ("institution_id", "major_node_id"):
            value = (getattr(self, ref) or "").strip() or None
            if value is not None and not UUID_RE.match(value):
                raise ValueError(f"{ref} is not an id")
            setattr(self, ref, value)
        if not (self.institution_id or self.institution_raw):
            raise ValueError("institution_id or institution_raw is required")
        if not (self.major_node_id or self.major_raw):
            raise ValueError("major_node_id or major_raw is required")
        return self

    def cohort_filters(self) -> dict:
        return {"institution_ids": (self.institution_id,) if self.institution_id else (),
                "major_node_ids": (self.major_node_id,) if self.major_node_id else ()}


# Only as written (e.g. 인턴 -> INTERN); unknown stays None. An internship never counts as the
# first job (first_employment_rule).
EmploymentType = Literal["FULL_TIME", "PART_TIME", "CONTRACT", "INTERN"]


class AcqJob(BaseModel):
    organization_id: str | None = None
    organization_name: str | None = Field(default=None, max_length=200)
    role_node_id: str
    role_raw: str | None = Field(default=None, max_length=200)
    start_year: int = Field(ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)
    # Months and the employment type come from a resume when it shows them (MONTH precision).
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_month: int | None = Field(default=None, ge=1, le=12)
    employment_type: EmploymentType | None = None

    @model_validator(mode="after")
    def _months(self):
        if self.end_year is None:
            self.end_month = None
        return self


class AcqPastJob(BaseModel):
    """Another job read from the person's resume or capture (besides the current and first job).
    The role pick is optional: the title stays as written and waits for standardisation."""
    organization_id: str | None = None
    organization_name: str | None = Field(default=None, max_length=200)
    role_node_id: str | None = None
    role_raw: str | None = Field(default=None, max_length=200)
    start_year: int = Field(ge=1950, le=2100)
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_year: int | None = Field(default=None, ge=1950, le=2100)
    end_month: int | None = Field(default=None, ge=1, le=12)
    employment_type: EmploymentType | None = None
    is_current: bool = False

    @model_validator(mode="after")
    def _check(self):
        self.organization_name = (self.organization_name or "").strip() or None
        self.role_raw = (self.role_raw or "").strip() or None
        for ref in ("organization_id", "role_node_id"):
            value = (getattr(self, ref) or "").strip() or None
            if value is not None and not UUID_RE.match(value):
                raise ValueError(f"{ref} is not an id")
            setattr(self, ref, value)
        if not (self.role_node_id or self.role_raw):
            raise ValueError("role_node_id or role_raw is required")
        if self.is_current or self.end_year is None:
            self.end_year = self.end_month = None
        elif (self.end_year, self.end_month or 12) < (self.start_year, self.start_month or 1):
            raise ValueError("end before start")
        return self


class AcqDesiredRole(BaseModel):
    """One wanted role: a node from the role list, or the typed name when it is not listed."""
    role_node_id: str | None = None
    role_raw: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _one(self):
        self.role_raw = (self.role_raw or "").strip() or None
        self.role_node_id = (self.role_node_id or "").strip() or None
        if self.role_node_id is not None and not UUID_RE.match(self.role_node_id):
            raise ValueError("role_node_id is not an id")
        if not (self.role_node_id or self.role_raw):
            raise ValueError("role_node_id or role_raw is required")
        return self


# CHOSEN: desired_roles holds 1-3 roles in the member's order. NONE: no desired role yet.
# UNSURE: not sure. KEEP_CURRENT: professionals who want to stay in their role. None: not asked
# or skipped, which is different from NONE.
DesiredRoleStatus = Literal["CHOSEN", "NONE", "UNSURE", "KEEP_CURRENT"]


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
    desired_roles: list[AcqDesiredRole] = Field(default_factory=list, max_length=3)
    desired_role_status: DesiredRoleStatus | None = None
    # From a resume or capture the person uploaded (career_import): the other jobs it showed, and
    # which read they came from (the source type of the records written at login).
    other_jobs: list[AcqPastJob] = Field(default_factory=list, max_length=12)
    import_attempt_id: str | None = Field(default=None, pattern=UUID_RE.pattern)

    @model_validator(mode="after")
    def _desired(self):
        if self.desired_roles and self.desired_role_status in (None, "CHOSEN"):
            self.desired_role_status = "CHOSEN"
        elif self.desired_roles:
            raise ValueError(f"{self.desired_role_status} must not list desired roles")
        elif self.desired_role_status == "CHOSEN":
            raise ValueError("CHOSEN needs at least one desired role")
        if self.desired_role_status == "KEEP_CURRENT" and self.user_type != "PROFESSIONAL":
            raise ValueError("KEEP_CURRENT is for professionals")
        return self

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
        """SELECT i.institution_id::text AS id, i.name, i.region,
                  (SELECT coalesce(json_agg(a.alias_text ORDER BY a.alias_text), '[]'::json)
                     FROM institution_alias a
                    WHERE a.institution_id = i.institution_id AND a.status = 'ACTIVE') AS aliases
           FROM institution i WHERE i.is_active ORDER BY i.name"""))]


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
                    ORDER BY length(a.alias_text) LIMIT 1) AS matched_alias,
                  (SELECT coalesce(json_agg(a.alias_text ORDER BY a.alias_text), '[]'::json)
                     FROM taxonomy_alias a
                    WHERE a.taxonomy_node_id = n.taxonomy_node_id AND a.status = 'ACTIVE') AS aliases
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


# --- unlisted names: the nearest group ----------------------------------------------------
# A typed name the list does not know still tells something: 경영정보학과 is close to 경영학과,
# 데이터사이언스학과 belongs to 수학·통계·데이터, a school named after 부산 is a 부산 school. The
# cohort starts from those, with the same years and the same widening ladder as a listed answer,
# so an unlisted answer lands on a group of the same size, never on everyone of that year. A name
# that tells nothing leaves the dimension out, as before.

# How people write a name beyond the list's own (the web's SearchSelect uses the same list).
NAME_SUFFIXES = ("학과", "학부", "전공", "계열", "과")
# Region words in school names, as institution.region writes them (cities name their province).
REGION_WORDS = {
    **{r: r for r in ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
                      "충북", "충남", "전북", "전남", "경북", "경남", "제주")},
    "충청북": "충북", "충청남": "충남", "전라북": "전북", "전라남": "전남", "경상북": "경북",
    "경상남": "경남", "수원": "경기", "용인": "경기", "성남": "경기", "안산": "경기", "안양": "경기",
    "평택": "경기", "의정부": "경기", "춘천": "강원", "원주": "강원", "강릉": "강원", "청주": "충북",
    "충주": "충북", "천안": "충남", "아산": "충남", "전주": "전북", "군산": "전북", "익산": "전북",
    "목포": "전남", "순천": "전남", "여수": "전남", "포항": "경북", "경주": "경북", "안동": "경북",
    "경산": "경북", "창원": "경남", "진주": "경남", "김해": "경남",
}


def _norm_name(s: str) -> str:
    return re.sub(r"[\s·・,./()\[\]_&+-]+", "", s.lower())


def _name_base(s: str) -> str:
    """The name without the usual suffix (경영학과 -> 경영, 생명과학과 -> 생명과)."""
    n = _norm_name(s)
    for suffix in sorted(NAME_SUFFIXES, key=len, reverse=True):
        if n.endswith(suffix) and len(n) > len(suffix) + 1:
            n = n[: -len(suffix)]
            break
    return n[:-1] if n.endswith("학") and len(n) > 2 else n


# Words in typed major names, to the group of the major list they belong to (by label, so a longer
# list keeps working). The list is small (20 majors in 10 families, 5 top groups), so many common
# majors are typed (docs/10 §목록 밖 전공). Earlier groups win (고고미술사학과 is 인문학, not 미술).
# Health majors (간호·치료·보건·체육) have no group in the list yet and stay unmatched.
MAJOR_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("인문학", ("철학", "사학", "역사", "고고", "미술사", "문헌정보", "종교", "신학", "한문", "인문")),
    ("언어·문학", ("어문", "영어", "영문", "국어", "국문", "일본", "일어", "중국", "중어", "중문", "독일",
                "독어", "독문", "불어", "불문", "프랑스", "러시아", "노어", "스페인", "서어", "문예창작",
                "문학")),
    ("미디어·커뮤니케이션", ("신문방송", "언론", "방송", "저널리즘", "광고", "홍보", "엔터테인먼트",
                       "콘텐츠", "컨텐츠")),
    ("예술·디자인", ("영상", "영화", "연극", "연출", "공예", "미술", "음악", "무용", "패션", "사진", "만화",
                 "애니메이션")),
    ("경영·경제", ("금융", "재무", "회계", "세무", "무역", "벤처", "창업", "마케팅", "호텔", "관광", "물류",
               "부동산")),
    ("행정·정책", ("법", "경찰", "정치", "공공")),
    ("국제·글로벌", ("통상", "외교", "지역학")),
    ("사회·심리", ("복지", "아동", "가족", "상담", "청소년")),
    ("수학·통계·데이터", ("데이터", "인공지능")),
    ("자연과학", ("화학", "물리", "생물", "생명", "지구", "천문", "식품", "영양", "해양", "수산", "동물",
              "축산", "원예", "환경", "산림", "농")),
    ("공학", ("공학", "건축", "토목", "신소재", "재료", "반도체", "정보통신", "로봇")),
)


def _word_group(majors: Taxonomy, full: str) -> str | None:
    """The list group a typed name's words point to (the deepest node with that label)."""
    for label, words in MAJOR_WORDS:
        if any(w in full for w in words):
            nodes = [i for i, n in majors.nodes.items() if n["label"] == label]
            if nodes:
                return max(nodes, key=lambda i: (majors.nodes[i]["depth"], i))
    return None


def similar_majors(majors: Taxonomy, typed: str) -> tuple[tuple[str, ...], str | None]:
    """Listed majors close to a typed major: listed names inside it (글로벌경영학부 -> 경영학과),
    else the family it names (데이터사이언스학과 -> 수학·통계·데이터), else listed names that start
    the same way (국어교육과 -> 국어국문학과), else the group its words point to (일본학과 -> 언어·문학,
    철학과 -> 인문학, MAJOR_WORDS). Returns (node ids, SIMILAR | FAMILY)."""
    parents = {n["parent"] for n in majors.nodes.values() if n["parent"]}
    leaves = sorted(i for i in majors.nodes if i not in parents)
    full, base = _norm_name(typed), _name_base(typed)
    bases = {i: _name_base(majors.nodes[i]["label"]) for i in leaves}
    inside = sorted((i for i in leaves if len(bases[i]) >= 2 and bases[i] in base),
                    key=lambda i: (-len(bases[i]), i))
    if inside:
        return tuple(inside[:3]), "SIMILAR"
    families = sorted({majors.nodes[i]["parent"] for i in leaves if majors.nodes[i]["parent"]})
    named = [f for f in families
             if any(len(t) >= 2 and t in full
                    for t in (_name_base(w) for w in majors.nodes[f]["label"].split("·")))]
    if named:
        return tuple(named[:3]), "FAMILY"

    def shared(a: str, b: str) -> int:
        k = 0
        while k < min(len(a), len(b)) and a[k] == b[k]:
            k += 1
        return k
    best = max((shared(base, bases[i]) for i in leaves), default=0)
    if best >= 2:
        return tuple([i for i in leaves if shared(base, bases[i]) == best][:3]), "SIMILAR"
    group = _word_group(majors, full)
    if group:
        return (group,), "FAMILY"
    return (), None


def similar_region(typed: str) -> str | None:
    """The province a typed school name names (부산○○대학교 -> 부산), if any."""
    n = _norm_name(typed)
    for word in sorted(REGION_WORDS, key=len, reverse=True):
        if word in n:
            return REGION_WORDS[word]
    return None


def _region_institutions(conn: Connection, region: str) -> tuple[str, ...]:
    names = [region] + [w for w, r in REGION_WORDS.items() if r == region and w != region]
    return tuple(conn.execute(text(
        """SELECT institution_id::text FROM institution
           WHERE is_active AND string_to_array(region, '/') && CAST(:names AS text[])
           ORDER BY institution_id"""), {"names": names}).scalars())


def cohort_inputs(conn: Connection, e: AcqEducation) -> tuple[dict, dict]:
    """Cohort filters for the education answer, and what stood in for an unlisted name."""
    filters, similar = e.cohort_filters(), {}
    if not e.institution_id and e.institution_raw:
        region = similar_region(e.institution_raw)
        ids = _region_institutions(conn, region) if region else ()
        if ids:
            filters["institution_ids"], similar["region"] = ids, region
    if not e.major_node_id and e.major_raw:
        ids, kind = similar_majors(load_taxonomy(conn, "MAJOR"), e.major_raw)
        if ids:
            filters["major_node_ids"], similar["major"] = ids, kind
    return filters, similar


def _say_similar(result: tuple[dict, Filters], e: AcqEducation,
                 similar: dict) -> tuple[dict, Filters]:
    """Mark what stood in for an unlisted name, while the widened group still uses it. Nobody on
    record has exactly an unlisted name, so the exact-match count is 0."""
    out, eff = result
    kept = {k: v for k, v in similar.items()
            if (eff.institution_ids if k == "region" else eff.major_node_ids)}
    if kept:
        out["effective_filters"]["similar"] = kept
    if (e.institution_raw and not e.institution_id) or (e.major_raw and not e.major_node_id):
        out["exact_n"] = 0
    return out, eff


def _other_schools(filters: dict, e: AcqEducation) -> dict:
    """The same answers at every other known school (the member's own school left out)."""
    return {**filters, "institution_ids": (), "exclude_institution_ids": (e.institution_id,)}


def student_first_roles(conn, p: AcquisitionPayload, *, layers, as_of, exclude=(),
                        other_schools: bool = False, metric: str = "FIRST_ROLE_DISTRIBUTION"):
    """S2: what similar seniors did first (FIRST_ROLE at the surface depth). The result cards
    ask other questions (metric) of the same education cohort."""
    _require(p, "education")
    e = p.education
    filters, similar = cohort_inputs(conn, e)
    if other_schools:
        filters = _other_schools(filters, e)
    return _say_similar(evaluate_with_filters(conn, CareerQuery(
        as_of_date=as_of, target_metric=metric, surface_code=SURFACE,
        **filters,
        admission_year_from=e.admission_year, admission_year_to=e.admission_year,
        graduation_year_from=e.graduation_year, graduation_year_to=e.graduation_year,
        gender_codes=_gender(p), exclude_person_ids=tuple(exclude)), layers=layers), e, similar)


def professional_next_roles(conn, p: AcquisitionPayload, *, layers, as_of, exclude=(),
                            with_first_job: bool = False, other_schools: bool = False,
                            metric: str = "NEXT_ROLE_DISTRIBUTION"):
    """P2 (current role only) and P4 (same first role and current role): the next choice. The
    result cards ask other questions (metric) of the same people."""
    _require(p, "education", "current_job")
    roles = load_taxonomy(conn, "ROLE")
    current = _surface_node(conn, roles, p.current_job.role_node_id)
    first: tuple[str, ...] = ()
    if with_first_job:
        if p.first_job_is_current or p.first_job is None:
            raise QueryInvalid("first job is needed for similar paths")
        first = (_surface_node(conn, roles, p.first_job.role_node_id),)
    e = p.education
    filters, similar = cohort_inputs(conn, e)
    if other_schools:
        filters = _other_schools(filters, e)
    return _say_similar(evaluate_with_filters(conn, CareerQuery(
        as_of_date=as_of, target_metric=metric, surface_code=SURFACE,
        **filters,
        graduation_year_from=e.graduation_year, graduation_year_to=e.graduation_year,
        gender_codes=_gender(p), from_role_node_ids=(current,), first_role_node_ids=first,
        exclude_person_ids=tuple(exclude)), layers=layers), e, similar)


# Result cards after the free one (docs/10 §결과 카드): insight_type -> (flow, metric) on the same
# cohort as the free card. Each opens with 튜브 (unlock_policy); titles are on the web.
CARDS = {
    "FIRST_COMPANY_SIZE": ("STUDENT", "FIRST_COMPANY_SIZE_DISTRIBUTION"),
    "SIZE_MOVE": ("STUDENT", "SIZE_MOVE_DISTRIBUTION"),
    "FIRST_JOB_TENURE": ("STUDENT", "FIRST_JOB_TENURE_DISTRIBUTION"),
    "JOB_MOVES": ("STUDENT", "JOB_MOVES_DISTRIBUTION"),
    "ROLE_NOW": ("STUDENT", "CURRENT_ROLE_DISTRIBUTION"),
    "NEXT_COMPANY_SIZE": ("PROFESSIONAL", "NEXT_COMPANY_SIZE_DISTRIBUTION"),
    "ROLE_SIZE_MOVE": ("PROFESSIONAL", "ROLE_SIZE_MOVE_DISTRIBUTION"),
    "ROLE_SWITCH": ("PROFESSIONAL", "ROLE_SWITCH_DISTRIBUTION"),
    "ROLE_TENURE": ("PROFESSIONAL", "ROLE_TENURE_DISTRIBUTION"),
    "ROLE_JOB_MOVES": ("PROFESSIONAL", "ROLE_JOB_MOVES_DISTRIBUTION"),
}


def cards_for(p: AcquisitionPayload) -> list[str]:
    flow = "PROFESSIONAL" if p.is_professional else "STUDENT"
    return [card for card, (f, _) in CARDS.items() if f == flow]


def card_result(conn, p: AcquisitionPayload, card: str, *, layers, as_of, exclude=()) -> dict | None:
    """One result card's distribution, or None when the card is not one of this flow's."""
    if card not in cards_for(p):
        return None
    metric = CARDS[card][1]
    if p.is_professional:
        out, _ = professional_next_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude,
                                         metric=metric)
    else:
        out, _ = student_first_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude,
                                     metric=metric)
    return out


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
    if step == "teaser":
        # Before login: proof that the answer exists (how many, how many directions), no answer.
        if p.is_professional:
            out, _ = professional_next_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude)
        else:
            out, _ = student_first_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude)
        return {"step": step, "base": _summary(out), "n_directions": out["n_directions"]}
    if step == "first_roles":
        out, _ = student_first_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude)
        return {"step": step, "result": out}
    if step == "next_roles":
        out, _ = professional_next_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude)
        return {"step": step, "result": out}
    if step == "other_schools":
        # The same question at other schools (a paid comparison); needs a listed own school.
        if not (p.education and p.education.institution_id):
            return {"step": step, "result": None}
        if p.is_professional:
            out, _ = professional_next_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude,
                                             other_schools=True)
        else:
            out, _ = student_first_roles(conn, p, layers=layers, as_of=as_of, exclude=exclude,
                                         other_schools=True)
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
    summary = {k: out[k] for k in keep}
    # Small-cohort suppression: a group too small to show is not described by its size either,
    # and the exact-match count is only told once it is large enough to stand on its own.
    if summary["suppressed"]:
        summary["effective_n"] = None
    # "Nobody matches exactly" (0) is safe to say; 1 to min_cell_n - 1 is not told.
    if summary["exact_n"] and summary["exact_n"] < out.get("min_cell_n", 0):
        summary["exact_n"] = None
    return summary


def resolve_names(conn: Connection, p: AcquisitionPayload) -> AcquisitionPayload:
    """Typed school/major names that the list already knows (by name or alias, e.g. "경영학과"
    → 경영학) get their id, keeping the typed text; unknown ids are refused. Names nobody knows
    stay typed: that dimension is left out of the cohort."""
    from hellomyme.ingest.pipeline import _lookup  # shared deterministic matcher

    p = _resolve_desired(conn, p, _lookup)
    p = _resolve_other_jobs(conn, p, _lookup)
    e = p.education
    if e is None:
        return p
    inst, major = e.institution_id, e.major_node_id
    if inst and not conn.execute(text(
            "SELECT 1 FROM institution WHERE institution_id = CAST(:i AS uuid) AND is_active"),
            {"i": inst}).first():
        raise QueryInvalid("unknown institution")
    if major and major not in load_taxonomy(conn, "MAJOR").nodes:
        raise QueryInvalid("unknown major")
    inst = inst or _lookup(conn, "INSTITUTION", e.institution_raw)
    major = major or _lookup(conn, "MAJOR", e.major_raw)
    if (inst, major) == (e.institution_id, e.major_node_id):
        return p
    return p.model_copy(update={"education": e.model_copy(
        update={"institution_id": inst, "major_node_id": major})})


def _resolve_desired(conn: Connection, p: AcquisitionPayload, lookup) -> AcquisitionPayload:
    """Same rules for desired roles: listed ids are checked, typed names the list knows get their
    id (the typed text stays), and a role given twice counts once."""
    if not p.desired_roles:
        return p
    roles = load_taxonomy(conn, "ROLE")
    out, seen = [], set()
    for r in p.desired_roles:
        if r.role_node_id and r.role_node_id not in roles.nodes:
            raise QueryInvalid("unknown role")
        node = r.role_node_id or lookup(conn, "ROLE", r.role_raw)
        key = node or f"raw:{r.role_raw.casefold()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r.model_copy(update={"role_node_id": node}))
    return p.model_copy(update={"desired_roles": out})


def _resolve_other_jobs(conn: Connection, p: AcquisitionPayload, lookup) -> AcquisitionPayload:
    """Jobs read from a resume: listed ids are checked; a title the role list knows exactly gets
    its id (the title stays as written); the rest keep only the title."""
    if not p.other_jobs:
        return p
    roles = load_taxonomy(conn, "ROLE")
    out = []

    def key(j) -> tuple:
        name = "".join(ch for ch in (j.organization_name or "").casefold() if ch.isalnum())
        return (name, j.start_year, j.start_month, j.role_node_id or (j.role_raw or "").casefold())

    # The same position twice, or the current/first job again, is written once.
    seen = {key(j) for j in (p.current_job, p.first_job) if j is not None}
    for j in p.other_jobs:
        if key(j) in seen:
            continue
        seen.add(key(j))
        if j.role_node_id and j.role_node_id not in roles.nodes:
            raise QueryInvalid("unknown role")
        if j.organization_id and not conn.execute(text(
                "SELECT 1 FROM organization WHERE organization_id = CAST(:o AS uuid)"),
                {"o": j.organization_id}).first():
            raise QueryInvalid("unknown organization")
        out.append(j if j.role_node_id else
                   j.model_copy(update={"role_node_id": lookup(conn, "ROLE", j.role_raw)}))
    return p.model_copy(update={"other_jobs": out})


IMPORT_SOURCE_TYPES = {"LINKEDIN": "LINKEDIN_USER_UPLOAD", "RESUME": "CAREER_DOCUMENT",
                       "OTHER": "CAREER_DOCUMENT"}


def import_source_type(conn: Connection, attempt_id: str | None) -> str | None:
    """The source type for rows that came from a read file (None: typed by hand)."""
    if not attempt_id:
        return None
    kind = conn.execute(text(
        """SELECT source_kind FROM import_attempt
           WHERE import_attempt_id = CAST(:i AS uuid) AND outcome = 'PARSED'"""),
        {"i": attempt_id}).scalar()
    return kind and IMPORT_SOURCE_TYPES[kind]


def unlisted(p: AcquisitionPayload) -> list[str]:
    """Which answers were typed names the list does not know (said next to the result)."""
    e = p.education
    if e is None:
        return []
    return [k for k, ref, raw in (("institution", e.institution_id, e.institution_raw),
                                  ("major", e.major_node_id, e.major_raw)) if raw and not ref]


def insight_key(p: AcquisitionPayload, target_node: str | None) -> str:
    """Entitlement key: the cohort inputs plus the target, independent of wording/order."""
    basis = p.model_dump(mode="json", exclude={"intents", "desired_roles", "desired_role_status",
                                               "other_jobs", "import_attempt_id"})
    # Months and employment type never change the cohort; leaving them out keeps every key from
    # before they existed unchanged.
    for job in ("current_job", "first_job"):
        for extra in ("start_month", "end_month", "employment_type"):
            (basis.get(job) or {}).pop(extra, None)
    # Keep keys of payloads from before typed school names existed unchanged (an unlock bought
    # then must stay unlocked and never be charged again).
    if basis.get("education") and basis["education"].get("institution_raw") is None:
        basis["education"].pop("institution_raw", None)
    return hashlib.sha256(json.dumps({"p": basis, "t": target_node}, sort_keys=True)
                          .encode()).hexdigest()


# --- member profile -> payload (post-login, no re-entry) ----------------------------------

def member_payload(conn: Connection, person_id: str, as_of: date) -> AcquisitionPayload | None:
    person = conn.execute(text(
        "SELECT declared_stage, gender_code FROM person WHERE person_id = :p"),
        {"p": person_id}).first()
    edu = conn.execute(text(
        """SELECT institution_id::text, institution_raw, major_taxonomy_node_id::text AS major,
                  major_raw, admission_year, graduation_year
           FROM canonical_education WHERE person_id = :p
             AND (major_taxonomy_node_id IS NOT NULL OR major_raw IS NOT NULL)
             AND (institution_id IS NOT NULL OR institution_raw IS NOT NULL)
             AND admission_year IS NOT NULL AND graduation_year IS NOT NULL
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
        f"""SELECT {cols} FROM first_employment_for(:r, :d, ARRAY[CAST(:p AS uuid)]) fe
            JOIN work_event w ON w.work_event_id = fe.work_event_id"""),
        {"p": person_id, "d": as_of, "r": FIRST_EMPLOYMENT_RULE}).first()
    if first is not None and first.role is None:
        # The first job is on record without a role (a title from a resume nobody has mapped
        # yet): compare by the earliest qualifying job whose role is known.
        first = conn.execute(text(
            f"""SELECT {cols} FROM canonical_work_event w
                JOIN first_employment_rule r ON r.version = :r
                WHERE w.person_id = :p AND w.event_type = ANY (r.included_event_types)
                  AND (w.employment_type IS NULL
                       OR NOT (w.employment_type = ANY (r.excluded_employment_types)))
                  AND w.start_date IS NOT NULL AND w.start_date <= :d
                  AND w.role_taxonomy_node_id IS NOT NULL
                ORDER BY w.start_date, w.work_event_id LIMIT 1"""),
            {"p": person_id, "d": as_of, "r": FIRST_EMPLOYMENT_RULE}).first()
    intents = conn.execute(text(
        """SELECT source_surface, target_kind, target_taxonomy_node_id::text AS node, captured_at
           FROM intent_event WHERE person_id = :p AND signal_type = :s
           ORDER BY captured_at NULLS FIRST, created_at"""),
        {"p": person_id, "s": INTENT_SIGNAL}).all()
    stage = person.declared_stage or ("PROFESSIONAL" if current else "STUDENT")
    return AcquisitionPayload(
        user_type=stage,
        education=AcqEducation(institution_id=edu.institution_id,
                               institution_raw=None if edu.institution_id else edu.institution_raw,
                               major_node_id=edu.major, major_raw=edu.major_raw,
                               admission_year=edu.admission_year,
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
           VALUES (:t, 'VERIFIED', 'HELLOMYME_APP', :k, CAST(:raw AS jsonb), 'MEMBER_CONSENT')
           ON CONFLICT (source_system, source_key) DO NOTHING RETURNING source_id::text"""),
        {"k": source_key, "raw": json.dumps(raw_payload, ensure_ascii=False, default=str),
         "t": import_source_type(conn, p.import_attempt_id) or "MANUAL_INPUT"}
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
        out["education_id"] = _write_education(conn, person_id, account_id, source_id,
                                               p.education, majors)

    jobs: list[tuple[AcqJob | AcqPastJob, bool]] = []
    if p.first_job and not p.first_job_is_current:
        jobs.append((p.first_job, False))
    if p.current_job:
        jobs.append((p.current_job, True))
    jobs += [(j, j.is_current) for j in p.other_jobs]
    for j, current in jobs:
        weid = _write_job(conn, person_id, account_id, source_id, j, current, roles)
        out["work_event_ids"].append(weid)
        if current:
            out["current_work_event_ids"].append(weid)

    out["intent_event_ids"] = record_intents(conn, person_id, p, draft_id)
    out["desired_role_ids"] = record_desired_roles(conn, person_id, p, draft_id)
    return out


def _write_education(conn: Connection, person_id: str, account_id: str, source_id: str,
                     e: AcqEducation, majors: Taxonomy) -> str:
    """One SELF_REPORTED education row with its source; typed names go to the mapping queue."""
    if e.major_node_id and e.major_node_id not in majors.nodes:
        raise QueryInvalid(f"unknown major node {e.major_node_id}")
    inst_name = e.institution_id and conn.execute(text(
        "SELECT name FROM institution WHERE institution_id::text = :i"),
        {"i": e.institution_id}).scalar()
    inst_id = e.institution_id if inst_name else None
    major_raw = e.major_raw or (majors.nodes[e.major_node_id]["label"] if e.major_node_id else None)
    mapped = [bool(inst_id), bool(e.major_node_id)]
    education_id = conn.execute(text(
        """INSERT INTO education (person_id, institution_raw, institution_id, major_raw,
               major_taxonomy_node_id, admission_year, admission_date_precision,
               graduation_year, graduation_date_precision, data_layer, verification_level,
               normalization_status, last_verified_at)
           VALUES (:p, :ir, CAST(:iid AS uuid), :mr, CAST(:m AS uuid), :ay, 'YEAR', :gy,
                   'YEAR', 'VERIFIED', 'SELF_REPORTED', :ns, now())
           RETURNING education_id::text"""),
        {"p": person_id, "ir": inst_name or e.institution_raw, "iid": inst_id,
         "mr": major_raw, "m": e.major_node_id,
         "ay": e.admission_year, "gy": e.graduation_year,
         "ns": "MAPPED" if all(mapped) else ("PARTIAL" if any(mapped) else "UNMAPPED")}).scalar_one()
    # Typed names nobody has standardised yet wait in the mapping queue (raw stays as typed).
    for kind, raw, known in (("INSTITUTION", e.institution_raw, inst_id),
                             ("MAJOR", e.major_raw, e.major_node_id)):
        if raw and not known:
            conn.execute(text(
                """INSERT INTO mapping_queue (entity_kind, raw_value) VALUES (:k, :r)
                   ON CONFLICT (entity_kind, normalized_key)
                   DO UPDATE SET occurrences = mapping_queue.occurrences + 1"""),
                {"k": kind, "r": raw})
    fields = ["institution", "major", "admission_year", "graduation_year"]
    conn.execute(text(
        """INSERT INTO education_source (education_id, source_id, supported_fields, is_primary)
           VALUES (:e, :s, :f, true)"""),
        {"e": education_id, "s": source_id, "f": fields})
    _log(conn, "EDUCATION", education_id, account_id, source_id, fields)
    return education_id


# --- a returning member's new answers ------------------------------------------------------
# A member who answers again (e.g. a student who now works) sees what would change and decides;
# nothing is overwritten: an applied change is a new record, the old one is withdrawn
# (retracted_at), and a job that started later than the current one is a move, not a correction.

USER_TYPE_LABELS = {"STUDENT": "학생", "JOB_SEEKER": "취업 준비", "PROFESSIONAL": "직장인"}


def _profile_ids(conn: Connection, person_id: str, as_of: date) -> tuple[str | None, dict | None]:
    """The education and current job member_payload compares with (same choice as there)."""
    edu = conn.execute(text(
        """SELECT education_id::text FROM canonical_education WHERE person_id = :p
             AND (major_taxonomy_node_id IS NOT NULL OR major_raw IS NOT NULL)
             AND (institution_id IS NOT NULL OR institution_raw IS NOT NULL)
             AND admission_year IS NOT NULL AND graduation_year IS NOT NULL
           ORDER BY graduation_year DESC LIMIT 1"""), {"p": person_id}).scalar()
    job = conn.execute(text(
        """SELECT w.work_event_id::text AS id, w.start_date FROM canonical_work_event w
           WHERE w.person_id = :p AND w.start_date <= :d AND (w.end_date IS NULL OR w.end_date > :d)
             AND w.role_taxonomy_node_id IS NOT NULL
           ORDER BY w.start_date DESC LIMIT 1"""), {"p": person_id, "d": as_of}).first()
    return edu, (dict(job._mapping) if job else None)


def _edu_label(conn: Connection, e: AcqEducation | None) -> str | None:
    if e is None:
        return None
    school = e.institution_raw or (e.institution_id and conn.execute(text(
        "SELECT name FROM institution WHERE institution_id::text = :i"), {"i": e.institution_id}).scalar())
    majors = load_taxonomy(conn, "MAJOR")
    major = e.major_raw if not e.major_node_id else majors.nodes.get(e.major_node_id, {}).get("label")
    return f"{school or '학교 미입력'} · {major or '전공 미입력'} · {e.admission_year}–{e.graduation_year}"


def _job_label(conn: Connection, j: AcqJob | None) -> str | None:
    if j is None:
        return None
    role = load_taxonomy(conn, "ROLE").nodes.get(j.role_node_id, {}).get("label") or j.role_raw
    return f"{j.organization_name or '회사 미입력'} · {role or '직무 미입력'} · {j.start_year}~"


def _key(s: str | None) -> str:
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())


def profile_changes(conn: Connection, person_id: str, p: AcquisitionPayload, as_of: date) -> list[dict]:
    """What the new answers would change in the member's profile, as before/after lines."""
    cur = member_payload(conn, person_id, as_of)
    if cur is None:
        return []
    changes = []
    if cur.user_type != p.user_type:
        changes.append({"field": "user_type", "before": USER_TYPE_LABELS.get(cur.user_type),
                        "after": USER_TYPE_LABELS.get(p.user_type)})

    def edu_key(e: AcqEducation | None):
        return e and (e.institution_id or _key(e.institution_raw), e.major_node_id or _key(e.major_raw),
                      e.admission_year, e.graduation_year)
    if p.education and edu_key(cur.education) != edu_key(p.education):
        changes.append({"field": "education", "before": _edu_label(conn, cur.education),
                        "after": _edu_label(conn, p.education)})

    def job_key(j: AcqJob | None):
        return j and (j.role_node_id, _key(j.organization_name), j.start_year)
    if p.is_professional and p.current_job and job_key(cur.current_job) != job_key(p.current_job):
        changes.append({"field": "current_job", "before": _job_label(conn, cur.current_job),
                        "after": _job_label(conn, p.current_job)})
    return changes


def apply_profile_changes(conn: Connection, account_id: str, person_id: str, draft_id: str,
                          p: AcquisitionPayload, as_of: date) -> list[str]:
    """Apply what profile_changes shows, once per draft (a replay changes nothing)."""
    changes = {c["field"] for c in profile_changes(conn, person_id, p, as_of)}
    if not changes:
        return []
    source_id = conn.execute(text(
        """INSERT INTO source_record (source_type, data_layer, source_system, source_key,
               raw_payload, legal_basis)
           VALUES (:t, 'VERIFIED', 'HELLOMYME_APP', :k, CAST(:raw AS jsonb), 'MEMBER_CONSENT')
           ON CONFLICT (source_system, source_key) DO NOTHING RETURNING source_id::text"""),
        {"k": f"draft:{draft_id}:profile",
         "t": import_source_type(conn, p.import_attempt_id) or "MANUAL_INPUT",
         "raw": json.dumps(p.model_dump(mode="json"), ensure_ascii=False)}).scalar()
    if source_id is None:
        return []
    old_edu, old_job = _profile_ids(conn, person_id, as_of)
    if "user_type" in changes:
        conn.execute(text("UPDATE person SET declared_stage = :s WHERE person_id = :p"),
                     {"s": p.user_type, "p": person_id})
    if "education" in changes:
        if old_edu:
            conn.execute(text("UPDATE education SET retracted_at = now() WHERE education_id = :e"),
                         {"e": old_edu})
        _write_education(conn, person_id, account_id, source_id, p.education, load_taxonomy(conn, "MAJOR"))
    if "current_job" in changes:
        j = p.current_job
        # Started no later than the job on record: a correction of it. Later: a move (both stay).
        if old_job and j.start_year <= old_job["start_date"].year:
            conn.execute(text("UPDATE work_event SET retracted_at = now() WHERE work_event_id = :w"),
                         {"w": old_job["id"]})
        # Already on record (e.g. added from the same file at login): not written twice.
        same = conn.execute(text(
            """SELECT organization_raw FROM work_event
               WHERE person_id = :p AND retracted_at IS NULL AND role_taxonomy_node_id = CAST(:r AS uuid)
                 AND extract(year FROM start_date) = :y"""),
            {"p": person_id, "r": j.role_node_id, "y": j.start_year}).scalars().all()
        if _key(j.organization_name) not in {_key(o) for o in same}:
            _write_job(conn, person_id, account_id, source_id, j, True, load_taxonomy(conn, "ROLE"))
    return sorted(changes)


DESIRED_SURFACE = {"STUDENT": "STUDENT_PREVIEW", "JOB_SEEKER": "STUDENT_PREVIEW",
                   "PROFESSIONAL": "PROFESSIONAL_PREVIEW"}


def record_desired_roles(conn: Connection, person_id: str, p: AcquisitionPayload,
                         draft_id: str | None, captured_at: datetime | None = None) -> list[str]:
    """The desired-role answer as rows of the member's own (replay-safe per draft). A skipped
    question writes nothing; 'no desired role yet' writes one NONE row."""
    if p.desired_role_status is None:
        return []
    at = captured_at or datetime.now(UTC)
    rows = ([(i + 1, r.role_node_id, r.role_raw) for i, r in enumerate(p.desired_roles)]
            if p.desired_role_status == "CHOSEN" else [(1, None, None)])
    ids = []
    for rank, node, raw in rows:
        rid = conn.execute(text(
            """INSERT INTO desired_role (person_id, status, rank, role_taxonomy_node_id, role_raw,
                   source_surface, anonymous_draft_id, captured_at)
               VALUES (:p, :s, :r, CAST(:n AS uuid), :raw, :surface, CAST(:d AS uuid), :at)
               ON CONFLICT (anonymous_draft_id, rank) WHERE anonymous_draft_id IS NOT NULL
               DO NOTHING RETURNING desired_role_id::text"""),
            {"p": person_id, "s": p.desired_role_status, "r": rank, "n": node, "raw": raw,
             "surface": DESIRED_SURFACE[p.user_type], "d": draft_id, "at": at}).scalar()
        if rid:
            ids.append(rid)
    return ids


def _write_job(conn: Connection, person_id: str, account_id: str, source_id: str,
               j: AcqJob | AcqPastJob, current: bool, roles: Taxonomy) -> str:
    if j.role_node_id and j.role_node_id not in roles.nodes:
        raise QueryInvalid(f"unknown role node {j.role_node_id}")
    org = None
    if j.organization_id:
        org = conn.execute(text(
            "SELECT organization_id::text AS id, name FROM organization "
            "WHERE organization_id::text = :o"), {"o": j.organization_id}).first()
    end = j.end_year if (j.end_year and not current) else None
    fields = ["event_type", "role", "start_date", "is_current"]
    if org or j.organization_name:
        fields.append("organization")
    if end:
        fields.append("end_date")
    mapped = [bool(j.role_node_id), bool(org or not j.organization_name)]
    weid = conn.execute(text(
        """INSERT INTO work_event (person_id, event_type, organization_raw, organization_id,
               role_raw, role_taxonomy_node_id, employment_type, start_date, start_date_precision,
               end_date, end_date_precision, is_current, data_layer, verification_level,
               normalization_status, last_verified_at)
           VALUES (:p, 'EMPLOYMENT', :or, CAST(:oid AS uuid), :rr, CAST(:r AS uuid), :et, :sd,
                   :sp, :ed, :ep, :cur, 'VERIFIED', 'SELF_REPORTED', :ns, now())
           RETURNING work_event_id::text"""),
        {"p": person_id, "or": j.organization_name or (org and org.name),
         "oid": org and org.id,
         "rr": j.role_raw or (roles.nodes[j.role_node_id]["label"] if j.role_node_id else None),
         "r": j.role_node_id, "et": j.employment_type,
         # Unknown stays unknown: a year without a month is 1 Jan with YEAR precision.
         "sd": date(j.start_year, j.start_month or 1, 1),
         "sp": "MONTH" if j.start_month else "YEAR",
         "ed": date(end, (j.end_month or 1) if end else 1, 1) if end else None,
         "ep": None if not end else ("MONTH" if j.end_month else "YEAR"), "cur": current,
         "ns": "MAPPED" if all(mapped) else ("PARTIAL" if any(mapped) else "UNMAPPED")}).scalar_one()
    conn.execute(text(
        """INSERT INTO work_event_source (work_event_id, source_id, supported_fields,
               is_primary) VALUES (:w, :s, :f, true)"""),
        {"w": weid, "s": source_id, "f": fields})
    # Names the lists do not know (a typed company, a title read from a resume) wait for
    # standardisation; the raw text stays on the record as written.
    for kind, raw, known in (("ORGANIZATION", j.organization_name, org),
                             ("ROLE", j.role_raw, j.role_node_id)):
        if raw and not known:
            conn.execute(text(
                """INSERT INTO mapping_queue (entity_kind, raw_value) VALUES (:k, :r)
                   ON CONFLICT (entity_kind, normalized_key)
                   DO UPDATE SET occurrences = mapping_queue.occurrences + 1"""),
                {"k": kind, "r": raw})
    _log(conn, "WORK_EVENT", weid, account_id, source_id, fields)
    return weid


def add_member_job(conn: Connection, account_id: str, person_id: str, j: AcqJob,
                   idempotency_key: str) -> dict:
    """A past job added after login (professional flow, P3). One source record per request,
    so a replayed request writes nothing twice."""
    source_key = f"member:{account_id}:{idempotency_key}"
    source_id = conn.execute(text(
        """INSERT INTO source_record (source_type, data_layer, source_system, source_key,
               raw_payload, legal_basis)
           VALUES ('MANUAL_INPUT', 'VERIFIED', 'HELLOMYME_APP', :k, CAST(:raw AS jsonb),
                   'MEMBER_CONSENT')
           ON CONFLICT (source_system, source_key) DO NOTHING RETURNING source_id::text"""),
        {"k": source_key, "raw": j.model_dump_json()}).scalar()
    if source_id is None:
        return {"replayed": True, "work_event_id": None}
    weid = _write_job(conn, person_id, account_id, source_id, j, False, load_taxonomy(conn, "ROLE"))
    return {"replayed": False, "work_event_id": weid}


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
