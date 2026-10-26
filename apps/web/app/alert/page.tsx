import type { Metadata } from "next";

import BusinessInfo from "@/components/BusinessInfo";
import TrackView from "@/components/TrackView";

import "./alert.css";

/* 공고 알림 test landing (/alert, owner decision 2026-10-26), in the Hello My Me look and voice. Same
   funnel as the main landing: the view counts as a 방문 (landing_viewed, variant "alert"), the button
   opens the resume upload, and the sign-up happens there. No job postings are listed until real ones
   are collected: a job-info page may only carry postings whose company is known (직업안정법 시행령
   §28 1호). The notification and analysis panels are marked as examples. */

const TITLE = "이력서만 올리면, 나에게 맞는 공고를 먼저 알려드려요";
const DESCRIPTION = "잘 맞는 직군과 회사 유형을 1차 분석하고, 맞는 공고가 올라오면 문자로 알려드려요. 분석과 알림은 무료예요.";

export const metadata: Metadata = {
  title: `nextpath · ${TITLE}`,
  description: DESCRIPTION,
  openGraph: { type: "website", locale: "ko_KR", siteName: "nextpath", url: "/alert", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
};

// from=alert: after login the flow offers the alert opt-in first (AcquisitionFlow, ALERT_ENTRY).
const UPLOAD = "/upload?from=alert";

const Check = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
);
const Bell = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
  </svg>
);
const Note = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" /><path d="M12 8v5" /><path d="M12 16.5h.01" />
  </svg>
);

const STEPS = [
  { b: "이력서 올리기", s: "PDF, 사진, 링크드인 캡처 모두 돼요. 읽은 학력·경력은 직접 확인한 것만 남아요." },
  { b: "1차 분석 받기", s: "잘 맞는 직군과 회사 유형, 보완하면 좋은 점을 바로 보여드려요." },
  { b: "맞는 공고 알림 받기", s: "나에게 맞는 공고가 올라오면 오전 8시~밤 9시 사이에 문자로 알려드려요." },
];

const FITS = [
  { name: "그로스 마케팅", level: "잘 맞아요", high: true, why: "가입 전환을 3년 맡은 경험이 있어요" },
  { name: "CRM 마케팅", level: "잘 맞아요", high: true, why: "재방문 캠페인을 직접 운영했어요" },
  { name: "PM", level: "도전해 볼 만해요", high: false, why: "실험 설계 경험이 기획으로 이어질 수 있어요" },
];

const FAQ = [
  { q: "어떤 공고를 알려주나요?", a: "회사 채용 페이지와 채용 사이트에 공개된 공고 중 회사가 확인되는 공고만 알려드려요. 마감된 공고는 보내지 않아요." },
  { q: "알림은 언제, 어떻게 오나요?", a: "맞는 공고가 올라오면 오전 8시~밤 9시 사이에 문자로 보내요. 알림은 결과 화면에서 언제든 끌 수 있어요." },
  { q: "분석은 무엇으로 하나요?", a: "이력서에서 읽고 직접 확인한 학력·경력으로 AI가 잘 맞는 직군과 회사 유형, 보완하면 좋은 점을 알려드려요. 비슷한 경력의 사람들이 간 길은 실제 기록이 충분히 모이기 전까지 예시 데이터로 계산한 결과를 보여드려요." },
  { q: "코칭은 꼭 받아야 하나요?", a: "아니요. 분석과 공고 알림은 무료예요. 코칭은 원할 때만 따로 신청하고, 결제는 코치와 통화한 뒤에 해요." },
];

