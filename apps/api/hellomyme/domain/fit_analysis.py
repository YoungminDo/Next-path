"""First-pass fit analysis for a member (/alert, migration 0044; docs/10 §공고 알림 랜딩).

Claude reads the member's confirmed records only (school, major, years; each job's company, role,
type and dates; desired roles) and answers in a fixed structure: one summary line, three roles
that fit with a reason each, the kinds of company that fit (never a named company), and two or
three things to strengthen. No file, no name, no contact
goes out. Sending the records to Anthropic (US) is an overseas transfer (PIPA §28-8): the consent
wording version is written on the run before anything is sent. A rerun with the same records
returns the stored answer. No database connection is held while the model answers.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from hellomyme.config import Settings
from hellomyme.domain.career_import import role_list
from hellomyme.domain.career_query import load_taxonomy

log = logging.getLogger(__name__)

_IN_FLIGHT = threading.BoundedSemaphore(4)
EMPLOYMENT = {"FULL_TIME": "정규직", "PART_TIME": "파트타임", "CONTRACT": "계약직", "INTERN": "인턴"}
EVENTS = {"STARTUP": "창업", "SIDE_BUSINESS": "부업", "SELF_EMPLOYED": "자영업", "FREELANCE": "프리랜서",
          "STUDY": "학업", "CAREER_BREAK": "공백", "MILITARY": "군 복무", "PROJECT": "프로젝트"}
STAGES = {"STUDENT": "학생", "JOB_SEEKER": "취업 준비 중", "PROFESSIONAL": "직장인"}


class FitAnalysisFailed(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class FitRole(BaseModel):
    role_code: str | None = Field(description="Code of this role in the role list, or null")
    role_name: str = Field(description="Role name in Korean as the person would say it")
    level: Literal["HIGH", "MEDIUM"] = Field(description="HIGH: the records show this work already; "
                                                         "MEDIUM: close, but a step away")
    reason: str = Field(description="One Korean sentence (해요체) naming what in the records fits")


class FitResult(BaseModel):
    summary: str = Field(description="One short Korean sentence (해요체): who the person is by the "
                                     "records and which direction fits best")
    fits: list[FitRole] = Field(description="Exactly three roles, best first")
    company_types: list[str] = Field(description="Two or three kinds of company that fit, as short "
                                                 "Korean phrases of industry and size (e.g. '핀테크 "
                                                 "스타트업'); never a specific company name")
    gaps: list[str] = Field(description="Two or three Korean sentences (해요체): what to strengthen "
                                        "for those roles, judged only from the records")


SYSTEM = (
    "You give a first-pass career fit analysis to one person, in Korean (해요체), from the career "
    "records they confirmed: education, each job with company, role, type and dates, and the "
    "roles they want. Name exactly three roles that fit, best first, each with one sentence that "
    "points at what in the records fits (a company, a role, years). Name two or three kinds of "
    "company that fit (industry and size, never a specific company). Then two or three things to "
    "strengthen for those roles, judged only from the records: for example a short tenure, a "
    "career break, no experience in the wanted role yet, or a long stay in one role. A wanted role "
    "that is missing or not decided yet is never one of them (the person may simply not have been "
    "asked). Never invent "
    "experience, skills, numbers, achievements or companies that are not in the records, never "
    "promise a hire or a pass, and never judge the person. Use the role list for role_code when "
    "a role matches; otherwise null. Keep every sentence short and plain."
)


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    failure: str | None = Field(default=None, max_length=300)


class Analyzer(Protocol):
    model: str

    def analyze(self, records: str, roles: list[tuple[str, str, str | None]]) -> tuple[
        FitResult | None, str, Usage]: ...


class ClaudeAnalyzer:
    def __init__(self, settings: Settings, client=None):
        import anthropic

        self.model = settings.career_import_model
        self.client = client or anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(), timeout=50.0, max_retries=0,
            default_headers=({"anthropic-workspace-id": workspace.strip()}
                             if (workspace := getattr(settings, "anthropic_workspace_id", None))
                             and workspace.strip() else None))

    def analyze(self, records, roles):
        import anthropic

        content = [
            {"type": "text", "text": "Role list (code: role - group):\n" + "\n".join(
                f"{code}: {label} - {group or ''}" for code, label, group in roles)},
            {"type": "text", "text": "Confirmed records:\n" + records},
            {"type": "text", "text": "Give the first-pass fit analysis."},
        ]
        try:
            response = self.client.beta.messages.parse(
                model=self.model, max_tokens=4000, system=SYSTEM,
                messages=[{"role": "user", "content": content}],
                output_format=FitResult, output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except anthropic.APIStatusError as exc:
            reason = f"api {exc.status_code} (request {getattr(exc, 'request_id', None)})"
            log.error("fit analysis: Claude API error %s", reason)
            return None, "FAILED", Usage(failure=reason[:300])
        except anthropic.APIConnectionError as exc:
            log.error("fit analysis: Claude API unreachable (%s)", type(exc).__name__)
            return None, "FAILED", Usage(failure=f"api unreachable: {type(exc).__name__}")
        except Exception as exc:
            log.exception("fit analysis: unreadable answer")
            return None, "FAILED", Usage(failure=f"unreadable answer: {type(exc).__name__}")
        usage = Usage(input_tokens=response.usage.input_tokens,
                      output_tokens=response.usage.output_tokens)
        if response.stop_reason == "refusal":
            return None, "REFUSED", usage
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            return None, "FAILED", usage.model_copy(update={"failure": f"stop {response.stop_reason}"})
        return response.parsed_output, "DONE", usage


_ANALYZERS: dict[tuple, ClaudeAnalyzer] = {}


def get_analyzer(settings: Settings) -> Analyzer | None:
    """None without an API key: the analysis is off."""
    if not settings.anthropic_api_key or not settings.fit_analysis_enabled:
        return None
    key = (settings.anthropic_api_key.get_secret_value(), settings.career_import_model,
           settings.anthropic_workspace_id)
    if key not in _ANALYZERS:
        _ANALYZERS[key] = ClaudeAnalyzer(settings)
    return _ANALYZERS[key]


# --- the records sent (labels only; no name, no contact) ---------------------------------------

def _ym(d: date | None) -> str:
    return f"{d.year}.{d.month:02d}" if d else "지금"


def member_records(conn: Connection, person_id: str) -> str | None:
    """The confirmed records as short Korean lines, oldest job first. None without education."""
    majors = load_taxonomy(conn, "MAJOR")
    roles = load_taxonomy(conn, "ROLE")
    person = conn.execute(text("SELECT declared_stage FROM person WHERE person_id = :p"),
                          {"p": person_id}).first()
    edu = conn.execute(text(
        """SELECT coalesce(i.name, e.institution_raw) AS school, e.major_taxonomy_node_id::text AS major,
                  e.major_raw, e.admission_year, e.graduation_year
           FROM canonical_education e LEFT JOIN institution i ON i.institution_id = e.institution_id
           WHERE e.person_id = :p AND e.admission_year IS NOT NULL AND e.graduation_year IS NOT NULL
           ORDER BY e.graduation_year DESC LIMIT 1"""), {"p": person_id}).first()
    if person is None or edu is None:
        return None
    jobs = conn.execute(text(
        """SELECT coalesce(o.name, w.organization_raw) AS org, w.role_taxonomy_node_id::text AS role,
                  w.role_raw, w.employment_type, w.event_type, w.start_date, w.end_date
           FROM canonical_work_event w LEFT JOIN organization o ON o.organization_id = w.organization_id
           WHERE w.person_id = :p AND w.start_date IS NOT NULL
           ORDER BY w.start_date, w.work_event_id"""), {"p": person_id}).all()
    desired = conn.execute(text(
        """SELECT status, role_taxonomy_node_id::text AS role, role_raw FROM desired_role
           WHERE person_id = :p AND captured_at = (SELECT max(captured_at) FROM desired_role
                                                   WHERE person_id = :p)
           ORDER BY rank"""), {"p": person_id}).all()
    major = majors.nodes.get(edu.major, {}).get("label") if edu.major else edu.major_raw
    lines = [f"지금: {STAGES.get(person.declared_stage or '', '알 수 없음')}",
             f"학력: {edu.school or '학교 미입력'} · {major or '전공 미입력'} · "
             f"{edu.admission_year} 입학 · {edu.graduation_year} 졸업"]
    if jobs:
        lines.append("경력 (오래된 순):")
        for j in jobs:
            role = roles.nodes.get(j.role, {}).get("label") if j.role else None
            kind = EMPLOYMENT.get(j.employment_type or "") or EVENTS.get(j.event_type or "") or ""
            parts = [j.org or "회사 미입력", role or j.role_raw or "직무 미입력"] + ([kind] if kind else [])
            lines.append(f"- {' · '.join(parts)} · {_ym(j.start_date)}~{_ym(j.end_date)}")
    else:
        lines.append("경력: 없음")
    wanted = [roles.nodes.get(d.role, {}).get("label") if d.role else d.role_raw
              for d in desired if d.status == "CHOSEN"]
    if any(wanted):
        lines.append("희망 직무: " + ", ".join(w for w in wanted if w))
    elif desired:
        lines.append("희망 직무: 아직 정하지 않음")
    return "\n".join(lines)


# --- runs -------------------------------------------------------------------------------------

# Without a chosen wanted role, a "decide what you want" gap is about our question, not the person.
_NO_WANTED = re.compile(r"희망\s*직무|원하는\s*(방향|직무|일)")


def _wants_a_role(records: str) -> bool:
    """The records name at least one wanted role (member_records' 희망 직무 line)."""
    return "\n희망 직무: " in records and "\n희망 직무: 아직 정하지 않음" not in records

def _view(row) -> dict:
    return {"analysis_id": row.analysis_id, "created_at": row.created_at.isoformat(), **row.result}


def latest(conn: Connection, account_id: str) -> dict | None:
    row = conn.execute(text(
        """SELECT analysis_id::text, created_at, result FROM fit_analysis
           WHERE account_id = :a AND outcome = 'DONE' ORDER BY created_at DESC LIMIT 1"""),
        {"a": account_id}).first()
    return _view(row) if row else None


def status(conn: Connection, settings: Settings, account_id: str, analyzer: Analyzer | None) -> dict:
    return {"enabled": analyzer is not None, "consent_text_version": settings.fit_analysis_consent_version,
            "latest": latest(conn, account_id)}


def run(engine: Engine, settings: Settings, account_id: str, person_id: str | None,
        consent_text_version: str, analyzer: Analyzer | None) -> dict:
    if analyzer is None:
        raise FitAnalysisFailed(409, "지금은 분석을 쓸 수 없어요. 잠시 후 다시 시도해 주세요")
    if consent_text_version != settings.fit_analysis_consent_version:
        raise FitAnalysisFailed(409, "안내 문구가 바뀌었어요. 새로고침 후 다시 동의해 주세요")
    if not person_id:
        raise FitAnalysisFailed(404, "아직 저장된 경력이 없어요")
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 44))"),
                     {"k": f"fit:{account_id}"})
        records = member_records(conn, person_id)
        if records is None:
            raise FitAnalysisFailed(404, "아직 저장된 경력이 없어요")
        input_hash = hashlib.sha256(records.encode()).hexdigest()
        same = conn.execute(text(
            """SELECT analysis_id::text, created_at, result FROM fit_analysis
               WHERE account_id = :a AND outcome = 'DONE' AND input_hash = :h
               ORDER BY created_at DESC LIMIT 1"""), {"a": account_id, "h": input_hash}).first()
        if same is not None:
            return _view(same)
        used = conn.execute(text(
            """SELECT count(*) FROM fit_analysis WHERE account_id = :a
               AND created_at > now() - interval '1 day'
               AND NOT (outcome = 'FAILED' AND input_tokens IS NULL)"""), {"a": account_id}).scalar()
        if used >= settings.fit_analysis_daily_limit:
            raise FitAnalysisFailed(429, "오늘은 더 분석할 수 없어요. 내일 다시 시도해 주세요")
        roles = role_list(conn)
        run_id = conn.execute(text(
            """INSERT INTO fit_analysis (account_id, consent_text_version, input_hash, model, outcome)
               VALUES (:a, :v, :h, :m, 'PENDING') RETURNING analysis_id::text"""),
            {"a": account_id, "v": consent_text_version, "h": input_hash,
             "m": analyzer.model}).scalar_one()
    if not _IN_FLIGHT.acquire(blocking=False):
        _finish(engine, run_id, None, "FAILED", Usage(failure="busy"))
        raise FitAnalysisFailed(503, "지금 분석하는 분이 많아요. 잠시 후 다시 시도해 주세요")
    try:
        result, outcome, usage = analyzer.analyze(records, roles)
    finally:
        _IN_FLIGHT.release()
    if result is not None:
        known = {code for code, _, _ in roles}
        for f in result.fits:
            if f.role_code not in known:
                f.role_code = None
        gaps = result.gaps if _wants_a_role(records) else [g for g in result.gaps if not _NO_WANTED.search(g)]
        result = result.model_copy(update={"fits": result.fits[:3], "gaps": gaps[:3],
                                           "company_types": result.company_types[:3]})
    _finish(engine, run_id, result, outcome, usage)
    if result is None:
        raise FitAnalysisFailed(503, "분석하지 못했어요. 잠시 후 다시 시도해 주세요")
    with engine.begin() as conn:
        return latest(conn, account_id)


def _finish(engine: Engine, run_id: str, result: FitResult | None, outcome: str, usage: Usage) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            """UPDATE fit_analysis SET outcome = :o, result = CAST(:r AS jsonb), input_tokens = :i,
                   output_tokens = :t, failure_reason = :f
               WHERE analysis_id = CAST(:id AS uuid)"""),
            {"o": outcome if result is not None or outcome != "DONE" else "FAILED",
             "r": json.dumps(result.model_dump(), ensure_ascii=False) if result else None,
             "i": usage.input_tokens, "t": usage.output_tokens, "f": usage.failure, "id": run_id})
