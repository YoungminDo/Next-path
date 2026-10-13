"""Resume / LinkedIn-capture import (docs/10 §이력서·캡처로 시작).

A person uploads their *own* resume (PDF or image) or LinkedIn screenshots. Claude reads the
experience and education sections into a fixed structure. Nothing read is kept as a record until
the person has checked it:

- before login, the read prefills the same input form as typing by hand; the person corrects it,
  sees the preview, and logs in to see the result. The login merge writes it as their own
  SELF_REPORTED records (source LINKEDIN_USER_UPLOAD or CAREER_DOCUMENT);
- a member adds the jobs they tick to their profile, which widens what they can compare.

Own data, uploaded by the person: no scraping (LinkedIn User Agreement §8.2, docs/00). Files are
never stored: they go to the model once and are dropped; names, photos and contact details are
not extracted at all. Sending them to Anthropic (US) is an overseas transfer (PIPA §28-8): the
consent wording version is recorded on the attempt before anything is sent. Each read costs
money, so reads are limited per account, per anonymous session and for all anonymous reads
together.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import threading
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from hellomyme.config import Settings
from hellomyme.domain import ledger
from hellomyme.domain.acquisition import (
    AcqPastJob,
    EmploymentType,
    _write_job,
    import_source_type,
    load_taxonomy,
)
from hellomyme.domain.career_input import member_person_id
from hellomyme.domain.career_query import QueryInvalid
from hellomyme.domain.drafts import session_hash

log = logging.getLogger(__name__)

MAX_UPLOADS = 4  # files a person picks (shown in the form)
MAX_FILES = 6  # parts sent: the browser cuts a very long screenshot into pieces it can read
MAX_IMAGE_BYTES = 3_000_000  # decoded; the browser re-encodes screenshots before sending
MAX_PDF_BYTES = 2_500_000
MAX_TOTAL_BYTES = 3_200_000  # the web proxy takes about 4.5 MB per request (base64 adds a third)
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
PDF = "application/pdf"
MAX_ITEMS = 12
MAX_PDF_PAGES = 10  # a resume or a LinkedIn PDF; every page costs model input
# Reads in flight at once in this process (each holds a worker thread for up to 50 s).
_IN_FLIGHT = threading.BoundedSemaphore(8)


class ImportFailed(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# --- what the model returns (structured output; no names or contact details) ---------------

class ExtractedExperience(BaseModel):
    company: str | None = Field(description="Company or organization exactly as written, or null")
    title: str | None = Field(description="Job title exactly as written, or null")
    employment_type: EmploymentType | None = Field(
        description="Only if written: 인턴/Intern -> INTERN, 정규직/Full-time -> FULL_TIME, "
                    "계약직/Contract -> CONTRACT, 파트타임/Part-time -> PART_TIME; else null")
    start_year: int | None = None
    start_month: int | None = Field(default=None, description="1-12 only if written, else null")
    end_year: int | None = None
    end_month: int | None = Field(default=None, description="1-12 only if written, else null")
    is_current: bool = Field(description="true when written as 현재 / 재직 중 / Present")


class ExtractedEducation(BaseModel):
    school: str | None = None
    major: str | None = None
    degree: str | None = Field(default=None, description="e.g. 학사, 석사, Bachelor, as written")
    start_year: int | None = None
    end_year: int | None = None


class Extraction(BaseModel):
    is_career_document: bool = Field(
        description="false if the files are not a resume or a LinkedIn profile")
    source_kind: Literal["LINKEDIN", "RESUME", "OTHER"]
    experiences: list[ExtractedExperience]
    education: list[ExtractedEducation]


SYSTEM = (
    "You read one person's own resume or LinkedIn profile screenshots, uploaded by that person "
    "to fill in their career history. Extract only work experience and education. Copy company "
    "names, job titles, schools and majors exactly as written (Korean or English); do not "
    "translate or normalize them. Use null for anything not written; never guess a month or "
    "year. When one company lists several positions, return one experience per position. Do not "
    "extract the person's name, photo, headline, contact details, or anything about other "
    "people. Order experiences from most recent to oldest. Set source_kind to LINKEDIN for "
    "LinkedIn screenshots or a LinkedIn PDF and RESUME for a resume. If the files are neither, "
    "set is_career_document to false and return empty lists."
)


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class Extractor(Protocol):
    model: str

    def extract(self, files: list[tuple[str, str]]) -> tuple[Extraction | None, str, Usage]: ...


class ClaudeExtractor:
    """Claude vision/PDF with structured output. Returns (extraction or None, outcome, usage)."""

    def __init__(self, settings: Settings, client=None):
        import anthropic

        self.model = settings.career_import_model
        self.client = client or anthropic.Anthropic(
            # Inside the web proxy's 60 s: one try, then the person can retry or type it in.
            api_key=settings.anthropic_api_key.get_secret_value(), timeout=50.0, max_retries=0)

    def extract(self, files: list[tuple[str, str]]) -> tuple[Extraction | None, str, Usage]:
        import anthropic

        content: list[dict] = []
        for i, (media_type, data) in enumerate(files, 1):
            content.append({"type": "text", "text": f"File {i}:"})
            content.append({"type": "document" if media_type == PDF else "image",
                            "source": {"type": "base64", "media_type": media_type, "data": data}})
        content.append({"type": "text", "text": "Extract the work experience and education."})
        try:
            response = self.client.beta.messages.parse(
                model=self.model, max_tokens=8000, system=SYSTEM,
                messages=[{"role": "user", "content": content}],
                output_format=Extraction, output_config={"effort": "low"},
                # A safety decline is retried server-side on the model Anthropic recommends.
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except anthropic.APIStatusError as exc:
            log.error("career import: Claude API error %s (request %s)", exc.status_code,
                      getattr(exc, "request_id", None))
            return None, "FAILED", Usage()
        except anthropic.APIConnectionError:
            log.error("career import: Claude API unreachable")
            return None, "FAILED", Usage()
        except Exception:  # e.g. an answer cut off mid-JSON fails the SDK's own validation
            log.exception("career import: unreadable answer")
            return None, "FAILED", Usage()
        usage = Usage(input_tokens=response.usage.input_tokens,
                      output_tokens=response.usage.output_tokens)
        if response.stop_reason == "refusal":
            return None, "REFUSED", usage
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            return None, "FAILED", usage
        out = response.parsed_output
        return out, "PARSED" if out.is_career_document else "NOT_CAREER", usage


_EXTRACTORS: dict[tuple, ClaudeExtractor] = {}


def get_extractor(settings: Settings) -> Extractor | None:
    """None without an API key: the feature is off."""
    if not settings.anthropic_api_key:
        return None
    key = (settings.anthropic_api_key.get_secret_value(), settings.career_import_model)
    if key not in _EXTRACTORS:
        _EXTRACTORS[key] = ClaudeExtractor(settings)
    return _EXTRACTORS[key]


# --- limits and status ------------------------------------------------------------------

def _used(conn: Connection, account_id: str | None, sid: str | None) -> int:
    if account_id:
        return conn.execute(text(
            """SELECT count(*) FROM import_attempt
               WHERE account_id = :a AND created_at > now() - interval '1 day'"""),
            {"a": account_id}).scalar_one()
    return conn.execute(text(
        """SELECT count(*) FROM import_attempt
           WHERE session_hash = :s AND created_at > now() - interval '1 day'"""),
        {"s": sid}).scalar_one()


def _client_today(conn: Connection, client: str) -> int:
    return conn.execute(text(
        """SELECT count(*) FROM import_attempt
           WHERE client_hash = :c AND created_at > now() - interval '1 day'"""),
        {"c": client}).scalar_one()


def _anonymous_today(conn: Connection) -> int:
    return conn.execute(text(
        """SELECT count(*) FROM import_attempt
           WHERE account_id IS NULL AND created_at > now() - interval '1 day'""")).scalar_one()


def _limit(settings: Settings, account_id: str | None) -> int:
    return settings.career_import_daily_limit if account_id else settings.career_import_session_limit


def status(conn: Connection, settings: Settings, account_id: str | None,
           anonymous_session: str | None, extractor: Extractor | None) -> dict:
    sid = anonymous_session and session_hash(anonymous_session)
    remaining = max(_limit(settings, account_id) - _used(conn, account_id, sid), 0)
    if not account_id and _anonymous_today(conn) >= settings.career_import_anonymous_daily_limit:
        remaining = 0
    return {"enabled": extractor is not None,
            "consent_text_version": settings.career_import_consent_version,
            "stats_consent_text_version": settings.career_import_stats_consent_version,
            "max_files": MAX_UPLOADS, "remaining_today": remaining}


def _files(raw: list[dict]) -> list[tuple[str, str]]:
    if not 1 <= len(raw) <= MAX_FILES:
        raise ImportFailed(422, "한 번에 올릴 수 있는 양을 넘었어요. 파일 수를 줄여 주세요")
    out, total = [], 0
    for f in raw:
        media_type, data = f.get("media_type"), f.get("data") or ""
        if media_type not in (*IMAGE_TYPES, PDF):
            raise ImportFailed(422, "PDF나 JPG·PNG 이미지만 올릴 수 있어요")
        try:
            size = len(base64.b64decode(data, validate=True))
        except (ValueError, TypeError) as exc:
            raise ImportFailed(422, "파일을 읽지 못했어요. 다른 파일로 다시 올려 주세요") from exc
        total += size
        if size > (MAX_PDF_BYTES if media_type == PDF else MAX_IMAGE_BYTES) or total > MAX_TOTAL_BYTES:
            raise ImportFailed(413, "파일이 너무 커요. PDF는 2.5MB, 전체 3MB까지 올릴 수 있어요")
        if media_type == PDF and _pdf_pages(data) > MAX_PDF_PAGES:
            raise ImportFailed(413, f"PDF가 너무 길어요. 경력이 있는 {MAX_PDF_PAGES}쪽 이내로 올려 주세요")
        out.append((media_type, data))
    return out


def _pdf_pages(data: str) -> int:
    """Pages, counted before anything is sent (each page is model input, i.e. cost)."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(base64.b64decode(data)))
        if reader.is_encrypted:
            raise ImportFailed(422, "암호가 걸린 PDF는 읽을 수 없어요. 암호를 풀고 올려 주세요")
        return len(reader.pages)
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise ImportFailed(422, "PDF를 열지 못했어요. 다른 파일로 다시 올려 주세요") from exc


