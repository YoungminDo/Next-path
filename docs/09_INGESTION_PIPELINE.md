# 경력 수집 파이프라인 (Ingestion Pipeline)

> 캡처 → AI JSON → 자동 검증 → 사람 검수 → DB(SEED) → (필요할 때) 엑셀 추출.
> 코드: `apps/api/hellomyme/ingest/` · 마이그레이션 `0022_ingestion_pipeline.py` ·
> 계약: `ingest/career_extraction.v1.schema.json` · 테스트 `tests/test_ingest.py`.
> 기준 템플릿: `HELLOMYME_Career_Ingestion_Template_v2.1` (19시트, 2026-10-08).

## 1. 결정: 엑셀이 아니라 DB가 원본이다 (안 B)

| 안 | 흐름 | 장점 | 단점 |
|---|---|---|---|
| A | 캡처 → 사람이 엑셀 입력 → 업로드 | 도구가 익숙하고 시작이 빠름 | 셀 한 칸에 별칭이 여러 개 들어가는 등 구조가 깨짐. 원본과 수정본을 구분할 수 없음. 같은 사람이 여러 번 들어가기 쉬움 |
| **B (채택)** | 캡처 → AI JSON → 자동 검증 → 필드 검수 → DB → 엑셀은 추출만 | AI 출력 원문, 검수 결정, 근거 스크린샷이 각각 행으로 남음. 같은 입력을 다시 넣어도 결과가 하나 (멱등). 표준화가 별칭으로 쌓임 | 검수 화면이 필요함 (Phase 1에서는 CLI, 다음 단계에서 엑셀 왕복) |
| C | AI 결과를 검수 없이 바로 적재 | 가장 빠름 | 오독이 그대로 통계에 들어감. "unknown = NULL" 원칙과 충돌 |

B를 택한 근거는 세 가지다. 첫째, 프로젝트 원칙(원본 append-only, 모르면 NULL, 멱등 적재)을 엑셀로는
강제할 수 없다. 둘째, 해자 데이터(docs/08)는 시간이 지나며 쌓이는데, 출처를 행 단위로 추적하지 못하면
나중에 출처 하나를 통째로 빼야 할 때(법적 요청 등) 뺄 수 없다. 셋째, 엑셀은 운영팀이 편한
**작업 화면**으로만 쓰면 되고 원본일 필요는 없다.

## 2. 세 가지 질문에 대한 답

### 2.1 원본 보존
- `parse_run.raw_output`: AI 출력 원문. 트리거로 수정을 막는다(`parse_run_output_frozen`).
  다시 파싱하면 새 run이 생기고 이전 run은 `SUPERSEDED`가 된다.
- `extraction_field`: 필드 하나당 한 행. AI가 읽은 값(`raw_value`), 규칙이 만든 값(`normalized_value`/`normalized_ref`),
  사람의 결정(`review_status`, `corrected_value`), 근거 스크린샷과 그 줄(`source_asset_id`, `evidence_text`)을 남긴다.
- `work_event.organization_raw` / `role_raw`: 화면에 보인 글자 그대로 저장한다. 사람이 고치는 것은
  "AI가 잘못 읽은 글자"뿐이고, 표준 이름은 별칭 테이블에만 붙는다.
- `source_record`(SEED, append-only)에는 이름을 `[person_pii]`로 가린 사본을 저장한다.
  실명은 `person_pii`에만 둔다(PII 분리).

### 2.2 표준화: 회사 이름이 제각각인 문제
```
"PepsiCo Korea" / "펩시코리아" / "롯데칠성(펩시)"   →  같은 회사인가?
```
1. 자동 매칭은 결정론적으로만 한다. `normalize_label()`(공백·기호 제거, 소문자) 기준으로
   ① 승인된 매핑 큐 → ② `organization.name` → ③ `organization_alias` 순서로 찾는다.
   직무·전공은 `taxonomy_alias`, 학교는 `institution.name`을 쓴다.
