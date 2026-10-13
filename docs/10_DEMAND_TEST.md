# 수요 테스트 운영 (2026-10-12~)

> 질문: 학교 정보를 넣는 사람이 얼마나 되고, 결과를 얼마나 깊이 보는가.
> 사이트: https://nextpath.da-sh.io · 데이터: 베타(결과는 예시 데이터로 계산). 결과 화면에는 베타 문구를 두지 않는다
> (대표 결정 2026-10-13). 랜딩 FAQ("지금은 베타라서 … 예시 데이터로 계산")와 랜딩 하단 문구는 그대로 둔다.

## 시작 전 체크
1. **실제 카카오 로그인 1회 완료**(팀원 휴대폰): 랜딩 → 학교 입력 → 카카오 → 결과까지.
   - 외부 점검 결과, 카카오 로그인 화면으로 넘어가는 단계까지는 정상이다.
   - 로그인 완료는 사람만 확인할 수 있다.
2. 팀원 브라우저는 `https://nextpath.da-sh.io/?internal=1` 로 한 번 연다. 그 브라우저의 이벤트는 통계에서 빠진다(`?internal=0` 으로 해제).
3. 채널별 링크에 utm 을 붙인다. 예: `https://nextpath.da-sh.io/?utm_source=instagram&utm_medium=dm&utm_campaign=reels1012`
   (첫 방문 채널이 로그인 뒤까지 이어져 기록된다). utm 이 없어도 인앱 브라우저(instagram, threads,
   facebook, kakaotalk, naver, line)는 `in_app` 으로 따로 남는다. 인스타 앱 안에서는 로그인 화면에
   "외부 브라우저로 열기" 안내가 뜬다.
4. 링크 미리보기: `og.png`(1200×630)와 제목·설명이 DM·게시물 카드로 보인다.

## 무엇을 기록하나 (`analytics.event`, 익명 세션 단위, 이름·연락처 없음)
| 이벤트 | 시점 |
|---|---|
| `landing_viewed` | 랜딩 표시 |
| `career_input_started` | 첫 입력(랜딩 폼 또는 /start) |
| `school_requested` | 목록에 없는 학교·전공을 직접 입력 (중간에 떠나도 남음) |
| `career_input_completed` | 학교·전공·학번 저장 (학교명·학과명, 목록 안/밖 포함) |
| `login_wall_viewed` | 미리보기(몇 명·몇 갈래) 표시 |
| `login_clicked` → `signup_completed` | 카카오 버튼 → 로그인 완료 |
| `result_step_viewed` / `result_left` | 결과 화면별 진입과 머문 시간 |
| `intent_selected` · `unlock_purchased` | 궁금한 길 선택 · 깊은 분석 열기 |

## 팀 대시보드 (/admin)
- 주소: `https://nextpath.da-sh.io/admin` → 카카오로 로그인. 처음에는 "볼 수 없는 계정"과 함께 **계정 번호**가 보인다.
- 권한 주기: Render → nextpath-api → Environment 에 `HELLOMYME_ADMIN_ACCOUNT_IDS` 를 JSON 목록으로 넣고 저장한다.
  예: `["<내 계정 번호>", "<다른 팀원 계정 번호>"]`. 저장하면 다시 배포되고(수 분), 그 뒤 새로고침하면 보인다.
- 보이는 것: 기간(오늘/7일/30일/전체)·팀 기록 포함 여부, 핵심 숫자, 퍼널, 날짜별 추이, 입력한 학교·전공·조합,
  희망 직무, 채널, 결과 화면 체류 시간, 표준화 대기 이름, 인터뷰 신청 수. 숫자만 보여 주고 전화번호·세션 id는 내보내지 않는다.
- 차트마다 "표로 보기"가 있다. 정의는 아래 `funnel.sql`과 같다(서버 `domain/admin_stats.py`).

## 숫자 보는 법
- 시각은 서버가 받은 시각(`received_at`) 기준이다. 사용자 기기의 시계가 틀려도 날짜가 밀리지 않는다.
- **Supabase SQL Editor**에 `scripts/funnel.sql`을 붙여넣고 실행한다.
  - 결과: 퍼널, 채널별, 결과 화면 체류 시간, 입력된 학교·학과, 학교×학과 조합, 목록 밖 입력.
