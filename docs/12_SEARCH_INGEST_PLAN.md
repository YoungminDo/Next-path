# Search Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Render cron job that searches public-profile snippets (SerpAPI + Brave), turns each into a `career_extraction.v1` document with the name masked, and hands it to the existing `receive()` for human review as SEED statistics input.

**Architecture:** Four focused modules in `apps/api/hellomyme/ingest/` — `snippet.py` (pure conversion), `search_source.py` (HTTP clients), `search_plan.py` (which queries this run), `search_run.py` (one run on the caller's connection, one savepoint per person) — plus a `search-run` CLI subcommand and a `type: cron` service in `render.yaml`. Migration 0041 adds `search_ingest_policy`, `search_query`, `search_run`. Spec: `docs/12_SEARCH_INGEST.md`.

**Tech Stack:** Python 3.12+, SQLAlchemy 2 (`text()` raw SQL), Alembic raw-SQL migrations, pydantic-settings, pytest against PostgreSQL 16 (`hellomyme_test`), stdlib `urllib` for HTTP (no new dependency).

## Global Constraints

- Statistics only: `source_type='PUBLIC_PROFILE'`, `permitted_use='AGGREGATE_ONLY'`; nothing is shown as a person/profile (docs/09 §8).
- Every field goes through human review: the job calls `receive()` only, never `accept_pending()` or `approve()`.
- `person.display_name_raw` is always `null`; the title's first segment (the name) is replaced with `[person_pii]` in every evidence text before `receive()`.
- Profile URLs are never stored: `external_submission_id` = sha256 of `linkedin:<slug>`.
- Unknown = NULL: a date is attached only when it sits in the same snippet segment as that organization/school; a month is never invented.
- One collector: `search-cron`. `prompt_version='snippet_v1'`. `model_version` = `serpapi-google` or `brave`.
- Providers alternate per query; 401/403/429 removes a provider for the rest of the run and the failed query is retried once on the other; both gone = run FAILED.
- Production refuses to run unless `HELLOMYME_PUBLIC_PROFILE_LEGAL_REVIEWED=true`.
- Every new table enables RLS (`tests/test_data_api_lock.py`).
- Policy numbers live in `search_ingest_policy` (seed `search_v1`: 20 / 10 / 30 / 30 / 5), never in code.
- Settings: `serpapi_key`, `brave_api_key`, `public_profile_legal_basis`, `public_profile_legal_reviewed` (env prefix `HELLOMYME_`).
- `--dry-run` = the same run inside one transaction that is rolled back (searches really happen; nothing is received or logged).
- Repo style: ruff line length 110, docstrings that say why, raw SQL via `text()`.

## Prerequisites (once)

Tests need the test database, so Docker Desktop must be running.

```bash
cd C:/Next-path && make db
cd apps/api && PYTHONUTF8=1 uv run pytest tests/test_ingest.py -q   # baseline passes
```
On Windows prefix Python runs with `PYTHONUTF8=1` (`pipeline._validator()` reads the schema with the locale encoding).

## File Structure

| File | Responsibility |
|---|---|
| Create `apps/api/hellomyme/ingest/snippet.py` | `profile_key(url)`, `to_extraction(title, snippet, submission_id)` — pure |
| Create `apps/api/hellomyme/ingest/search_source.py` | `Result`, `SearchError`, `SerpApi`, `Brave`, `from_settings()` |
| Create `apps/api/hellomyme/ingest/search_plan.py` | `Policy`, `active_policy()`, `PlannedQuery`, `demand_candidates()`, `plan()` |
| Create `apps/api/hellomyme/ingest/search_run.py` | `run(conn, *, settings, providers, as_of, now)` |
| Create `apps/api/migrations/versions/0041_search_ingest.py` | three tables, RLS, policy seed |
| Modify `apps/api/hellomyme/config.py` | four settings |
| Modify `apps/api/hellomyme/ingest/cli.py` | `search-run` subcommand |
| Modify `render.yaml` | `nextpath-search-ingest` cron service |
| Modify `scripts/linkedin_snippet_yield.py` | use `snippet.py` instead of its own copy |
| Modify `docs/12_SEARCH_INGEST.md`, `docs/03_DEPLOYMENT.md` | dry-run wording, status, deploy row |
| Create `apps/api/tests/test_snippet.py`, `test_search_source.py`, `test_search_plan.py`, `test_search_run.py` | tests |

---

### Task 1: Snippet → career_extraction.v1 (`snippet.py`)

**Files:**
- Create: `apps/api/hellomyme/ingest/snippet.py`
- Modify: `scripts/linkedin_snippet_yield.py`
- Test: `apps/api/tests/test_snippet.py`

**Interfaces:**
- Consumes: `hellomyme.ingest.pipeline.check(doc, as_of) -> list[Issue]` (existing)
- Produces:
  - `PROMPT_VERSION = "snippet_v1"`, `MASK = "[person_pii]"`
  - `profile_key(url: str) -> str | None` — 64-char hex; `None` when not a `linkedin.com/in/` URL
  - `to_extraction(title: str, snippet: str, submission_id: str) -> dict | None` — `None` when neither an education nor a work event was read

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_snippet.py`:
```python
"""Search result -> career_extraction.v1 (docs/12). Pure: no database."""
import json
from datetime import date

from hellomyme.ingest.pipeline import check
from hellomyme.ingest.snippet import MASK, profile_key, to_extraction

AS_OF = date(2026, 10, 15)
TITLE = "홍길동 - 백엔드 개발자 - 토스 | LinkedIn"
SNIPPET = ("경력: 토스, 카카오 · 토스 2022.03 - 현재 · 카카오 2019 - 2022 · 학력: 고려대학교 · "
           "고려대학교 컴퓨터학과 2013 - 2019 · 홍길동님의 프로필")


def test_profile_key_ignores_subdomain_query_and_case():
    a = profile_key("https://kr.linkedin.com/in/Hong-GilDong/?trk=x")
    b = profile_key("https://www.linkedin.com/in/hong-gildong")
    assert a == b and len(a) == 64
    assert profile_key("https://www.linkedin.com/company/toss") is None


def test_passes_the_pipeline_checks_without_blocks():
    doc = to_extraction(TITLE, SNIPPET, "k1")
    assert not [i for i in check(doc, AS_OF) if i.severity == "BLOCK"]


def test_dates_only_from_the_same_segment_and_no_invented_month():
    doc = to_extraction(TITLE, SNIPPET, "k1")
    jobs = {w["organization_raw"]: w for w in doc["work_events"]}
    assert jobs["토스"]["start"] == {"value": "2022-03", "precision": "MONTH"}
    assert jobs["토스"]["is_current"] is True
    assert jobs["카카오"]["start"] == {"value": "2019", "precision": "YEAR"}
    assert jobs["카카오"]["end"] == {"value": "2022", "precision": "YEAR"}
    edu = doc["educations"][0]
    assert edu["institution_raw"] == "고려대학교" and edu["major_raw"] == "컴퓨터학과"
    assert edu["start"]["value"] == "2013" and edu["end"]["value"] == "2019"


def test_a_lone_year_is_not_attached_to_any_job():
    doc = to_extraction("Kim Lee – PM – Coupang | LinkedIn",
                        "Experience: Coupang, Naver · Seoul · 2019", "k2")
    assert all("start" not in w for w in doc["work_events"])


def test_the_name_never_leaves_the_function():
    doc = to_extraction(TITLE, SNIPPET, "k1")
    assert "홍길동" not in json.dumps(doc, ensure_ascii=False)
    assert doc["person"]["display_name_raw"] is None
    assert doc["person"]["headline_raw"] == "백엔드 개발자 - 토스"
    # A company shown only in the title has the title line as its evidence: the name is masked there.
    doc = to_extraction("홍길동 - PM - 쿠팡 | LinkedIn", "서울", "k4")
    dumped = json.dumps(doc, ensure_ascii=False)
    assert "홍길동" not in dumped and MASK in dumped


def test_nothing_read_is_empty():
    assert to_extraction("박영희 | LinkedIn", "서울 · 1촌 300명 이상", "k3") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Next-path/apps/api && PYTHONUTF8=1 uv run pytest tests/test_snippet.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hellomyme.ingest.snippet'`

- [ ] **Step 3: Write the implementation**

`apps/api/hellomyme/ingest/snippet.py`:
```python
"""Search result (title + snippet of a public profile) -> career_extraction.v1 (docs/12).

Rule-based, raw text only: the same contract as the AI path, so receive() checks it and a person
reviews every field. Unknown = NULL: a date is attached only when it sits in the same snippet
segment as that organization or school, and a month is never invented. The name (the title's
first segment) is never copied: display_name_raw is null and every evidence text masks it,
because parse_run.raw_output keeps what receive() is given forever.
"""
from __future__ import annotations

import hashlib
import re
import urllib.parse

PROMPT_VERSION = "snippet_v1"
MASK = "[person_pii]"
ASSET = "S1"

_PROFILE = re.compile(r"linkedin\.com/in/([^/?#]+)", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_POINT = (r"(?:(?P<{p}mon>[A-Za-z]{{3}})\w*\.?\s+(?P<{p}y1>(?:19|20)\d\d)"
          r"|(?P<{p}y2>(?:19|20)\d\d)(?:\s*[.\-/년]\s*(?P<{p}m>\d{{1,2}})월?)?)")
_RANGE = re.compile(_POINT.format(p="s") + r"\s*[-–~]\s*(?:(?P<now>Present|현재|재직\s*중)|"
                    + _POINT.format(p="e") + ")", re.I)
_EXPERIENCE = re.compile(r"(?:Experience|경력)\s*[:：]\s*([^·|\n]+)")
_EDUCATION = re.compile(r"(?:Education|학력)\s*[:：]\s*([^·|\n]+)")
_SCHOOL = re.compile(r"[가-힣A-Za-z ]*?(?:대학교|대학|University|College)(?:\s*\([^)]*\))?")
_MAJOR = re.compile(r"([가-힣]+(?:학과|학부|전공))")


def profile_key(url: str) -> str | None:
    """sha256 of the profile slug: one key per person whatever subdomain, query or case the
    search engine returned. The URL itself is never stored."""
    m = _PROFILE.search(url or "")
    if not m:
        return None
    slug = urllib.parse.unquote(m.group(1)).strip().lower()
    return hashlib.sha256(f"linkedin:{slug}".encode()).hexdigest()


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" .,…")


def _point(m: re.Match, p: str) -> dict | None:
    mon, y = m.group(p + "mon"), m.group(p + "y1") or m.group(p + "y2")
    if not y:
        return None
    month = _MONTHS.get((mon or "")[:3].lower()) or (int(m.group(p + "m")) if m.group(p + "m") else None)
    if month and 1 <= month <= 12:
        return {"value": f"{y}-{month:02d}", "precision": "MONTH"}
    return {"value": y, "precision": "YEAR"}


def _dates(segment: str) -> dict:
    m = _RANGE.search(segment)
    if not m:
        return {}
    out = {"start": _point(m, "s")}
    if m.group("now"):
        out["is_current"] = True
    else:
        out["end"] = _point(m, "e")
    return {k: v for k, v in out.items() if v is not None}


def to_extraction(title: str, snippet: str, submission_id: str) -> dict | None:
    """One search result as career_extraction.v1, or None when it carries neither an education
    nor a work event (nothing for a reviewer to look at)."""
    snippet = snippet or ""
    t = re.sub(r"\s*\|\s*LinkedIn.*$", "", title or "", flags=re.I)
    head = [_clean(p) for p in re.split(r"\s+[-–—]\s+", t)]
    name, parts = (head[0] or None), [p for p in head[1:] if p]

    def ev(s: str) -> list[dict]:
        text = s.replace(name, MASK) if name else s
        return [{"asset_id": ASSET, "text": text[:2000]}]

    segments = [_clean(s) for s in re.split(r"[·|\n]", snippet) if _clean(s)]
    orgs = [parts[-1]] if parts else []
    for m in _EXPERIENCE.finditer(snippet):
        orgs += [_clean(c) for c in re.split(r",|，", m.group(1)) if _clean(c)]

    work_events = []
    for i, org in enumerate(dict.fromkeys(o for o in orgs if o), 1):
        seg = next((s for s in segments if org in s and _RANGE.search(s)), None)
        we = {"local_id": f"W{i}", "organization_raw": org, "event_type_hint": "UNKNOWN",
              "evidence": ev(seg or (t if org in t else snippet))}
        if i == 1 and len(parts) >= 2:
            we["role_raw"] = parts[0]
        if seg:
            we.update(_dates(seg))
        work_events.append(we)

    schools = [_clean(m.group(1)) for m in _EDUCATION.finditer(snippet)]
    if not schools:
        schools = [_clean(s) for s in _SCHOOL.findall(snippet)]
    educations = []
    for i, school in enumerate(dict.fromkeys(s for s in schools if s), 1):
        seg = (next((s for s in segments if school in s and (_MAJOR.search(s) or _RANGE.search(s))), None)
               or next((s for s in segments if school in s), snippet))
        ed = {"local_id": f"E{i}", "institution_raw": school, "evidence": ev(seg)}
        major = _MAJOR.search(seg)
        if major:
            ed["major_raw"] = major.group(1)
        d = _dates(seg)
        for key in ("start", "end"):
            if d.get(key):
                ed[key] = d[key]
        educations.append(ed)

    if not educations and not work_events:
        return None
    return {
        "schema_version": "career_extraction.v1",
        "submission_id": submission_id,
        "assets": [{"asset_id": ASSET, "page_order": 1}],
        "person": {"display_name_raw": None, "headline_raw": " - ".join(parts) or None},
        "educations": educations,
        "work_events": work_events,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Next-path/apps/api && PYTHONUTF8=1 uv run pytest tests/test_snippet.py -q && uv run ruff check hellomyme/ingest/snippet.py tests/test_snippet.py`
Expected: `6 passed`, `All checks passed!`

- [ ] **Step 5: Point the yield script at the module**

In `scripts/linkedin_snippet_yield.py`:
1. Delete the local definitions `MONTHS`, `POINT`, `RANGE`, `EXPERIENCE`, `EDUCATION`, `SCHOOL`, `MAJOR`, `_clean`, `_point`, `_dates`, `to_extraction`, and the `import hashlib` line.
2. Below `from hellomyme.ingest.pipeline import _norm, check  # noqa: E402` add:
```python
from hellomyme.ingest.snippet import profile_key, to_extraction  # noqa: E402
```
3. In `run()`, replace the block from `if "linkedin.com/in/" not in url:` through `doc = to_extraction(title, snippet)` with:
```python
        h = profile_key(url)
        if h is None or h in seen:
            continue
        seen.add(h)
        doc = to_extraction(title, snippet, "snippet")
        if doc is None:
            codes["EMPTY"] += 1
            continue
```
4. `self_test()` keeps its fixtures and expectations: the third fixture ("박영희 - 카카오") is not empty, because a company shown in the title is a work event. Assertions: `unique_profiles == 3`, `schema_pass == 3`, `school_mapped == 2`, `nextpath_ready == 1`, `transition_ready == 1`, `WARN:MISSING_START == 3`.

Run: `cd C:/Next-path && PYTHONUTF8=1 uv run --project apps/api python scripts/linkedin_snippet_yield.py --self-test >/dev/null && cd apps/api && uv run ruff check ../../scripts/linkedin_snippet_yield.py`
Expected: `self-test ok`, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
cd C:/Next-path
git add apps/api/hellomyme/ingest/snippet.py apps/api/tests/test_snippet.py scripts/linkedin_snippet_yield.py
git commit -m "ingest: snippet -> career_extraction.v1 with the name masked (docs/12)"
```

---

### Task 2: Settings + migration 0041

**Files:**
- Modify: `apps/api/hellomyme/config.py` (after `interview_reward_text`)
- Create: `apps/api/migrations/versions/0041_search_ingest.py`
- Modify: `docs/12_SEARCH_INGEST.md` (§2 CLI row, §3 `search_run` row)
- Test: `apps/api/tests/test_search_plan.py` (first test; the file grows in Task 4)

**Interfaces:**
- Produces: tables `search_ingest_policy`, `search_query`, `search_run` (columns below); settings `serpapi_key: SecretStr | None`, `brave_api_key: SecretStr | None`, `public_profile_legal_basis: str | None`, `public_profile_legal_reviewed: bool`

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_search_plan.py`:
```python
"""Search ingest planning (docs/12 §4). Each test runs in a transaction that is rolled back."""
import pytest
from sqlalchemy import text


@pytest.fixture
def conn(engine):
    with engine.connect() as c:
        tx = c.begin()
        yield c
        tx.rollback()


def test_seeded_policy_is_the_one_active(conn):
    rows = conn.execute(text(
        """SELECT version, max_queries_per_run, results_per_query, requery_after_days,
                  demand_lookback_days, max_consecutive_errors
           FROM search_ingest_policy WHERE status = 'ACTIVE'""")).all()
    assert [tuple(r) for r in rows] == [("search_v1", 20, 10, 30, 30, 5)]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd C:/Next-path/apps/api && uv run pytest tests/test_search_plan.py -q`
Expected: FAIL — `relation "search_ingest_policy" does not exist`

- [ ] **Step 3: Write the migration**

`apps/api/migrations/versions/0041_search_ingest.py`:
```python
"""Search ingest (docs/12): public-profile snippets from search APIs, received for review as SEED.

- search_ingest_policy: how much one run may search; numbers are policy, not code. One ACTIVE.
- search_query: operator queries and the demand-based ones the planner adds (same table).
- search_run: one row per run with its counts; no result text is kept.
Every table enables RLS (migration 0025: nothing is served over the Supabase Data API).

Revision ID: 0041
Revises: 0040
"""
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE search_ingest_policy (
        search_ingest_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        version                 text NOT NULL UNIQUE,
        status                  text NOT NULL CHECK (status IN ('ACTIVE','RETIRED')),
        max_queries_per_run     integer NOT NULL CHECK (max_queries_per_run > 0),
        results_per_query       integer NOT NULL CHECK (results_per_query BETWEEN 1 AND 20),
        requery_after_days      integer NOT NULL CHECK (requery_after_days >= 0),
        demand_lookback_days    integer NOT NULL CHECK (demand_lookback_days > 0),
        max_consecutive_errors  integer NOT NULL CHECK (max_consecutive_errors > 0),
        created_at              timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX search_ingest_policy_one_active_uq ON search_ingest_policy ((true))
        WHERE status = 'ACTIVE';
    INSERT INTO search_ingest_policy (version, status, max_queries_per_run, results_per_query,
        requery_after_days, demand_lookback_days, max_consecutive_errors)
    VALUES ('search_v1', 'ACTIVE', 20, 10, 30, 30, 5);

    CREATE TABLE search_query (
        search_query_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        query_text      text NOT NULL UNIQUE,
        origin          text NOT NULL CHECK (origin IN ('OPERATOR','DEMAND')),
        status          text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','PAUSED')),
        institution_id  uuid REFERENCES institution,
        major_node_id   uuid REFERENCES taxonomy_node,
        last_run_at     timestamptz,
        last_provider   text CHECK (last_provider IN ('serpapi','brave')),
        created_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX search_query_due_idx ON search_query (origin, status, last_run_at);

    CREATE TABLE search_run (
        search_run_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        started_at     timestamptz NOT NULL DEFAULT now(),
        finished_at    timestamptz,
        status         text NOT NULL DEFAULT 'RUNNING'
                           CHECK (status IN ('RUNNING','DONE','FAILED','SKIPPED')),
        reason         text,
        queries        integer NOT NULL DEFAULT 0,
        results        integer NOT NULL DEFAULT 0,
        received       integer NOT NULL DEFAULT 0,
        replayed       integer NOT NULL DEFAULT 0,
        already_loaded integer NOT NULL DEFAULT 0,
        rejected       integer NOT NULL DEFAULT 0,
        empty          integer NOT NULL DEFAULT 0,
        errors         integer NOT NULL DEFAULT 0,
        by_provider    jsonb NOT NULL DEFAULT '{}'
    );

    ALTER TABLE search_ingest_policy ENABLE ROW LEVEL SECURITY;
    ALTER TABLE search_query ENABLE ROW LEVEL SECURITY;
    ALTER TABLE search_run ENABLE ROW LEVEL SECURITY;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE search_run; DROP TABLE search_query; DROP TABLE search_ingest_policy;")
```

- [ ] **Step 4: Add the settings**

In `apps/api/hellomyme/config.py`, after the `interview_reward_text: str | None = None` line:
```python
    # Search ingest (docs/12): public-profile snippets from search APIs, received for review as
    # SEED statistics input. Either key alone works; with both the run alternates per query.
    # Production also needs the legal review flag (docs/09 §9), like the workbook's --legal-reviewed.
    serpapi_key: SecretStr | None = None
    brave_api_key: SecretStr | None = None
    public_profile_legal_basis: str | None = None
    public_profile_legal_reviewed: bool = False
```

- [ ] **Step 5: Update the spec**

In `docs/12_SEARCH_INGEST.md`:
- §2, CLI row description → `크론 진입점. \`--dry-run\`은 같은 회차를 한 트랜잭션 안에서 돌리고 마지막에 롤백한다(검색은 실제로 하고, 접수·기록은 남지 않음)`
- §3, `search_run` row → remove `` `dry_run`, `` from the column list.

- [ ] **Step 6: Run tests**

Run: `cd C:/Next-path/apps/api && uv run pytest tests/test_search_plan.py tests/test_data_api_lock.py -q && uv run ruff check .`
Expected: `2 passed`, `All checks passed!` (the session fixture rebuilds the schema to head, so 0041 is applied)

- [ ] **Step 7: Commit**

```bash
cd C:/Next-path
git add apps/api/hellomyme/config.py apps/api/migrations/versions/0041_search_ingest.py apps/api/tests/test_search_plan.py docs/12_SEARCH_INGEST.md
git commit -m "search ingest: settings and migration 0041 (policy, queries, runs; RLS)"
```

---

### Task 3: Search clients (`search_source.py`)

**Files:**
- Create: `apps/api/hellomyme/ingest/search_source.py`
- Test: `apps/api/tests/test_search_source.py`

**Interfaces:**
- Consumes: `Settings.serpapi_key`, `Settings.brave_api_key` (Task 2)
- Produces:
  - `@dataclass(frozen=True) Result(url: str, title: str, snippet: str)`
  - `class SearchError(Exception)` with `.provider: str`, `.status: int | None`, `.fatal: bool` (status in 401/403/429)
  - `SerpApi(key)` / `Brave(key)` with `name` (`"serpapi"` / `"brave"`), `model_version` (`"serpapi-google"` / `"brave"`), `search(query: str, count: int) -> list[Result]`
  - `from_settings(settings) -> list[SerpApi | Brave]` — serpapi first, only those with a key

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_search_source.py`:
```python
"""Search API clients (docs/12). HTTP is replaced; no real request is made."""
import io
import json
import urllib.error

import pytest
from pydantic import SecretStr

from hellomyme.ingest import search_source
from hellomyme.ingest.search_source import Brave, Result, SearchError, SerpApi, from_settings


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake(monkeypatch, payload=None, status=None):
    seen = {}

    def urlopen(req, timeout):
        seen["url"], seen["headers"] = req.full_url, dict(req.headers)
        if status:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, None)
        return _Resp(json.dumps(payload).encode())
    monkeypatch.setattr(search_source.urllib.request, "urlopen", urlopen)
    return seen


