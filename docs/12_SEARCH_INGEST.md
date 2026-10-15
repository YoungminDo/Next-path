# 검색 반입 (Search Ingest) — 공개 프로필 요약문 → SEED

> 결정(2026-10-15, owner): 검색 엔진(SerpAPI·Brave)이 보여주는 공개 프로필의 제목·요약문을 반입 파이프라인(docs/09)에
> 넣어 **통계 재료(SEED)로만** 쓴다. 결과 화면에 사람·프로필로 보여주지 않는다(docs/09 §8 그대로).
> 회원가입 때 본인이 입력·업로드한 경력(`SELF_REPORTED`, `career_import.py`)은 지금처럼 따로 쌓인다.
> 상태: 구현됨 (마이그레이션 0041, `hellomyme-ingest search-run`, render.yaml `nextpath-search-ingest`).

## 1. 결정 요약

| 질문 | 결정 |
|---|---|
| 어디에 쓰나 | SEED 통계 재료만 (`permitted_use=AGGREGATE_ONLY`). 사람·프로필·멘토로 노출하지 않음 |
| 어디서 돌리나 | Render Cron Job (`nextpath-search-ingest`), API 서버와 같은 Docker 이미지 |
| 검수 | 전부 사람이 한다. 서버는 `receive()`까지만, 승인은 운영자가 기존 CLI로 (docs/09 §7) |
| 검색어 | 운영자 목록 + 수요 기반 자동, 둘 다 |
| 검색 API | SerpAPI(구글)와 Brave를 검색어마다 번갈아 쓰고, 한쪽이 401/403/429면 그 회차의 나머지는 다른 쪽으로 (§5) |
| 원문 보관 | 이름은 저장하지 않음, URL은 키 있는 해시(HMAC)만, 근거 문장·원문 필드의 이름은 `[person_pii]`로 가리거나 필드째 뺌 (§6) |

검색 결과는 링크드인에 접속하지 않고 검색 API의 결과(제목·요약문)만 읽는다.
요약문에서 얼마나 쓸 만한 데이터가 나오는지는 `scripts/linkedin_snippet_yield.py`로 먼저 잴 수 있다.

## 2. 구성 요소

| 단위 | 위치 | 하는 일 |
|---|---|---|
| `snippet.py` | `hellomyme/ingest/` | 검색 결과 1건 → `career_extraction.v1`. 실험 스크립트의 변환 로직을 옮긴다. 근거 문장에서 이름을 가린다 |
| `search_source.py` | `hellomyme/ingest/` | 검색 API 호출만 담당. `serpapi`, `brave` 두 구현이 같은 형태 `(url, title, snippet)`를 돌려준다. 키는 `serpapi_key`, `brave_api_key` |
| `search_plan.py` | `hellomyme/ingest/` | 이번 회차 검색어 고르기 (§4) |
| `search_run.py` | `hellomyme/ingest/` | 회차 실행: 고르기 → 검색 → 변환 → `receive()` → 기록 (§5) |
| CLI `search-run` | `hellomyme/ingest/cli.py` | 크론 진입점. `--dry-run`은 같은 회차를 한 트랜잭션 안에서 돌리고 마지막에 롤백한다(검색은 실제로 하고, 접수·기록은 남지 않음) |
| 크론 서비스 | `render.yaml` | `type: cron`, 매일 03:00 KST (`0 18 * * *` UTC), `hellomyme-ingest search-run` |

## 3. 데이터

### 새 테이블 (마이그레이션 0041, 모두 RLS 켬 — `tests/test_data_api_lock.py`)

