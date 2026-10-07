# Pre-seed v1.3 패키지 규격 (제품 오너 제공)

> 결정(2026-10-07): Pre-seed v1.3 데이터와 직무·산업·전공 분류 체계는 **제품 오너가 직접 제공**한다.
> 이 문서는 importer가 그대로 읽을 수 있는 형식이다. 이 형식이면 별도 변환 없이 import·검증된다.
> 모든 파일: UTF-8(BOM 허용) CSV, 첫 줄 헤더, 빈 칸 = 값 없음(NULL). 값을 추측해서 채우지 않는다.

## 파일 목록

| 파일 | 필수 | 내용 |
|---|---|---|
| `manifest.csv` | ✅ | 데이터셋 메타 (key,value) |
| `taxonomy_nodes.csv` | ✅ | ROLE / INDUSTRY / MAJOR 분류 트리 |
| `taxonomy_aliases.csv` | 권장 | 원문 표기 → 분류 노드 별칭 |
| `product_taxonomy_views.csv` | ✅ | 화면별 기본 분류 깊이 |
| `institutions.csv` | ✅ | 학교 |
| `organizations.csv` | ✅ | 회사(조직) |
| `organization_industries.csv` | ✅ | 회사 ↔ 산업 분류 (복수 가능) |
| `persons.csv` | ✅ | 인물 |
| `educations.csv` | ✅ | 학력 (1인 N건) |
| `work_events.csv` | ✅ | 경력 이벤트 |
| `work_event_sources.csv` | ✅ | 경력 근거 (v1.2와 동일) |

## 1. manifest.csv
`key,value` — `dataset_version`(예: `v1.3`), `as_of_date`(예: `2026-12-31`), `taxonomy_version`(예: `tax_2026_1`), `description`

## 2. taxonomy_nodes.csv

| 컬럼 | 예 | 규칙 |
|---|---|---|
| taxonomy_type | `ROLE` | `ROLE` / `INDUSTRY` / `MAJOR` |
| code | `ROLE.MKT.BRAND.BM` | 분류 안에서 유일·불변. 이름이 바뀌어도 code는 유지 |
| parent_code | `ROLE.MKT.BRAND` | 최상위는 비움. 같은 taxonomy_type 안의 code여야 함 |
| canonical_name | `브랜드 마케팅` | 정식 명칭 |
| display_name | `브랜드 마케팅` | 화면 표시명 (비우면 canonical_name) |
| sort_order | `10` | 같은 부모 안 정렬 |

- 깊이는 제한 없음(3단계 이상 가능). `depth` 컬럼은 넣지 않는다 — 부모 관계로 계산한다.
- 예시 트리: `마케팅(ROLE.MKT) → 브랜드·콘텐츠(ROLE.MKT.BRAND) → 브랜드 마케팅(ROLE.MKT.BRAND.BM)`

## 3. taxonomy_aliases.csv
`taxonomy_type, code, alias_text, locale` — 예: `ROLE, ROLE.MKT.BRAND.BM, 브랜드마케터, ko`
work_events의 `raw_role_title`, educations의 `raw_major_name` 이 code 없이 들어올 때 이 표로 매핑한다.

## 4. product_taxonomy_views.csv
`surface_code, taxonomy_type, default_depth, min_depth, max_depth` — 예: `ACQUISITION, ROLE, 2, 1, 3`
(depth는 최상위 = 1)

## 5. institutions.csv (v1.2와 동일)
`institution_id, institution_name, region, institution_type`

## 6. organizations.csv

| 컬럼 | 규칙 |
|---|---|
| organization_id | 유일 |
| organization_name | 회사명. "스타트업 A"처럼 실존 회사가 아닌 묶음은 `organization_type=PLACEHOLDER` |
| organization_type | `COMPANY` / `PUBLIC_INSTITUTION` / `NONPROFIT` / `SELF` / `PLACEHOLDER` |
| company_size_band | `MICRO` / `SMALL` / `MID` / `LARGE` / `ENTERPRISE` / 빈칸 |
| company_stage, ownership_type, listed_status, country_code, b2b_b2c_type, founded_year | 선택 |