2. 아무것도 맞지 않은 이름은 `mapping_queue`에 들어간다. 정규화한 이름 하나당 한 행이고,
   몇 번 나왔는지(`occurrences`)를 센다. **많이 나온 이름부터** 처리하면 적은 노력으로 커버리지가 가장 크게 오른다.
3. 사람이 `map`(기존 항목에 연결) 또는 `--new`(새 회사·학교 생성)를 하면
   - 별칭이 생겨서 다음 캡처부터는 자동으로 매칭된다.
   - 이미 적재된 행 중 같은 원문을 가진 행에 canonical id만 채운다. 원문은 바꾸지 않고, `normalization_status`만 다시 계산한다.
4. AI가 canonical id를 고르는 일은 **없다**. JSON 스키마가 id 필드를 거부한다(`additionalProperties: false`).
   AI는 읽기만 하고, 연결은 규칙과 사람이 한다.

### 2.3 경력 순서: "첫 직장 · 두 번째 · 현재 · 이후 이동"
- **PERSON 1행, WORK_EVENT N행.** 순서는 저장하지 않는다. 조회할 때 `start_date`로 정한다
  (`domain/career_query.py`, `first_employment_all`).
- 순서를 저장하지 않는 이유: 나중에 경력이 하나 추가되거나 날짜가 고쳐지면 저장된 순번이 모두 틀어진다.
  날짜와 정밀도(`YEAR`/`MONTH`)만 정확하면 순서는 언제든 다시 계산된다.
- 겹치는 기간(사이드 프로젝트, 겸직)은 허용한다. `period` daterange와 `event_type`으로 구분한다.
- 인턴은 `event_type=EMPLOYMENT`, `employment_type=INTERN`으로 저장한다. 그래서 "첫 정규직"과 "첫 경험"을 둘 다 계산할 수 있다.
- 예: 펩시 → 니베아 → 밀리의서재 → 창업은 사람 1명과 이벤트 4개다. 테스트 `test_capture_to_seed_person`이 이 형태를 그대로 검증한다.
  이 구조라야 다음 단계의 **경로 접두(prefix) 지표**를 만들 수 있다. 예를 들어 "2번째 직장까지 나와 비슷한 사람들은 3·4번째에 어디로 갔나"(§7).

## 3. 흐름과 상태

```
캡처 이미지(들) ──► AI 추출 ──► receive() ──► 자동 검증 ─┬─ BLOCK ─► parse_run REJECTED (원문은 보관)
 (한 사람 = 한 submission)        (JSON)                    │
                                                            └─ 통과 ─► extraction_field 생성
                                                                       ├─ 알려진 이름 + 신뢰도 ≥ 0.9 → AUTO_ACCEPTED
                                                                       └─ 모르는 이름 / 낮은 신뢰도 / 분류 불가 → PENDING
                                                                                │  review_field / accept_pending
                                                                                ▼
                                                                  approve() ─► SEED person + education + work_event
                                                                                + *_source(스크린샷·근거 줄)
                                                                                + identity_match 후보(자동 병합 없음)
```

| 테이블 | 상태 |
|---|---|
| `source_submission` | RECEIVED → IN_REVIEW → LOADED / REJECTED / WITHDRAWN |
| `parse_run` | NEEDS_REVIEW / READY → LOADED, 또는 REJECTED / SUPERSEDED |
| `extraction_field` | PENDING → ACCEPTED / CORRECTED / REJECTED (또는 처음부터 AUTO_ACCEPTED) |
| `mapping_queue` | PENDING → APPROVED / NEW_ENTITY / REJECTED |

멱등성:
- 같은 AI 출력(sha256)을 다시 넣으면 같은 run이 반환된다.
- 적재된 run을 다시 `approve`해도 같은 person이 반환된다.
- 같은 사람이 다른 수집자를 통해 두 번 들어오면 `identity_match` **후보**(CANDIDATE)만 생긴다. 판단 기준은 이름과 첫 회사이고, 병합은 사람이 한다.