export default function AlertLanding() {
  return (
    <div className="al">
      <TrackView name="landing_viewed" variant="alert" />
      <div className="al-app">
        <header className="al-top">
          <div className="al-top-row al-g">
            <a className="al-brand" href="/alert">nextpath</a>
            <span className="al-brand-sub">공고 알림</span>
          </div>
        </header>

        <main>
          <section className="al-hero al-g">
            <span className="al-stage"><i aria-hidden="true" />나도 도전하기 · 어디에 지원하지?</span>
            <h1>이력서만 올리면,<br />나에게 맞는 공고를 <em>먼저</em> 알려드려요</h1>
            <p className="al-lead">마감이 닥쳐서야 공고를 보는 일, 이제 그만해요. 분석과 알림은 모두 무료예요.</p>
            <a className="al-cta" href={UPLOAD}>이력서 올리고 시작하기</a>
            <ul className="al-trust">
              <li><Check />1분이면 끝나요</li>
              <li><Check />분석·알림 무료</li>
              <li><Check />카카오로 3초 로그인</li>
            </ul>

            <div className="al-demo" aria-label="알림 예시">
              <div className="al-demo-label"><span>이런 알림을 받아요</span><span className="al-chip">예시</span></div>
              <div className="al-note">
                <div className="al-note-icon"><Bell /></div>
                <div className="al-note-body">
                  <div className="al-note-top"><span>nextpath 공고 알림</span><span>오전 10:12</span></div>
                  <div className="al-note-title">헬스케어 스타트업의 CRM 마케팅 매니저 공고가 올라왔어요</div>
                  <div className="al-note-meta">
                    <span className="al-chip warn">마감 D-14</span>
                    <span className="al-chip mint">올라온 지 1일</span>
                    <span className="al-chip">맞는 이유: CRM 캠페인 경험</span>
                  </div>
                </div>
              </div>
              <div className="al-note" aria-hidden="true">
                <div className="al-note-icon"><Bell /></div>
                <div className="al-note-body">
                  <div className="al-note-top"><span>nextpath 공고 알림</span><span>어제</span></div>
                  <div className="al-note-title">커머스 플랫폼의 그로스 마케터 공고가 올라왔어요</div>
                </div>
              </div>
            </div>
          </section>

          <section className="al-sec al-g">
            <p className="al-eyebrow">이렇게 진행돼요</p>
            <h2>이력서 하나로 세 가지를 받아요</h2>
            <p className="al-sub">처음 한 번만 올리면, 그다음은 알아서 챙겨드려요.</p>
            <ol className="al-steps">
              {STEPS.map((s, i) => (
                <li key={s.b}><span className="al-n">{i + 1}</span><div><b>{s.b}</b><span className="al-step-desc">{s.s}</span></div></li>
              ))}
            </ol>
          </section>

          <section className="al-sec al-g">
            <p className="al-eyebrow">AI 1차 분석</p>
            <h2>어디랑 잘 맞는지 먼저 알려드려요</h2>
            <p className="al-sub">직접 확인한 학력·경력만으로 분석해요. 결과는 이런 모습이에요.</p>
            <div className="al-panel">
              <div className="al-panel-head">
                <b>그로스 마케터 3년차,<br />그로스·CRM 쪽이 가장 잘 맞아요</b>
                <span className="al-chip">예시</span>
              </div>
              <ul className="al-rows">
                {FITS.map((f) => (
                  <li key={f.name} className="al-row">
                    <div className="al-row-top">{f.name}<span className={f.high ? "al-chip mint" : "al-chip"}>{f.level}</span></div>
                    <p>{f.why}</p>
                  </li>
                ))}
              </ul>
              <p className="al-panel-label">어울리는 회사 유형</p>
              <div className="al-tags"><span className="al-tag">핀테크 스타트업</span><span className="al-tag">커머스 플랫폼</span><span className="al-tag">헬스케어 서비스</span></div>
              <p className="al-panel-label">보완하면 좋은 점</p>
              <div className="al-gap"><Note />성과를 숫자로 보여주는 경력이 아직 적어요</div>
            </div>
          </section>

          <section className="al-sec al-g">
            <p className="al-eyebrow">이력서 첨삭 코칭</p>
            <h2>서류에서 더 잘 보이고 싶다면</h2>
            <p className="al-sub">분석에서 나온 보완점부터 코치가 직접 고쳐 드려요. 원할 때만 신청해요.</p>
            <div className="al-plans">
              <div className="al-plan">
                <div><b>1회 첨삭</b><span className="al-desc">이력서를 한 번 꼼꼼히 고쳐 드려요</span></div>
                <div className="al-price">59,000원</div>
              </div>
              <div className="al-plan pick">
                <div>
                  <span className="al-chip mint">지원 마감까지</span>
                  <b>마감까지 무제한 첨삭</b>
                  <span className="al-desc">지원하는 공고 마감 전까지 횟수 제한 없이 고쳐 드려요</span>
                </div>
                <div className="al-price">99,000원</div>
              </div>
            </div>
            <p className="al-fine">마감까지 무제한 첨삭은 마감일이 있는 공고만 돼요. 신청하면 코치가 연락드리고, 결제는 통화 뒤에 해요.</p>
          </section>

          <section className="al-sec al-g">
            <p className="al-eyebrow">자주 묻는 질문</p>
            <h2>궁금한 점</h2>
            <div className="al-faq">
              {FAQ.map((f) => <details key={f.q}><summary>{f.q}</summary><p>{f.a}</p></details>)}
            </div>
          </section>

          <footer className="al-foot al-g"><BusinessInfo /></footer>
        </main>

        <div className="al-bar al-g">
          <a className="al-cta" href={UPLOAD}>이력서 올리고 맞는 공고 받기 · 무료</a>
        </div>
      </div>
    </div>
  );
}
