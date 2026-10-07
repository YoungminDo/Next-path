"""Career transition derivation (versioned logic) and per-person snapshots.

transition_v1
- Only canonical (non-superseded, non-retracted) events with a known start_date <= as_of.
- Primary track: every event type except SIDE_BUSINESS / FREELANCE / PROJECT that overlap a
  primary event. Those overlapping ones form the parallel track and never create transitions.
- Entry transition: education -> first primary event starting on/after 1 Jan of the
  graduation year (earlier events, e.g. internships, are counted but are not the entry).
- Primary transitions: consecutive primary events ordered by (start_date, end_date).
  Overlapping primary events (A still running when B starts) are kept with overlap_months.
- Unknown values stay NULL: tenure needs both dates, gaps need A.end and B.start.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine, text

LOGIC_VERSION = "transition_v1"
PARALLEL_CAPABLE = {"SIDE_BUSINESS", "FREELANCE", "PROJECT"}


@dataclass
class Event:
    work_event_id: str
    event_type: str
    start: date
    end: date | None
    is_current: bool | None
    role_id: str | None
    job_family: str | None
    organization_id: str | None
    industry: str | None
    size: str | None
    placeholder: bool | None


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _overlaps(a: Event, b: Event) -> bool:
    a_end = a.end or date.max
    b_end = b.end or date.max
    return a.start < b_end and b.start < a_end


def split_tracks(events: list[Event]) -> tuple[list[Event], list[Event]]:
    base = [e for e in events if e.event_type not in PARALLEL_CAPABLE]
    primary, parallel = list(base), []
    for e in events:
        if e.event_type in PARALLEL_CAPABLE:
            (parallel if any(_overlaps(e, b) for b in base) else primary).append(e)
    key = lambda e: (e.start, e.end or date.max)  # noqa: E731
    return sorted(primary, key=key), sorted(parallel, key=key)


def derive_stage(graduation_year: int | None, current: Event | None, as_of: date) -> str:
    if graduation_year is not None and graduation_year > as_of.year:
        return "STUDENT"
    return "PROFESSIONAL" if current else "JOB_SEEKER"


def build_person(person: dict, education: dict | None, events: list[Event], as_of: date):
    primary, parallel = split_tracks(events)
    current_candidates = [e for e in primary if e.is_current]
    current = current_candidates[-1] if current_candidates else None
    gy = education["graduation_year"] if education else None

    snapshot = {
        "person_id": person["person_id"], "origin_layer": person["origin_layer"],
        "derived_stage": derive_stage(gy, current, as_of),
        "institution_id": education and education["institution_id"],
        "major_id": education and education["major_id"],
        "major_family": education and education["major_family"],
        "graduation_year": gy,
        "current_work_event_id": current and current.work_event_id,
        "current_event_type": current and current.event_type,
        "current_role_id": current and current.role_id,
        "current_job_family": current and current.job_family,
        "current_organization_id": current and current.organization_id,
        "current_industry": current and current.industry,
        "current_company_size_band": current and current.size,
        "job_family_sequence": [e.job_family or e.event_type for e in primary],
        "event_type_sequence": [e.event_type for e in primary],
        "primary_event_count": len(primary), "parallel_event_count": len(parallel),
    }

    transitions = []
    entry_from = date(gy, 1, 1) if gy else date.min
    entry = next((e for e in primary if e.start >= entry_from), None)

    def row(a: Event | None, b: Event, index: int) -> dict:
        tenure = gap = overlap = None
        if a is not None and a.end is not None:
            tenure = months_between(a.start, a.end)
            delta = months_between(a.end, b.start)
            gap, overlap = (delta, 0) if delta >= 0 else (0, -delta)
        return {
            "person_id": person["person_id"], "origin_layer": person["origin_layer"],
            "from_work_event_id": a and a.work_event_id, "to_work_event_id": b.work_event_id,
            "from_event_type": a and a.event_type, "from_role_id": a and a.role_id,
            "from_job_family": a and a.job_family, "from_organization_id": a and a.organization_id,
            "from_industry": a and a.industry, "from_company_size_band": a and a.size,
            "to_event_type": b.event_type, "to_role_id": b.role_id, "to_job_family": b.job_family,
            "to_organization_id": b.organization_id, "to_industry": b.industry,
            "to_company_size_band": b.size, "to_org_is_placeholder": b.placeholder,
            "from_tenure_months": tenure, "gap_months": gap, "overlap_months": overlap,
            "years_since_graduation": (b.start.year - gy) if gy else None,
            "transition_index": index,
        }

    if entry is not None:
        transitions.append(row(None, entry, 0))
    for i, (a, b) in enumerate(zip(primary, primary[1:], strict=False), start=1):
        transitions.append(row(a, b, i))
    return snapshot, transitions


def run_aggregation(engine: Engine, *, as_of: date, logic_version: str = LOGIC_VERSION) -> dict:
    if logic_version != LOGIC_VERSION:
        raise ValueError(f"unsupported transition logic {logic_version}")
    with engine.begin() as conn:
        run_id = conn.execute(
            text("INSERT INTO aggregation_run (logic_version, as_of_date, status) "
                 "VALUES (:v, :d, 'RUNNING') RETURNING aggregation_run_id"),
            {"v": logic_version, "d": as_of},
        ).scalar_one()

        persons = [dict(r._mapping) for r in conn.execute(text(
            "SELECT person_id::text, origin_layer FROM person WHERE deleted_at IS NULL"))]
        educations = {}
        for r in conn.execute(text("""
            SELECT DISTINCT ON (e.person_id) e.person_id::text, e.institution_id::text,
                   e.major_id::text, m.major_family, e.graduation_year
            FROM canonical_education e LEFT JOIN major m USING (major_id)
            ORDER BY e.person_id, e.graduation_year DESC NULLS LAST, e.created_at DESC""")):
            educations[r.person_id] = dict(r._mapping)
        events: dict[str, list[Event]] = defaultdict(list)
        for r in conn.execute(text("""
            SELECT w.person_id::text, w.work_event_id::text, w.event_type, w.start_date,
                   w.end_date, w.is_current, w.role_id::text, r.job_family,
                   w.organization_id::text, o.industry, o.company_size_band, o.is_placeholder
            FROM canonical_work_event w
            LEFT JOIN role r USING (role_id) LEFT JOIN organization o USING (organization_id)
            WHERE w.start_date IS NOT NULL AND w.start_date <= :as_of"""), {"as_of": as_of}):
            events[r.person_id].append(Event(
                r.work_event_id, r.event_type, r.start_date, r.end_date, r.is_current,
                r.role_id, r.job_family, r.organization_id, r.industry, r.company_size_band,
                r.is_placeholder))

        snapshots, transitions = [], []
        for p in persons:
            s, t = build_person(p, educations.get(p["person_id"]), events[p["person_id"]], as_of)
            snapshots.append(s)
            transitions.extend(t)

        conn.execute(text("DELETE FROM career_transition WHERE logic_version = :v"),
                     {"v": logic_version})
        conn.execute(text("DELETE FROM career_person_snapshot WHERE logic_version = :v"),
                     {"v": logic_version})
        _bulk(conn, "career_person_snapshot", logic_version, snapshots)
        _bulk(conn, "career_transition", logic_version, transitions)
        stats = {"logic_version": logic_version, "as_of": str(as_of), "persons": len(snapshots),
                 "transitions": len(transitions),
                 "entry_transitions": sum(1 for t in transitions if t["from_work_event_id"] is None)}
        conn.execute(
            text("UPDATE aggregation_run SET status = 'COMPLETED', finished_at = now(), "
                 "stats = CAST(:s AS jsonb) WHERE aggregation_run_id = :id"),
            {"s": json.dumps(stats), "id": run_id},
        )
    return stats


def _bulk(conn, table: str, logic_version: str, rows: list[dict], chunk: int = 5000) -> None:
    if not rows:
        return
    cols = ["logic_version", *rows[0].keys()]
    sql = text(f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
               f"({', '.join(':' + c for c in cols)})")
    for i in range(0, len(rows), chunk):
        conn.execute(sql, [{"logic_version": logic_version, **r} for r in rows[i:i + chunk]])
