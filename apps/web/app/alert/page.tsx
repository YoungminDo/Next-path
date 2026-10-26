import type { Metadata } from "next";

import BusinessInfo from "@/components/BusinessInfo";
import TrackView from "@/components/TrackView";

import "./alert.css";

/* 공고 알림 test landing (/alert, owner decision 2026-10-26). Same funnel as the main landing: the
   view counts as a 방문 (landing_viewed, variant "alert"), the button opens the resume upload, and the
   sign-up happens there. No job postings are listed until real ones are collected: a job-info page
   may only carry postings whose company is known (직업안정법 시행령 §28 1호). */

const TITLE = "이력서만 올리면, 나랑 맞는 공고를 먼저 알려드려요";
const DESCRIPTION = "어디랑 잘 맞는지 1차 분석하고, 맞는 공고가 올라오면 문자로 알려드려요. 분석과 알림은 무료예요.";

export const metadata: Metadata = {
  title: `nextpath · ${TITLE}`,
  description: DESCRIPTION,
  openGraph: { type: "website", locale: "ko_KR", siteName: "nextpath", url: "/alert", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
};

const UPLOAD = "/upload";

const GETS = [
  { b: "어디랑 잘 맞는지 1차 분석", s: "잘 맞는 직군과 회사, 보완하면 좋은 점을 알려드려요" },
  { b: "맞는 공고가 올라오면 문자 알림", s: "마감이 닥쳐서야 알게 되는 일이 없게, 올라온 공고를 먼저 보내드려요" },
  { b: "비슷한 경력의 사람들이 간 길", s: "나와 같은 자리였던 사람들이 다음에 어디로 옮겼는지 보여드려요" },
];

export default function AlertLanding() {
  return (
    <div className="al">
      <TrackView name="landing_viewed" variant="alert" />
      <div className="al-app">
        <header className="al-top">
          <div className="al-top-row al-g">
            <a className="al-brand" href="/alert">nextpath</a>
            <span className="al-pill">공고 알림</span>
          </div>
        </header>

        <main>
          <section className="al-hero al-g">
            <h1>이력서만 올리면,<br />나랑 맞는 공고를 먼저 알려드려요</h1>
            <p className="al-lead">공고, 닥쳐서 보지 마세요. 분석과 알림은 무료예요.</p>
            <ol className="al-steps">
              <li><span className="al-n">1</span>이력서 올리기 · 1분</li>
              <li><span className="al-n">2</span>어디랑 잘 맞는지 1차 분석</li>
              <li><span className="al-n">3</span>맞는 공고가 올라오면 문자로 알림</li>
            </ol>
            <a className="al-cta" href={UPLOAD}>이력서 올리고 맞는 공고 받기 · 무료</a>
            <p className="al-cta-sub">PDF·사진·링크드인 캡처 모두 돼요 · 파일은 저장하지 않아요</p>
          </section>

          <section className="al-sec al-g">
            <h2>이력서 하나로 받는 것</h2>
            <p className="al-sub">카카오로 3초 로그인하면 바로 열려요</p>
            <div className="al-cards">
              {GETS.map((g) => (
                <div key={g.b} className="al-card"><b>{g.b}</b><span>{g.s}</span></div>
              ))}
            </div>
          </section>

          <section className="al-sec al-g">
            <h2>이런 문자로 알려드려요</h2>
            <p className="al-sub">오전 8시~밤 9시에만 보내요 · 언제든 끌 수 있어요</p>
            <div className="al-sms">
              <div className="al-sms-when">문자 예시</div>
              <div className="al-bubble">{"[넥스트패스] ○○회사 CRM 마케팅 매니저 공고가 올라왔어요\n올라온 지 1일 · 마감 D-14\n맞는 이유: CRM 캠페인 운영 경험"}</div>
            </div>
          </section>

          <section className="al-sec al-g">
            <h2>서류에서 더 잘 보이고 싶다면</h2>
            <p className="al-sub">분석에서 나온 보완점을 코치가 직접 고쳐 드려요</p>
            <div className="al-cards">
              <div className="al-card al-plan">
                <div><b>1회 첨삭</b><span>이력서를 한 번 꼼꼼히 고쳐 드려요</span></div>
                <div className="al-price">59,000원</div>
              </div>
              <div className="al-card al-plan">
                <div><b>마감까지 무제한 첨삭</b><span>지원하는 공고 마감 전까지 횟수 제한 없이 고쳐 드려요 · 마감일이 있는 공고만</span></div>
                <div className="al-price">99,000원</div>
              </div>
            </div>
          </section>

          <section className="al-sec al-g">
            <h2>자주 묻는 질문</h2>
            <div className="al-faq">
              <details><summary>올린 이력서 파일은 저장되나요?</summary><p>아니요. 파일은 경력과 학력을 읽는 데만 쓰고 바로 지워요. 이름, 연락처, 사진은 읽지 않아요. 읽은 내용도 직접 확인한 것만 남아요.</p></details>
              <details><summary>어떤 공고를 알려주나요?</summary><p>회사 채용 페이지와 채용 사이트에 공개된 공고 중 회사가 확인되는 공고만 알려드려요. 마감된 공고는 보내지 않아요.</p></details>
              <details><summary>알림은 언제, 어떻게 오나요?</summary><p>맞는 공고가 올라오면 오전 8시~밤 9시 사이에 문자로 보내요. 알림은 언제든 끌 수 있어요.</p></details>
              <details><summary>분석은 무엇으로 하나요?</summary><p>올린 이력서와 공개된 공고를 비교해요. 비슷한 경력의 사람들이 간 길은 실제 기록이 충분히 모이기 전까지 예시 데이터로 계산한 결과를 보여드려요.</p></details>
              <details><summary>코칭은 꼭 받아야 하나요?</summary><p>아니요. 분석과 공고 알림은 무료예요. 코칭은 원할 때만 따로 신청해요.</p></details>
            </div>
          </section>

          <footer className="al-foot al-g"><BusinessInfo /></footer>
        </main>

        <div className="al-bar al-g">
          <a className="al-cta" href={UPLOAD}>이력서 올리고 맞는 공고 받기 · 무료</a>
          <p className="al-cta-sub">1분이면 끝나요 · 파일은 저장하지 않아요</p>
        </div>
      </div>
    </div>
  );
}
