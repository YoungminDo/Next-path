"""Measure how much of a Nextpath SEED record search-engine snippets of public profiles carry.

Experiment only (owner request 2026-10-15). It answers one question before any load:
"if we kept only what a search engine already shows, how many people would pass our own pipeline
and be usable by CareerQuery?"

It reuses the ingestion architecture (docs/09) instead of its own rules:
- each result becomes a `career_extraction.v1` document (the AI-JSON contract), one person per
  submission, the snippet as its only asset; raw text only, unknown = NULL, no guessed dates
- `hellomyme.ingest.pipeline.check()` runs on it: same BLOCK / WARN codes as the ingestion report
- schools are matched like the loader does (`_norm` against name / name_en / aliases of
  `reference/kr_institutions.csv`), majors against `reference/kr_school_departments.csv`;
  organizations need the DB alias table, so they are only counted as raw names
- readiness follows CareerQuery: a cohort needs institution + major + graduation/admission year
  (domain/career_query.py cohort_sql), a transition needs work events ordered by start_date

What it does not do:
- never opens a profile site; it reads a search API's result title + snippet only
- stores nothing: documents live in memory; the report has counts and field samples without
  names, URLs or evidence text. A real load would go through `hellomyme-ingest receive` with
  `--source-type PUBLIC_PROFILE --permitted-use AGGREGATE_ONLY` and the legal basis (docs/09 §9).

Providers (pick one, key in env):
    BRAVE_API_KEY    https://api.search.brave.com   (--provider brave)
    SERPAPI_KEY      https://serpapi.com  (Google)  (--provider serpapi)

Run from the repo root (needs the API's environment for jsonschema/sqlalchemy; on Windows set
PYTHONUTF8=1, pipeline._validator() reads the schema with the locale encoding):
    uv run --project apps/api python scripts/linkedin_snippet_yield.py --self-test
    uv run --project apps/api python scripts/linkedin_snippet_yield.py --provider serpapi --limit 35
"""
import argparse
import csv
import itertools
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

API = Path(__file__).resolve().parent.parent / "apps/api"
sys.path.insert(0, str(API))
from hellomyme.ingest.pipeline import _norm, check  # noqa: E402
from hellomyme.ingest.snippet import profile_key, to_extraction  # noqa: E402

REFERENCE = API / "hellomyme/reference"
# profile keys here only dedup within one process (nothing is stored): a random key per run
_DEDUP_KEY = os.urandom(32)
ROLES = ["백엔드 개발자", "프로덕트 매니저", "마케터", "데이터 분석가", "UX 디자이너"]
ORGS = ["토스", "카카오", "네이버", "쿠팡", "삼성전자"]
SCHOOLS = ["고려대학교", "연세대학교"]


def default_queries():
    qs = [f'site:linkedin.com/in "{r}" "{o}"' for r, o in itertools.product(ROLES, ORGS)]
    qs += [f'site:linkedin.com/in "{r}" "{s}"' for r, s in itertools.product(ROLES, SCHOOLS)]
    return qs


# --- providers ---------------------------------------------------------------------------------

def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def search_brave(q, key):
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": q, "count": 20, "country": "KR", "search_lang": "ko"})
    data = _get_json(url, {"Accept": "application/json", "X-Subscription-Token": key})
    for r in data.get("web", {}).get("results", []):
        snippet = " · ".join([r.get("description", "")] + r.get("extra_snippets", []))
        yield r.get("url", ""), r.get("title", ""), snippet


def search_serpapi(q, key):
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(
        {"engine": "google", "q": q, "num": 20, "hl": "ko", "gl": "kr", "api_key": key})
    data = _get_json(url)
    for r in data.get("organic_results", []):
        yield r.get("link", ""), r.get("title", ""), r.get("snippet", "")


PROVIDERS = {"brave": (search_brave, "BRAVE_API_KEY"), "serpapi": (search_serpapi, "SERPAPI_KEY")}


# --- reference (same normalisation as the loader) ----------------------------------------------

