-- nextpath 수요 테스트 퍼널 (docs/10_DEMAND_TEST.md)
-- Supabase → SQL Editor 에 이 파일 전체를 붙여넣고 Run. 읽기만 하고 아무것도 바꾸지 않습니다.
-- 기간은 params 의 t_from / t_to 만 바꾸면 됩니다 (기본: 오늘 0시(한국 시간)부터 지금까지).
-- 사람 수 = 브라우저(익명 세션) 수, 방문은 아래 visit 기준. 팀이 ?internal=1 로 한 번 연 브라우저와 사람이 아닌 방문(Meta 검토 등)은 빠집니다.
-- 시각은 서버가 받은 시각(received_at) 기준. 채널: utm_source → 인앱 앱(instagram 등) → referrer.

WITH params AS (
  SELECT (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')) AT TIME ZONE 'Asia/Seoul' AS t_from,
         now() AS t_to
),
ev AS (
  SELECT e.event_name, e.properties, e.occurred_at, e.received_at,
         coalesce(e.anonymous_session_id, e.account_id::text) AS sid
  FROM analytics.event e CROSS JOIN params p
  WHERE e.received_at >= p.t_from AND e.received_at < p.t_to
    AND coalesce(e.properties->>'internal', 'false') <> 'true'
    AND NOT (coalesce(e.properties->>'bot', 'false') = 'true'  -- not a person (docs/10)
         OR ((coalesce(e.properties->>'utm_medium', '') = 'paid_social'
              OR coalesce(e.properties->>'referrer', '') LIKE '%facebook.com')
             AND e.properties->>'in_app' IS NULL AND e.properties->>'fbclid' IS NULL))
),
-- 방문 (docs/10 §방문): 기간 안 첫 이벤트가 랜딩이거나 /start·/upload 로 바로 들어온 브라우저.
-- 인앱 브라우저가 답을 넘겨준 휴대폰 브라우저(handoff)와, 랜딩 중간 단계로 시작한 브라우저(인스타 인앱이
-- 미리 연 랜딩의 저장소가 바뀐 같은 사람)는 새 방문이 아닙니다. /admin·슬랙 알림과 같은 기준.
visit AS (
  SELECT sid FROM (
    SELECT DISTINCT ON (sid) sid, event_name, properties->>'path' AS path, properties ? 'handoff' AS handoff
    FROM ev ORDER BY sid, received_at) f
  WHERE event_name = 'landing_viewed' OR (path IN ('/start', '/upload') AND NOT handoff)
),
steps (ord, step, event_name, screens) AS (
  VALUES
    (1,  '1. 방문',                     'landing_viewed',        NULL::text[]),  -- visit 기준
    (2,  '2. 입력 시작',                 'career_input_started',  NULL),
    (3,  '3. 학교 정보 입력 완료',        'career_input_completed', NULL),
    (4,  '4. 미리보기(몇 명·몇 갈래) 확인', 'login_wall_viewed',     NULL),
    (5,  '5. 카카오 로그인 누름',         'login_clicked',         NULL),
    (6,  '6. 로그인 완료',               'signup_completed',      NULL),
    (7,  '7. 첫 결과 확인',              'result_step_viewed',    ARRAY['s_result','p_next']),
    (8,  '8. 궁금한 길 고름',             'intent_selected',       NULL),
    (9,  '9. 경로 결과 확인',             'result_step_viewed',    ARRAY['me']),
    (10, '10. 깊은 분석 열기(튜브)',       'unlock_purchased',      NULL)
),
counts AS (
  SELECT s.ord, s.step,
         CASE WHEN s.ord = 1 THEN (SELECT count(*) FROM visit) ELSE count(DISTINCT ev.sid) END AS people
  FROM steps s
  LEFT JOIN ev ON ev.event_name = s.event_name
              AND (s.screens IS NULL OR ev.properties->>'screen' = ANY (s.screens))
  GROUP BY s.ord, s.step
)
SELECT step AS "단계",
       people AS "사람 수",
       round(100.0 * people / nullif(first_value(people) OVER (ORDER BY ord), 0), 1) AS "방문 대비 %",
       round(100.0 * people / nullif(lag(people) OVER (ORDER BY ord), 0), 1) AS "이전 단계 대비 %"
FROM counts ORDER BY ord;

-- ─────────────────────────────────────────────────────────────────────────────
-- 아래 쿼리들은 하나씩 선택해서 실행하세요 (같은 기간 조건).

-- [채널별] 어디서 온 사람이 입력·로그인·결과까지 갔나 (utm_source, 없으면 referrer)
WITH params AS (
  SELECT (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')) AT TIME ZONE 'Asia/Seoul' AS t_from, now() AS t_to
), ev AS (
  SELECT e.event_name, e.properties, e.received_at, coalesce(e.anonymous_session_id, e.account_id::text) AS sid
  FROM analytics.event e CROSS JOIN params p
  WHERE e.received_at >= p.t_from AND e.received_at < p.t_to
    AND coalesce(e.properties->>'internal', 'false') <> 'true'
    AND NOT (coalesce(e.properties->>'bot', 'false') = 'true'  -- not a person (docs/10)
         OR ((coalesce(e.properties->>'utm_medium', '') = 'paid_social'
              OR coalesce(e.properties->>'referrer', '') LIKE '%facebook.com')
             AND e.properties->>'in_app' IS NULL AND e.properties->>'fbclid' IS NULL))
), visit AS (  -- 방문: 맨 위 퍼널과 같은 기준
  SELECT sid FROM (
    SELECT DISTINCT ON (sid) sid, event_name, properties->>'path' AS path, properties ? 'handoff' AS handoff
    FROM ev ORDER BY sid, received_at) f
  WHERE event_name = 'landing_viewed' OR (path IN ('/start', '/upload') AND NOT handoff)
), channel AS (
  SELECT DISTINCT ON (sid) sid,
         coalesce(properties->>'utm_source', properties->>'in_app', properties->>'referrer', '(직접 방문)') AS ch
  FROM ev ORDER BY sid, (properties ? 'utm_source') DESC
)
SELECT c.ch AS "채널",
       count(DISTINCT c.sid) FILTER (WHERE c.sid IN (SELECT sid FROM visit)) AS "방문",
       count(DISTINCT c.sid) FILTER (WHERE e.event_name = 'career_input_completed') AS "입력 완료",
       count(DISTINCT c.sid) FILTER (WHERE e.event_name = 'signup_completed') AS "로그인",
       count(DISTINCT c.sid) FILTER (WHERE e.event_name = 'result_step_viewed') AS "결과 확인"
FROM channel c JOIN ev e USING (sid)
GROUP BY c.ch ORDER BY "방문" DESC;

-- [결과를 얼마나 보나] 결과 화면별 머문 시간(초): 중앙값과 상위 25%
WITH params AS (
  SELECT (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')) AT TIME ZONE 'Asia/Seoul' AS t_from, now() AS t_to
), stay AS (
  SELECT e.properties->>'previous' AS screen, CASE WHEN e.properties->>'seconds_on_previous' ~ '^[0-9]{1,6}$' THEN (e.properties->>'seconds_on_previous')::int END AS seconds
  FROM analytics.event e CROSS JOIN params p
  WHERE e.event_name = 'result_step_viewed' AND e.received_at >= p.t_from AND e.received_at < p.t_to
    AND coalesce(e.properties->>'internal', 'false') <> 'true'
    AND NOT (coalesce(e.properties->>'bot', 'false') = 'true'  -- not a person (docs/10)
         OR ((coalesce(e.properties->>'utm_medium', '') = 'paid_social'
              OR coalesce(e.properties->>'referrer', '') LIKE '%facebook.com')
             AND e.properties->>'in_app' IS NULL AND e.properties->>'fbclid' IS NULL))
    AND e.properties->>'previous' IN ('s_result','s_intent','p_next','p_first','p_similar','me')
  UNION ALL
  SELECT e.properties->>'screen', CASE WHEN e.properties->>'seconds' ~ '^[0-9]{1,6}$' THEN (e.properties->>'seconds')::int END
  FROM analytics.event e CROSS JOIN params p
  WHERE e.event_name = 'result_left' AND e.received_at >= p.t_from AND e.received_at < p.t_to
    AND coalesce(e.properties->>'internal', 'false') <> 'true'
    AND NOT (coalesce(e.properties->>'bot', 'false') = 'true'  -- not a person (docs/10)
         OR ((coalesce(e.properties->>'utm_medium', '') = 'paid_social'
              OR coalesce(e.properties->>'referrer', '') LIKE '%facebook.com')
             AND e.properties->>'in_app' IS NULL AND e.properties->>'fbclid' IS NULL))
)
SELECT screen AS "화면", count(*) AS "조회 수",
       percentile_cont(0.5) WITHIN GROUP (ORDER BY seconds) AS "중앙값(초)",
       percentile_cont(0.75) WITHIN GROUP (ORDER BY seconds) AS "상위25%(초)"
FROM stay WHERE seconds BETWEEN 0 AND 3600
GROUP BY screen ORDER BY "조회 수" DESC;

-- [어떤 학교·학과를 입력했나] 입력 완료 기준. "목록 밖" = 검색 목록에 없어 직접 입력한 이름
WITH params AS (
  SELECT (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')) AT TIME ZONE 'Asia/Seoul' AS t_from, now() AS t_to
), inp AS (
  SELECT DISTINCT ON (e.anonymous_session_id) e.anonymous_session_id AS sid, e.properties AS p
  FROM analytics.event e CROSS JOIN params x
  WHERE e.event_name = 'career_input_completed' AND e.received_at >= x.t_from AND e.received_at < x.t_to
    AND coalesce(e.properties->>'internal', 'false') <> 'true'
    AND NOT (coalesce(e.properties->>'bot', 'false') = 'true'  -- not a person (docs/10)
         OR ((coalesce(e.properties->>'utm_medium', '') = 'paid_social'
              OR coalesce(e.properties->>'referrer', '') LIKE '%facebook.com')
             AND e.properties->>'in_app' IS NULL AND e.properties->>'fbclid' IS NULL))
  ORDER BY e.anonymous_session_id, e.received_at DESC
)
SELECT 'school' AS "구분", p->>'institution_name' AS "이름",
       CASE WHEN p->>'institution_listed' = 'true' THEN '목록' ELSE '목록 밖' END AS "출처",
       count(*) AS "사람 수"
FROM inp GROUP BY 2, 3
UNION ALL
SELECT 'major', p->>'major_label',
       CASE WHEN p->>'major_listed' = 'true' THEN '목록' ELSE '목록 밖' END, count(*)
FROM inp GROUP BY 2, 3
ORDER BY 1 DESC, 4 DESC, 2;

-- [학교 × 학과 조합] 많이 들어온 순
WITH params AS (
  SELECT (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')) AT TIME ZONE 'Asia/Seoul' AS t_from, now() AS t_to
)
SELECT e.properties->>'institution_name' AS "학교", e.properties->>'major_label' AS "학과",
       count(DISTINCT e.anonymous_session_id) AS "사람 수"
FROM analytics.event e CROSS JOIN params x
WHERE e.event_name = 'career_input_completed' AND e.received_at >= x.t_from AND e.received_at < x.t_to
  AND coalesce(e.properties->>'internal', 'false') <> 'true'
  AND NOT (coalesce(e.properties->>'bot', 'false') = 'true'  -- not a person (docs/10)
       OR ((coalesce(e.properties->>'utm_medium', '') = 'paid_social'
            OR coalesce(e.properties->>'referrer', '') LIKE '%facebook.com')
           AND e.properties->>'in_app' IS NULL AND e.properties->>'fbclid' IS NULL))
GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2;

-- [목록 밖으로 검색만 하고 떠난 이름 포함] 입력 중 직접 친 학교·전공 (많이 원한 순)
WITH params AS (
  SELECT (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')) AT TIME ZONE 'Asia/Seoul' AS t_from, now() AS t_to
)
SELECT e.properties->>'kind' AS "종류", e.properties->>'name' AS "이름",
       count(DISTINCT e.anonymous_session_id) AS "사람 수"
FROM analytics.event e CROSS JOIN params p
WHERE e.event_name = 'school_requested' AND e.received_at >= p.t_from AND e.received_at < p.t_to
  AND coalesce(e.properties->>'internal', 'false') <> 'true'
  AND NOT (coalesce(e.properties->>'bot', 'false') = 'true'  -- not a person (docs/10)
       OR ((coalesce(e.properties->>'utm_medium', '') = 'paid_social'
            OR coalesce(e.properties->>'referrer', '') LIKE '%facebook.com')
           AND e.properties->>'in_app' IS NULL AND e.properties->>'fbclid' IS NULL))
GROUP BY 1, 2 ORDER BY 3 DESC, 2;

-- ============================================================================================
-- 아래는 이벤트가 아니라 저장된 입력 자체(DB, migration 0026)로 본 숫자. 가입하지 않고 떠난 입력도
-- 모두 들어 있습니다. 수정할 때마다 남는 이력은 anonymous_draft_revision 에 있습니다.

-- [입력 DB] 기간 안에 저장된 입력: 사람(브라우저) 수, 희망 직무 응답, 로그인으로 계정에 연결된 수
WITH params AS (
  SELECT (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')) AT TIME ZONE 'Asia/Seoul' AS t_from, now() AS t_to
)
SELECT user_type AS "유형",
       count(DISTINCT session_hash) AS "입력한 사람",
       count(DISTINCT session_hash) FILTER (WHERE NOT institution_listed) AS "목록 밖 학교",
       count(DISTINCT session_hash) FILTER (WHERE NOT major_listed) AS "목록 밖 전공",
       count(DISTINCT session_hash) FILTER (WHERE desired_role_status = 'CHOSEN') AS "희망 직무 고름",
       count(DISTINCT session_hash) FILTER (WHERE desired_role_status = 'NONE') AS "희망 직무 아직 없음",
       count(DISTINCT session_hash) FILTER (WHERE desired_role_status = 'KEEP_CURRENT') AS "지금 직무 유지",
       count(DISTINCT session_hash) FILTER (WHERE desired_role_status IS NULL) AS "희망 직무 건너뜀",
       count(DISTINCT session_hash) FILTER (WHERE claimed_at IS NOT NULL) AS "로그인으로 연결"
FROM analytics.acq_input i CROSS JOIN params p
WHERE NOT i.internal AND i.created_at >= p.t_from AND i.created_at < p.t_to
GROUP BY 1 ORDER BY 2 DESC;

-- [희망 직무] 학교 × 전공 × 졸업연도 × 희망 직무 ('아직 없음'·'건너뜀'도 한 줄씩)
WITH params AS (
  SELECT (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')) AT TIME ZONE 'Asia/Seoul' AS t_from, now() AS t_to
),
d AS (
  SELECT i.draft_id, i.session_hash, coalesce(i.institution_name, i.institution_raw) AS school,
         coalesce(i.major_label, i.major_raw) AS major, i.graduation_year,
         CASE i.desired_role_status WHEN 'NONE' THEN '(아직 없음)' WHEN 'KEEP_CURRENT' THEN '(지금 직무 유지)'
              WHEN 'UNSURE' THEN '(모르겠음)' ELSE NULL END AS status_label, i.desired_role_status
  FROM analytics.acq_input i CROSS JOIN params p
  WHERE NOT i.internal AND i.created_at >= p.t_from AND i.created_at < p.t_to
)
SELECT d.school AS "학교", d.major AS "전공", d.graduation_year AS "졸업",
       coalesce(r.role_label, r.role_raw, d.status_label, '(건너뜀)') AS "희망 직무",
       r.rank AS "순위", count(DISTINCT d.session_hash) AS "사람 수"
FROM d LEFT JOIN analytics.acq_desired_role r ON r.draft_id = d.draft_id AND d.desired_role_status = 'CHOSEN'
GROUP BY 1, 2, 3, 4, 5 ORDER BY 6 DESC, 1, 2, 3, 5;

-- [표준화 대기] 목록에 없는 학교·전공·희망 직무: 철자가 달라도 같은 이름끼리 묶어 사람 수 순 (전체 기간)
SELECT kind AS "종류", most_typed AS "가장 많이 쓴 이름", people AS "사람 수",
       array_to_string(spellings, ' / ') AS "적힌 철자들", first_seen AS "처음", last_seen AS "마지막"
FROM analytics.acq_unlisted_backlog ORDER BY people DESC, kind, most_typed LIMIT 100;

-- [인터뷰 신청] 숫자만 (번호는 이 파일에서 꺼내지 않습니다). 신청 대상 뽑기는 docs/10 의 안내대로.
SELECT count(*) FILTER (WHERE withdrawn_at IS NULL) AS "신청 중",
       count(*) FILTER (WHERE withdrawn_at IS NULL AND phone_verified_at IS NOT NULL) AS "번호 인증됨",
       count(*) FILTER (WHERE withdrawn_at IS NOT NULL) AS "철회"
FROM interview_contact;
