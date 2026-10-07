# 데이터 해자 (Data Moat)

> 포지셔닝: Nextpath는 Hello My Me의 첫 번째 Acquisition 프로덕트(토스 송금처럼 트래픽 제너레이터).
> 무료 결과 → 데이터 → 튜브 마이크로머니 → 데이터 기반 연결("한 걸음 먼저 간 사람").
> 이 문서는 그 흐름에서 **어떤 원천 데이터를 쌓아야 해자가 되는지**와 스키마 변경을 정한다.

## 1. 해자가 되는 데이터의 조건

1. **우리 흐름 안에서만 생긴다.** 공개 프로필 크롤링으로 얻을 수 없다.
2. **그 시점에만 잡힌다.** 결정 이전의 의도처럼, 나중에 돈을 들여도 복원할 수 없다.
3. **쌓일수록 다음 사용자의 결과가 좋아진다.** (데이터 네트워크 효과)
4. **연결·수익 흐름에서 저절로 생긴다.** 별도 설문 비용이 들지 않는다.

공개 프로필(링크드인 등)은 개인 이력을 공개할 뿐 가공하지 않으며 "나 같은 사람은 어디로 갔나"라는
결정 질문에 답하지 않는다. 직접 경쟁은 아니다. 다만 이력 원천 데이터를 가장 많이 가진 쪽이라
집계 기능을 강화하면 무료 결과를 대체할 수 있으므로, 해자는 **그들이 갖지 못한 데이터**에 둔다.

## 2. 후보 평가

| 데이터 | 독점성 | 시점성 | 수집 비용 | 개인정보 위험 | 결정 |
|---|---|---|---|---|---|
| **A. 의도 → 실제 결과** (궁금했던 길 → 6·12개월 뒤 실제 선택) | 높음 | 높음 | 낮음 | 중간 | **Phase 1** |
| **B. 선택 이유·대안·다시 고를지** | 높음 | 중간 | 중간 | 낮음 | **Phase 1.5** (스키마는 Phase 1) |
| **C. 이력서에 안 쓰는 이벤트** (휴학·공백·전과·교환·부트캠프·대학원 포기·접은 창업) | 높음 | 중간 | 중간 | 중간~높음 | **Phase 2** |
| **D. 연결 데이터** (어떤 질문을, 누구에게, 도움이 됐나, 결정을 바꿨나) | 높음 | 높음 | 낮음 | 중간 | **Phase 1** |
| E. 재직·졸업 인증 | 중간 | 낮음 | 중간 | 중간 | 신뢰 기반(A~D를 VERIFIED로 올림) |
| F. 지원·합격 과정, 당시 스펙 | 중간 | 높음 | 높음 | 높음 | 보류 |
| G. 연봉 · 자기소개서 | 낮음 | 낮음 | 중간 | 중간 | **하지 않음** (크레딧잡·잡플래닛·링커리어·자소설닷컴 등이 이미 보유) |

### 왜 A가 핵심인가
결과(어디로 갔나)는 누구나 모을 수 있지만, **결정 이전의 의도**는 그 순간 기록하지 않으면 사라진다.
의도와 결과가 이어지면 "PM을 궁금해한 사람 중 실제로 간 비율, 간 사람의 경로, 안 간 사람이 대신 고른 길"을
보여줄 수 있다. 6·12개월 뒤 묻는 follow-up은 약점이던 **재방문 이유**도 함께 만든다.

### B
공개 이력은 경로만 보여주고 그 선택이 좋았는지는 보여주지 않는다. "다시 고르겠다" 비율은 결정 앞의
사람에게 가장 강한 신호다. 도운 사람이 튜브를 받는 순간 질문 3개(이유, 다른 후보, 다시 고를지)를 받는다.

### C
실패·공백은 공개 이력에서 지워지지만 "나 같은 사람"을 찾는 사용자에게 가장 중요하다.
**사유는 받지 않는다.** 휴학 사유에 건강이 들어가면 개인정보보호법 제23조 민감정보가 된다.
이벤트 종류와 기간만 받고, 익명 집계로만 쓴다.

### D
질문 주제·도움 평가·결정 영향이 쌓이면 다음 연결을 더 잘 고르는 양면 네트워크 효과가 생긴다.
동의받은 답변은 익명 인사이트 콘텐츠(검색 유입)로 재사용할 수 있다.

### 반론과 대응
a16z "The Empty Promise of Data Moats"는 데이터가 늘수록 한계 가치가 줄어 데이터만으로는 해자가 약하다고 본다.
대응: (1) 양이 아니라 **한 사람 단위로 의도·결과·만족·연결이 이어진 결합**으로 승부한다.
(2) 데이터를 연결(수익) 흐름에서 생기게 해서, 경쟁자가 데이터가 아니라 **흐름 전체**를 복제해야 하게 만든다.

## 3. 스키마 (마이그레이션 0019, 구현됨)

기존 0008(`intent_event`/`decision_event`/`outcome`)과 0009(`mentor_profile`/`orders`)를 확장한다.

