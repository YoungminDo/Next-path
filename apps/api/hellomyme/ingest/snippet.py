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


def _has(name: str, s: str) -> bool:
    """name appears in s as a whole word (토스 is not found in 토스뱅크)."""
    return re.search(r"(?<![가-힣A-Za-z0-9])" + re.escape(name) + r"(?![가-힣A-Za-z0-9])", s) is not None


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
    tokens = sorted({name, *(w for w in re.split(r"[\s(),]+", name) if len(w) >= 2)} if name else set(),
                    key=len, reverse=True)
    mask_re = re.compile("|".join(re.escape(w) for w in tokens), re.I) if tokens else None

    def ev(s: str) -> list[dict]:
        text = mask_re.sub(MASK, s) if mask_re else s
        return [{"asset_id": ASSET, "text": text[:2000]}]

    segments = [_clean(s) for s in re.split(r"[·|\n]", snippet) if _clean(s)]
    orgs = [parts[-1]] if parts else []
    for m in _EXPERIENCE.finditer(snippet):
        orgs += [_clean(c) for c in re.split(r",|，", m.group(1)) if _clean(c)]

    work_events = []
    for i, org in enumerate(dict.fromkeys(o for o in orgs if o), 1):
        seg = next((s for s in segments if _has(org, s) and _RANGE.search(s)), None)
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
        seg = (next((s for s in segments if _has(school, s) and (_MAJOR.search(s) or _RANGE.search(s))), None)
               or next((s for s in segments if _has(school, s)), None))
        ed = {"local_id": f"E{i}", "institution_raw": school, "evidence": ev(seg or snippet)}
        if seg is not None:  # a fallback to the whole snippet attaches no major or dates
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