def client_hash(ip: str | None) -> str | None:
    """A per-day key for the client address (limits only; the address itself is not kept)."""
    if not ip:
        return None
    return hashlib.sha256(f"{date.today().isoformat()}:{ip.strip()}".encode()).hexdigest()


# --- read -------------------------------------------------------------------------------

def _lookup(conn: Connection, kind: str, raw: str | None) -> str | None:
    from hellomyme.ingest.pipeline import _lookup as lookup  # shared deterministic matcher

    return lookup(conn, kind, raw) if raw else None


def _year(y: int | None) -> int | None:
    return y if y is not None and 1950 <= y <= date.today().year + 6 else None


def _month(m: int | None) -> int | None:
    return m if m is not None and 1 <= m <= 12 else None


def _text(s: str | None, limit: int) -> str | None:
    s = (s or "").strip()
    return s[:limit] or None


def parse(engine: Engine, settings: Settings, account_id: str | None,
          anonymous_session: str | None, raw_files: list[dict], consent_text_version: str,
          extractor: Extractor | None, internal: bool = False, client_ip: str | None = None,
          stats_consent_text_version: str | None = None) -> dict:
    """No database connection is held while the model reads (10-30 s): each step before and
    after it is its own short transaction, so a burst of uploads cannot starve the pool."""
    if extractor is None:
        raise ImportFailed(409, "지금은 파일로 채우기를 쓸 수 없어요. 직접 입력해 주세요")
    if consent_text_version != settings.career_import_consent_version:
        raise ImportFailed(409, "안내 문구가 바뀌었어요. 새로고침 후 다시 동의해 주세요")
    if stats_consent_text_version not in (None, settings.career_import_stats_consent_version):
        raise ImportFailed(409, "안내 문구가 바뀌었어요. 새로고침 후 다시 동의해 주세요")
    if not account_id and (not anonymous_session or len(anonymous_session) < 16):
        raise ImportFailed(400, "세션 정보가 없어요. 새로고침 후 다시 시도해 주세요")
    files = _files(raw_files)
    if not _IN_FLIGHT.acquire(blocking=False):
        raise ImportFailed(503, "지금 읽는 분이 많아요. 잠시 후 다시 시도해 주세요")
    try:
        return _parse(engine, settings, account_id, anonymous_session, files, consent_text_version,
                      extractor, internal, client_hash(client_ip), stats_consent_text_version)
    finally:
        _IN_FLIGHT.release()