- 사람 수는 단계별 고유 세션 수다. 각 단계를 따로 세기 때문에 직접 /start 로 들어온 사람은 랜딩을 거치지 않는다.
  그래서 "이전 단계 대비"가 100%를 넘을 수 있다.

## 판단에 쓸 핵심 비율
1. 랜딩 → 입력 완료: 첫 제안("학교만 고르면")이 끌리는가
2. 미리보기 → 로그인 완료: 로그인 벽을 넘을 만큼 궁금한가
3. 첫 결과 → 궁금한 길 고름 → 경로 결과: 결과를 끝까지 보는가 (체류 시간 중앙값과 함께)
4. 목록 밖 입력 비율과 이름: 다음에 데이터를 모을 학교·학과 우선순위

## 입력은 전부 DB에 남는다 (migration 0026)
가입 여부와 관계없이, 화면에서 입력한 내용은 저장할 때마다 서버 DB에 남는다. 이벤트가 끊겨도 입력은 남는다.

| 무엇 | 어디 |
|---|---|
| 최신 입력 (학교·전공 id 또는 입력한 이름, 학번, 직장인 직무·회사·입사 연도, 희망 직무) | `anonymous_draft.payload_json` |
| 수정 이력 (덮어쓰지 않음, append-only) | `anonymous_draft_revision` (draft_id, revision) |
| 팀 브라우저 표시 | `anonymous_draft.internal` (`?internal=1`) |
| 로그인 연결 | `anonymous_draft.claimed_account_id / claimed_person_id / claimed_at` |
| 동의 (항목·문구 버전·시각) | `data_consent` (PRIVACY_PROCESSING, CAREER_DATA_AGGREGATION, `policy_version`, `consented_at`, scope.draft_id) |
| 가입자의 희망 직무 (변경 시 행 추가) | `desired_role` (CHOSEN 1~3순위 / NONE / UNSURE / KEEP_CURRENT) |
| 통계용 뷰 | `analytics.acq_input`, `analytics.acq_desired_role`, `analytics.acq_unlisted_backlog` |

- **목록에 없는 이름:** 입력한 그대로 저장한다. `name_key()`(공백·기호, 대학교/학과 같은 접미사 정리)로 철자만 다른 이름을 묶어,
  `acq_unlisted_backlog`에서 몇 명이 입력했는지 센다. 원문은 바꾸지 않는다.
- **희망 직무:** 질문을 건너뛴 경우(`desired_role_status` NULL)와 "아직 없어요"(`NONE`)를 구분해서 저장한다.
- **로그인:**
  - 처음 가입하면 입력을 회원 기록으로 한 번만 옮긴다.
  - 같은 계정으로 다시 로그인하면 사람(person)을 새로 만들지 않는다. 새 입력은 계정에 연결하고, 희망 직무만 이력에 추가한다.
  - 로그인하지 않은 입력은 어떤 계정에도 연결하지 않는다.
- **퍼널 연결:** 이벤트의 `anonymous_session_id`를 SHA-256 하면 `anonymous_draft.session_id`와 같다.
  계정에는 이벤트를 붙이지 않고, draft의 claimed 열로 연결한다.
- **식별 정보:** 익명 입력에는 IP·UA·이름·연락처를 저장하지 않는다.

## 진로 인터뷰 신청 (migration 0027, 선택)
- **흐름:** 카카오 로그인 직후 한 번 "진로 인터뷰에 참여해 주실래요?" 화면이 나온다.
  - 화면 구성: 휴대전화번호 → (문자 업체 설정 시) 인증번호 → 별도 동의 → 신청.
  - "다음에 할게요"를 누르면 바로 결과로 간다. 건너뛰어도 아무것도 막히지 않는다(개인정보보호법 §16③).
  - 결과 화면 아래에서 나중에 신청하거나, 신청을 취소(번호 즉시 삭제)할 수 있다.
- **동의 문구:** 목적·항목·보유 기간(동의일부터 1년, 철회하면 즉시 삭제)·거부할 권리를 적는다(§15②).
  버전은 `interview_contact_v1`이다(웹 `INTERVIEW_CONSENT_VERSION` 상수와 서버 설정이 같아야 신청된다).
