# Meta 광고: 타겟별 캠페인과 측정 (2026-10-14~)

> 질문: 학생·취준생·직장인 중 누가 광고를 가장 많이 누르고(CTR·CPC), 누가 가장 싸게 가입하는가(가입 전환율·가입당 비용).
> 소재: 타겟별 2장씩(4:5 피드, 9:16 스토리·릴스). 화면 속 숫자는 "예시" 표시.

## 핵심 지표 두 쌍
| 지표 | 계산 | 어디서 보나 |
|---|---|---|
| CTR (클릭률) | 링크 클릭 ÷ 노출 | 광고 관리자 `CTR(링크 클릭률)` |
| CPC (클릭당 비용) | 광고비 ÷ 링크 클릭 | 광고 관리자 `CPC(링크 클릭당 비용)` |
| 가입 전환율 | 신규 가입 ÷ 방문 | `/admin` → 광고 캠페인 (기준값) |
| 가입당 비용 (CPA) | 광고비 ÷ 신규 가입 | 광고비(광고 관리자) ÷ 신규 가입(`/admin`) |

- 광고 관리자의 `CompleteRegistration`(픽셀) 숫자는 참고값이다. iOS 추적 제한과 광고 차단 때문에 실제보다 적게 잡힌다.
  판단은 `/admin` 숫자로 한다.
- `/admin` 의 방문은 해당 utm_campaign 으로 처음 들어온 브라우저 수다. 어느 페이지로 들어왔든 센다.
  신규 가입은 그 브라우저에서 처음 저장한 입력으로 가입한 계정 수다(팀 계정 제외).
- 첫 방문 채널만 남는다. 예전에 다른 경로로 왔던 사람이 광고를 눌러도 그 사람은 예전 채널로 센다.

## 캠페인 구조 (권장)
캠페인 1개, 광고 세트 3개(타겟별). 예산은 **광고 세트마다 따로**(Advantage+ 캠페인 예산 끔) 잡는다.
캠페인 예산을 켜면 Meta가 처음 반응이 좋은 세트에 돈을 몰아준다. 그러면 세 타겟을 같은 조건으로 비교할 수 없다.

| 항목 | 설정 |
|---|---|
| 캠페인 목표 | **리드** → 전환 위치 `웹사이트` → 성과 목표 `전환수 최대화` → 픽셀 이벤트 **`Lead`** (정보 입력 완료) |
| 캠페인 이름 | `np_1014` |
| 특별 광고 카테고리 | 없음 (채용 공고가 아닌 진로 정보 서비스) |
| 일정 | 5일 (예: 10/15 00:00 ~ 10/19 24:00) |
| 위치 | Advantage+ 노출 위치. 피드에는 4:5, 스토리·릴스에는 9:16 소재를 쓴다 |