| 테이블 | 열 | 메모 |
|---|---|---|
| `search_ingest_policy` | `version`, `status`(ACTIVE/RETIRED), `max_queries_per_run`, `results_per_query`, `requery_after_days`, `demand_lookback_days`, `max_consecutive_errors` | ACTIVE는 하나만. 시드 `search_v1`: 20 / 10 / 30 / 30 / 5 |
| `search_query` | `search_query_id`, `query_text`(UNIQUE), `origin`(OPERATOR/DEMAND), `status`(ACTIVE/PAUSED), `institution_id`, `major_node_id`, `last_run_at`, `created_at` | 운영자 목록과 수요 기반으로 만든 검색어를 같은 곳에 둔다 |
| `search_run` | `search_run_id`, `started_at`, `finished_at`, `status`(RUNNING/DONE/FAILED/SKIPPED), `reason`, `queries`, `results`, `received`, `replayed`, `already_loaded`, `rejected`, `empty`, `errors`, `in_review`(0042), `by_provider` jsonb | 회차 기록. `by_provider`는 검색 API별 `{queries, results, received, failed}`로 어느 쪽 수율이 좋은지 비교한다. 결과 문장은 남기지 않는다 |
| `search_query` 추가 열 | `last_provider` | 다음 회차에 반대쪽부터 시작하도록 |

### 기존 테이블에 들어가는 값

- `source_submission.external_submission_id` = 프로필 키: 정규화한 프로필 slug의 HMAC-SHA256,
  키는 `HELLOMYME_PROFILE_KEY_SECRET` (§7). slug는 이름 모양(`gildong-hong`)이라 키 없는 해시는 이름을
  추측해 맞춰볼 수 있으므로 키를 쓴다. 첫 실제 회차 전에 정하고 바꾸지 않는다(바꾸면 이전 회차와 중복 제거가 끊긴다).
  `UNIQUE (collector_id, external_submission_id)`가 같은 사람을 한 건으로 만든다.
  정보주체가 삭제나 출처 확인을 요청하면, 그 사람의 URL을 같은 키로 해시해서 기록을 찾는다.
- `source_type = 'PUBLIC_PROFILE'`, `permitted_use = 'AGGREGATE_ONLY'`, `legal_basis` = 설정값
  `public_profile_legal_basis`.
- `collector.name = 'search-cron'` 하나로 둔다. 같은 사람이 두 검색 API에서 나와도 URL 해시가 같아
  한 건이 된다.
- `parse_run.model_version` = 그 결과를 준 검색 API (`serpapi-google` / `brave`), `prompt_version = 'snippet_v1'`
  (규칙 기반 변환의 버전).
- 이후는 docs/09 흐름 그대로다: `extraction_field`(검수 대기) → `approve` → SEED `person`·`education`·`work_event`.

## 4. 검색어 고르기 (`search_plan.py`)

1. **운영자 목록:** `search_query`에서 `origin=OPERATOR`, `status=ACTIVE`, `last_run_at`이 없거나
   `requery_after_days`보다 오래된 것을 `last_run_at` 오래된 순(NULL 먼저)으로 고른다.
2. **수요 기반:** 남은 한도만큼 채운다.
   - `analytics.acq_input`에서 `internal = false`, 최근 `demand_lookback_days`일, 학교·학과가 목록에 있는 초안을
     (`institution_id`, `major_node_id`)별로 센다.
   - 그 조합의 SEED+VERIFIED 인원이 활성 `cohort_policy.min_exact_n`에 못 미치는 것만 남긴다.
   - 초안 수가 많은 순으로 `site:linkedin.com/in "<학교명>" "<학과명>"` 검색어를 만들어 `origin=DEMAND`로
     `search_query`에 넣는다(이미 있으면 재사용). 재실행 간격 규칙은 1과 같다.
   - 즉 `plan()`은 읽기만 하지 않는다: 수요 기반 검색어를 `origin=DEMAND` 행으로 기록한다(회차 트랜잭션 안,
     `--dry-run`이면 함께 롤백). 활성 `cohort_policy`가 없으면 수요 기반은 건너뛴다.
3. 희망 직무(`desired_role`) 조합은 2차 범위다. 비교 집단은 학교·학과로 묶이므로 그쪽을 먼저 채운다.