- **삭제:** 1년이 지난 번호와 하루가 지난 인증 기록은 인터뷰 API가 호출될 때마다 지운다. 철회하면 번호와 인증 기록을 바로 지운다.
- **끄기:** `HELLOMYME_INTERVIEW_ENABLED=false`로 두면 초대 화면이 사라지고 새 신청을 받지 않는다(철회는 계속 된다).
  홍보 문자는 이 동의로 보낼 수 없다(정보통신망법 §50, 별도 수신 동의 필요).
- **저장 위치:**
  - `interview_contact`: 계정당 1행. `phone_e164`, `phone_verified_at`, `consent_text_version`, `consented_at`, `withdrawn_at`
  - `data_consent`: `INTERVIEW_CONTACT` 동의와 철회 행
  - `phone_verification`: 번호와 코드는 키를 건 해시로만 저장한다.
- **문자 인증 설정** (Render 환경변수):
  - `HELLOMYME_SMS_PROVIDER=solapi`, `HELLOMYME_SOLAPI_API_KEY`, `HELLOMYME_SOLAPI_API_SECRET`, `HELLOMYME_SMS_SENDER_NUMBER`(등록한 발신번호), `HELLOMYME_PHONE_HASH_SECRET`
  - 설정하지 않으면(`none`) 인증 없이 번호와 동의만 저장한다(`phone_verified_at` NULL).
  - staging·production에서 문자를 보내려면 `HELLOMYME_PHONE_HASH_SECRET`이 필요하다(없으면 API가 기동을 거부한다). `log` 방식은 개발 환경에서만 쓸 수 있다.
  - 인증 규칙: 6자리, 3분 만료, 5회까지 입력, 30초 재요청 간격, 번호·계정당 시간당 5회, 하루 10회.
- **보상 문구:** `HELLOMYME_INTERVIEW_REWARD_TEXT`를 설정했을 때만 화면에 보인다. 보상이 정해지기 전에는 약속하지 않는다.
- **인터뷰 대상 뽑기:**
  - Supabase SQL Editor에서 `interview_contact`(withdrawn_at IS NULL) → account → `person` / `canonical_education` / `desired_role`을 조인한다.
  - 번호를 내려받은 파일은 공유 드라이브에 두지 않고, 인터뷰가 끝나면 1년 안에 지운다.

## 이력서·캡처로 시작 (migration 0030)
- **원칙:** 입력이 먼저, 결과를 보려고 로그인한다. 파일 읽기도 로그인 전에 된다.
  - 비회원: 랜딩 CTA 또는 `/upload` → 파일 올리기(국외 이전 동의) → 읽은 내용으로 입력칸이 채워짐 → 고치고 "나와 비슷한 사람 찾기"
    → 미리보기 → 카카오 로그인 → 결과. 읽은 경력은 초안(draft)과 함께 다니다가 로그인할 때 내 기록으로 저장된다.
  - 회원: 결과 화면의 "경력을 다 채우면 더 많이 보여요" → 파일 올리기 → 더할 경력만 체크 → 저장 → 결과를 다시 계산.
    이미 있는 경력(같은 회사·같은 시작 연도)은 "이미 있어요"로 표시하고 다시 쓰지 않는다.
  - 릴스·게시물 링크는 `https://nextpath.da-sh.io/upload?utm_source=instagram&utm_medium=reels` 처럼 utm을 붙인다(대시보드 채널에 잡힘).
- **읽는 방법:** Claude(`HELLOMYME_CAREER_IMPORT_MODEL`, 기본 claude-opus-5-5)가 경력·학력만 정해진 형식으로 읽는다.
  - 이름·연락처·사진·자기소개는 읽지 않는다. 회사명·직함·학교·전공은 쓰인 그대로 두고, 직무 목록과 맞는 것만 제안한다.
  - 월이 적혀 있으면 MONTH 정밀도로, 없으면 YEAR로 저장한다(추정하지 않음). "인턴"은 employment_type INTERN(첫 직장에서 제외).
  - 목록에 없는 회사·직함은 원문 그대로 저장하고 `mapping_queue`에 올린다.
  - 직무 제안: 읽기와 같은 호출에서 고를 수 있는 직무 목록(leaf, `role_list`)을 함께 보내고, 경력마다 가장 가까운 직무 코드를
    받는다. 직함이 별칭과 정확히 같으면 그것이 먼저다. 화면에서 미리 골라두고 본인이 바꿀 수 있으며, 저장은 본인이 확인한 것만.
  - 안식년·휴직·구직 기간(`is_career_break`)은 목록에 "경력 공백"으로 보이고, 체크할 수 없으며 경력으로 저장하지 않는다.