def load_reference():
    schools, departments = {}, {}
    with open(REFERENCE / "kr_institutions.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            for label in [row["name"], row["name_en"], *re.split(r"[,;|]", row.get("aliases") or "")]:
                if label.strip():
                    schools.setdefault(_norm(label), row["name"])
    with open(REFERENCE / "kr_school_departments.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            departments.setdefault(row["school"], set()).add(_norm(row["department"]))
    return schools, departments


# --- readiness (CareerQuery terms) -------------------------------------------------------------

def assess(doc, issues, schools, departments):
    blocked = any(i.severity == "BLOCK" for i in issues)
    mapped_school = cohort = False
    for ed in doc["educations"]:
        name = schools.get(_norm(ed["institution_raw"]))
        if not name:
            continue
        mapped_school = True
        major_ok = bool(ed.get("major_raw")) and _norm(ed["major_raw"]) in departments.get(name, set())
        if major_ok and (ed.get("end") or ed.get("start")):
            cohort = True
    dated = [w for w in doc["work_events"] if w.get("start")]
    return {
        "schema_pass": not blocked,
        "school_mapped": mapped_school,
        "cohort_ready": cohort and not blocked,
        "first_job_ready": len(dated) >= 1 and not blocked,
        "transition_ready": len(dated) >= 2 and not blocked,
        "nextpath_ready": cohort and len(dated) >= 2 and not blocked,
    }


def run(results, as_of=None):
    """results: iterable of (url, title, snippet). Returns the report (no names, URLs or evidence)."""
    as_of = as_of or date.today()
    schools, departments = load_reference()
    seen, rows, codes = set(), [], Counter()
    for url, title, snippet in results:
        h = profile_key(url, _DEDUP_KEY)
        if h is None or h in seen:
            continue
        seen.add(h)
        doc = to_extraction(title, snippet, "snippet")
        if doc is None:
            codes["EMPTY"] += 1
            continue
        issues = check(doc, as_of)
        codes.update(f"{i.severity}:{i.code}" for i in issues)
        rows.append((doc, assess(doc, issues, schools, departments)))
    n = len(rows)

    def pct(x):
        return round(100 * x / n, 1) if n else 0.0

    def sample(doc):
        return {
            "headline_raw": doc["person"]["headline_raw"],
            "educations": [{k: e.get(k) for k in ("institution_raw", "major_raw", "start", "end")}
                           for e in doc["educations"]],
            "work_events": [{k: w.get(k) for k in ("organization_raw", "role_raw", "start", "end",
                                                    "is_current")} for w in doc["work_events"]],
        }

    keys = ("schema_pass", "school_mapped", "cohort_ready", "first_job_ready",
            "transition_ready", "nextpath_ready")
    return {
        "as_of": as_of.isoformat(),
        "unique_profiles": n,
        "readiness": {k: {"n": sum(1 for _, a in rows if a[k]),
                          "pct": pct(sum(1 for _, a in rows if a[k]))} for k in keys},
        "issues_by_rule": dict(codes.most_common()),
        "work_events_per_person": round(sum(len(d["work_events"]) for d, _ in rows) / n, 2) if n else 0,
        "samples_no_name_no_url": [sample(d) for d, _ in rows[:10]],
    }


def live(provider, queries, pause):
    fn, env = PROVIDERS[provider]
    key = os.environ.get(env)
    if not key:
        sys.exit(f"{env} is not set")
    for i, q in enumerate(queries, 1):
        print(f"[{i}/{len(queries)}] {q}", file=sys.stderr)
        try:
            yield from fn(q, key)
        except Exception as e:  # one bad query should not end the experiment
            print(f"  failed: {e}", file=sys.stderr)
        time.sleep(pause)


FIXTURES = [
    ("https://kr.linkedin.com/in/aaa", "홍길동 - 백엔드 개발자 - 토스 | LinkedIn",
     "경력: 토스, 카카오 · 토스 2022.03 - 현재 · 카카오 2019 - 2022 · 학력: 고려대학교 · "
     "고려대학교 컴퓨터학과 2013 - 2019"),
    ("https://kr.linkedin.com/in/bbb", "Kim Lee – Product Manager – Coupang | LinkedIn",
     "Experience: Coupang, Naver · Education: Yonsei University · Location: Seoul · 2019"),
    ("https://kr.linkedin.com/in/ccc/", "박영희 - 카카오 | LinkedIn", "서울 · 1촌 300명 이상"),
    ("https://kr.linkedin.com/in/ccc", "박영희 - 카카오 | LinkedIn", "duplicate of the row above"),
    ("https://www.linkedin.com/company/toss", "Toss | LinkedIn", "not a person"),
]


def self_test():
    r = run(FIXTURES, as_of=date(2026, 10, 15))
    rd = {k: v["n"] for k, v in r["readiness"].items()}
    assert r["unique_profiles"] == 3, r
    assert rd["schema_pass"] == 3, r
    assert rd["school_mapped"] == 2, r          # 고려대학교, Yonsei University (name_en)
    assert rd["nextpath_ready"] == 1, r         # only the person with dated jobs + school/major/year
    assert rd["transition_ready"] == 1, r       # a lone "2019" is not attached to any job
    assert r["issues_by_rule"].get("WARN:MISSING_START") == 3, r
    dump = json.dumps(r, ensure_ascii=False)
    for leaked in ("홍길동", "Kim Lee", "박영희", "linkedin.com/in"):
        assert leaked not in dump, f"report leaks {leaked}"
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print("self-test ok", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", choices=PROVIDERS)
    p.add_argument("--queries", help="text file, one query per line (default: built-in 35)")
    p.add_argument("--limit", type=int, default=50, help="max queries to send")
    p.add_argument("--pause", type=float, default=1.1, help="seconds between queries")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        return self_test()
    if not a.provider:
        p.error("--provider is required (or --self-test)")
    if a.queries:
        with open(a.queries, encoding="utf-8") as fh:
            qs = [line.strip() for line in fh if line.strip()]
    else:
        qs = default_queries()
    print(json.dumps(run(live(a.provider, qs[: a.limit], a.pause)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