`Lead` 로 최적화하는 이유: Meta가 학습을 마치려면 광고 세트당 주 50건 정도의 최적화 이벤트가 필요하다고 알려져 있다
([Cometly](https://www.cometly.com/post/facebook-ads-learning-phase-optimization),
[AdManage](https://admanage.ai/blog/facebook-ads-learning-phase-guide)). 하루 1만 원으로는 가입(`CompleteRegistration`)이
주 50건에 못 미친다. 정보 입력 완료는 로그인 전 단계라 가입보다 2~3배 자주 일어나서 학습에 더 가깝다. 가입이 주 50건을 넘는
세트가 생기면 그 세트만 `CompleteRegistration` 최적화로 복제해 비교한다.

대안: `트래픽` 목표(랜딩 페이지 조회 최적화)를 쓰면 CPC는 낮게 나온다. 하지만 누르기만 하는 사람에게 광고가 몰려 가입당 비용이
나빠지기 쉽다. 이번 테스트의 두 번째 지표와 맞지 않아 권장하지 않는다.

## 광고 세트 3개
나이를 겹치지 않게 나눈다. 겹치면 우리 광고 세트끼리 같은 사람을 두고 경매에서 다투고, 결과도 섞인다.

| 광고 세트 | 나이 | 지역·언어 | 상세 타겟 | 소재 | utm_campaign |
|---|---|---|---|---|---|
| 학생 | 19–23 | 대한민국 · 한국어 | 없음 (브로드) | `nextpath_student_4x5`, `_9x16` | `np_1014_student` |
| 취준생 | 24–28 | 대한민국 · 한국어 | 없음 (브로드) | `nextpath_seeker_4x5`, `_9x16` | `np_1014_seeker` |
| 직장인 | 29–35 | 대한민국 · 한국어 | 없음 (브로드) | `nextpath_pro_4x5`, `_9x16` | `np_1014_pro` |

- 타겟팅은 나이로만 하고, 누구 얘기인지는 소재 문구가 고르게 한다. 상세 관심사는 모수를 줄이고 학습을 늦춘다.
- 예산: 세트마다 하루 10,000원 × 5일, 총 150,000원.
- 판단에 필요한 최소량은 세트마다 노출 1,000회 이상, 링크 클릭 100회 이상이다. CPC가 500원이면 5일이면 100회에 닿는다.
- 남자 대학생은 군 복무로 24세 이상도 많다. 학생 세트에서 빠지는 이 구간은 취준생 소재가 받는다.

## 링크 (광고마다)
웹사이트 URL은 `https://nextpath.da-sh.io/` 로 한다. 랜딩이 픽셀 `PageView` 를 보내고, FAQ의 예시 데이터 안내도 거기에 있다.
URL 매개변수 칸에 세트별로 아래를 넣는다. `{{ad.name}}` 은 Meta가 광고 이름으로 바꿔 넣는다.

```
utm_source=meta&utm_medium=paid_social&utm_campaign=np_1014_student&utm_content={{ad.name}}
utm_source=meta&utm_medium=paid_social&utm_campaign=np_1014_seeker&utm_content={{ad.name}}
utm_source=meta&utm_medium=paid_social&utm_campaign=np_1014_pro&utm_content={{ad.name}}
```

광고 이름은 `student_4x5` 처럼 소재 이름으로 짓는다(utm_content로 남는다).

## 픽셀 (web `lib/pixel.ts`)
- 켜는 법:
  1. 이벤트 관리자에서 픽셀(데이터 세트)을 만든다.
  2. 설정 → "코드 없이 자동으로 이벤트 추적"을 **끈다**. 새 "자동 이벤트" 항목이 있으면 그것도 끈다
     ([Pixelflow](https://docs.pixelflow.so/turn-off-automatic-event-tracking-in-meta-biywn),
     [Jon Loomer](https://www.jonloomer.com/meta-automatic-events-feature/)).
  3. 데이터 세트 **NEXTPATH웹 (ID `1422190370051636`, 2026-10-14 생성)** 을 쓴다. ID는 코드(`web/lib/pixel-id.ts`)에 들어 있다.
     공개값이라 비밀이 아니다. FACE커리어 웹 픽셀과 섞지 않는다(이벤트 의미가 달라 CPA가 흐려짐).
- Vercel 환경변수 `NEXT_PUBLIC_META_PIXEL_ID` 로 다른 ID를 넣을 수 있고, `off` 로 두면 끈다(재배포 필요).
  끄면 스크립트를 아예 불러오지 않고, 개인정보처리방침의 픽셀 항목도 사라진다.
- 데이터 세트 설정: 자동 고급 매칭 끔, 자동 이벤트 끔, 트래픽 권한 허용 목록 `nextpath.da-sh.io`.
  전환 API 게이트웨이는 연결하지 않는다(방침에 없는 처리 경로). 붙일 때는 eventID로 중복이 제거된다.
- 보내는 이벤트는 세 가지뿐이다:
  - `PageView`: 랜딩 화면
  - `Lead`: 정보 입력 완료. `eventID = lead-<draft_id>`
  - `CompleteRegistration`: 신규 가입만. 기존 회원 재로그인은 보내지 않는다. `eventID = signup-<draft_id>`
- 이벤트 속성은 비어 있다. 학교·전공 등 입력값은 보내지 않는다. `/start` 는 측정 전에 주소창의 입력값을 지운다(type·utm만 남김).
  코드에서도 `autoConfig` 를 꺼서, 픽셀이 버튼 문구나 화면 내용을 읽지 않는다.
- 팀 브라우저(`?internal=1`)에서는 픽셀이 돌지 않는다.
- 확인 방법: 이벤트 관리자 → 이벤트 테스트에서 위 세 이벤트만 들어오는지 본다.
- 공식 이벤트 정의: [Meta Pixel reference](https://developers.facebook.com/docs/meta-pixel/reference)

## 판단 규칙 (5일 뒤, 또는 세트별 클릭 100회 뒤)
1. **CTR이 낮다** (노출 1,000회 이상인데 링크 CTR 0.8% 미만): 소재 문제다. 키 메시지나 히어로 이미지를 바꾼다.
   - 참고로 미국 교육 업종 평균은 트래픽 목표 기준 CTR 1.45%, CPC $0.86이다
     ([LocaliQ](https://localiq.com/blog/facebook-advertising-benchmarks/),
     [WordStream 2025](https://www.wordstream.com/blog/facebook-ads-benchmarks-2025)).
   - 한국 수치는 아니라 출발점으로만 쓴다.
2. **CTR은 괜찮은데 가입 전환율이 낮다**: 광고가 아니라 사이트 문제다. `/admin` 에서 방문 → 입력 → 로그인 클릭 → 가입 중 어디서
   빠지는지 본다.
3. **가입당 비용 비교**: 세 세트 모두 클릭 100회를 넘긴 뒤에 비교한다. 이긴 세트만 예산을 올리고, 하루 20% 이내로 올린다.
   크게 바꾸면 학습이 다시 시작된다고 알려져 있다([Cometly](https://www.cometly.com/post/facebook-ads-learning-phase-optimization)).
4. **중단**: 목표 가입당 비용의 3배를 쓰고도 가입이 0이면 그 세트를 끈다.
   - 목표 가입당 비용은 대표가 정한다. 가입 1명의 가치는 카드 매출(990원)보다 Hello My Me 유입·데이터 가치가 크다.
   - 이번 테스트에서는 임시로 5,000원을 쓴다(가정값).

## 위험과 확인할 것
- **표시·광고**: 지금 결과는 예시 데이터로 계산된다(랜딩 FAQ). 광고가 "먼저 간 사람들의 실제 진로"처럼 읽히면 거짓·과장 또는
  기만 광고로 볼 여지가 있다([표시·광고의 공정화에 관한 법률 제3조](https://www.law.go.kr/법령/표시ㆍ광고의공정화에관한법률)).
  - 소재에는 "화면 속 숫자는 예시예요"가 들어가 있다.
  - 본문 문구에도 "실제", "진짜 데이터" 같은 표현은 쓰지 않는다. SEED 데이터가 쌓이면 문구를 바꾼다.
- **행태정보**: 픽셀은 Meta가 사이트 방문 기록을 가져가게 하는 것이다.
  - 개인정보보호위원회는 맞춤형 광고의 행태정보 처리를 투명하게 공개하라고 한다
    ([이투데이 2024-01](https://www.etoday.co.kr/news/view/2327015)).
  - 그래서 `/privacy` 7항에 수집 항목·목적·거부 방법을 적었다(픽셀이 켜질 때만 표시).
  - 최종 문구는 대표 검토가 필요하다.
- **특별 광고 카테고리**: 채용 카테고리를 쓰면 나이 타겟을 18–65+로 고정해야 한다
  ([Meta Marketing API](https://developers.facebook.com/documentation/ads-commerce/marketing-api/audiences/special-ad-category),
  [Jon Loomer](https://www.jonloomer.com/special-ad-categories-meta-ads/)).
  - 우리 광고는 채용 공고가 아니라서 해당하지 않는다고 본다.
  - 심사에서 채용으로 분류되면 나이로 나눌 수 없다. 그때는 세트를 소재별로만 나누고, 나이는 Meta 보고서의 `연령` 분석으로 본다.
- **개인 특성 단정 문구**: 메타 정책은 인종·종교·건강·재정 상태 같은 개인 특성을 단정하는 문구를 막는다. 직무·학과는 그 목록에
  없어서 "나와 같은 직무였던 사람들"은 위험이 낮다.

## 캠페인 생성 스펙 np_1014 (Marketing API로 만들 때)
소재: `docs/ads/np_1014/nextpath_{student,seeker,pro}_{4x5,9x16}.png` (예시 숫자에 "예시" 표시).
API로 만들 때 필요한 것:
- 환경 네트워크 허용: `graph.facebook.com`
- 토큰: 시스템 사용자 `nextpath-ads`(앱 `nextpath웹`, ads_management·ads_read·business_management)의 토큰을
  클라우드 환경의 **네트워크 시크릿**으로 넣는다(허용 웹사이트 `graph.facebook.com`, 헤더 `Authorization: Bearer`).
  프록시가 요청에 붙이므로 코드에 `access_token` 을 넣지 않는다. 세션에는 토큰 값이 보이지 않는다.
- 광고 계정: DA-SH (`act_1102865001932830`)
- 데이터 세트: NEXTPATH웹 `1422190370051636`

모든 객체는 **PAUSED** 로 만든다. 켜는 것은 대표가 광고 관리자에서 한다.

| 객체 | 값 |
|---|---|
| 캠페인 | `np_1014`, objective `OUTCOME_LEADS`, special_ad_categories `[]`, 캠페인 예산 없음(광고 세트 예산) |
| 광고 세트 공통 | optimization_goal `OFFSITE_CONVERSIONS`, promoted_object `{pixel_id: 1422190370051636, custom_event_type: LEAD}`, billing `IMPRESSIONS`, bid `LOWEST_COST_WITHOUT_CAP`, 일 예산 $7(계정 통화 USD), 2026-10-15 00:00 ~ 10-19 23:59 KST, 국가 KR, 한국어, 자동 노출 위치 |
| 광고 세트 | `student` 19–23 · `seeker` 24–28 · `pro` 29–35 (Advantage+ 타겟 끔: 연령 고정) |
| 광고 | 세트마다 1개, 피드 4:5 · 스토리/릴스 9:16 (노출 위치별 이미지), 버튼 LEARN_MORE, 링크 `https://nextpath.da-sh.io/`, url_tags = 아래 utm |

| 세트 | 제목 | 기본 문구 |
|---|---|---|
| student | 우리 과 선배들의 첫 직장 | 우리 과 선배들은 졸업하고 처음에 어디로 갔을까? 학교·전공만 넣으면 나와 비슷한 사람들의 첫 진로를 1분 만에 볼 수 있어요. 무료예요. |
| seeker | 먼저 간 사람들의 첫 직장 | 감으로 지원하기 전에, 나와 같은 전공으로 먼저 간 사람들이 어디서 시작했는지 확인해 보세요. 학교·전공만 넣으면 1분이면 끝나요. 무료예요. |
| pro | 같은 직무였던 사람들의 다음 이동 | 나와 같은 직무였던 사람들, 다음엔 어디로 갔을까? 지금 직무만 넣으면 비슷한 경력의 다음 이동을 1분 만에 볼 수 있어요. 무료예요. |

문구에 "실제", "진짜 데이터"는 쓰지 않는다(위험과 확인할 것 참고).

### 만든 객체 (2026-10-14, 모두 PAUSED로 생성, API v25.0)
집행 시작: 대표 결정으로 10/15 00:00 → **10/14 19:43** 으로 당김(광고 세트 start_time). 아침 요약 누적도 이 시각부터.

| 객체 | ID |
|---|---|
| 캠페인 np_1014 | 120249946050460296 |
| 광고 세트 student / seeker / pro | 120249946055550296 / 120249946057570296 / 120249946057850296 |
| 광고 student_ad / seeker_ad / pro_ad | 120249946209800296 / 120249946210240296 / 120249946210510296 |
| 소재 | 1101134082327075 / 2011212616502422 / 4376901405955344 |

- 소재: Advantage+ 자동 편집 83개를 모두 끔(이미지 잘림·문구 자동 변경 없음).
  `standard_enhancements` 를 한 번에 끄는 방식은 더 이상 지원되지 않아 항목별로 지정했다.
- 광고 소재를 만들려면 앱(nextpath웹)이 게시(공개 모드) 상태여야 한다.
