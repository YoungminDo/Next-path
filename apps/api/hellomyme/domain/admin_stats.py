"""Team dashboard numbers (docs/10): the demand-test funnel and what people entered.

Read-only aggregates, the same definitions as scripts/funnel.sql. A person is one anonymous
browser session. The team's sessions (any event sent with ?internal=1) are left out unless asked
for. Counts only: no phone numbers, no account or session ids leave this module.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from sqlalchemy import Connection, text

Range = Literal["today", "7d", "30d", "all"]
DAYS = {"today": 1, "7d": 7, "30d": 30, "all": None}

# (key, label, event, screens) in funnel order; screens narrows result_step_viewed.
FUNNEL = (
    ("landing", "랜딩 방문", "landing_viewed", None),
    ("input_started", "입력 시작", "career_input_started", None),
    ("input_completed", "학교 정보 입력 완료", "career_input_completed", None),
    ("preview", "미리보기 확인", "login_wall_viewed", None),
    ("login_clicked", "카카오 로그인 누름", "login_clicked", None),
    ("signup", "로그인 완료", "signup_completed", None),
    ("first_result", "첫 결과 확인", "result_step_viewed", ("s_result", "p_next")),
    ("intent", "궁금한 길 고름", "intent_selected", None),
    ("path_result", "경로 결과 확인", "result_step_viewed", ("me",)),
    ("unlock", "깊은 분석 열기", "unlock_purchased", None),
)
RESULT_SCREENS = ("s_result", "s_intent", "p_next", "p_first", "p_similar", "me")
SCREEN_LABELS = {"s_result": "첫 결과 (학생)", "s_intent": "궁금한 길 고르기", "p_next": "첫 결과 (직장인)",
                 "p_first": "첫 직장 입력", "p_similar": "비슷한 경로", "me": "경로 결과"}

# Every query below starts from these: the window (Korean days) and who counts.
_EVENTS = """
    WITH team AS (
        SELECT DISTINCT anonymous_session_id AS sid FROM analytics.event
        WHERE anonymous_session_id IS NOT NULL AND properties->>'internal' = 'true'),
    ev AS (
        SELECT e.event_name, e.properties, e.received_at,
               coalesce(e.anonymous_session_id, e.account_id::text, e.event_id::text) AS sid
        FROM analytics.event e
        WHERE (CAST(:t_from AS timestamptz) IS NULL OR e.received_at >= :t_from)
          AND (:with_team OR (coalesce(e.properties->>'internal', 'false') <> 'true'
               AND (e.anonymous_session_id IS NULL
                    OR e.anonymous_session_id NOT IN (SELECT sid FROM team)))))
"""
_INPUTS = """
    WITH inp AS (
        SELECT i.* FROM analytics.acq_input i
        WHERE (CAST(:t_from AS timestamptz) IS NULL OR i.created_at >= :t_from)
          AND (:with_team OR NOT i.internal))