- **파일:** PDF(2.5MB까지)와 이미지(최대 4개). 브라우저가 이미지를 JPEG로 다시 저장하고(위치 정보 등 메타데이터 제거),
  아주 긴 스크롤 캡처는 읽을 수 있는 크기로 나눈다. 파일은 서버에 저장하지 않는다.
- **동의(개인정보보호법 §28의8 국외 이전):** 파일을 보내기 전에 받는다. 받는 자(Anthropic, PBC·미국), 일시·방법, 항목, 목적,
  보유 기간, 거부할 권리(직접 입력으로 같은 결과)를 적는다. 문구 버전 `career_import_v1`(웹 `IMPORT_CONSENT_VERSION`과 서버 설정이 같아야 함).
  동의 기록은 `import_attempt`(문구 버전·시각·세션/계정)에 남는다.
- **비용 상한:** 읽기 1회 약 4천~2만 입력 토큰. `import_attempt`에 토큰을 남기고 대시보드에 추정 비용을 보여준다.
  - 계정당 하루 10회, 비회원 세션당 하루 3회, 비회원 접속 주소당 하루 20회(주소는 날짜를 섞은 해시로만 남김),
    **비회원 전체 하루 300회**(`HELLOMYME_CAREER_IMPORT_ANONYMOUS_DAILY_LIMIT`). 상한에 닿으면 "직접 입력"으로 안내한다.
    실패한 읽기도 횟수에 들어간다.
  - PDF는 10쪽까지(쪽마다 비용이 들어서, 보내기 전에 센다). 암호 걸린 PDF는 받지 않는다.
  - 동시에 읽는 건 8건까지(넘으면 "잠시 후 다시"). 읽는 동안(10~30초) DB 연결을 잡지 않는다.
  - 로그인 전에 파일로 시작한 기존 회원이 로그인하면, 확인한 경력 중 없는 것만 기존 프로필에 더한다.
- **가입하지 않아도 남기기 (migration 0031):** 업로드 화면의 [선택] "읽은 경력·학력을 익명 통계에 쓰는 것에 동의"를
  체크하면, 읽은 그대로(회사·직함·고용 형태·기간, 학교·전공·학위)를 `import_experience` / `import_education`에 남긴다.
  - 가입·로그인과 상관없이 남는다. 이름·연락처·파일은 남기지 않고, 시도(import_attempt: 세션 해시/계정)에만 연결된다.
  - 국외 이전 동의와 따로 받는다(§22①). 선택이라 거부해도 파일 읽기는 된다(§16③). "모두 동의하기"로 한 번에 체크할 수 있다.
  - 문구 버전 `career_import_stats_v1`(웹 `IMPORT_STATS_CONSENT_VERSION`). 동의 여부는 `import_attempt.stats_consent_version`.
  - 보유 기간 3년(`HELLOMYME_CAREER_IMPORT_RETENTION_DAYS`). 지난 행은 업로드 API가 호출될 때 지운다.
  - 입력 폼을 끝까지 제출한 사람은 동의와 별개로 기존처럼 초안(`anonymous_draft`)에도 남는다.
- **끄기:** Render에서 `ANTHROPIC_API_KEY`를 지우면 업로드 화면이 "직접 입력"으로 바뀐다.
- **실패 이유 (migration 0035):** 읽기가 실패하면 사람에게는 같은 안내 한 줄만 보이고, `import_attempt.failure_reason`에
  이유가 남는다(API 상태·오류 종류·메시지, 또는 내부 오류 이름, 300자 이내, 파일 내용 없음).
  `SELECT created_at, outcome, failure_reason FROM import_attempt ORDER BY created_at DESC LIMIT 20;`
- **API 키와 워크스페이스:** 워크스페이스에 묶이지 않은 키는 요청마다 워크스페이스를 밝혀야 한다(안 하면 400
  "This API key is not scoped to a workspace"). Render에 `ANTHROPIC_WORKSPACE_ID`(wrkspc_…)를 넣거나,
  워크스페이스 안에서 만든 키를 쓴다(2026-10-13 첫 실사용 실패 원인).