def test_serpapi_maps_organic_results(monkeypatch):
    seen = _fake(monkeypatch, {"organic_results": [
        {"link": "https://kr.linkedin.com/in/a", "title": "A - PM - X | LinkedIn", "snippet": "s"}]})
    out = SerpApi("k").search('site:linkedin.com/in "x"', 10)
    assert out == [Result("https://kr.linkedin.com/in/a", "A - PM - X | LinkedIn", "s")]
    assert "engine=google" in seen["url"] and "num=10" in seen["url"] and "api_key=k" in seen["url"]


def test_brave_joins_extra_snippets_and_sends_the_key_as_header(monkeypatch):
    seen = _fake(monkeypatch, {"web": {"results": [
        {"url": "https://www.linkedin.com/in/b", "title": "B | LinkedIn", "description": "d",
         "extra_snippets": ["e1", "e2"]}]}})
    out = Brave("k").search("q", 10)
    assert out == [Result("https://www.linkedin.com/in/b", "B | LinkedIn", "d · e1 · e2")]
    # urllib.request.Request stores header names capitalised this way
    assert seen["headers"]["X-subscription-token"] == "k"
    assert "count=10" in seen["url"]


@pytest.mark.parametrize("status,fatal", [(401, True), (429, True), (500, False)])
def test_http_errors_say_whether_the_provider_is_unusable(monkeypatch, status, fatal):
    _fake(monkeypatch, status=status)
    with pytest.raises(SearchError) as e:
        SerpApi("k").search("q", 10)
    assert (e.value.provider, e.value.status, e.value.fatal) == ("serpapi", status, fatal)