## 5. 회차 흐름 (`search_run.py`)

1. **시작 전 확인.** 하나라도 걸리면 검색하지 않고 `search_run.status=SKIPPED`와 `reason`만 남긴다.
   - ACTIVE `search_ingest_policy` 없음
   - `serpapi_key`와 `brave_api_key`가 둘 다 없음 (하나만 있으면 그쪽만 씀), `public_profile_legal_basis` 없음
   - `env=production`인데 `public_profile_legal_reviewed`가 `true`가 아님
     (엑셀 반입의 `--legal-reviewed`와 같은 원칙, docs/09 §9)
2. **중복 실행 방지.** `pg_try_advisory_xact_lock`(트랜잭션 범위: 회차 트랜잭션이 끝나면 풀림)을 못 잡으면
   SKIPPED (`reason=ALREADY_RUNNING`).
3. **검색어별:** 검색 API 고르기(아래) → 호출 → `linkedin.com/in/` 결과만 → `snippet.to_extraction()` →
   학력도 경력도 없으면 `empty`로 세고 넘어감 → `receive()`.
   **회차 1번 = 트랜잭션 1개, 사람 1명 = 그 안의 savepoint 1개**: 한 사람이 실패하면 그 savepoint만 롤백하고
   나머지는 남는다. CLI가 회차가 끝난 뒤 한 번 커밋한다(`--dry-run`이면 전부 롤백).
   검색어 처리가 끝나면 `search_query.last_run_at`을 갱신한다.
   - **검수 중인 사람은 다시 받지 않는다.** 이 크론이 전에 받은 같은 사람(같은 프로필 키)의 `parse_run`이
     `NEEDS_REVIEW`나 `READY`이면 `receive()`를 부르지 않고 `in_review`+1. 요약문은 검색어·API·날짜마다 조금씩
     달라 해시가 바뀌므로, 그대로 `receive()`하면 검수 중이거나 검수가 끝난 run을 `SUPERSEDED`로 만들어
     검수자의 작업을 버리게 된다(`review_field`는 SUPERSEDED run을 거부한다). LOADED/WITHDRAWN은 그대로
     `receive()`로 가서 `already_loaded`로 센다.
4. **종료.** 집계를 `search_run`에 쓰고 `DONE`. 검색어가 1개 이상인데 하나도 결과 페이지를 받지 못했으면
   (전부 5xx·네트워크 등) `FAILED` (`reason=ALL_QUERIES_FAILED`).

### 검색 API 고르기

- 쓸 수 있는 쪽(키가 있고 이번 회차에 401/403/429가 나지 않은 쪽)을 검색어마다 번갈아 쓴다.
  각 검색어는 `last_provider`의 반대쪽부터 시작한다.
- 한쪽이 401(키 오류), 403(권한·플랜) 또는 429(한도 초과)를 내면 그 회차 동안 그쪽을 빼고, 실패한 검색어는 다른 쪽으로 한 번 다시 보낸다.
- 둘 다 빠지면 회차를 중단한다.

### 오류 처리