def _parse(engine: Engine, settings: Settings, account_id: str | None,
           anonymous_session: str | None, files: list[tuple[str, str]], consent_text_version: str,
           extractor: Extractor, internal: bool, client: str | None,
           stats_version: str | None) -> dict:
    # The session is kept for members too: a draft made in this browser can then name the read.
    sid = anonymous_session and session_hash(anonymous_session)
    # The attempt (with the consent wording version) is committed before anything leaves: it is
    # the record of the transfer consent, and it counts against the limits even if the read fails.
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 31))"),
                     {"k": f"career-import:{account_id or sid}"})
        if _used(conn, account_id, sid) >= _limit(settings, account_id):
            raise ImportFailed(429, "오늘은 더 읽을 수 없어요. 내일 다시 시도하거나 직접 입력해 주세요")
        if not account_id:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('career-import:anon', 31))"))
            # One address (as the web proxy saw it) cannot use up everyone's reads.
            if client and _client_today(conn, client) >= settings.career_import_client_limit:
                raise ImportFailed(429, "오늘은 더 읽을 수 없어요. 내일 다시 시도하거나 직접 입력해 주세요")
            if _anonymous_today(conn) >= settings.career_import_anonymous_daily_limit:
                raise ImportFailed(429, "오늘은 요청이 많아 파일 읽기를 잠시 멈췄어요. 직접 입력해 주세요")
        attempt_id = conn.execute(text(
            """INSERT INTO import_attempt (account_id, session_hash, client_hash, internal, files,
                   consent_text_version, stats_consent_version, model)
               VALUES (:a, :s, :c, :i, :n, :v, :sv, :m) RETURNING import_attempt_id::text"""),
            {"a": account_id, "s": sid, "c": client, "i": internal, "n": len(files),
             "v": consent_text_version, "sv": stats_version, "m": extractor.model}).scalar_one()
        _purge(conn, settings.career_import_retention_days)

    try:
        extraction, outcome, usage = extractor.extract(files)
    except Exception:  # never leave the attempt open
        log.exception("career import: reader failed")
        extraction, outcome, usage = None, "FAILED", Usage()

    with engine.begin() as conn:
        conn.execute(text(
            """UPDATE import_attempt SET outcome = :o, source_kind = :k, input_tokens = :i,
                   output_tokens = :t, experiences = :e, finished_at = now()
               WHERE import_attempt_id = CAST(:id AS uuid)"""),
            {"o": outcome, "k": extraction and extraction.source_kind, "i": usage.input_tokens,
             "t": usage.output_tokens, "id": attempt_id,
             "e": len(extraction.experiences) if extraction else None})
    if outcome == "NOT_CAREER":
        raise ImportFailed(422, "이력서나 링*드인 캡처가 아닌 것 같아요. 경력이 보이는 파일을 올려 주세요")
    if extraction is None:
        raise ImportFailed(502, "파일을 읽지 못했어요. 잠시 후 다시 시도하거나 직접 입력해 주세요")
    with engine.begin() as conn:
        read = _suggest(conn, attempt_id, extraction, account_id)
        if stats_version:
            _keep(conn, read)
        return read