## 4. 자동 검증 규칙 (`ingest_rules_v1`)

| 심각도 | 코드 | 의미 |
|---|---|---|
| BLOCK | `SCHEMA` | JSON 계약 위반. 필수 필드 누락, canonical id 포함, 근거 없는 레코드 등 |
| BLOCK | `DUPLICATE_LOCAL_ID` | 같은 submission 안에서 local_id가 중복됨 |
| BLOCK | `EVIDENCE_ASSET_UNKNOWN` | 근거가 존재하지 않는 스크린샷을 가리킴 |
| BLOCK | `PRECISION_MISMATCH` | `2019-03`인데 YEAR, 또는 `2019`인데 MONTH |
| BLOCK | `YEAR_OUT_OF_RANGE` | 1950~2100 범위 밖 |
| BLOCK | `END_BEFORE_START` / `START_AFTER_AS_OF` / `CURRENT_WITH_END_DATE` | 날짜 모순 |
| WARN | `MISSING_START` | 시작일 없음. 해당 필드가 PENDING이 되고, 사람이 "모름" 확인 또는 수정 |
| WARN | `EVENT_TYPE_UNKNOWN` | 정규직·창업 등을 판단할 수 없음. PENDING. 그대로 승인하면 `OTHER`로 적재되어 고용 통계에서 빠짐 |
| INFO | `DUPLICATE_EVENT` | 캡처가 겹쳐서 같은 경력(회사+직무+시작일)이 반복됨. 하나만 남김 |

고용형태는 화면에 쓰인 라벨에서만 읽는다(인턴/계약직/파트타임/정규직, 영어·베트남어 포함).
라벨이 없으면 NULL이다. **"정규직일 것"이라고 가정하지 않는다.**

수정값 형식(`review --value`)은 다음과 같다. 형식이 틀리면 거부된다.
- 이름: 화면 글자 그대로
- 날짜: `YYYY` 또는 `YYYY-MM`
- `is_current`: `true`/`false`
- 코드 필드: `EMPLOYMENT`, `INTERN`, `BACHELOR` 등 코드값

## 5. JSON 계약 `career_extraction.v1` (요약 예시)

```json
{
  "schema_version": "career_extraction.v1",
  "submission_id": "VN-2026-10-0001",
  "assets": [{"asset_id": "A1", "page_order": 1}, {"asset_id": "A2", "page_order": 2}],
  "person": {"display_name_raw": "홍길동", "evidence": [{"asset_id": "A1", "text": "홍길동"}]},
  "educations": [{
    "local_id": "E1", "institution_raw": "OO대학교", "major_raw": "경영학과", "degree_raw": "학사",
    "start": {"value": "2014", "precision": "YEAR"}, "end": {"value": "2018", "precision": "YEAR"},
    "evidence": [{"asset_id": "A1", "text": "OO대학교 · 학사, 경영학과 2014 - 2018"}]
  }],
  "work_events": [{
    "local_id": "W1", "organization_raw": "PepsiCo Korea", "role_raw": "Brand Marketer",
    "employment_type_raw": "Full-time", "event_type_hint": "EMPLOYMENT",
    "start": {"value": "2018-03", "precision": "MONTH"}, "end": {"value": "2020-02", "precision": "MONTH"},
    "is_current": false, "confidence": {"organization": 0.97, "role": 0.92},
    "evidence": [{"asset_id": "A1", "text": "Brand Marketer · PepsiCo Korea Full-time Mar 2018 - Feb 2020"}]
  }]
}
```
AI 프롬프트에 넣을 금지 사항(스키마 description에도 있음):
- canonical id를 만들지 않는다.
- "3년 2개월" 같은 기간을 날짜로 바꾸지 않는다.
- 성별·나이를 추정하지 않는다.
- 보이지 않는 값은 키 자체를 넣지 않는다.

## 6. 템플릿 v2.1 시트 → DB