| 대상 | 변경 | 용도 |
|---|---|---|
| `followup_policy` (신규) | `horizons_months smallint[]`, 버전·상태. 시드 `fu_v1` = {6,12} ACTIVE | 언제 다시 물을지는 정책 값 |
| `intent_followup` (신규) | intent_event당 horizon별 1행, `due_at`, `status`(SCHEDULED/SENT/ANSWERED/SKIPPED/EXPIRED), `resolution`(PURSUED/PURSUING/CHANGED_TARGET/STAYED/STILL_EXPLORING/DROPPED), `decision_event_id` | A. 의도 → 결과 연결. `UNIQUE(intent_event_id, horizon_months)`로 멱등 스케줄링. ANSWERED 행은 트리거로 수정 불가(원천 기록) |
| `decision_event` | `intent_event_id`, `considered_targets jsonb[]`, `would_choose_again`(YES/NO/UNSURE), `source_surface` | B. 결정을 의도와 직접 잇고, 대안·재선택 의향 기록 (`reasons`, `reason_text`, `outcome.satisfaction`은 기존) |
| `orders` | `topic_taxonomy_node_id`, `intent_event_id` | D. 질문이 어떤 직무·산업에 관한 것이었고 어떤 의도에서 나왔나 |
| `help_feedback` (신규) | 주문당 1건, `helpfulness` 1~5, `decision_effect`(CHANGED/CONFIRMED/NO_EFFECT/TOO_EARLY) | D. 도움의 질과 결정 영향. 연결 랭킹·도운 사람 보상의 근거 |
| `reward_policy.action_type` | `INTENT_FOLLOWUP_ANSWERED`, `DECISION_RATIONALE_ADDED`, `HELP_COMPLETED`, `HELP_RATED` 추가 | 데이터를 남긴 사람에게 튜브 지급. **보상 값은 시드하지 않음** (제품 결정, 정책 테이블에서 설정) |

### Phase 2 제안 (아직 구현 안 함): C. 이력서에 안 쓰는 이벤트
`work_event.event_type`에는 이미 `CAREER_BREAK`, `STUDY`, `MILITARY`가 있다. 학업 중 이벤트는 별도 테이블로 둔다.

```sql
CREATE TABLE education_event (
    education_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id          uuid NOT NULL REFERENCES person ON DELETE CASCADE,
    education_id       uuid REFERENCES education ON DELETE CASCADE,
    event_type         text NOT NULL CHECK (event_type IN
                         ('LEAVE_OF_ABSENCE','MAJOR_CHANGE','TRANSFER','EXCHANGE',
                          'DOUBLE_MAJOR','MINOR','BOOTCAMP','GRAD_SCHOOL_ATTEMPT','JOB_SEARCH')),
    start_date date, start_date_precision text, end_date date, end_date_precision text,
    data_layer text NOT NULL, verification_level text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
    -- 사유(reason) 컬럼은 의도적으로 두지 않는다: 민감정보 수집 방지.
);
```
그리고 `work_event`에 `ended_reason`을 두지 않고, 접은 창업은 `STARTUP` + `end_date`로 표현한다.

## 4. 운영 규칙

- follow-up은 의도를 남긴 시점의 **알림 수신 동의**가 있을 때만 SENT로 보낸다(카카오 알림 채널은 HMM ID 쪽 동의와 별도).
- `resolution`과 `decision_event`는 사용자가 말한 그대로 저장한다. 행동 데이터로 추정해 채우지 않는다(unknown = NULL).
- 도운 사람 보상은 `help_feedback` 이후에만 지급할지 정책으로 정한다. 보상만 노린 형식적 답변을 막기 위함.
- 모든 집계는 기존 small-cohort/small-cell suppression을 그대로 따른다. C 데이터는 cohort 필터가 아니라 결과 분포에만 쓴다.

## 5. 측정 지표

| 지표 | 의미 |
|---|---|
| follow-up 응답률 (6·12개월) | A 데이터가 실제로 쌓이는가 |
| 의도 → 결과 연결 건수 / 월 | 해자 데이터의 누적 속도 |
| 결정 이유 기록률 (도운 사람 기준) | B 수집이 보상 흐름에 붙었는가 |
| help_feedback 작성률, 평균 helpfulness, CHANGED 비율 | D 품질과 연결의 실제 영향 |
| follow-up 알림 → 재방문률 | 재방문 이유가 되는가 |

## 출처
- a16z, The Empty Promise of Data Moats — https://a16z.com/the-empty-promise-of-data-moats/
- NFX, The Network Effects Bible — https://www.nfx.com/post/network-effects-bible
- 개인정보보호법 제23조(민감정보) — https://www.law.go.kr/법령/개인정보보호법
- Pre-seed v1.3 검증 — `docs/06_PRESEED_V13_VALIDATION.md`
- 서비스 디자인 기획 — `docs/07_SERVICE_DESIGN.html`