def _keep(conn: Connection, read: dict) -> None:
    """What the read showed, kept as anonymous statistics input (the person agreed separately).
    As read and checked for plausibility only; unknown stays NULL; nothing about the person."""
    for i, x in enumerate(read["experiences"], 1):
        conn.execute(text(
            """INSERT INTO import_experience (import_attempt_id, ordinal, company_raw, title_raw,
                   employment_type, start_year, start_month, end_year, end_month, is_current,
                   role_taxonomy_node_id, organization_id)
               VALUES (CAST(:a AS uuid), :o, :c, :t, :et, :sy, :sm, :ey, :em, :cur,
                       CAST(:r AS uuid), CAST(:org AS uuid))"""),
            {"a": read["import_attempt_id"], "o": i, "c": x["company"], "t": x["title"],
             "et": x["employment_type"], "sy": x["start_year"], "sm": x["start_month"],
             "ey": x["end_year"], "em": x["end_month"], "cur": x["is_current"],
             "r": x["suggested_role_node_id"], "org": x["suggested_organization_id"]})
    for i, e in enumerate(read["education"], 1):
        conn.execute(text(
            """INSERT INTO import_education (import_attempt_id, ordinal, school_raw, major_raw,
                   degree_raw, start_year, end_year, institution_id, major_taxonomy_node_id)
               VALUES (CAST(:a AS uuid), :o, :s, :m, :d, :sy, :ey, CAST(:i AS uuid),
                       CAST(:mj AS uuid))"""),
            {"a": read["import_attempt_id"], "o": i, "s": e["school"], "m": e["major"],
             "d": e["degree"], "sy": e["start_year"], "ey": e["end_year"],
             "i": e["suggested_institution_id"], "mj": e["suggested_major_node_id"]})


