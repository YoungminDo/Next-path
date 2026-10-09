# 경력 수집 파이프라인 (Ingestion Pipeline)

> **입력 표준은 수집 엑셀(템플릿 v2.1)이다** (2026-10-09 결정: 운영팀이 엑셀로 데이터화해서 올리고,
> 시스템은 그 기준으로 받는다). 엑셀 → 시트 검증 → 사람 단위 자동 검증 → (검수 대기만 보류) → DB(SEED).
> 캡처 → AI JSON 경로는 같은 파이프라인의 두 번째 입구로 남겨 둔다.
> 코드: `apps/api/hellomyme/ingest/` (`sheet.py` 엑셀, `pipeline.py` 공통) · 마이그레이션 `0022`, `0023` ·
> 계약: `ingest/career_extraction.v1.schema.json` · 테스트 `tests/test_ingest.py`, `tests/test_ingest_sheet.py`.
> 기준 템플릿: `HELLOMYME_Career_Ingestion_Template_v2.1` (19시트, 2026-10-08). 엑셀 규칙은 §10.

## 1. 결정: 엑셀은 입력 표준, 기록의 원본은 DB (안 B)

| 안 | 흐름 | 장점 | 단점 |
|---|---|---|---|
| A | 캡처 → 사람이 엑셀 입력 → 업로드 | 도구가 익숙하고 시작이 빠름 | 셀 한 칸에 별칭이 여러 개 들어가는 등 구조가 깨짐. 원본과 수정본을 구분할 수 없음. 같은 사람이 여러 번 들어가기 쉬움 |
| **B (채택)** | 캡처 → AI JSON → 자동 검증 → 필드 검수 → DB → 엑셀은 추출만 | AI 출력 원문, 검수 결정, 근거 스크린샷이 각각 행으로 남음. 같은 입력을 다시 넣어도 결과가 하나 (멱등). 표준화가 별칭으로 쌓임 | 검수 화면이 필요함 (Phase 1에서는 CLI, 다음 단계에서 엑셀 왕복) |
| C | AI 결과를 검수 없이 바로 적재 | 가장 빠름 | 오독이 그대로 통계에 들어감. "unknown = NULL" 원칙과 충돌 |

2026-10-09 보완: 운영팀이 엑셀로 데이터화해서 올리기로 했다. 그래서 엑셀이 **입력 표준**이 된다.
다만 A의 단점은 적재기가 막는다. 시트와 행 단위로 검증하고, 사람 단위로 멱등 처리하며, 검수 상태를 따른다.
표준화는 별칭과 매핑 대기열로 하고, 각 사람의 원본 행은 그대로 보관한다(§10).

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

## 6. 템플릿 v2.1 시트 → DB (구현됨)

| 시트 | DB | 적재 방식 |
|---|---|---|
| 01_PERSON | `person` (SEED) | 1행 = 1명 = 1 submission. `career_stage` → `declared_stage`. `record_status`가 demo/test/excluded면 건너뜀. `member_id`는 쓰지 않음 (ACCOUNT ≠ PERSON) |
| 02_EDUCATION | `education` + `education_source` | 원문 학교·전공 보존. `institution_id`/`major_id`는 05/08 시트로 연결. 졸업예정·재학·중퇴는 졸업연도를 넣지 않음 |
| 03_WORK_EVENT | `work_event` + `work_event_source` | 원문 회사·직무 보존. `employment_type`으로 경력 유형과 고용형태를 함께 판정. `is_parallel`·`industry_id`는 저장하지 않음 (계산값, 회사 속성) |
| 04_ORGANIZATION | `organization` + `organization_alias` (+ `organization_industry`) | 이름·별칭으로 기존 회사를 찾고, 없으면 새로 만듦. 별칭은 `,` `;` `|` 줄바꿈으로 구분 |
| 05_INSTITUTION | `institution` + `institution_alias` (0023) | 04와 같음 |
| 06·07·08 *_TAXONOMY | 기존 분류표에 **연결만** + `taxonomy_alias` | 분류표 자체는 만들지 않음 (제품 분류표는 하나). 못 찾은 직무·전공은 매핑 대기열로 |
| 09_SOURCE | `source_submission` + `source_asset` | `source_type`·`permitted_use` 필수. `storage_ref` 보존 |
| 12_CONSENT | `source_submission.legal_basis` | 동의가 있으면 `CONSENT:목적:버전`이 근거. 철회·거부면 적재하지 않음 |
| 15_MENTOR | 사용 안 함 | SEED는 멘토로 노출하지 않음. 멘토는 가입 후 본인 opt-in |
| 13·14·16 | **입력 아님** | 질의 엔진이 계산하는 결과물 |
| 10·11·17·18 | 반영 안 함 | 작업 기록. 각 사람의 원본 행은 parse run에 그대로 보관 |