| 시트 | DB | 비고 |
|---|---|---|
| 01_PERSON | `person` (+ `person_pii`) | `member_id`는 ACCOUNT 연결이므로 SEED에서는 비움 (ACCOUNT ≠ PERSON) |
| 02_EDUCATION | `education` + `education_source` | **보완 필요:** `admission_year`, 연도 정밀도 열 추가 (cohort가 입학연도를 씀) |
| 03_WORK_EVENT | `work_event` + `work_event_source` | **보완 필요:** `event_type` 열 추가. `is_parallel`은 저장하지 않음 (기간에서 계산) |
| 04_ORGANIZATION | `organization` + `organization_alias` | `aliases`는 셀 하나에 몰지 말고 별칭 1개당 1행으로 |
| 05_INSTITUTION | `institution` | 별칭은 매핑 큐 승인으로 관리 |
| 06~08 *_TAXONOMY | `taxonomy` / `taxonomy_node` / `taxonomy_alias` | **보완 필요:** taxonomy 버전 열. 부모 변경은 새 버전 + mapping |
| 09_SOURCE | `source_submission` + `source_asset` + `source_record` | submission(사람 1명)과 asset(스크린샷 N장)을 분리 |
| 10_PARSE_JOB | `parse_run` | prompt/schema/rule 버전까지 기록 |
| 11_FIELD_REVIEW | `extraction_field` | 근거 스크린샷과 근거 줄 포함 |
| 12_CONSENT | 기존 consent 테이블 | 가입자(VERIFIED)용. SEED는 `permitted_use`/`legal_basis`로 관리 |
| 13_SNAPSHOT · 14_TRANSITION · 16_SIMILARITY | **입력 아님** | 질의 엔진이 계산하는 결과물. 입력으로 받으면 원본과 계산이 섞임 |
| 15_MENTOR | 기존 mentor 테이블 | **본인 opt-in만.** SEED 인물은 멘토나 사람으로 노출하지 않음 |
| 17_MAPPING_QUEUE | `mapping_queue` | 정규화한 이름 1개당 1행, 등장 횟수 포함 |
| 18_QA_LOG | `parse_run.issues` + 기존 `qa_review` | |

## 7. 운영 명령 (CLI)

```bash
cd apps/api
uv run hellomyme-ingest receive out/VN-0001.json --collector ops-vn-01 \
    --source-type PUBLIC_PROFILE --permitted-use AGGREGATE_ONLY \
    --legal-basis "<법률 검토 후 확정한 근거>" --model <model> --prompt extract_v1
uv run hellomyme-ingest fields <parse_run_id>          # PENDING 먼저
uv run hellomyme-ingest review <field_id> correct --value "브랜드 매니저"
uv run hellomyme-ingest accept-pending <parse_run_id>
uv run hellomyme-ingest approve <parse_run_id>
uv run hellomyme-ingest queue --kind ORGANIZATION      # 많이 나온 이름부터
uv run hellomyme-ingest map <mapping_id> --ref <organization_id>   # 또는 --new "펩시코코리아"
```

## 8. 지켜야 할 것
- SEED는 통계에만 쓴다. 결과 화면에 사람·프로필·멘토로 보여주지 않는다. 연결 대상은 본인이 가입하고 opt-in한 VERIFIED뿐이다.
- 모든 레코드에 `source_type`과 `permitted_use`가 붙는다. 법률 검토 결과에 따라 출처 하나(예: `PUBLIC_PROFILE`)를 통째로 집계에서 빼거나 삭제할 수 있어야 한다.
- 스크린샷 원본은 접근이 통제된 오브젝트 스토리지에 둔다. DB에는 `storage_ref`와 sha256만 저장한다.
- 실명은 `person_pii`에만 저장한다. 그 외에는 동일인 후보를 찾는 데만 쓴다.

## 9. 다음 단계