def _purge(conn: Connection, days: int) -> None:
    """Rows kept for statistics leave after the retention period promised in the consent."""
    for table in ("import_experience", "import_education"):
        conn.execute(text(f"DELETE FROM {table} WHERE created_at < now() - make_interval(days => :d)"),
                     {"d": days})


def _suggest(conn: Connection, attempt_id: str, extraction: Extraction,
             account_id: str | None) -> dict:
    person_id = account_id and member_person_id(conn, account_id)
    existing = _existing_jobs(conn, person_id) if person_id else []
    experiences, seen = [], set()
    for x in extraction.experiences:
        company, title = _text(x.company, 200), _text(x.title, 200)
        sy, ey = _year(x.start_year), None if x.is_current else _year(x.end_year)
        sm, em = _month(x.start_month), _month(x.end_month) if ey else None
        if sy and ey and (ey, em or 12) < (sy, sm or 1):
            ey = em = None  # a misread end date: left for the person to fill in
        # The same position twice (overlapping screenshot pieces, two captures) is shown once.
        key = (_norm(company), _norm(title), sy, sm)
        if key in seen:
            continue
        seen.add(key)
        if len(experiences) >= MAX_ITEMS:
            break
        role = _lookup(conn, "ROLE", title)
        experiences.append({
            "company": company, "title": title, "employment_type": x.employment_type,
            "start_year": sy, "start_month": sm if sy else None, "end_year": ey, "end_month": em,
            "is_current": x.is_current,
            "suggested_role_node_id": role,
            "suggested_organization_id": _lookup(conn, "ORGANIZATION", company),
            "already_saved": _duplicate(existing, company, role, sy)})
    education = []
    for e in extraction.education[:MAX_ITEMS]:
        school, major = _text(e.school, 100), _text(e.major, 200)
        education.append({
            "school": school, "major": major, "degree": _text(e.degree, 50),
            "start_year": _year(e.start_year), "end_year": _year(e.end_year),
            "suggested_institution_id": _lookup(conn, "INSTITUTION", school),
            "suggested_major_node_id": _lookup(conn, "MAJOR", major)})
    return {"import_attempt_id": attempt_id, "source_kind": extraction.source_kind,
            "experiences": experiences, "education": education}


def attempt_belongs(conn: Connection, attempt_id: str, account_id: str | None,
                    anonymous_session: str | None) -> bool:
    """A draft may name only a read made by the same browser session (or the same member)."""
    return conn.execute(text(
        """SELECT 1 FROM import_attempt WHERE import_attempt_id::text = :i AND outcome = 'PARSED'
             AND (session_hash = :s OR (CAST(:a AS uuid) IS NOT NULL AND account_id = CAST(:a AS uuid)))"""),
        {"i": attempt_id, "s": anonymous_session and session_hash(anonymous_session),
         "a": account_id}).first() is not None


# --- member: add the ticked jobs to the profile ------------------------------------------

def _existing_jobs(conn: Connection, person_id: str) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(text(
        """SELECT coalesce(organization_raw, '') AS org, role_taxonomy_node_id::text AS role,
                  extract(year FROM start_date)::int AS year
           FROM work_event WHERE person_id = :p"""), {"p": person_id})]


def _norm(s: str | None) -> str:
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())


def _duplicate(existing: list[dict], org: str | None, role: str | None, year: int | None) -> bool:
    """Already on record: same start year and the same company; when either side has no company
    (it is optional when typed by hand), the same role."""
    if year is None:
        return False
    key = _norm(org)
    for e in existing:
        if e["year"] != year:
            continue
        other = _norm(e["org"])
        if key and other and key == other:
            return True
        if (not key or not other) and role and e["role"] == role:
            return True
    return False