## 7. 운영 명령 (CLI)

엑셀(주 경로). PowerShell 한 줄로 실행하면 미리보기 → 리포트 확인 → y 입력 → 적재 순서로 진행된다.
```powershell
irm https://raw.githubusercontent.com/YoungminDo/Next-path/main/scripts/ingest-sheet.ps1 | iex
```
```bash
cd apps/api
uv run hellomyme-ingest sheet 수집.xlsx --dry-run --legal-basis "..."   # 저장 없이 리포트만
uv run hellomyme-ingest sheet 수집.xlsx --legal-basis "..."             # 적재 + 리포트(xlsx)
#   --accept-unreviewed  review_status가 비었거나 pending인 행도 올린 사람이 검수한 것으로 처리
#   --collector NAME     업로드할 때마다 같은 이름을 써야 다시 올려도 중복이 생기지 않음 (기본 workbook)
#   운영(production) 환경에서는 --legal-reviewed 없이는 적재하지 않음
```
AI JSON 경로:
```bash
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
2. **적재 후 수정:** 이미 적재된 사람의 행이 바뀌면 지금은 `LOADED_CHANGED`로 알리기만 한다.
   바뀐 행을 새 이벤트로 넣고 기존 행은 `supersedes_*`로 대체하는 방식으로 연결한다(덮어쓰지 않음).
3. **동의 철회 후 삭제:** 이미 적재된 사람의 동의가 철회되면 지금은 `WITHDRAWN_AFTER_LOAD`로 알린다.
   erasure 모드로 삭제하는 절차와 명령을 만든다.
4. **표준화 대기열 엑셀 왕복:** 리포트의 `표준화 대기` 시트에 연결할 대상 열을 채워 다시 올리면 `resolve_mapping`에 일괄 적용한다.
5. **경로 접두 지표(k-step):** "k번째 직장까지 비슷한 사람의 k+1, k+2번째"를 계산한다. CareerQuery에 `PATH_PREFIX` 지표로 추가하고, 소표본 억제는 기존 정책을 그대로 쓴다.
6. **추출 품질 측정 (AI 경로를 쓸 때):** 정답을 붙인 캡처 50~100건으로 프롬프트·모델 버전별 필드 정확도를 비교한다(`parse_run`에 이미 버전이 기록됨). 자동 승인 기준(0.9)은 이 결과로 조정한다.
7. 스크린샷 업로드와 오브젝트 스토리지 연결(`storage_ref`), 보존 기한(`retention_until`) 집행.

## 10. 엑셀 입력 표준 (템플릿 v2.1 그대로)

열 이름은 템플릿과 같아야 한다. 대소문자와 앞뒤 공백은 무시한다. 시트 이름은 번호를 빼고 비교한다
(`01_PERSON`과 `PERSON` 모두 인식). 값은 한글과 영어를 모두 받는다.

**필수:** `01_PERSON.person_id`, `02/03.person_id`·`source_id`, `09_SOURCE.source_id`·`person_id`·`source_type`·`permitted_use`.
이 열이 없으면 파일 전체를 적재하지 않는다(`MISSING_COLUMN`).

| 열 | 받는 값 | 결과 |
|---|---|---|
| `employment_type` | employee·직원 / full_time·정규직 / intern·인턴 / contract·계약직 / part_time·파트타임 / freelance·프리랜서 / founder·창업 / self_employed·자영업 / side_business·부업 / military·군복무 / career_break·휴직 / study·학업 / project / other | 경력 유형 + 고용형태. employee는 고용형태를 비워 둔다(정규직이라고 가정하지 않음). 비어 있으면 **검수 대기** |
| `start_value`·`end_value` | `2018`, `2018-03`, `2018.3`, `2018년 3월`, 엑셀 날짜 | 함께 적힌 `*_precision`(year/month)을 따른다. 정밀도가 비어 있으면 값에서 판단하고, 월을 지어내지 않는다 |
| `is_current` | TRUE/FALSE, Y/N, 예/아니오, 현재 | 못 읽으면 비워 두고 경고 |
| `degree_level` | bachelor·학사 / master·석사 / doctorate·박사 / associate·전문학사 / other | |
| `graduation_status` | graduated·졸업 (또는 비움) / expected·졸업예정·재학·휴학·중퇴 | 졸업이 아니면 졸업연도를 넣지 않음 |
| `admission_year` (선택 열) | `2014` | 있으면 입학연도로 넣음. **추가 권장:** 입학연도 기준 비교가 가능해짐 |
| `event_type` (선택 열) | 위 유형 코드 | 있으면 `employment_type`보다 우선. 고용형태는 `employment_type`에서 읽음 |
| `review_status` | approved·검수완료·승인 → 적재 / pending·비움 → **대기** / rejected·삭제 → 제외 | 대기 행이 하나라도 있으면 그 사람은 보류. `--accept-unreviewed`를 주면 올린 사람이 검수한 것으로 처리 |
| `source_type` | linkedin_capture·링크드인 → PUBLIC_PROFILE / linkedin_upload → LINKEDIN_USER_UPLOAD / resume·이력서·self_submitted·직접제출 → CAREER_DOCUMENT / manual → MANUAL_RESEARCH | 모르는 값이면 그 사람은 막힘. 한 사람에게 출처가 여러 개면 가장 엄격한 것(PUBLIC_PROFILE 우선)을 쓴다 |
| `12_CONSENT.granted`·`withdrawn_at` | TRUE + 철회일 없음 | 동의가 법적 근거가 됨. 철회·거부면 적재하지 않음(적재된 뒤라면 `WITHDRAWN_AFTER_LOAD`) |
| `aliases` (04~08) | `인제스트(주), Ingest Co.` | 별칭이 쌓여 다음 파일부터 자동으로 표준화됨 |

**적재 단위와 다시 올리기**
- 사람 1명 = 1 submission(`person_id`).
- 내용이 같으면 `이미 적재됨`이 나오고 아무것도 바뀌지 않는다.
- 검수 대기였던 사람은 상태를 바꿔 다시 올리면 적재된다.
- 시트 오류는 **그 사람만** 막고, 다른 사람은 그대로 진행한다.

**리포트** (`<파일명>_미리보기.xlsx` / `_적재결과.xlsx`)
- `요약`
- `사람별 결과`: 적재됨, 검수 대기, 거부, 건너뜀, 동의 철회
- `고칠 것`: 심각도, 시트, **엑셀 행 번호**, ID, 설명
- `표준화 대기`: 연결되지 않은 이름과 등장 횟수

## 출처
- LinkedIn User Agreement §8.2 (Don'ts: 스크래핑·복사 금지) — https://www.linkedin.com/legal/user-agreement
- hiQ Labs v. LinkedIn (9th Cir. 2022, 2022.12 합의 종결) — https://en.wikipedia.org/wiki/HiQ_Labs_v._LinkedIn
- 개인정보 보호법 제15조·제20조·제26조·제28조의8 — https://www.law.go.kr/법령/개인정보보호법
- 대법원 2016. 8. 17. 선고 2014다235080 판결 — https://www.law.go.kr (판례 검색)
- 개인정보보호위원회, 「인공지능(AI) 개발·서비스를 위한 공개된 개인정보 처리 안내서」(2024.7) — https://www.pipc.go.kr
- Vietnam Decree 13/2023/ND-CP on Personal Data Protection — https://thuvienphapluat.vn (Nghị định 13/2023/NĐ-CP)
- JSON Schema 2020-12 — https://json-schema.org/draft/2020-12
