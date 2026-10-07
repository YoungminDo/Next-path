# HMM ID 연동 — 카카오 로그인

HELLOMYME Career는 카카오 OAuth를 직접 호출하지 않습니다. 회사 IdP인 **HMM ID**(`id.da-sh.io`,
repo `YoungminDo/hmm-id`)가 카카오 로그인을 처리하고, 우리는 HMM ID 문서
`docs/docking-protocol.md`의 **Backend-only docking** 패턴으로 결과를 검증합니다.

## 흐름

```
[브라우저] "카카오로 계속하기"  (동의 체크 후에만 활성화)
   │  draft_id·동의 버전을 localStorage에 보관 (로그인으로 페이지를 떠나기 때문)
   ▼
GET  /auth/hmm/start                                  (Next.js, 우리 웹)
   │  302 → {HMM_ID}/api/oauth/kakao/start?redirect_uri={APP_ORIGIN}/auth/hmm/callback
   ▼
HMM ID ── 카카오 OAuth(PKCE·state) ── dash-access-token 쿠키 설정 (Domain=.da-sh.io, HttpOnly)
   │  302 → {APP_ORIGIN}/auth/hmm/callback        (실패 시 ?error=<reason>)
   ▼
GET  /auth/hmm/callback                               (Next.js 서버)
   │  쿠키의 dash-access-token 을 읽어 FastAPI 로 전달 (URL·브라우저 JS 로는 절대 노출 안 함)
   ▼
POST /auth/login {provider:"HMM_ID", token}          (FastAPI)
   │  GET {HMM_ID}/api/v1/auth/me  (Authorization: Bearer, 서버 간 호출 → Origin 없음)
   │  200 → subject = id (dash_user_id, 예: kakao_12345) → account_identity(HMM_ID, subject)
   │  401/403/404 → 401 (재로그인)   /  5xx·네트워크 오류 → 503 (로그인으로 처리하지 않음)
   ▼
Next.js 가 우리 세션 토큰을 HttpOnly 쿠키 `hmc_session` 으로 저장 → /?login=success
   ▼
POST /auth/merge-draft {draft_id, consent_policy_version}  → 익명 입력이 재입력 없이 회원 경력으로
```

이후 모든 API 호출은 같은 출처 프록시 `/api/backend/*` 를 거치며, 프록시가 `hmc_session` 쿠키를
`Authorization: Bearer` 로 바꿔 FastAPI 에 전달합니다. 브라우저 JS 는 어떤 토큰도 볼 수 없습니다.

## HMM ID SP 책임 체크리스트 (docking-protocol.md "SP 측 책임")

| 항목 | 구현 |
|---|---|
| 토큰 안전 보관 (표시·로그 X) | `dash-access-token` 은 서버에서 한 번 검증에만 쓰고 저장·로그하지 않음. 우리 세션은 SHA-256 해시로만 DB 저장 |
| HTTPS only | 운영(`HELLOMYME_ENV=production`)에서 `HMM_ID_BASE_URL` 이 https 가 아니면 API 기동 거부. 세션 쿠키 `Secure` |
| 만료 처리 (401 → 재인증) | HMM ID 401 → 로그인 실패 안내 / 우리 API 401 → 프록시가 세션 쿠키 삭제 |
| logout 시 토큰 폐기 | `/auth/logout` 이 우리 세션을 폐기. HMM ID SSO 쿠키는 다른 서비스와 공유하므로 건드리지 않음 |
| 사용자 데이터 결합 시 별도 동의 | 로그인 버튼은 동의 체크 후에만 활성화. merge 시 `data_consent` 에 `PRIVACY_PROCESSING`, `CAREER_DATA_AGGREGATION` + 정책 버전 기록 |
| 최소 수집 | `/me` 의 email·name·phone 은 저장하지 않음. 계정 연결에는 `id`(dash_user_id)만 사용 |
| fail-safe | HMM ID 장애 시 503 → "잠시 후 다시" 안내. 장애를 로그인 성공으로 처리하는 경로 없음 |

## 배포 전 필요한 것 (hmm-id 쪽)

1. **SP 등록** — `hmm-id/src/lib/sp-registry.ts` 의 `KNOWN_SPS` 에 이 웹의 origin 추가.
   HMM ID 는 `redirect_uri` 의 origin 이 정확히 일치하는 active SP 만 허용합니다(와일드카드 금지).
2. **같은 상위 도메인** — 웹이 `*.da-sh.io` 아래에 있어야 `Domain=.da-sh.io` 쿠키를 받을 수 있습니다.
3. `ALLOWED_ORIGINS`(CORS) 추가는 **불필요** — `/me` 는 서버 간 호출입니다.

## 환경변수

| 위치 | 변수 | 운영 값 예 |
|---|---|---|
| web (server) | `HMM_ID_BASE_URL` | `https://id.da-sh.io` |
| web (server) | `APP_ORIGIN` | SP 로 등록한 origin |
| web (server) | `HELLOMYME_API_URL` | FastAPI 주소 |
| api | `HELLOMYME_AUTH_PROVIDERS` | `["HMM_ID"]` |
| api | `HELLOMYME_HMM_ID_BASE_URL` | `https://id.da-sh.io` |

## 로컬 개발

hmm-id 를 `localhost:3000` 에서(`COOKIE_DOMAIN` 비움), 이 웹을 `localhost:3001` 에서 실행합니다.
localhost 쿠키는 포트를 구분하지 않으므로 hmm-id 가 심은 `dash-access-token` 을 3001 서버가 읽을 수
있습니다. hmm-id 는 개발 모드에서 localhost redirect 를 허용합니다.

## 검증

- `apps/api/tests/test_hmm_id.py` — 유효/만료 토큰, HMM ID 장애(5xx·연결 실패), 운영 https 강제,
  같은 dash_user_id 재로그인 시 계정 1개, 상태 코드.
- 브라우저 E2E (HMM ID 와 같은 엔드포인트·쿠키 계약을 가진 로컬 모의 서버 사용): 동의 전 버튼 비활성 →
  로그인 → draft 병합 → Career Map, 쿠키 2개 모두 HttpOnly, 재로그인, 카카오 취소 안내, 프록시의
  타 출처 POST 403, 운영 빌드에서 개발용 로그인 404. 실제 카카오·Supabase 를 쓰는 hmm-id 로는
  아직 검증하지 않았습니다.
