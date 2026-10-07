# Pre-seed v1.2 검증 결과 · Migration 목록 · Blocking 이슈

> Master Prompt v1.3 "Before PR1/PR2, briefly report only" 항목.
> 기준: `HELLOMYME_Project_Package_v1.3.zip` (Architecture v1.3, Pre-seed v1.2 CSV), as-of 2026-10-07.
> 재현: `scripts/profile_preseed.py`, `apps/api/tests/test_real_preseed.py`, `make import-preseed`.

## 1. Pre-seed v1.2 검증 결과: **PASS**

| 체크 | v1.1 (이전) | v1.2 | 결과 |
|---|---|---|---|
| ID 중복 / orphan FK (person·institution·major·org·role·work_event) | 0 | 0 | PASS |
| `end_date < start_date` | 376 | 0 | PASS |
| as-of 이후 시작 이벤트 (현재 재직 포함) | 1,136 (974) | 0 (0) | PASS |
| JOB_SEEKER가 현재 재직 중 | 706 | 0 | PASS |
| 창업자 역할 ≠ STARTUP / 프리랜서 역할 ≠ FREELANCE | 1,617 | 0 / 0 | PASS |
| `is_current` ↔ `end_date` 모순 | 0 | 0 | PASS |
| work_event ↔ work_event_source 1:1, source_ref 일치 | ✓ | ✓ | PASS |
| School+Major cohort < 30 | 162 / 480 | 0 / 480 (41~42명) | PASS |

**실제 import 결과 (개발 DB):** persons 20,000 · education 20,000 · work_events 37,357 · work_event_sources 37,357 · source_records 20,000 · rejected 0 · duplicate 0 · 무결성 체크 7/7 통과 · 재실행 시 `ALREADY_IMPORTED`(변경 0건) · transition_v1 36,241건 (entry 17,086 + 이동 19,155).

**정보성 경고 (blocking 아님)**

| 항목 | 값 | 처리 |
|---|---|---|
| Placeholder 조직("스타트업 A", "공공기관 A", "창업/자영업" 등 12곳)에 속한 이벤트 | 15,485 (41%) | `organization.is_placeholder=true`. 회사명 통계(COMPANY_BREAKDOWN)에서 제외, 산업·규모 통계에는 포함 |
| 병행 이벤트(겹침·다중 current) | 0 | v1.2에는 없음 → parallel 모델은 단위 테스트로 검증 |
| School+Major+졸업년도 cohort | 6,545셀 모두 < 30 (최대 11) | 설계대로 Adaptive Cohort가 Level 1~3으로 fallback |
| School+Major ±2년 window | 6,543셀 < 30 (중앙값 14) | Level 1도 대부분 미달 → 대부분 Level 2(School+Major) 결과 |
| 학생 425명의 졸업 전 EMPLOYMENT(인턴 추정) | 425 | transition_v1의 entry(첫 진로)에서 제외, 이벤트 자체는 보존 |

## 2. 최종 Migration 목록 (Alembic, raw SQL, 모두 up/down 쌍)

| # | Revision | 내용 |
|---|---|---|
| 1 | `0001_taxonomy_provenance` | taxonomy_version, institution, major, organization(`is_placeholder`), role, import_batch(manifest 기반 idempotency), **source_record (append-only trigger)**, entity_key_map, import_issue |
| 2 | `0002_account_person` | account, account_identity(KAKAO/GOOGLE/APPLE/DEV), auth_session, **person (ACCOUNT와 분리)**, person_pii(PII 분리) |
| 3 | `0003_career_core` | education(+raw/normalized), education_source, **work_event (daterange·병행 허용·supersede)**, **work_event_source (supported_fields, 1 event : N source)**, work_event_field_resolution, verification_log(append-only), identity_match(PRE_SEED 차단 trigger), identity_merge_log, canonical_* view |
| 4 | `0004_seed_staging_qa` | collector, collection_batch, seed_staging_record, qa_review (PENDING/APPROVED/NEEDS_FIX/REJECTED) |
| 5 | `0005_cohort_aggregation` | **COHORT_POLICY**, scoring_policy(CAREER_SIMILARITY/MENTOR_RANKING), aggregation_run, career_person_snapshot, career_transition(logic_version), **cohort_result_log (exact_n·effective_n·fallback_level·policy_version)** |
| 6 | `0006_anonymous_draft_consent` | **ANONYMOUS_DRAFT**, **DATA_CONSENT**, EXTERNAL_CONNECTION(token_ref만, 평문 credential 없음), source_record.external_connection_id |
| 7 | `0007_credit_unlock` | **REWARD_POLICY · UNLOCK_POLICY · PRICING_POLICY(Phase 1 비활성)**, **credit_ledger (UPDATE/DELETE/TRUNCATE 금지, reversal만)**, credit_balance view, unlock_event, entitlement |
| 8 | `0008_intent_decision_outcome` | intent_event(BEHAVIORAL/EXPLICIT), decision_event, outcome(Decision 1:N, horizon_months) |
| 9 | `0009_mentor_marketplace` | mentor_profile(opt-in), mentor_offer(12 types, MVP API는 QNA·15_MIN_CHAT만), orders, transaction, platform_fee, payout |
| 10 | `0010_analytics_privacy` | `analytics` schema(event 15종, filter_event) — canonical과 분리, deletion_request, audit_log |

정책 기본값(cohort 30·±2년·K=100·cell 5, 보상/unlock MY)은 migration의 **데이터 행**으로 들어가며, 애플리케이션 코드에는 상수로 존재하지 않습니다.

## 3. Blocking 이슈: **없음**

진행에 영향 없는 문서 정합성 메모 (Architecture v1.3):
- `SELF_SELF_RECONFIRMED` 오타 (README, 05, 08 시트) → `SELF_RECONFIRMED`로 구현.
- `05_QUALITY_PRIVACY`의 verification_level 값이 구버전(`PRE_SEED/OBSERVED/…`) → `08_SOURCE_VERIFICATION` 기준으로 구현.
- `07_MIGRATION_ORDER`에 11번이 없음(10 → 12) → 위 10개 revision으로 통합.

## 4. 구현 중 확정한 설계 판단

| 판단 | 근거 |
|---|---|
| Cohort threshold는 **실제 분석 대상(다음 이동을 한 사람)** 기준으로 적용 | 학교+학과 42명 cohort라도 "현재 직무에서 이동한 사람"은 23명 → membership 기준이면 근거 부족한 수치가 노출됨 |
| Pre-seed source system에 데이터셋 버전 포함(`PRESEED_v1.2`) | v1.1과 v1.2가 같은 `PSP00001`을 다른 인물에 사용 → 버전 없이 결정적 UUID를 만들면 v1.2 인물이 조용히 누락됨 (테스트로 재현·수정) |
| Suppressed insight는 unlock해도 **과금하지 않음** | 표본이 없는 결과에 MY를 받으면 신뢰 훼손 |
| reward idempotency key는 policy version을 **제외**, ledger 행에 version 기록 | 정책 변경 시 같은 기여에 재지급되는 farming 차단 |
| 운영 환경에서 `PRE_SEED` 레이어 또는 `DEV` 로그인 설정 시 **앱 기동 거부** | 결정 Q2, Q6 |