1. **법률 검토 (적재 전 필수)**
   - **수집 방식:** LinkedIn 사용자 약관 8.2는 자동화 수단(스크래핑, 봇 등)으로 프로필 데이터를 복사하는 것을 금지한다.
     사람이 직접 캡처하더라도 상업적 DB 구축은 약관 위반이 될 수 있다. hiQ v. LinkedIn은 공개 데이터 크롤링에 대해
     CFAA(미국 연방 컴퓨터 사기·남용법) 쟁점으로는 hiQ에 유리한 판단이 있었지만, 최종적으로 hiQ의 약관 위반이 인정되며 종결됐다(2022).
     검토 결과에 따라 `PUBLIC_PROFILE` 대신 **본인이 직접 올린 자료**(`LINKEDIN_USER_UPLOAD`, `CAREER_DOCUMENT`)로 전환할지 결정한다.
   - **공개된 개인정보의 처리 근거:** 개인정보보호법 제15조(수집·이용), 제20조(정보주체가 아닌 곳에서 수집한 경우 출처 통지).
     대법원 2016. 8. 17. 선고 2014다235080(공개된 개인정보는 정보주체가 공개한 목적 범위 안에서 별도 동의 없이 처리할 수 있다는 취지)이
     "진로 통계"라는 목적에도 적용되는지 확인한다.
   - **베트남 운영팀 처리위탁:** 개인정보보호법 제26조에 따라 위탁계약서를 작성하고, 위탁 사실을 공개하며, 수탁자를 교육·감독한다.
   - **국외 이전:** 베트남에서 열람·처리하는 것은 제28조의8 국외 이전에 해당할 수 있다(동의, 고지·공개, 인증 중 하나).
     베트남 쪽 개인정보 규정(Decree 13/2023/ND-CP, 2026년 시행 개인정보보호법)의 적용 여부도 확인한다.
   - 검토가 끝나면 `legal_basis` 문구와 `permitted_use` 값 목록을 확정한다. 확정 전에는 스테이징에만 적재한다.
2. **엑셀 검수 왕복:** PENDING 필드와 매핑 큐를 xlsx로 내보낸다. 운영팀이 결정 열만 채우고, 그 파일을 다시 받아 `review_field`/`resolve_mapping`에 일괄 적용한다(검증은 같은 규칙).
3. **경로 접두 지표(k-step):** "k번째 직장까지 비슷한 사람의 k+1, k+2번째"를 계산한다. CareerQuery에 `PATH_PREFIX` 지표로 추가하고, 소표본 억제는 기존 정책을 그대로 쓴다.
4. **추출 품질 측정:** 정답을 붙인 캡처 50~100건으로 프롬프트·모델 버전별 필드 정확도를 비교한다(`parse_run`에 이미 버전이 기록됨). 자동 승인 기준(0.9)은 이 결과로 조정한다.
5. 스크린샷 업로드와 오브젝트 스토리지 연결(`storage_ref`), 보존 기한, 삭제 요청 처리 절차.

## 출처
- LinkedIn User Agreement §8.2 (Don'ts: 스크래핑·복사 금지) — https://www.linkedin.com/legal/user-agreement
- hiQ Labs v. LinkedIn (9th Cir. 2022, 2022.12 합의 종결) — https://en.wikipedia.org/wiki/HiQ_Labs_v._LinkedIn
- 개인정보 보호법 제15조·제20조·제26조·제28조의8 — https://www.law.go.kr/법령/개인정보보호법
- 대법원 2016. 8. 17. 선고 2014다235080 판결 — https://www.law.go.kr (판례 검색)
- 개인정보보호위원회, 「인공지능(AI) 개발·서비스를 위한 공개된 개인정보 처리 안내서」(2024.7) — https://www.pipc.go.kr
- Vietnam Decree 13/2023/ND-CP on Personal Data Protection — https://thuvienphapluat.vn (Nghị định 13/2023/NĐ-CP)
- JSON Schema 2020-12 — https://json-schema.org/draft/2020-12