def confirm(conn: Connection, account_id: str, person_id: str, attempt_id: str,
            jobs: list[AcqPastJob], idempotency_key: str) -> dict:
    if not jobs:
        raise ImportFailed(422, "더할 경력을 하나 이상 골라 주세요")
    if len(jobs) > MAX_ITEMS:
        raise ImportFailed(422, f"한 번에 {MAX_ITEMS}개까지 더할 수 있어요")
    owned = conn.execute(text(
        "SELECT 1 FROM import_attempt WHERE import_attempt_id::text = :i AND account_id = :a"),
        {"i": attempt_id, "a": account_id}).first()
    source_type = owned and import_source_type(conn, attempt_id)
    if not source_type:
        raise ImportFailed(404, "읽은 결과를 찾지 못했어요. 다시 올려 주세요")
    roles = load_taxonomy(conn, "ROLE")
    if any(j.role_node_id and j.role_node_id not in roles.nodes for j in jobs):
        raise QueryInvalid("unknown role")

    return add_jobs(conn, account_id, person_id, source_type,
                    f"career_import:{account_id}:{idempotency_key}", attempt_id, jobs, roles)


def add_jobs(conn: Connection, account_id: str, person_id: str, source_type: str, source_key: str,
             attempt_id: str, jobs: list[AcqPastJob], roles) -> dict:
    """Jobs from a read file added to an existing profile under one source record (a replay
    writes nothing); jobs already on record are skipped."""
    source_id = conn.execute(text(
        """INSERT INTO source_record (source_type, data_layer, source_system, source_key,
               raw_payload, legal_basis, metadata)
           VALUES (:t, 'VERIFIED', 'HELLOMYME_APP', :k, CAST(:raw AS jsonb), 'MEMBER_CONSENT',
                   CAST(:meta AS jsonb))
           ON CONFLICT (source_system, source_key) DO NOTHING RETURNING source_id::text"""),
        {"t": source_type, "k": source_key,
         "raw": json.dumps([j.model_dump() for j in jobs], ensure_ascii=False),
         "meta": json.dumps({"import_attempt_id": attempt_id})}).scalar()
    if source_id is None:
        return {"replayed": True, "added": 0, "skipped": 0, "rewards": []}

    existing = _existing_jobs(conn, person_id)
    added, skipped, rewards = 0, 0, []
    for j in jobs:
        if _duplicate(existing, j.organization_name, j.role_node_id, j.start_year):
            skipped += 1
            continue
        weid = _write_job(conn, person_id, account_id, source_id, j, j.is_current, roles)
        existing.append({"org": j.organization_name or "", "role": j.role_node_id,
                         "year": j.start_year})
        added += 1
        rewards.append(ledger.grant_reward(
            conn, account_id, "CURRENT_ROLE_ADDED" if j.is_current else "PREVIOUS_CAREER_ADDED",
            "WORK_EVENT", weid))
    return {"replayed": False, "added": added, "skipped": skipped,
            "rewards": [{"ledger_id": r.ledger_id, "amount": r.amount} for r in rewards if r]}


def add_draft_jobs(conn: Connection, account_id: str, person_id: str, payload, draft_id: str) -> dict:
    """A returning member who started from a file before logging in: the jobs they confirmed in
    the form are added to the profile they already have (nothing else of the draft is)."""
    source_type = import_source_type(conn, payload.import_attempt_id)
    if not source_type:
        return {"replayed": False, "added": 0, "skipped": 0, "rewards": []}
    jobs = list(payload.other_jobs)
    if payload.current_job is not None:
        jobs.append(AcqPastJob(**payload.current_job.model_dump(), is_current=True))
    if payload.first_job is not None and not payload.first_job_is_current:
        jobs.append(AcqPastJob(**payload.first_job.model_dump()))
    if not jobs:
        return {"replayed": False, "added": 0, "skipped": 0, "rewards": []}
    return add_jobs(conn, account_id, person_id, source_type, f"draft:{draft_id}:jobs",
                    payload.import_attempt_id, jobs, load_taxonomy(conn, "ROLE"))