| 상황 | 처리 |
|---|---|
| 한쪽 401 / 403 / 429 | 그 회차 동안 그쪽 제외, 다른 쪽으로 계속. `by_provider.<쪽>.failed`에 상태 코드 |
| 양쪽 다 401 / 403 / 429 | 회차 중단, `FAILED`, `reason`에 상태 코드 |
| 검색어 1건 실패 (네트워크, 5xx, 그 밖의 4xx, 예상 밖 응답 모양 등 `SearchError`가 아닌 예외 포함) | `errors`+1, 다음 검색어로 (다른 쪽으로 재시도하지 않음) |
| 모든 검색어 실패 | `FAILED`, `reason=ALL_QUERIES_FAILED` |
| 같은 사람의 이전 run이 `NEEDS_REVIEW`/`READY` | `receive()` 안 함, `in_review`+1 |
| `receive()`가 `IngestError` ("already LOADED/WITHDRAWN") | `already_loaded`+1 |
| `receive()` 결과 `replayed` | `replayed`+1 (같은 요약문을 다시 받음) |
| `receive()` 결과 `REJECTED` | `rejected`+1 |
| 그 밖의 예외 | 그 사람의 savepoint만 롤백, `errors`+1, 예외 클래스 이름만 로그(`logging`, 메시지는 요약문을 담을 수 있어 남기지 않음). 연속 `max_consecutive_errors`회면 회차 중단 `FAILED` |
| `run()` 밖으로 나온 예외 (`plan()` 오류, 0041 미적용 등) | CLI가 회차 트랜잭션 전체를 롤백한 뒤 새 트랜잭션으로 `search_run`에 `FAILED`, `reason=EXCEPTION:<예외 클래스>` 한 줄을 쓰고(메시지 없음, `--dry-run`이면 쓰지 않음) 요약을 출력, 종료 코드 1 |

## 6. 개인정보 처리

- `person.display_name_raw`는 항상 `null`. 이름을 받지 않으므로 `approve` 때 동일인 후보(이름+첫 회사)도 생기지 않는다.
- 제목의 첫 구간(이름)을 근거 문장과 `headline_raw`에서 `[person_pii]`로 바꾼 뒤 `receive()`에 넘긴다.
  `institution_raw`·`organization_raw`·`role_raw`·`major_raw`에 이름이 들어 있으면 그 필드를 뺀다(학교는 그 학력
  행째, 회사는 직무도 없으면 그 경력 행째). 라벨(`학력:`) 없는 학교는 학교 이름 자체(한글 한 토큰 + 대학교/대학, 또는
  대문자로 시작하는 영단어 3개까지 + University/College)만 읽고 앞의 말("홍길동님의 프로필 보기", "LinkedIn")은 읽지
  않는다. 근거 문장은 그 이름부터 그것에 붙인 날짜·전공까지만 인용하므로, 요약문의 다른 사람 이름은 남지 않는다.
  제목 끝의 `- LinkedIn` 구간은 회사로 읽지 않는다. `parse_run.raw_output`은
  수정할 수 없는 원본이므로 이 단계가 이름이 남지 않게 하는 유일한 지점이다.
- 프로필 URL은 키 있는 해시(HMAC)만 저장한다. 로그(`search_run`, stdout)에는 검색어와 개수, 실패한 예외의 클래스 이름만 남긴다.
- 검수자가 보는 근거는 가려진 요약문이다. 원문 프로필은 시스템이 열지 않는다.
- 법률 검토 항목(처리 근거·출처 통지, docs/09 §9)은 그대로 적용된다.
- **수집 시작 시점 (owner 결정, 2026-10-16):** 법률 검토 전이라도 운영 DB에서 수집을 시작한다. 현재 운영
  서비스는 `HELLOMYME_ENV=staging`으로 돌고 크론도 같은 DB를 쓰므로, `public_profile_legal_reviewed` 게이트는
  `production`에서만 막는다(staging은 막지 않음). 들어온 사람은 모두 검수 대기(PENDING)로만 쌓이고, 운영자가
  `approve` 하기 전에는 SEED·통계에 들어가지 않는다. 검토 결과에 따라 `collector='search-cron'` 출처를 통째로
  빼거나 지울 수 있다(docs/09 §8).

## 7. 설정

| 설정 (`hellomyme/config.py`) | 환경변수 | Render |
|---|---|---|
| `serpapi_key` | `HELLOMYME_SERPAPI_KEY` | 크론 서비스, `sync: false` |
| `brave_api_key` | `HELLOMYME_BRAVE_API_KEY` | 크론 서비스, `sync: false` |
| `public_profile_legal_basis` | `HELLOMYME_PUBLIC_PROFILE_LEGAL_BASIS` | 크론 서비스, `sync: false` |
| `public_profile_legal_reviewed` | `HELLOMYME_PUBLIC_PROFILE_LEGAL_REVIEWED` | 기본 `false` |
| `profile_key_secret` | `HELLOMYME_PROFILE_KEY_SECRET` | 크론 서비스, `sync: false`. staging/production에서 검색 API 키가 있으면 개발용 기본값을 거부 (§3) |