"""


def window_start(conn: Connection, rng: Range):
    days = DAYS[rng]
    if days is None:
        return None
    return conn.execute(text(
        """SELECT (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul') - make_interval(days => :d))
                  AT TIME ZONE 'Asia/Seoul'"""), {"d": days - 1}).scalar_one()


def _rows(conn: Connection, sql: str, params: dict) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def stats(conn: Connection, rng: Range, with_team: bool) -> dict:
    t_from = window_start(conn, rng)
    p = {"t_from": t_from, "with_team": with_team}

    counts = conn.execute(text(_EVENTS + "SELECT " + ", ".join(
        f"count(DISTINCT sid) FILTER (WHERE event_name = '{ev}'"
        + (f" AND properties->>'screen' IN ({', '.join(repr(s) for s in screens)})" if screens else "")
        + f") AS {key}" for key, _, ev, screens in FUNNEL) + " FROM ev"), p).one()._mapping
    funnel = [{"key": key, "label": label, "people": counts[key]} for key, label, _, _ in FUNNEL]

    daily = _rows(conn, _EVENTS + """
        SELECT (received_at AT TIME ZONE 'Asia/Seoul')::date AS day,
               count(DISTINCT sid) FILTER (WHERE event_name = 'landing_viewed') AS landing,
               count(DISTINCT sid) FILTER (WHERE event_name = 'career_input_completed') AS input_completed,
               count(DISTINCT sid) FILTER (WHERE event_name = 'signup_completed') AS signup
        FROM ev GROUP BY 1 ORDER BY 1""", p)
    daily = _fill_days(daily, t_from and conn.execute(text(
        "SELECT (CAST(:t AS timestamptz) AT TIME ZONE 'Asia/Seoul')::date"), {"t": t_from}).scalar_one(),
        conn.execute(text("SELECT (now() AT TIME ZONE 'Asia/Seoul')::date")).scalar_one())

    channels = _rows(conn, _EVENTS + """
        , channel AS (
            SELECT DISTINCT ON (sid) sid,
                   coalesce(properties->>'utm_source', properties->>'in_app', properties->>'referrer',
                            '(직접 방문)') AS channel
            FROM ev ORDER BY sid, (properties ? 'utm_source') DESC, received_at)
        SELECT c.channel,
               count(DISTINCT c.sid) FILTER (WHERE e.event_name = 'landing_viewed') AS landing,
               count(DISTINCT c.sid) FILTER (WHERE e.event_name = 'career_input_completed')
                   AS input_completed,
               count(DISTINCT c.sid) FILTER (WHERE e.event_name = 'signup_completed') AS signup,
               count(DISTINCT c.sid) FILTER (WHERE e.event_name = 'result_step_viewed') AS result
        FROM channel c JOIN ev e USING (sid)
        GROUP BY 1 ORDER BY landing DESC, input_completed DESC LIMIT 20""", p)

    dwell = _rows(conn, _EVENTS + """
        , stay AS (
            SELECT properties->>'previous' AS screen,
                   CASE WHEN properties->>'seconds_on_previous' ~ '^[0-9]{1,6}$'
                        THEN (properties->>'seconds_on_previous')::int END AS seconds
            FROM ev WHERE event_name = 'result_step_viewed'
              AND properties->>'previous' = ANY(:screens)
            UNION ALL
            SELECT properties->>'screen',
                   CASE WHEN properties->>'seconds' ~ '^[0-9]{1,6}$'
                        THEN (properties->>'seconds')::int END
            FROM ev WHERE event_name = 'result_left')
        SELECT screen, count(*) AS views,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY seconds) AS median_seconds
        FROM stay WHERE seconds BETWEEN 0 AND 3600 AND screen = ANY(:screens)
        GROUP BY 1 ORDER BY views DESC""", {**p, "screens": list(RESULT_SCREENS)})
    for d in dwell:
        d["label"] = SCREEN_LABELS.get(d["screen"], d["screen"])

    def top(name_sql: str, listed_sql: str, limit: int = 20) -> list[dict]:
        return _rows(conn, _INPUTS + f"""
            SELECT {name_sql} AS name, bool_or({listed_sql}) AS listed,
                   count(DISTINCT session_hash) AS people
            FROM inp WHERE {name_sql} IS NOT NULL GROUP BY 1 ORDER BY people DESC, name LIMIT {limit}""", p)

    schools = top("coalesce(institution_name, institution_raw)", "institution_listed")
    majors = top("coalesce(major_label, major_raw)", "major_listed")
    combos = _rows(conn, _INPUTS + """
        SELECT coalesce(institution_name, institution_raw) AS school,
               coalesce(major_label, major_raw) AS major, count(DISTINCT session_hash) AS people
        FROM inp GROUP BY 1, 2 ORDER BY people DESC, school, major LIMIT 15""", p)
    inputs = conn.execute(text(_INPUTS + """
        SELECT count(DISTINCT session_hash) AS people,
               count(DISTINCT session_hash) FILTER (WHERE user_type = 'PROFESSIONAL') AS professionals,
               count(DISTINCT session_hash) FILTER (WHERE NOT institution_listed) AS unlisted_school,
               count(DISTINCT session_hash) FILTER (WHERE NOT major_listed) AS unlisted_major,
               count(DISTINCT session_hash) FILTER (WHERE claimed_at IS NOT NULL) AS linked
        FROM inp"""), p).one()._mapping

    # Only drafts saved since the question exists carry the key (null = skipped).
    desired_status = _rows(conn, _INPUTS + """
        SELECT coalesce(inp.desired_role_status, 'SKIPPED') AS status,
               count(DISTINCT inp.session_hash) AS people
        FROM inp JOIN anonymous_draft d USING (draft_id)
        WHERE d.payload_json ? 'desired_role_status'
        GROUP BY 1 ORDER BY people DESC""", p)
    desired_roles = _rows(conn, _INPUTS + """
        SELECT coalesce(r.role_label, r.role_raw) AS name, bool_or(r.role_listed) AS listed,
               count(DISTINCT r.session_hash) AS people,
               count(DISTINCT r.session_hash) FILTER (WHERE r.rank = 1) AS first_choice
        FROM analytics.acq_desired_role r JOIN inp USING (draft_id)
        GROUP BY 1 ORDER BY people DESC, name LIMIT 20""", p)

    backlog = _rows(conn, """
        SELECT kind, most_typed AS name, people, cardinality(spellings) AS spellings
        FROM analytics.acq_unlisted_backlog ORDER BY people DESC, kind, most_typed LIMIT 20""", {})
    interview = conn.execute(text("""
        SELECT count(*) FILTER (WHERE withdrawn_at IS NULL) AS applied,
               count(*) FILTER (WHERE withdrawn_at IS NULL AND phone_verified_at IS NOT NULL) AS verified,
               count(*) FILTER (WHERE withdrawn_at IS NOT NULL) AS withdrawn,
               count(*) FILTER (WHERE (CAST(:t_from AS timestamptz) IS NULL OR consented_at >= :t_from)
                                  AND withdrawn_at IS NULL) AS applied_in_range
        FROM interview_contact"""), {"t_from": t_from}).one()._mapping
    shown = conn.execute(text(_EVENTS + """
        SELECT count(DISTINCT sid) FILTER (WHERE event_name = 'interview_step_viewed') AS shown,
               count(DISTINCT sid) FILTER (WHERE event_name = 'interview_skipped') AS skipped,
               count(DISTINCT sid) FILTER (WHERE event_name = 'interview_submitted') AS submitted
        FROM ev"""), p).one()._mapping

    return {
        "range": rng, "with_team": with_team,
        "since": t_from.isoformat() if t_from else None,
        "funnel": funnel, "daily": daily, "channels": channels, "dwell": dwell,
        "inputs": dict(inputs), "schools": schools, "majors": majors, "combos": combos,
        "desired_status": desired_status, "desired_roles": desired_roles, "backlog": backlog,
        "interview": {**dict(interview), **dict(shown)},
    }


def _fill_days(rows: list[dict], start: date | None, end: date) -> list[dict]:
    """A day with no visits is a zero on the chart, not a gap."""
    by_day = {r["day"]: r for r in rows}
    if not rows and start is None:
        return []
    day = start or min(by_day)
    out = []
    while day <= end:
        r = by_day.get(day, {"landing": 0, "input_completed": 0, "signup": 0})
        out.append({"day": day.isoformat(), "landing": r["landing"],
                    "input_completed": r["input_completed"], "signup": r["signup"]})
        day += timedelta(days=1)
    return out