- **저장 위치:** `import_attempt`(읽기 1회 = 1행, 결과·토큰·출처 종류), 통계 동의 시 `import_experience`/`import_education`, 확인된 경력은 `work_event` +
  `source_record`(`LINKEDIN_USER_UPLOAD` 또는 `CAREER_DOCUMENT`), 초안은 `anonymous_draft.payload_json.other_jobs`.
- **이벤트:** `import_viewed` → `import_uploaded` → `import_parsed` → `import_confirmed`(member true/false).

## 개인정보처리방침 (web `/privacy`)
- 개인정보 보호법 §30. 랜딩 하단, 업로드 동의(자세히 보기), 로그인 동의, 입력·결과 화면 하단에서 링크한다.
- 처리 항목·기간·위탁(Anthropic 미국, Render 싱가포르, Supabase 서울, Vercel, 솔라피)은 실제 동작과 같아야 한다.
  수집 항목, 보관 기간, 업체가 바뀌면 같은 커밋에서 페이지도 고친다.
- 보관 기간: 가입하지 않은 입력(`anonymous_draft`·수정 이력)과 이용 기록(`analytics.event`)은 3년
  (`HELLOMYME_UNCLAIMED_INPUT_RETENTION_DAYS`, 기본 1095일). 초안 저장 API가 하루 한 번 지운다(`drafts.purge_expired`).
  회원의 입력은 탈퇴까지, 파일은 저장하지 않음, 읽은 내용의 통계 이용분 3년, 인터뷰 번호 1년.

## 학교 목록 (migration 0032)
- 4년제·전문대 418곳(같은 이름의 캠퍼스는 하나로, 고려대학교(세종)처럼 이름이 다른 캠퍼스는 따로)을 고를 수 있다.
  - 출처: 공공데이터포털 「전국대학및전문대학정보표준데이터」(교육부·대학알리미, 2026-05-21 수집, Hello My Me `public/data/schools-info.json`).
  - 다시 만들기: `python scripts/build_kr_institutions.py <hello-my-me>/public/data/schools-info.json` → `apps/api/hellomyme/reference/kr_institutions.csv`.
- 줄임말은 정해진 규칙으로만 만든다(삼육대학교→삼육대, 서울여자대학교→서울여대, 서울교육대학교→서울교대, 고려대학교(세종)→고려대(세종)).
  두 학교가 같은 줄임말이 되면 넣지 않는다.
- 학교 목록에 있어도 그 학교 경력 데이터가 없으면, 결과는 학교 조건을 넓혀서 계산되고 숫자 아래 기준 표시("여러 학교 · …")로 그렇게 말한다.

## PRE_SEED v1.4 (4년제 전체, 추가분)
- **무엇:** v1.3(24개 학교 × 20개 전공, 2만 명)에 더해, 학과 정보가 공개되고 20개 전공 중 하나라도 있는 4년제 119곳에
  예시 인물을 만든다. 시뮬레이션 데이터이며 실제 사람이 아니다(사람·멘토로 보여주지 않음).
- **운영 반영:** 2026-10-13 06:48(UTC) SQL로 넣음. 38,193명, 119곳, 949칸, 근거 없는 경력 0건, 계정 연결 0건 확인.
- **만드는 방법(`hellomyme-make-preseed`, `importer/generate.py`):**
  - 학교: `reference/kr_institutions.csv`의 4년제 중 v1.3에 없고 `reference/kr_school_departments.csv`에 학과가 공개된 곳.
    학과 정보가 없는 4년제(광운대·동아대 등 39곳)와 전문대는 만들지 않는다(전공을 추측하지 않음, v1.3 경로는 4년제 졸업자 기준).
  - 전공: 그 학교에 실제로 있는 학과와 맞는 v1.3 전공만(정해진 학과명 규칙).
  - 인원: 학교·전공마다 30~45명(학과가 많은 학교일수록 많게, 칸마다 ±3 차이). 30명은 결과가 "같은 학교" 기준으로
    나오는 최소 인원(`cohort_policy.min_exact_n`)이다.
  - 사람: v1.3의 같은 전공 사람을 통째로 복사한다(학번·경력 이벤트·근거 그대로, 수도권/비수도권 학교끼리).
    바뀌는 것은 id·근거 번호·학교뿐이다. 같은 v1.3 파일과 seed면 항상 같은 결과가 나온다.