def test_from_settings_keeps_only_providers_with_a_key():
    class S:
        serpapi_key = None
        brave_api_key = SecretStr("b")
    assert [p.name for p in from_settings(S())] == ["brave"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd C:/Next-path/apps/api && uv run pytest tests/test_search_source.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hellomyme.ingest.search_source'`

- [ ] **Step 3: Write the implementation**

`apps/api/hellomyme/ingest/search_source.py`:
```python
"""Search API clients for search ingest (docs/12). Each returns (url, title, snippet) rows only;
nothing here stores or logs a result. 401/403/429 mean the provider is unusable for the rest of
a run (bad key or quota); anything else is one failed query."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

FATAL = {401, 403, 429}
TIMEOUT = 30


@dataclass(frozen=True)
class Result:
    url: str
    title: str
    snippet: str


class SearchError(Exception):
    def __init__(self, provider: str, status: int | None, message: str):
        super().__init__(f"{provider}: {status or 'network'} {message}")
        self.provider, self.status = provider, status
        self.fatal = status in FATAL


def _get_json(provider: str, url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise SearchError(provider, exc.code, str(exc.reason)) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SearchError(provider, None, str(exc)) from exc


class SerpApi:
    name, model_version = "serpapi", "serpapi-google"

    def __init__(self, key: str):
        self._key = key

    def search(self, query: str, count: int) -> list[Result]:
        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(
            {"engine": "google", "q": query, "num": count, "hl": "ko", "gl": "kr", "api_key": self._key})
        data = _get_json(self.name, url)
        return [Result(r.get("link", ""), r.get("title", ""), r.get("snippet", ""))
                for r in data.get("organic_results", [])]


class Brave:
    name, model_version = "brave", "brave"

    def __init__(self, key: str):
        self._key = key

    def search(self, query: str, count: int) -> list[Result]:
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
            {"q": query, "count": count, "country": "KR", "search_lang": "ko"})
        data = _get_json(self.name, url, {"Accept": "application/json",
                                          "X-Subscription-Token": self._key})
        return [Result(r.get("url", ""), r.get("title", ""),
                       " · ".join([r.get("description", "")] + r.get("extra_snippets", [])))
                for r in data.get("web", {}).get("results", [])]


def from_settings(settings) -> list[SerpApi | Brave]:
    out: list[SerpApi | Brave] = []
    if settings.serpapi_key:
        out.append(SerpApi(settings.serpapi_key.get_secret_value()))
    if settings.brave_api_key:
        out.append(Brave(settings.brave_api_key.get_secret_value()))
    return out
```

- [ ] **Step 4: Run tests**

Run: `cd C:/Next-path/apps/api && uv run pytest tests/test_search_source.py -q && uv run ruff check hellomyme/ingest/search_source.py tests/test_search_source.py`
Expected: `6 passed`, `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd C:/Next-path
git add apps/api/hellomyme/ingest/search_source.py apps/api/tests/test_search_source.py
git commit -m "search ingest: SerpAPI and Brave clients (fatal on 401/403/429)"
```

---

### Task 4: Query planning (`search_plan.py`)

**Files:**
- Create: `apps/api/hellomyme/ingest/search_plan.py`
- Test: `apps/api/tests/test_search_plan.py` (extend)

**Interfaces:**
- Consumes: tables from Task 2; view `analytics.acq_input` (0026: `institution_id` text, `institution_name`, `institution_listed`, `major_node_id` text, `major_label`, `internal`, `created_at`); `person.origin_layer`, `canonical_education.institution_id` / `.major_taxonomy_node_id`; `cohort_policy.min_exact_n` (ACTIVE, seeded 30); for the test, `pipeline.receive/accept_pending/approve`
- Produces:
  - `@dataclass(frozen=True) Policy(version: str, max_queries_per_run: int, results_per_query: int, requery_after_days: int, demand_lookback_days: int, max_consecutive_errors: int)`
  - `active_policy(conn) -> Policy | None`
  - `@dataclass(frozen=True) PlannedQuery(search_query_id: str, query_text: str, last_provider: str | None)`
  - `demand_candidates(conn, since: datetime, min_n: int) -> list[dict]` — keys `institution_id`, `major_node_id`, `institution_name`, `major_label`, `drafts`, `supply`
  - `plan(conn, policy: Policy, now: datetime) -> list[PlannedQuery]`

- [ ] **Step 1: Write the failing tests**

Replace the imports at the top of `apps/api/tests/test_search_plan.py` with:
```python
"""Search ingest planning (docs/12 §4). Each test runs in a transaction that is rolled back."""
import dataclasses
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from hellomyme.ingest.pipeline import accept_pending, approve, receive
from hellomyme.ingest.search_plan import active_policy, demand_candidates, plan

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)
```
Keep the `conn` fixture and `test_seeded_policy_is_the_one_active` from Task 2, then append:
```python
def _ref(c):
    """Two listed schools and one major node the planner can name."""
    tv = c.execute(text(
        """INSERT INTO taxonomy_version (taxonomy, version) VALUES ('INSTITUTION', 'plan-test')
           ON CONFLICT (taxonomy, version) DO UPDATE SET version = EXCLUDED.version
           RETURNING taxonomy_version_id""")).scalar_one()
    a, b = (c.execute(text("INSERT INTO institution (name, taxonomy_version_id) VALUES (:n, :v) "
                           "RETURNING institution_id::text"), {"n": n, "v": tv}).scalar_one()
            for n in ("플랜대학교", "수요대학교"))
    tid = c.execute(text("SELECT taxonomy_id FROM taxonomy WHERE taxonomy_type = 'MAJOR' "
                         "AND status = 'ACTIVE'")).scalar() or c.execute(text(
        """INSERT INTO taxonomy (taxonomy_type, name, version, status)
           VALUES ('MAJOR', 'plan test', 'plan-test', 'ACTIVE') RETURNING taxonomy_id""")).scalar_one()
    m = c.execute(text(
        """INSERT INTO taxonomy_node (taxonomy_id, code, canonical_name, display_name, depth)
           VALUES (:t, 'PLAN_M1', '플랜학과', '플랜학과', 1) RETURNING taxonomy_node_id::text"""),
        {"t": tid}).scalar_one()
    return a, b, m


def _draft(c, inst, major, n=1, internal=False, days_ago=1):
    payload = json.dumps({"schema_version": "acq_v1",
                          "education": {"institution_id": inst, "major_node_id": major}})
    for _ in range(n):
        c.execute(text(
            """INSERT INTO anonymous_draft (session_id, user_type, payload_json, expires_at,
                                            created_at, internal)
               VALUES ('plan-test', 'STUDENT', CAST(:p AS jsonb), now(), :at, :i)"""),
            {"p": payload, "at": NOW - timedelta(days=days_ago), "i": internal})


def _seed_person(c, school):
    """One SEED person at school + 플랜학과, loaded through the real pipeline."""
    doc = {"schema_version": "career_extraction.v1", "submission_id": f"plan-{school}",
           "assets": [{"asset_id": "S1", "page_order": 1}], "person": {"display_name_raw": None},
           "educations": [{"local_id": "E1", "institution_raw": school, "major_raw": "플랜학과",
                           "start": {"value": "2016", "precision": "YEAR"},
                           "end": {"value": "2020", "precision": "YEAR"},
                           "evidence": [{"asset_id": "S1", "text": f"{school} 플랜학과 2016 - 2020"}]}],
           "work_events": []}
    r = receive(c, json.dumps(doc, ensure_ascii=False), collector="plan-test",
                source_type="PUBLIC_PROFILE", permitted_use="AGGREGATE_ONLY", legal_basis="test",
                model_version="t", prompt_version="t", as_of=NOW.date())
    accept_pending(c, r["parse_run_id"])
    approve(c, r["parse_run_id"])


def _operator(c, q, last_run_at=None):
    c.execute(text("INSERT INTO search_query (query_text, origin, last_run_at) "
                   "VALUES (:q, 'OPERATOR', :t)"), {"q": q, "t": last_run_at})


def test_demand_counts_external_recent_drafts_and_skips_filled_cohorts(conn):
    a, b, m = _ref(conn)
    _draft(conn, a, m, n=3)
    _draft(conn, b, m, n=2)
    _draft(conn, b, m, n=5, internal=True)          # the team's own browsers
    _draft(conn, b, m, n=4, days_ago=90)            # outside the window
    _seed_person(conn, "플랜대학교")                  # 플랜대학교 + 플랜학과 now has 1 SEED person
    rows = demand_candidates(conn, NOW - timedelta(days=30), min_n=1)
    assert [(r["institution_name"], r["drafts"], r["supply"]) for r in rows] == [("수요대학교", 2, 0)]


def test_operator_queries_first_then_demand_up_to_the_limit(conn):
    a, b, m = _ref(conn)
    _draft(conn, a, m, n=3)
    _draft(conn, b, m, n=2)
    _operator(conn, "op-old", NOW - timedelta(days=40))
    _operator(conn, "op-new")
    _operator(conn, "op-recent", NOW - timedelta(days=2))   # inside requery_after_days
    out = plan(conn, dataclasses.replace(active_policy(conn), max_queries_per_run=3), NOW)
    assert [q.query_text for q in out] == [
        "op-new", "op-old", 'site:linkedin.com/in "플랜대학교" "플랜학과"']
    origin = conn.execute(text("SELECT origin FROM search_query WHERE query_text = :q"),
                          {"q": out[2].query_text}).scalar_one()
    assert origin == "DEMAND"


def test_a_demand_query_run_recently_is_not_planned_again(conn):
    a, b, m = _ref(conn)
    _draft(conn, a, m, n=3)
    _draft(conn, b, m, n=2)
    conn.execute(text(
        """INSERT INTO search_query (query_text, origin, institution_id, major_node_id, last_run_at)
           VALUES ('site:linkedin.com/in "플랜대학교" "플랜학과"', 'DEMAND', CAST(:a AS uuid),
                   CAST(:m AS uuid), :t)"""), {"a": a, "m": m, "t": NOW - timedelta(days=1)})
    out = plan(conn, active_policy(conn), NOW)
    assert [q.query_text for q in out] == ['site:linkedin.com/in "수요대학교" "플랜학과"']
```
(Both schools have no SEED people and the seeded `cohort_policy.min_exact_n` is 30, so both are demand candidates in the last two tests.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd C:/Next-path/apps/api && PYTHONUTF8=1 uv run pytest tests/test_search_plan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hellomyme.ingest.search_plan'`

- [ ] **Step 3: Write the implementation**

`apps/api/hellomyme/ingest/search_plan.py`:
```python
"""Which queries one search-ingest run sends (docs/12 §4).

Operator queries come first (never-run first, then the oldest run). The rest of the run's budget
goes to demand: school + major pairs people typed recently (the team's own browsers left out)
whose SEED + VERIFIED people are still fewer than the cohort minimum, most-asked first.
A query run within requery_after_days is not planned again.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Connection, text

# acq_input compares ids as text so one malformed answer never breaks the view; cast only valid ones.
UUID_RE = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


@dataclass(frozen=True)
class Policy:
    version: str
    max_queries_per_run: int
    results_per_query: int
    requery_after_days: int
    demand_lookback_days: int
    max_consecutive_errors: int


@dataclass(frozen=True)
class PlannedQuery:
    search_query_id: str
    query_text: str
    last_provider: str | None


def active_policy(conn: Connection) -> Policy | None:
    row = conn.execute(text(
        """SELECT version, max_queries_per_run, results_per_query, requery_after_days,
                  demand_lookback_days, max_consecutive_errors
           FROM search_ingest_policy WHERE status = 'ACTIVE'""")).first()
    return Policy(*row) if row else None


def demand_candidates(conn: Connection, since: datetime, min_n: int) -> list[dict]:
    rows = conn.execute(text(
        """WITH demand AS (
             SELECT CAST(a.institution_id AS uuid) AS institution_id,
                    CAST(a.major_node_id AS uuid) AS major_node_id,
                    max(a.institution_name) AS institution_name, max(a.major_label) AS major_label,
                    count(*) AS drafts
             FROM analytics.acq_input a
             WHERE NOT a.internal AND a.institution_listed AND a.major_label IS NOT NULL
               AND a.major_node_id ~ :uuid_re AND a.created_at >= :since
             GROUP BY 1, 2),
           supply AS (
             SELECT e.institution_id, e.major_taxonomy_node_id AS major_node_id,
                    count(DISTINCT p.person_id) AS n
             FROM person p JOIN canonical_education e ON e.person_id = p.person_id
             WHERE p.deleted_at IS NULL AND p.origin_layer IN ('SEED','VERIFIED')
             GROUP BY 1, 2)
           SELECT d.institution_id::text AS institution_id, d.major_node_id::text AS major_node_id,
                  d.institution_name, d.major_label, d.drafts, coalesce(s.n, 0) AS supply
           FROM demand d LEFT JOIN supply s USING (institution_id, major_node_id)
           WHERE coalesce(s.n, 0) < :min_n
           ORDER BY d.drafts DESC, d.institution_name, d.major_label"""),
        {"since": since, "min_n": min_n, "uuid_re": UUID_RE}).mappings().all()
    return [dict(r) for r in rows]


def _due(conn: Connection, origin: str, cutoff: datetime, limit: int,
         query_text: str | None = None) -> list[PlannedQuery]:
    rows = conn.execute(text(
        """SELECT search_query_id::text, query_text, last_provider FROM search_query
           WHERE origin = :o AND status = 'ACTIVE' AND (last_run_at IS NULL OR last_run_at < :cut)
             AND (CAST(:q AS text) IS NULL OR query_text = :q)
           ORDER BY last_run_at NULLS FIRST, created_at, query_text LIMIT :n"""),
        {"o": origin, "cut": cutoff, "n": limit, "q": query_text}).all()
    return [PlannedQuery(*r) for r in rows]


def plan(conn: Connection, policy: Policy, now: datetime) -> list[PlannedQuery]:
    cutoff = now - timedelta(days=policy.requery_after_days)
    out = _due(conn, "OPERATOR", cutoff, policy.max_queries_per_run)
    if len(out) >= policy.max_queries_per_run:
        return out
    min_n = conn.execute(text("SELECT min_exact_n FROM cohort_policy WHERE status = 'ACTIVE'")).scalar()
    if not min_n:
        return out
    for c in demand_candidates(conn, now - timedelta(days=policy.demand_lookback_days), min_n):
        q = f'site:linkedin.com/in "{c["institution_name"]}" "{c["major_label"]}"'
        conn.execute(text(
            """INSERT INTO search_query (query_text, origin, institution_id, major_node_id)
               VALUES (:q, 'DEMAND', CAST(:i AS uuid), CAST(:m AS uuid))
               ON CONFLICT (query_text) DO NOTHING"""),
            {"q": q, "i": c["institution_id"], "m": c["major_node_id"]})
        out += _due(conn, "DEMAND", cutoff, 1, query_text=q)
        if len(out) >= policy.max_queries_per_run:
            break
    return out
```

- [ ] **Step 4: Run tests**

Run: `cd C:/Next-path/apps/api && PYTHONUTF8=1 uv run pytest tests/test_search_plan.py -q && uv run ruff check hellomyme/ingest/search_plan.py tests/test_search_plan.py`
Expected: `4 passed`, `All checks passed!`
If `test_demand_counts...` shows supply 0 for 플랜대학교: the education did not map. Check with `SELECT institution_id, major_taxonomy_node_id FROM canonical_education` inside the test — `플랜대학교` must match `institution.name` and `플랜학과` the node's `display_name` exactly (`pipeline._candidates`).

- [ ] **Step 5: Commit**

```bash
cd C:/Next-path
git add apps/api/hellomyme/ingest/search_plan.py apps/api/tests/test_search_plan.py
git commit -m "search ingest: plan operator queries, then demand (school+major short of the cohort minimum)"
```

---

### Task 5: One run (`search_run.py`)

**Files:**
- Create: `apps/api/hellomyme/ingest/search_run.py`
- Test: `apps/api/tests/test_search_run.py`

**Interfaces:**
- Consumes: `snippet.profile_key`, `snippet.to_extraction`, `snippet.PROMPT_VERSION` (Task 1); `search_source.SearchError` and any provider object with `name`, `model_version`, `search(query, count) -> list[Result]` (Task 3); `search_plan.active_policy`, `plan` (Task 4); `pipeline.receive`, `pipeline.IngestError` (existing)
- Produces: `COLLECTOR = "search-cron"`, `LOCK_KEY = 120041`, `run(conn, *, settings, providers, as_of: date, now: datetime) -> dict` with keys `search_run_id, status, reason, queries, results, received, replayed, already_loaded, rejected, empty, errors, by_provider`. The caller owns the transaction (commit, or roll back for a dry run). `settings` needs `env`, `public_profile_legal_basis`, `public_profile_legal_reviewed`.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_search_run.py`:
```python
"""One search-ingest run (docs/12 §5) with fake providers. Each test rolls back."""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from hellomyme.ingest.search_run import LOCK_KEY, run
from hellomyme.ingest.search_source import Result, SearchError

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)
AS_OF = date(2026, 10, 15)


class S:
    env = "staging"
    public_profile_legal_basis = "test basis"
    public_profile_legal_reviewed = False


def person(slug, org="토스", year="2022"):
    return Result(f"https://kr.linkedin.com/in/{slug}", f"테스트{slug} - 개발자 - {org} | LinkedIn",
                  f"경력: {org} · {org} {year} - 현재")


class Fake:
    def __init__(self, name, pages=None, fail=None):
        self.name = self.model_version = name
        self.pages, self.fail, self.calls = pages or {}, fail, []

    def search(self, query, count):
        self.calls.append(query)
        if self.fail:
            raise SearchError(self.name, self.fail, "fake")
        return self.pages.get(query, [])


@pytest.fixture
def conn(engine):
    with engine.connect() as c:
        tx = c.begin()
        yield c
        tx.rollback()


def _ops(c, *queries):
    for q in queries:
        c.execute(text("INSERT INTO search_query (query_text, origin) VALUES (:q, 'OPERATOR')"), {"q": q})


def go(c, providers, settings=S):
    return run(c, settings=settings, providers=providers, as_of=AS_OF, now=NOW)


def test_alternates_providers_and_receives_each_person_once(conn):
    _ops(conn, "q1", "q2")
    a = Fake("serpapi", {"q1": [person("a"), person("b")]})
    b = Fake("brave", {"q2": [person("a"), person("c", "카카오")]})
    out = go(conn, [a, b])
    assert out["status"] == "DONE"
    assert (a.calls, b.calls) == (["q1"], ["q2"])
    assert (out["received"], out["replayed"], out["results"]) == (3, 1, 4)
    assert out["by_provider"]["brave"]["received"] == 1
    subs = conn.execute(text(
        """SELECT count(*) FROM source_submission s JOIN collector c USING (collector_id)
           WHERE c.name = 'search-cron' AND s.source_type = 'PUBLIC_PROFILE'
             AND s.permitted_use = 'AGGREGATE_ONLY'""")).scalar_one()
    assert subs == 3
    raw = conn.execute(text("SELECT string_agg(raw_output::text, ' ') FROM parse_run")).scalar_one()
    assert "테스트a" not in raw and "linkedin.com" not in raw
    last = conn.execute(text("SELECT query_text, last_provider FROM search_query ORDER BY 1")).all()
    assert [tuple(r) for r in last] == [("q1", "serpapi"), ("q2", "brave")]


def test_a_quota_error_moves_the_rest_of_the_run_to_the_other_provider(conn):
    _ops(conn, "q1", "q2")
    a = Fake("serpapi", fail=429)
    b = Fake("brave", {"q1": [person("a")], "q2": [person("b")]})
    out = go(conn, [a, b])
    assert out["status"] == "DONE" and out["received"] == 2
    assert (a.calls, b.calls) == (["q1"], ["q1", "q2"])
    assert out["by_provider"]["serpapi"]["failed"] == [429]


def test_both_providers_unusable_fails_the_run(conn):
    _ops(conn, "q1")
    out = go(conn, [Fake("serpapi", fail=401), Fake("brave", fail=401)])
    assert out["status"] == "FAILED" and out["reason"].startswith("ALL_PROVIDERS_FAILED")


def test_a_loaded_person_counts_as_already_loaded(conn):
    _ops(conn, "q1")
    go(conn, [Fake("serpapi", {"q1": [person("a")]})])
    conn.execute(text("UPDATE source_submission SET status = 'LOADED'"))
    conn.execute(text("UPDATE search_query SET last_run_at = NULL"))
    out = go(conn, [Fake("serpapi", {"q1": [person("a", year="2023")]})])
    assert (out["already_loaded"], out["received"]) == (1, 0)


def test_empty_results_and_non_profiles_are_not_received(conn):
    _ops(conn, "q1")
    out = go(conn, [Fake("serpapi", {"q1": [
        Result("https://kr.linkedin.com/in/z", "Z | LinkedIn", "서울"),
        Result("https://www.linkedin.com/company/toss", "Toss | LinkedIn", "회사")]})])
    assert (out["results"], out["empty"], out["received"]) == (1, 1, 0)


def test_production_waits_for_the_legal_review(conn):
    _ops(conn, "q1")
    p = Fake("serpapi", {"q1": [person("a")]})

    class Prod(S):
        env = "production"
    out = go(conn, [p], settings=Prod)
    assert (out["status"], out["reason"], p.calls) == ("SKIPPED", "LEGAL_REVIEW_PENDING", [])


def test_no_active_policy_skips_and_is_logged(conn):
    conn.execute(text("UPDATE search_ingest_policy SET status = 'RETIRED'"))
    out = go(conn, [Fake("serpapi")])
    assert (out["status"], out["reason"]) == ("SKIPPED", "NO_ACTIVE_POLICY")
    row = conn.execute(text("SELECT status, reason FROM search_run")).one()
    assert tuple(row) == ("SKIPPED", "NO_ACTIVE_POLICY")


def test_no_provider_skips(conn):
    assert go(conn, [])["reason"] == "NO_SEARCH_PROVIDER"


def test_a_second_run_at_the_same_time_skips(conn, engine):
    _ops(conn, "q1")
    with engine.connect() as other:
        otx = other.begin()
        other.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
        out = go(conn, [Fake("serpapi", {"q1": [person("a")]})])
        otx.rollback()
    assert (out["status"], out["reason"]) == ("SKIPPED", "ALREADY_RUNNING")


def test_one_failing_person_does_not_stop_the_others(conn, monkeypatch):
    from hellomyme.ingest import search_run as sr
    real = sr.receive

    def flaky(c, raw, **kw):
        if "카카오" in raw:
            raise RuntimeError("boom")
        return real(c, raw, **kw)
    monkeypatch.setattr(sr, "receive", flaky)
    _ops(conn, "q1")
    out = go(conn, [Fake("serpapi", {"q1": [person("a"), person("b", "카카오"), person("c")]})])
    assert (out["status"], out["received"], out["errors"]) == ("DONE", 2, 1)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd C:/Next-path/apps/api && PYTHONUTF8=1 uv run pytest tests/test_search_run.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hellomyme.ingest.search_run'`

- [ ] **Step 3: Write the implementation**

`apps/api/hellomyme/ingest/search_run.py`:
```python
"""One search-ingest run (docs/12 §5): plan -> search -> snippet -> receive(), counted in search_run.

Runs on the caller's connection and transaction (the CLI commits, or rolls back for --dry-run).
One savepoint per person, so one bad result never loses the others. The job only receives:
every field waits for a person (docs/09 §3), and nothing is shown as a person (docs/09 §8).

Providers alternate per query: a query run before starts with the provider it did not use last
time, a never-run query takes the next one in rotation. 401/403/429 removes a provider for the
rest of the run and the query is retried once on the other.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import Connection, text

from hellomyme.ingest.pipeline import IngestError, receive
from hellomyme.ingest.search_plan import active_policy, plan
from hellomyme.ingest.search_source import SearchError
from hellomyme.ingest.snippet import PROMPT_VERSION, profile_key, to_extraction

COLLECTOR = "search-cron"
LOCK_KEY = 120041  # transaction-scoped advisory lock: one run at a time
COUNTS = ("queries", "results", "received", "replayed", "already_loaded", "rejected", "empty", "errors")


class _Stop(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _finish(conn: Connection, run_id: str, status: str, reason: str | None, counts: dict,
            by_provider: dict) -> dict:
    conn.execute(text(
        f"""UPDATE search_run SET status = :st, reason = :r, finished_at = now(),
                {", ".join(f"{k} = :{k}" for k in COUNTS)}, by_provider = CAST(:bp AS jsonb)
            WHERE search_run_id = CAST(:id AS uuid)"""),
        {"st": status, "r": reason, "id": run_id, "bp": json.dumps(by_provider), **counts})
    return {"search_run_id": run_id, "status": status, "reason": reason, **counts,
            "by_provider": by_provider}


def _precondition(conn: Connection, settings, providers: list, policy) -> str | None:
    if policy is None:
        return "NO_ACTIVE_POLICY"
    if not providers:
        return "NO_SEARCH_PROVIDER"
    if not settings.public_profile_legal_basis:
        return "NO_LEGAL_BASIS"
    if settings.env == "production" and not settings.public_profile_legal_reviewed:
        return "LEGAL_REVIEW_PENDING"
    if not conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}).scalar():
        return "ALREADY_RUNNING"
    return None


def run(conn: Connection, *, settings, providers: list, as_of: date, now: datetime) -> dict:
    run_id = conn.execute(text("INSERT INTO search_run DEFAULT VALUES RETURNING search_run_id::text")
                          ).scalar_one()
    counts = dict.fromkeys(COUNTS, 0)
    by_provider = {p.name: {"queries": 0, "results": 0, "received": 0, "failed": []} for p in providers}
    policy = active_policy(conn)
    reason = _precondition(conn, settings, providers, policy)
    if reason:
        return _finish(conn, run_id, "SKIPPED", reason, counts, by_provider)

    usable, seen = list(providers), set()
    streak = rot = 0

    def take(person, provider) -> None:
        nonlocal streak
        key = profile_key(person.url)
        if key is None:  # a company or post page, not a person
            return
        counts["results"] += 1
        if key in seen:
            counts["replayed"] += 1
            return
        seen.add(key)
        doc = to_extraction(person.title, person.snippet, key)
        if doc is None:
            counts["empty"] += 1
            return
        sp = conn.begin_nested()
        try:
            r = receive(conn, json.dumps(doc, ensure_ascii=False), collector=COLLECTOR,
                        source_type="PUBLIC_PROFILE", permitted_use="AGGREGATE_ONLY",
                        legal_basis=settings.public_profile_legal_basis,
                        model_version=provider.model_version, prompt_version=PROMPT_VERSION,
                        as_of=as_of)
            sp.commit()
        except IngestError:  # already LOADED or WITHDRAWN: nothing to do
            sp.rollback()
            counts["already_loaded"] += 1
            return
        except Exception:
            sp.rollback()
            counts["errors"] += 1
            streak += 1
            if streak >= policy.max_consecutive_errors:
                raise _Stop("TOO_MANY_ERRORS") from None
            return
        streak = 0
        if r.get("replayed"):
            counts["replayed"] += 1
        elif r["status"] == "REJECTED":
            counts["rejected"] += 1
        else:
            counts["received"] += 1
            by_provider[provider.name]["received"] += 1

    try:
        for q in plan(conn, policy, now):
            counts["queries"] += 1
            if q.last_provider:
                order = sorted(usable, key=lambda p: p.name == q.last_provider)
            else:
                i = rot % len(usable)
                order, rot = usable[i:] + usable[:i], rot + 1
            for provider in order:
                if provider not in usable:
                    continue
                by_provider[provider.name]["queries"] += 1
                try:
                    page = provider.search(q.query_text, policy.results_per_query)
                except SearchError as exc:
                    if not exc.fatal:
                        counts["errors"] += 1
                        break
                    by_provider[provider.name]["failed"].append(exc.status)
                    usable.remove(provider)
                    if not usable:
                        raise _Stop("ALL_PROVIDERS_FAILED:" + ",".join(
                            f"{n}={v['failed']}" for n, v in by_provider.items())) from None
                    continue  # retry this query once on the other provider
                by_provider[provider.name]["results"] += len(page)
                for person in page:
                    take(person, provider)
                conn.execute(text(
                    """UPDATE search_query SET last_run_at = :now, last_provider = :p
                       WHERE search_query_id = CAST(:id AS uuid)"""),
                    {"now": now, "p": provider.name, "id": q.search_query_id})
                break
    except _Stop as stop:
        return _finish(conn, run_id, "FAILED", stop.reason, counts, by_provider)
    return _finish(conn, run_id, "DONE", None, counts, by_provider)
```

How the tests' expectations follow: in the alternate test q1 and q2 have never run, so the rotation gives q1 → serpapi, q2 → brave. In the 429 test q1 → serpapi fails (removed, retried on brave), q2 → only brave is left. `sorted(..., key=lambda p: p.name == q.last_provider)` puts the provider used last time at the end (False sorts first).

- [ ] **Step 4: Run tests**

Run: `cd C:/Next-path/apps/api && PYTHONUTF8=1 uv run pytest tests/test_search_run.py -q && uv run ruff check hellomyme/ingest/search_run.py tests/test_search_run.py`
Expected: `10 passed`, `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd C:/Next-path
git add apps/api/hellomyme/ingest/search_run.py apps/api/tests/test_search_run.py
git commit -m "search ingest: one run (alternate providers, failover, savepoint per person, counts)"
```

---

### Task 6: CLI `search-run` + Render cron

**Files:**
- Modify: `apps/api/hellomyme/ingest/cli.py`
- Modify: `render.yaml`
- Modify: `docs/12_SEARCH_INGEST.md` (status line), `docs/03_DEPLOYMENT.md` (progress row)
- Test: `apps/api/tests/test_search_run.py` (CLI test)

**Interfaces:**
- Consumes: `search_run.run`, `search_source.from_settings`, `config.get_settings`, `db.get_engine`
- Produces: `hellomyme-ingest search-run [--dry-run] [--as-of YYYY-MM-DD]`; prints the run summary as JSON with `"dry_run"`; exit 1 when the run FAILED, else 0

- [ ] **Step 1: Write the failing test** (append to `apps/api/tests/test_search_run.py`)

```python
def test_cli_dry_run_leaves_nothing(engine, monkeypatch, capsys):
    import sys

    from hellomyme.ingest import cli, search_source
    monkeypatch.setattr(search_source, "from_settings", lambda s: [Fake("serpapi")])
    monkeypatch.setattr(sys, "argv", ["hellomyme-ingest", "search-run", "--dry-run"])
    monkeypatch.setenv("HELLOMYME_PUBLIC_PROFILE_LEGAL_BASIS", "test basis")
    cli.get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as e:
            cli.main()
    finally:
        cli.get_settings.cache_clear()
    assert e.value.code == 0
    assert '"dry_run": true' in capsys.readouterr().out
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM search_run")).scalar_one() == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd C:/Next-path/apps/api && PYTHONUTF8=1 uv run pytest tests/test_search_run.py::test_cli_dry_run_leaves_nothing -q`
Expected: FAIL — `SystemExit: 2` from argparse (`invalid choice: 'search-run'`), so `e.value.code == 0` fails

- [ ] **Step 3: Add the subcommand**

In `apps/api/hellomyme/ingest/cli.py`:

1. Module docstring, after the `map ...` line add:
```
  search-run [--dry-run]          search public-profile snippets, receive them for review (docs/12)
```
2. Imports: replace `from datetime import date` with `from datetime import UTC, date, datetime`, and `from hellomyme.ingest import pipeline, sheet` with `from hellomyme.ingest import pipeline, search_run, search_source, sheet`.
3. After the `map` parser lines (before `args = p.parse_args()`):
```python
    sr = sub.add_parser("search-run", help="search public-profile snippets, receive them for review")
    sr.add_argument("--dry-run", action="store_true",
                    help="search and check, then roll everything back (nothing is received or logged)")
    sr.add_argument("--as-of", type=date.fromisoformat, default=date.today())
```
4. After the `if args.cmd == "sheet": ... return` block:
```python
    if args.cmd == "search-run":
        settings = get_settings()
        with get_engine().connect() as conn:
            tx = conn.begin()
            out = search_run.run(conn, settings=settings, providers=search_source.from_settings(settings),
                                 as_of=args.as_of, now=datetime.now(UTC))
            tx.rollback() if args.dry_run else tx.commit()
        out["dry_run"] = args.dry_run
        _dump(out)
        sys.exit(1 if out["status"] == "FAILED" else 0)
```

- [ ] **Step 4: Add the cron service**

Append to `services:` in `render.yaml`:
```yaml
  # Search ingest (docs/12): public-profile snippets -> receive() for human review, SEED statistics
  # only. Same image as the API; daily 03:00 KST. Keys, DB URL and legal basis are set in the dashboard.
  - type: cron
    name: nextpath-search-ingest
    runtime: docker
    rootDir: apps/api
    dockerfilePath: ./Dockerfile
    dockerCommand: hellomyme-ingest search-run
    region: singapore
    plan: starter
    schedule: "0 18 * * *"
    branch: main
    envVars:
      - key: HELLOMYME_ENV
        value: staging
      - key: HELLOMYME_DATABASE_URL
        sync: false
      - key: HELLOMYME_SERPAPI_KEY
        sync: false
      - key: HELLOMYME_BRAVE_API_KEY
        sync: false
      - key: HELLOMYME_PUBLIC_PROFILE_LEGAL_BASIS
        sync: false
```
(The image's default `CMD` runs migrations and the web server; `dockerCommand` replaces it. The API service's start already brings the schema to head.)

- [ ] **Step 5: Docs**

- `docs/12_SEARCH_INGEST.md`, the line `> 상태: 설계. 구현 전.` → `> 상태: 구현됨 (마이그레이션 0041, \`hellomyme-ingest search-run\`, render.yaml \`nextpath-search-ingest\`).`
- `docs/03_DEPLOYMENT.md` progress table, add a row:
```
| 검색 반입 크론 (`nextpath-search-ingest`) | ⬜ Blueprint 동기화 후 키·DB URL·법적 근거 입력, `search-run --dry-run` 1회 (docs/12) |
```

- [ ] **Step 6: Run the whole suite**

Run: `cd C:/Next-path/apps/api && uv run ruff check . && PYTHONUTF8=1 uv run pytest -q`
Expected: `All checks passed!` and every test passes (existing + 27 new: 6 + 1 + 6 + 3 + 10 + 1).

- [ ] **Step 7: Commit**

```bash
cd C:/Next-path
git add apps/api/hellomyme/ingest/cli.py apps/api/tests/test_search_run.py render.yaml docs/12_SEARCH_INGEST.md docs/03_DEPLOYMENT.md
git commit -m "search ingest: search-run CLI and the Render cron service"
```

---

## After the plan (owner, not code)

1. Merge to `main` (Render deploys `main`; syncing the Blueprint creates the cron service).
2. On `nextpath-search-ingest` in Render: `HELLOMYME_DATABASE_URL` (same as the API), `HELLOMYME_SERPAPI_KEY`, `HELLOMYME_BRAVE_API_KEY`, `HELLOMYME_PUBLIC_PROFILE_LEGAL_BASIS`. Values set on another service do not carry over (or use one Environment Group for both).
3. Run once by hand from the Render shell: `hellomyme-ingest search-run --dry-run`, read the counts, then let the schedule run.
4. Add operator queries: `INSERT INTO search_query (query_text, origin) VALUES ('site:linkedin.com/in "…" "…"', 'OPERATOR');`
5. Review as today: `hellomyme-ingest fields / review / accept-pending / approve` (docs/09 §7).
