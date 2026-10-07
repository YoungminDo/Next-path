# 배포 가이드 — 테스트 배포 (nextpath.da-sh.io)

결정 Q7: **Vercel(웹) + 관리형 FastAPI/PostgreSQL(백엔드)**. 테스트 기간에는 `HELLOMYME_ENV=staging`
으로 운영해 PRE_SEED 시뮬레이션 데이터를 쓰고, 모든 결과에 `SIMULATION` 안내가 붙습니다.
정식 출시 때 `production` 으로 바꾸면 PRE_SEED 는 자동으로 거부됩니다.

```
브라우저 ──▶ nextpath.da-sh.io (Vercel, apps/web)
               │  /auth/hmm/*  ──▶ id.da-sh.io (HMM ID, 카카오 로그인)
               │  /api/backend/* (서버 프록시)
               ▼
            nextpath-api (Render 등, apps/api Docker) ──▶ PostgreSQL 16 (Supabase 등)
                                                 └──▶ id.da-sh.io/api/v1/auth/me
```

## 진행 상황

| 단계 | 상태 |
|---|---|
| HMM ID 에 SP `nextpath` 등록 | ✅ hmm-id PR #10 main 머지 (Vercel 자동 배포 대상) |
| API Docker 이미지 | ✅ `apps/api/Dockerfile` — 로컬 빌드·기동·`/health`·운영 가드 확인 |
| DB 생성 | ⬜ 계정 필요 |
| API 배포 | ⬜ 계정 필요 (`render.yaml` 준비됨) |
| 웹 배포 + 도메인 | ⬜ Vercel 계정 + DNS 필요 |
| PRE_SEED import | ⬜ DB 생성 후 |
| 실 카카오 로그인 1회 검증 | ⬜ |

## 1. PostgreSQL (예: Supabase 새 프로젝트)

hmm-id 의 Supabase 와 **별도 프로젝트**로 만듭니다(테스트 데이터가 IdP DB 와 섞이지 않게).
리전 Seoul(ap-northeast-2). Connection string(**Direct** 또는 Session pooler, 5432)을 아래 형식으로:

```
HELLOMYME_DATABASE_URL=postgresql+psycopg://postgres:<PASSWORD>@<HOST>:5432/postgres?sslmode=require
```

`pgcrypto` 확장은 migration 0001 이 생성합니다. Transaction pooler(6543)는 migration 에 쓰지 마세요.

## 2. API (예: Render — `render.yaml` Blueprint)

1. Render → New → Blueprint → `YoungminDo/Next-path` 선택 (main 브랜치 기준).
2. `HELLOMYME_DATABASE_URL` 입력. 나머지 값은 Blueprint 에 들어 있습니다.
3. 배포되면 컨테이너가 시작할 때 `alembic upgrade head` 를 실행합니다.
4. 확인: `GET https://<api-host>/health` → `{"status":"ok","env":"staging","data_basis":"SIMULATION"}`

Railway·Fly.io·Cloud Run·App Runner 도 같은 Dockerfile 로 배포할 수 있습니다(포트는 `PORT` 환경변수).

## 3. PRE_SEED import (1회)

공식 PRE_SEED는 `HELLOMYME_PreSeed_Career_Data_v1.3.xlsx` 입니다(저장소에 없음). 이전 v1.2는 import 후 삭제합니다.
Windows: PowerShell 에서 `irm https://raw.githubusercontent.com/YoungminDo/Next-path/main/scripts/import-preseed.ps1 | iex`
(다운로드 폴더의 엑셀 파일을 찾아 import 하고 v1.2 를 정리). 직접 실행:

```bash
cd apps/api
HELLOMYME_DATABASE_URL='<위 URL>' uv run hellomyme-import-preseed /path/to/HELLOMYME_PreSeed_Career_Data_v1.3.xlsx \
  --retire v1.2
```
데이터셋 버전과 기준일은 엑셀의 `00_README` 에서 읽습니다. 재실행해도 `ALREADY_IMPORTED` 로 끝납니다.
약 45초 (20,000명). DB 스키마가 0020 이상이어야 하므로 API 배포(마이그레이션) 후에 실행합니다.

## 4. 웹 (Vercel)

1. Vercel → Add New Project → `YoungminDo/Next-path`, **Root Directory = `apps/web`** (Next.js 자동 감지).
2. Environment Variables (Production):

| 변수 | 값 |
|---|---|
| `HELLOMYME_API_URL` | `https://<api-host>` |
| `HMM_ID_BASE_URL` | `https://id.da-sh.io` |
| `APP_ORIGIN` | `https://nextpath.da-sh.io` |
| `NEXT_PUBLIC_ENABLE_DEV_LOGIN` | `false` |
| `NEXT_PUBLIC_CONSENT_POLICY_VERSION` | `career_terms_v1` |

`ENABLE_DEV_LOGIN` 은 넣지 않습니다(운영 빌드에서는 넣어도 무시됨).

3. Domains → `nextpath.da-sh.io` 추가 → GoDaddy DNS 에 Vercel 이 안내하는 CNAME(`cname.vercel-dns.com`) 등록.

> 반드시 `nextpath.da-sh.io` 로 접속해서 테스트하세요. `*.vercel.app` 주소에서는 HMM ID 의
> `.da-sh.io` 쿠키를 받을 수 없고, HMM ID 가 redirect_uri 를 거부합니다.

## 5. 배포 후 확인

1. `https://nextpath.da-sh.io` → 현직자 → 입력 → teaser 에 "시뮬레이션" 안내 표시
2. 동의 체크 → 카카오로 계속하기 → 카카오 로그인 → Career Map 표시, 보유 튜브 6
3. unlock 1회 → 튜브 1 차감, 같은 버튼 재클릭 시 추가 차감 없음
4. 로그아웃 후 재로그인 → 입력 없이 바로 Career Map
5. hmm-id 어드민 `/admin/audit` 에 `nextpath.da-sh.io` 의 oauth_start / callback_success 기록

## 정식 출시로 전환할 때

- API: `HELLOMYME_ENV=production`, `HELLOMYME_CAREER_MAP_DATA_LAYERS=["SEED","VERIFIED"]`
  (PRE_SEED 가 남아 있으면 API 가 기동을 거부합니다)
- 테스트 기간 튜브 원장은 수정·삭제가 불가능하므로, 초기화가 필요하면 새 DB 로 시작하거나 REVERSAL 로 정정