## 7. organization_industries.csv
`organization_id, industry_code, is_primary(True/False)` — 회사마다 primary 1개 필수, 추가 산업 선택.

## 8. persons.csv

| 컬럼 | 규칙 |
|---|---|
| person_id | 유일 |
| user_stage | `STUDENT` / `JOB_SEEKER` / `PROFESSIONAL` |
| gender_code | `MALE` / `FEMALE` / `OTHER` / `UNDISCLOSED` / `UNKNOWN`. **UNKNOWN과 UNDISCLOSED 둘 다 일부 포함** |
| reported_first_employment_year | 선택. 경력 이벤트 없이 "첫 취업 연도"만 아는 인물에만 |
| data_layer, source_ref, source_type | `PRE_SEED`, 고유 ref, `PRE_SEED_FILE` |

## 9. educations.csv

| 컬럼 | 규칙 |
|---|---|
| education_id, person_id, institution_id | |
| raw_major_name | 원문 전공명 (필수) |
| major_code | MAJOR 분류의 code. 비우면 alias로 매핑 시도 |
| education_role | `MAJOR` / `DOUBLE_MAJOR` / `MINOR` (복수전공은 행을 추가) |
| degree_type | `BACHELOR` / `MASTER` / … |
| admission_year | 선택 (일부 비움) |
| graduation_year | 선택 (일부 비움; 재학생은 예정 연도) |
| data_layer, source_ref, source_type | |

## 10. work_events.csv

| 컬럼 | 규칙 |
|---|---|
| work_event_id, person_id, event_type | event_type은 v1.2와 동일 10종 |
| organization_id | |
| raw_role_title | 원문 직무명 (필수) |
| role_code | ROLE 분류 code. 비우면 alias로 매핑 시도 |
| employment_type | `FULL_TIME` / `PART_TIME` / `CONTRACT` / `INTERN` / `UNKNOWN` |
| start_date, end_date, is_current | v1.2와 동일 규칙 (YYYY-MM-DD, 현재 재직이면 end_date 비움) |
| data_layer, source_ref, source_type | |

## 11. work_event_sources.csv
v1.2와 동일. `supported_fields`에 `role_code`, `employment_type`도 쓸 수 있다.

## 엔진 검증을 위해 꼭 들어가야 하는 것

- **기간:** as_of_date 기준 10년 이상 이력 → 최근 1/3/5/10년 창이 모두 채워짐
- **획득 결과:** 학교+전공별로 ACQUISITION 기본 깊이(예: 직무 중분류) 첫 직무 cohort가 대부분 30명 이상
- **일부러 희소한 칸:** 입학년도·성별 필터를 걸면 30명 미만이 되는 조합 → fallback 단계별 테스트용
- **첫 취업 규칙 테스트:** 졸업 전 인턴(employment_type=INTERN), 첫 이벤트가 창업/프리랜서인 인물, `reported_first_employment_year`만 있는 인물
- **분류 매핑 테스트:** code 없이 `raw_role_title` / `raw_major_name`만 있는 행 일부 + 대응 alias
- **성별:** UNKNOWN, UNDISCLOSED 포함

## import 시 자동 검증 항목
분류 무결성(순환·고아 노드·중복 code) · 원문→분류 매핑률과 미매핑 목록 · 입학≤졸업, 재학 기간 2~8년 ·
첫 취업 도출(이벤트/신고값/없음 건수, 인턴 제외 확인) · 날짜 무결성(v1.2 규칙) ·
1/3/5/10년 창별 cohort 크기 · 획득 화면 기본 깊이 직무 cohort 크기(학교+전공별 최소/중앙값/30명 이상 비율)