크론 서비스는 `HELLOMYME_ENV`, `HELLOMYME_DATABASE_URL`을 API 서비스와 같은 값으로 쓴다.

**크론을 production으로 바꿀 때** (`HELLOMYME_ENV=production`) 함께 넣어야 하는 것:

- `HELLOMYME_AUTH_PROVIDERS`, `HELLOMYME_CAREER_MAP_DATA_LAYERS`: API 서비스와 같은 production 유효값. 기본값(`DEV`,
  `PRE_SEED` 포함)이면 설정 검증(`_guard_production`)에서 크론이 시작하자마자 멈춘다.
- `HELLOMYME_PUBLIC_PROFILE_LEGAL_REVIEWED=true`: 법률 검토(docs/09 §9)가 끝난 뒤에만. 없으면 매 회차 SKIPPED
  (`LEGAL_REVIEW_PENDING`).
- `HELLOMYME_PROFILE_KEY_SECRET`: staging에서 쓰던 값 그대로 (바꾸면 중복 제거가 끊긴다).

**크론은 마이그레이션을 돌리지 않는다.** API 서비스 배포가 먼저 마이그레이션(0041, 0042)을 적용해야 한다. 적용 전에
크론이 돌면 `EXCEPTION:<클래스>`로 실패하고(테이블이 없으면 그 FAILED 행도 못 쓰고 출력에만 남는다) 종료 코드 1.

## 8. 테스트

| 파일 | 확인 |
|---|---|
| `tests/test_snippet.py` (DB 불필요) | 변환 결과가 `check()`를 통과. 이름 바로 뒤(사이에 다른 회사·학교 없음)의 날짜만 붙고, 실제 월 이름에서만 월을 읽음. 이름이 근거 문장·원문 필드·headline 어디에도 없음(검토 재현 사례 포함), 라벨 없는 학교는 학교 이름만. 프로필 키는 HMAC. 빈 결과 판정 |
| `tests/test_search_plan.py` | 운영자 목록 우선, 재실행 간격 적용, 수요 기반은 "초안 많고 인원 부족" 순, 내부 초안 제외 |
| `tests/test_search_run.py` | 가짜 검색 API 두 개로 회차 전체: 번갈아 쓰기, 한쪽 429면 나머지는 다른 쪽(실패 검색어 재시도 포함), 양쪽 401이면 중단, 두 API에서 같은 프로필이 와도 한 건, `already_loaded` 집계, 한 명 실패해도 나머지 접수, production + 미검토면 SKIPPED, 동시 실행 하나만, 검수 중인 사람은 `in_review`(SUPERSEDED 없음), 모든 검색어 실패면 `ALL_QUERIES_FAILED`, 예상 밖 예외는 그 검색어만 실패, 실패한 사람은 클래스 이름만 로그, CLI는 크래시를 `EXCEPTION:<클래스>` FAILED 행으로 남기고 종료 코드 1 |
| `tests/test_data_api_lock.py` (기존) | 새 테이블 RLS |

실제 검색 API는 테스트에서 부르지 않는다. 배포 후 Render에서 `search-run --dry-run`을 한 번 돌려 집계만 확인한다.

## 9. 범위 밖 (이번에 하지 않음)

- 결과 화면에 프로필·링크 노출 (docs/09 §8과 충돌)
- 자동 승인 (검수는 사람이 함, §1)
- 희망 직무 조합 검색어 (§4.3)
- 회사 이름 매칭 개선: 기존 `mapping_queue`가 맡는다
- 검색 API 사용량·비용 대시보드: `search_run.by_provider` 집계로 대신한다
