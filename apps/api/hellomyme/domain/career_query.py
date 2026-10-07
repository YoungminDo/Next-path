"""v1.4 career query engine (docs/04_ARCHITECTURE_V14.md §6-8).

CareerQuery (time window + cohort filters + target metric) is evaluated directly on canonical
education/work-event rows at query time. Nothing here reads the server clock: as_of_date is
always part of the query.

Adaptive cohort v2: the active cohort_policy's ordered fallback_steps widen the filters one step
at a time until the analysed basis (people for whom the metric has a value inside the window)
reaches the threshold. Every step taken is reported; nothing broadens silently. Cells under the
minimum size are folded into OTHER, and a result that never reaches the threshold is suppressed.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta

from sqlalchemy import Connection, text

from hellomyme.domain.policies import PolicyMissing

LOOKBACKS = {"1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10, "ALL": None}
FIRST_EMPLOYMENT_RULE = "fe_v1"
SUPPORTED_METRICS = {
    "FIRST_ROLE_DISTRIBUTION": "ROLE",
    "FIRST_INDUSTRY_DISTRIBUTION": "INDUSTRY",
    "CURRENT_ROLE_DISTRIBUTION": "ROLE",
    "NEXT_ROLE_DISTRIBUTION": "ROLE",
}
STAYED = "STAYED"


class QueryInvalid(ValueError):
    pass


@dataclass(frozen=True)
class CareerQuery:
    as_of_date: date
    target_metric: str
    lookback: str = "ALL"
    institution_ids: tuple[str, ...] = ()
    major_node_ids: tuple[str, ...] = ()
    admission_year_from: int | None = None
    admission_year_to: int | None = None
    graduation_year_from: int | None = None
    graduation_year_to: int | None = None
    gender_codes: tuple[str, ...] = ()
    # Professional flow: people whose current role / first role sits in these subtrees.
    current_role_node_ids: tuple[str, ...] = ()
    first_role_node_ids: tuple[str, ...] = ()
    # NEXT_ROLE_DISTRIBUTION: where people went after a role in this subtree.
    from_role_node_ids: tuple[str, ...] = ()
    surface_code: str = "ACQUISITION"
    requested_depth: int | None = None

    def normalized(self) -> dict:
        d = asdict(self)
        d["as_of_date"] = self.as_of_date.isoformat()
        return {k: (sorted(v) if isinstance(v, tuple) else v) for k, v in d.items()}

    def query_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.normalized(), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class CohortPolicyV2:
    version: str
    min_exact_n: int
    min_cell_n: int
    demographic_min_n: int
    demographic_min_cell_n: int
    top_n: int
    fallback_steps: tuple[dict, ...]


def active_cohort_policy_v2(conn: Connection) -> CohortPolicyV2:
    row = conn.execute(text(
        """SELECT version, min_exact_n, min_cell_n, demographic_min_n, demographic_min_cell_n,
                  top_n, fallback_steps
           FROM cohort_policy WHERE status = 'ACTIVE' AND fallback_steps IS NOT NULL
             AND effective_from <= now() AND (effective_to IS NULL OR effective_to > now())"""
    )).first()
    if row is None:
        raise PolicyMissing("no active cohort_policy with fallback_steps")
    return CohortPolicyV2(**{**row._mapping, "fallback_steps": tuple(row.fallback_steps)})


def time_window(as_of: date, lookback: str) -> tuple[date | None, date]:
    """[as_of - N years + 1 day, as_of], inclusive. ALL has no start."""
    if lookback not in LOOKBACKS:
        raise QueryInvalid(f"lookback must be one of {sorted(LOOKBACKS)}")
    years = LOOKBACKS[lookback]
    if years is None:
        return None, as_of
    try:
        back = as_of.replace(year=as_of.year - years)
    except ValueError:  # 29 Feb -> 28 Feb
        back = as_of.replace(year=as_of.year - years, day=28)
    return back + timedelta(days=1), as_of


# --- taxonomy helpers ---------------------------------------------------------------------

@dataclass
class Taxonomy:
    taxonomy_type: str
    version: str
    nodes: dict[str, dict]  # node uuid -> {code, label, depth, parent}

    def ancestor_at(self, node_id: str, depth: int) -> str:
        node = self.nodes[node_id]
        while node["depth"] > depth and node["parent"]:
            node_id, node = node["parent"], self.nodes[node["parent"]]
        return node_id

    def subtree(self, roots) -> list[str]:
        roots = set(roots)
        out = []
        for nid in self.nodes:
            cur = nid
            while cur:
                if cur in roots:
                    out.append(nid)
                    break
                cur = self.nodes[cur]["parent"]
        return out

    def parent_of(self, node_id: str) -> str | None:
        return self.nodes[node_id]["parent"]


def load_taxonomy(conn: Connection, taxonomy_type: str) -> Taxonomy:
    rows = conn.execute(text(
        """SELECT n.taxonomy_node_id::text AS id, n.code, n.display_name AS label, n.depth,
                  n.parent_node_id::text AS parent, t.version
           FROM taxonomy t JOIN taxonomy_node n USING (taxonomy_id)
           WHERE t.taxonomy_type = :t AND t.status = 'ACTIVE'"""), {"t": taxonomy_type}).all()
    if not rows:
        raise PolicyMissing(f"no active {taxonomy_type} taxonomy")
    return Taxonomy(taxonomy_type, rows[0].version,
                    {r.id: {"code": r.code, "label": r.label, "depth": r.depth, "parent": r.parent}
                     for r in rows})


def surface_depth(conn: Connection, surface: str, taxonomy_type: str,
                  requested: int | None) -> int:
    row = conn.execute(text(
        """SELECT default_depth, min_depth, max_depth FROM product_taxonomy_view
           WHERE surface_code = :s AND taxonomy_type = :t AND status = 'ACTIVE'"""),
        {"s": surface, "t": taxonomy_type}).first()
    if row is None:
        raise PolicyMissing(f"no product_taxonomy_view for {surface}/{taxonomy_type}")
    if requested is None:
        return row.default_depth
    return max(row.min_depth, min(row.max_depth, requested))


# --- cohort filters -----------------------------------------------------------------------

@dataclass
class Filters:
    institution_ids: list[str] = field(default_factory=list)
    major_node_ids: list[str] = field(default_factory=list)
    admission: tuple[int | None, int | None] = (None, None)
    graduation: tuple[int | None, int | None] = (None, None)
    gender_codes: list[str] = field(default_factory=list)
    current_role_node_ids: list[str] = field(default_factory=list)
    first_role_node_ids: list[str] = field(default_factory=list)

    def public(self, majors: Taxonomy, roles: Taxonomy) -> dict:
        def codes(tax, ids):
            return [{"node_id": i, "code": tax.nodes[i]["code"], "label": tax.nodes[i]["label"]}
                    for i in ids if i in tax.nodes]
        out = {
            "institution_ids": self.institution_ids,
            "majors": codes(majors, self.major_node_ids),
            "admission_year": _range(self.admission),
            "graduation_year": _range(self.graduation),
            "gender_codes": self.gender_codes,
            "current_roles": codes(roles, self.current_role_node_ids),
            "first_roles": codes(roles, self.first_role_node_ids),
        }
        return {k: v for k, v in out.items() if v}

    @property
    def demographic(self) -> bool:
        return bool(self.gender_codes)


def _range(r: tuple[int | None, int | None]) -> dict | None:
    return None if r == (None, None) else {"from": r[0], "to": r[1]}


def _apply_step(f: Filters, step: dict, majors: Taxonomy) -> tuple[Filters, str] | None:
    """Return the widened filters and a reason code, or None when the step does not apply."""
    kind, dim = step.get("step"), step.get("dimension")
    if kind == "widen_time" and dim in ("graduation_year", "admission_year"):
        attr = "graduation" if dim == "graduation_year" else "admission"
        lo, hi = getattr(f, attr)
        if lo is None and hi is None:
            return None
        by = int(step.get("by_years", 0))
        widened = (None if lo is None else lo - by, None if hi is None else hi + by)
        return replace(f, **{attr: widened}), f"WIDEN_{dim.upper()}_{by}Y"
    if kind == "broaden_taxonomy" and dim == "major":
        if not f.major_node_ids:
            return None
        levels = int(step.get("levels", 1))
        nodes = list(f.major_node_ids)
        for _ in range(levels):
            nodes = [majors.parent_of(n) or n for n in nodes]
        nodes = sorted(set(nodes))
        if nodes == sorted(f.major_node_ids):
            return None
        return replace(f, major_node_ids=nodes), f"BROADEN_MAJOR_{levels}_LEVEL"
    if kind == "drop":
        attr = {"gender": "gender_codes", "admission_year": "admission",
                "graduation_year": "graduation", "institution": "institution_ids",
                "major": "major_node_ids", "current_role": "current_role_node_ids",
                "first_role": "first_role_node_ids"}.get(dim)
        if attr is None:
            return None
        empty = (None, None) if attr in ("admission", "graduation") else []
        if getattr(f, attr) in (empty, [], ()):
            return None
        return replace(f, **{attr: empty}), f"DROP_{dim.upper()}"
    if kind == "similarity_top_k":
        # Not available in the query engine: the result stays suppressed and says so.
        return None
    return None


def _cohort_sql(f: Filters, majors: Taxonomy, roles: Taxonomy) -> tuple[str, dict]:
    where = ["p.deleted_at IS NULL", "p.origin_layer = ANY(:layers)"]
    params: dict = {}
    edu = []
    if f.institution_ids:
        edu.append("e.institution_id = ANY(CAST(:inst AS uuid[]))")
        params["inst"] = f.institution_ids
    if f.major_node_ids:
        edu.append("e.major_taxonomy_node_id = ANY(CAST(:majors AS uuid[]))")
        params["majors"] = majors.subtree(f.major_node_ids)
    for attr, col in (("admission", "admission_year"), ("graduation", "graduation_year")):
        lo, hi = getattr(f, attr)
        if lo is not None:
            edu.append(f"e.{col} >= :{attr}_lo")
            params[f"{attr}_lo"] = lo
        if hi is not None:
            edu.append(f"e.{col} <= :{attr}_hi")
            params[f"{attr}_hi"] = hi
    if edu:
        where.append("EXISTS (SELECT 1 FROM canonical_education e WHERE e.person_id = p.person_id "
                     "AND " + " AND ".join(edu) + ")")
    if f.gender_codes:
        where.append("p.gender_code = ANY(:genders)")
        params["genders"] = f.gender_codes
    if f.current_role_node_ids:
        where.append("""EXISTS (SELECT 1 FROM canonical_work_event w
                         WHERE w.person_id = p.person_id
                           AND w.role_taxonomy_node_id = ANY(CAST(:cur_roles AS uuid[]))
                           AND w.start_date <= :as_of
                           AND (w.end_date IS NULL OR w.end_date > :as_of))""")
        params["cur_roles"] = roles.subtree(f.current_role_node_ids)
    if f.first_role_node_ids:
        where.append("""EXISTS (SELECT 1 FROM first_employment_all(:fe_rule, :as_of) fe
                         JOIN work_event w ON w.work_event_id = fe.work_event_id
                         WHERE fe.person_id = p.person_id
                           AND w.role_taxonomy_node_id = ANY(CAST(:first_roles AS uuid[])))""")
        params["first_roles"] = roles.subtree(f.first_role_node_ids)
    return "SELECT p.person_id FROM person p WHERE " + " AND ".join(where), params


def _window_clause(col: str, start: date | None) -> str:
    return f"{col} <= :as_of" + (f" AND {col} >= :win_start" if start else "")


# One row per person in the analysed basis: (person_id, result node uuid or NULL/STAYED).
METRIC_SQL = {
    "FIRST_ROLE_DISTRIBUTION": """
        SELECT fe.person_id, w.role_taxonomy_node_id::text AS node
        FROM first_employment_all(:fe_rule, :as_of) fe
        JOIN cohort c ON c.person_id = fe.person_id
        LEFT JOIN work_event w ON w.work_event_id = fe.work_event_id
        WHERE {window_fe}""",
    "FIRST_INDUSTRY_DISTRIBUTION": """
        SELECT fe.person_id, oi.taxonomy_node_id::text AS node
        FROM first_employment_all(:fe_rule, :as_of) fe
        JOIN cohort c ON c.person_id = fe.person_id
        LEFT JOIN work_event w ON w.work_event_id = fe.work_event_id
        LEFT JOIN organization_industry oi ON oi.organization_id = w.organization_id
             AND oi.is_primary AND oi.valid_to IS NULL
        WHERE {window_fe}""",
    "CURRENT_ROLE_DISTRIBUTION": """
        SELECT DISTINCT ON (w.person_id) w.person_id, w.role_taxonomy_node_id::text AS node
        FROM canonical_work_event w
        JOIN cohort c ON c.person_id = w.person_id
        WHERE w.start_date <= :as_of AND (w.end_date IS NULL OR w.end_date > :as_of)
          AND w.event_type <> 'STUDY'
          AND (CAST(:win_start AS date) IS NULL OR EXISTS (
                SELECT 1 FROM first_employment_all(:fe_rule, :as_of) fe
                WHERE fe.person_id = w.person_id AND fe.start_date >= :win_start))
        ORDER BY w.person_id, w.start_date DESC, w.work_event_id""",
    # For each person: the first event in the from-subtree, then the next event that starts
    # after it (the next choice). Still in it at as_of with nothing after = STAYED.
    "NEXT_ROLE_DISTRIBUTION": """
        , ev AS (
            SELECT w.person_id, w.work_event_id, w.role_taxonomy_node_id, w.start_date,
                   w.end_date,
                   lead(w.role_taxonomy_node_id) OVER per AS next_node,
                   lead(w.start_date) OVER per AS next_start
            FROM canonical_work_event w JOIN cohort c ON c.person_id = w.person_id
            WHERE w.start_date IS NOT NULL AND w.start_date <= :as_of
              AND w.event_type NOT IN ('STUDY', 'MILITARY', 'CAREER_BREAK')
            WINDOW per AS (PARTITION BY w.person_id ORDER BY w.start_date, w.work_event_id)),
        src AS (
            SELECT DISTINCT ON (person_id) * FROM ev
            WHERE role_taxonomy_node_id = ANY(CAST(:from_roles AS uuid[]))
            ORDER BY person_id, start_date, work_event_id)
        SELECT person_id,
               CASE WHEN next_start IS NOT NULL THEN next_node::text
                    WHEN end_date IS NULL OR end_date > :as_of THEN 'STAYED' END AS node
        FROM src
        WHERE (next_start IS NOT NULL AND {window_next})
           OR (next_start IS NULL AND (end_date IS NULL OR end_date > :as_of))""",
}


def _basis(conn: Connection, q: CareerQuery, f: Filters, majors: Taxonomy, roles: Taxonomy,
           layers: list[str], win_start: date | None) -> list[tuple[str, str | None]]:
    cohort_sql, params = _cohort_sql(f, majors, roles)
    sql = METRIC_SQL[q.target_metric].format(
        window_fe=_window_clause("fe.start_date", win_start),
        window_next=_window_clause("next_start", win_start))
    params.update(layers=layers, as_of=q.as_of_date, win_start=win_start,
                  fe_rule=FIRST_EMPLOYMENT_RULE)
    if q.target_metric == "NEXT_ROLE_DISTRIBUTION":
        params["from_roles"] = roles.subtree(q.from_role_node_ids)
    # Metric SQL either starts with SELECT or continues the CTE list with ", name AS (...)".
    rows = conn.execute(text(f"WITH cohort AS ({cohort_sql}) {sql}"), params).all()
    return [(str(r.person_id), r.node) for r in rows]


def evaluate(conn: Connection, q: CareerQuery, *, layers: list[str]) -> dict:
    if q.target_metric not in SUPPORTED_METRICS:
        raise QueryInvalid(f"target_metric must be one of {sorted(SUPPORTED_METRICS)}")
    if q.target_metric == "NEXT_ROLE_DISTRIBUTION" and not q.from_role_node_ids:
        raise QueryInvalid("NEXT_ROLE_DISTRIBUTION needs from_role_node_ids")
    win_start, win_end = time_window(q.as_of_date, q.lookback)
    policy = active_cohort_policy_v2(conn)
    majors, roles = load_taxonomy(conn, "MAJOR"), load_taxonomy(conn, "ROLE")
    result_type = SUPPORTED_METRICS[q.target_metric]
    result_tax = roles if result_type == "ROLE" else load_taxonomy(conn, result_type)
    depth = surface_depth(conn, q.surface_code, result_type, q.requested_depth)
    for ids, tax in ((q.major_node_ids, majors), (q.current_role_node_ids, roles),
                     (q.first_role_node_ids, roles), (q.from_role_node_ids, roles)):
        unknown = [i for i in ids if i not in tax.nodes]
        if unknown:
            raise QueryInvalid(f"unknown taxonomy node(s): {unknown}")

    requested = Filters(
        institution_ids=list(q.institution_ids), major_node_ids=list(q.major_node_ids),
        admission=(q.admission_year_from, q.admission_year_to),
        graduation=(q.graduation_year_from, q.graduation_year_to),
        gender_codes=list(q.gender_codes), current_role_node_ids=list(q.current_role_node_ids),
        first_role_node_ids=list(q.first_role_node_ids))

    def threshold(f: Filters) -> int:
        return policy.demographic_min_n if f.demographic else policy.min_exact_n

    effective, reasons = requested, []
    rows = _basis(conn, q, effective, majors, roles, layers, win_start)
    exact_n = len(rows)
    for step in policy.fallback_steps:
        if len(rows) >= threshold(effective):
            break
        applied = _apply_step(effective, step, majors)
        if applied is None:
            continue
        effective, reason = applied
        reasons.append(reason)
        rows = _basis(conn, q, effective, majors, roles, layers, win_start)
    effective_n = len(rows)
    suppressed = effective_n < threshold(effective)
    min_cell = policy.demographic_min_cell_n if effective.demographic else policy.min_cell_n

    counts: dict[str, int] = defaultdict(int)
    unknown_n = 0
    for _, node in rows:
        if node is None or (node != STAYED and node not in result_tax.nodes):
            unknown_n += 1
        else:
            counts[node if node == STAYED else result_tax.ancestor_at(node, depth)] += 1
    cells, other_n = [], 0
    if not suppressed:
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        for key, n in ranked:
            if n < min_cell or len(cells) >= policy.top_n:
                other_n += n
                continue
            node = result_tax.nodes.get(key)
            cells.append({
                "key": key, "code": node["code"] if node else key,
                "label": node["label"] if node else None, "depth": node["depth"] if node else None,
                "n": n, "share": round(n / effective_n, 4)})
    other = None
    if other_n:
        # A folded remainder smaller than one cell would itself expose a small group.
        other = ({"n": other_n, "share": round(other_n / effective_n, 4)} if other_n >= min_cell
                 else {"n": None, "share": None, "suppressed": True})

    return {
        "target_metric": q.target_metric, "query_hash": q.query_hash(),
        "as_of_date": q.as_of_date.isoformat(), "lookback": q.lookback,
        "time_window": {"start": win_start.isoformat() if win_start else None,
                        "end": win_end.isoformat()},
        "taxonomy_depth": depth,
        "taxonomy_version": {"ROLE": roles.version, "MAJOR": majors.version,
                             result_type: result_tax.version},
        "cohort_policy_version": policy.version, "first_employment_rule": FIRST_EMPLOYMENT_RULE,
        "requested_filters": requested.public(majors, roles),
        "effective_filters": effective.public(majors, roles),
        "exact_n": exact_n, "effective_n": effective_n, "fallback_level": len(reasons),
        "fallback_reason": reasons, "threshold": threshold(effective),
        "min_cell_n": min_cell, "suppressed": suppressed,
        "cells": cells, "other": None if suppressed else other,
        "unknown_n": None if suppressed else unknown_n,
        "data_layers": layers,
    }
