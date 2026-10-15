"""Search result (title + snippet of a public profile) -> career_extraction.v1 (docs/12).

Rule-based, raw text only: the same contract as the AI path, so receive() checks it and a person
reviews every field. Unknown = NULL: a date range is attached to an organization or school only
when it is the first range after that name in the same snippet segment with no other name of the
document in between, and a month is taken only from a real month name. The name (the title's
first segment) is never copied: display_name_raw is null, every evidence text and headline masks
it, and an organization, school, role or major that contains it is dropped, because
parse_run.raw_output keeps what receive() is given forever. Evidence quotes only the span from
the name to the date or major it gives, so a stranger's name elsewhere in the snippet is not kept.
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
_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?"
          r"|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_POINT = (r"(?:\b(?P<{p}mon>" + _MONTH  # a real month name only (no braces: safe to format)
          + r")\b\.?\s+(?P<{p}y1>(?:19|20)\d\d)"
          r"|(?P<{p}y2>(?:19|20)\d\d)(?:\s*[.\-/년]\s*(?P<{p}m>\d{{1,2}})월?)?)")
_RANGE = re.compile(_POINT.format(p="s") + r"\s*[-–~]\s*(?:(?P<now>Present|현재|재직\s*중)|"
                    + _POINT.format(p="e") + ")", re.I)
_EXPERIENCE = re.compile(r"(?:Experience|경력)\s*[:：]\s*([^·|\n]+)")
_EDUCATION = re.compile(r"(?:Education|학력)\s*[:：]\s*([^·|\n]+)")
# Free text (no 학력:/Education: label): only the school name itself, never the words before it
# (a name, "님의 프로필 보기", "LinkedIn"): one Hangul token ending in 대학교/대학, or up to three
# capitalised words ending in University/College.
_SCHOOL = re.compile(r"(?<![가-힣])[가-힣]+(?:대학교|대학)"
                     r"|(?<![A-Za-z])(?:(?!LinkedIn\b)[A-Z][A-Za-z.&'-]*\s+){0,3}(?:University|College)\b")
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


def _dates(m: re.Match) -> dict:
    out = {"start": _point(m, "s")}
    if m.group("now"):
        out["is_current"] = True
    else:
        out["end"] = _point(m, "e")
    return {k: v for k, v in out.items() if v is not None}


def _words(name: str, s: str):
    return re.finditer(r"(?<![가-힣A-Za-z0-9])" + re.escape(name) + r"(?![가-힣A-Za-z0-9])", s)


def _dated(name: str, segments: list[str], others: set[str]):
    """(segment, name match, range match) for the first date range that starts after the name in
    the same segment with no other name of the document in between, else None. A range before the
    name, or one that follows another organization or school, belongs to that one."""
    for seg in segments:
        for w in _words(name, seg):
            r = _RANGE.search(seg, w.end())
            if r and not any(_has(o, seg[w.end():r.start()]) for o in others):
                return seg, w, r
    return None


def to_extraction(title: str, snippet: str, submission_id: str) -> dict | None:
    """One search result as career_extraction.v1, or None when it carries neither an education
    nor a work event (nothing for a reviewer to look at)."""
    snippet = snippet or ""
    t = re.sub(r"\s*\|\s*LinkedIn.*$", "", title or "", flags=re.I)
    t = re.sub(r"(?:\s+[-–—]\s+LinkedIn\s*)+$", "", t, flags=re.I)  # "홍길동 – LinkedIn": not a company
    head = [_clean(p) for p in re.split(r"\s+[-–—]\s+", t)]
    name, parts = (head[0] or None), [p for p in head[1:] if p]
    tokens = sorted({w for w in [name, *re.split(r"[\s(),]+", name or "")] if w and len(w) >= 2},
                    key=len, reverse=True)
    mask_re = re.compile("|".join(re.escape(w) for w in tokens), re.I) if tokens else None

    def mask(s: str) -> str:
        return mask_re.sub(MASK, s) if mask_re else s

    def ev(s: str) -> list[dict]:
        return [{"asset_id": ASSET, "text": mask(s)[:2000]}]

    segments = [_clean(s) for s in re.split(r"[·|\n]", snippet) if _clean(s)]
    orgs = [parts[-1]] if parts else []
    for m in _EXPERIENCE.finditer(snippet):
        orgs += [_clean(c) for c in re.split(r",|，", m.group(1)) if _clean(c)]
    orgs = list(dict.fromkeys(o for o in orgs if o))
    schools = [_clean(m.group(1)) for m in _EDUCATION.finditer(snippet)]
    if not schools:
        schools = [_clean(s) for s in _SCHOOL.findall(snippet)]
    schools = list(dict.fromkeys(s for s in schools if s))
    names = set(orgs) | set(schools)

    work_events = []
    for i, org in enumerate(orgs, 1):
        hit = _dated(org, segments, names - {org})
        # evidence: the name through its dates, the title it came from, or the name alone
        we = {"local_id": f"W{i}", "organization_raw": org, "event_type_hint": "UNKNOWN",
              "evidence": ev(hit[0][hit[1].start():hit[2].end()] if hit else (t if org in t else org))}
        if i == 1 and len(parts) >= 2:
            we["role_raw"] = parts[0]
        if hit:
            we.update(_dates(hit[2]))
        work_events.append(we)

    educations = []
    for i, school in enumerate(schools, 1):
        hit = _dated(school, segments, names - {school})
        if hit:
            seg, w = hit[0], hit[1]
        else:  # the first whole-word segment, else none: no major or dates from elsewhere
            seg = next((s for s in segments if _has(school, s)), None)
            w = next(_words(school, seg)) if seg is not None else None
        ed = {"local_id": f"E{i}", "institution_raw": school}
        end = w.end() if w else 0
        if seg is not None:
            major = _MAJOR.search(seg, w.end())
            if major and not any(_has(o, seg[w.end():major.start()]) for o in names - {school}):
                ed["major_raw"] = major.group(1)
                end = max(end, major.end())
            if hit:
                d = _dates(hit[2])
                for key in ("start", "end"):
                    if d.get(key):
                        ed[key] = d[key]
                end = max(end, hit[2].end())
        ed["evidence"] = ev(seg[w.start():end] if seg is not None else school)
        educations.append(ed)

    # The name never stays in a raw field: masked, and a name-bearing organization, school, role
    # or major is dropped (with its row when nothing a reviewer could use is left).
    for ed in educations:
        if "major_raw" in ed and MASK in mask(ed["major_raw"]):
            del ed["major_raw"]
    educations = [ed for ed in educations if MASK not in mask(ed["institution_raw"])]
    for we in work_events:
        for key in ("organization_raw", "role_raw"):
            if key in we and MASK in mask(we[key]):
                del we[key]
    work_events = [we for we in work_events if "organization_raw" in we or "role_raw" in we]
    headline = mask(" - ".join(parts))
    if not headline.replace(MASK, "").strip(" -"):
        headline = None

    if not educations and not work_events:
        return None
    return {
        "schema_version": "career_extraction.v1",
        "submission_id": submission_id,
        "assets": [{"asset_id": ASSET, "page_order": 1}],
        "person": {"display_name_raw": None, "headline_raw": headline},
        "educations": educations,
        "work_events": work_events,
    }