- **넣기 (DB에 v1.3이 있으면):** `generate.addon_sql(plan_cells(...))`가 만든 SQL 한 덩어리(DO 블록, 한 트랜잭션)를
  DB에서 실행한다. DB 안의 v1.3 사람을 같은 규칙으로 골라 importer와 같은 형태(근거 기록·키 매핑·import 배치)로 쓰므로
  `--retire v1.4`로 그대로 빠진다. 두 번 실행하면 거부하고, 확인이 하나라도 틀리면 전부 되돌린다.
- **넣기 (엑셀로):** PC의 PowerShell에서 `irm https://raw.githubusercontent.com/YoungminDo/Next-path/main/scripts/add-preseed-schools.ps1 | iex`
  (v1.3 엑셀을 다운로드 폴더에서 찾고, 만들고, DB 연결 문자열을 물은 뒤 v1.3 옆에 import). v1.3은 그대로 남는다.
- **빼기:** v1.3 import를 `--retire v1.4`로 다시 실행하면 추가분만 지워진다.
- **크기:** 약 3.8만 명 추가(119곳 × 개설 전공 949칸) → DB 약 400MB 예상(Supabase Pro, 8GB 포함).
- **빼는 시간:** 0033(외래키 인덱스) 이후 약 2분(그 전에는 사람 삭제가 연쇄 삭제마다 표 전체를 읽어 수십 분).
- **속도:** 첫 직장 계산을 코호트 사람에게만 하도록 바꿔(0034 `first_employment_for`) 5만 명 기준 미리보기 0.03~0.2초,
  비슷한 경로 0.2~0.3초(로컬 측정, 바꾸기 전 1.2~3초).

## 숫자 아래 기준 표시 (신뢰도)
- 미리보기와 결과의 큰 숫자 바로 아래에, 그 숫자가 세는 사람이 누구인지 적는다(실제로 쓴 조건 기준).
  - 예: "같은 학교 · 비슷한 전공 계열 · 비슷한 학번(±2년)", "여러 학교 · 여러 전공 · 같은 학번"
- 숫자를 자르거나 바꾸지 않는다.
  - 서로 다른 학교에서 같은 숫자(예: 35명)가 반복되는 것은 상한 때문이 아니다.
  - 예시 데이터(PRE_SEED)가 학교·전공마다 약 42명씩 고르게 만들어져 있어서다(2026-10-12 확인).
- **목록에 없는 이름은 가장 비슷한 묶음부터 센다** (`domain/acquisition.py` `cohort_inputs`, 대표 결정 2026-10-13).
  같은 학번에서 출발해 목록에 있는 답과 같은 순서로 넓히고, 처음 30명(`min_exact_n`)을 넘는 묶음의 실제 인원을 보여준다.
  - 전공: 이름 안의 목록 전공(글로벌경영학부 → 경영학과) → 이름이 가리키는 계열(데이터사이언스 → 수학·통계·데이터)
    → 앞부분이 같은 전공(국어교육과 → 국어국문학과). 기준 표시는 "비슷한 전공" / "비슷한 전공 계열".
  - 학교: 이름에 든 지역(부산○○대 → 부산 지역 학교). 기준 표시는 "부산 지역 학교".
  - 단서가 없으면 그 조건은 빠진다("여러 학교", "여러 전공"). 학교·전공 모두 단서가 없으면 같은 학번 전체가 된다
    (운영 데이터 2026-10-13: QA테스트대학교·QA테스트학과 2016–2019 = 2,736명). 그보다 작게 고를 근거가 없어서다.
    대표 결정 2026-10-13: 그대로 둔다(숨기거나 임의로 자르지 않음). 기준 표시와 "모으는 중" 안내가 설명한다.
  - 그 이름 그대로인 기록은 없으므로 "딱 같은 사람"은 0명으로 말한다.
  - 운영 데이터 예: 충남대 + 경영정보학과 71명, 부산○○대 + 국어국문 40명, 단서 없는 학교 + 데이터사이언스 74명,
    단서 없는 학교 + 국어국문 2021–2023 105명(목록에 있는 충남대 + 국어국문 32명).
