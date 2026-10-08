import ConditionDemo from "./ConditionDemo";
import HeroForm from "./HeroForm";
import InsightGallery from "./InsightGallery";
import StickyCta from "./StickyCta";
import type { Options } from "@/lib/server/options";

/* Landing (/). Results sit behind a free Kakao login, so this page has to make the login feel
   like an obvious "why not": curiosity (many real-looking insights, mobileindex-style), a big
   free offer, and almost no cost (three seconds, free, no sales calls). Tone: "people who stood
   where I stand", never "seniors"; evidence of what people did, never a promise. */

const WORRIES = [
  "내 전공으로 갈 수 있는 길이 뭐가 있지?",
  "나랑 같은 과 나온 사람들은 다 어디 갔을까?",
  "PM 하고 싶은데, 경영학과에서 간 사람이 있긴 해?",
  "마케터 4년 차, 이대로 계속 가도 될까?",
  "영업에서 기획으로 옮긴 사람, 얼마나 걸렸을까?",
];

const FREE = [
  { b: "내 진로 지도", s: "나와 같은 출발점의 사람들이 나뉜 길 전부" },
  { b: "궁금한 길의 실제 경로", s: "어떤 순서로, 몇 년 만에 갔는지" },
  { b: "깊은 분석 3번", s: "가입하면 3튜브 지급 · 도착한 회사 규모·산업" },
  { b: "한 걸음 먼저 간 사람에게 묻기", s: "곧 열려요", soon: true },
];

export default function Landing({ options }: { options: Options }) {
  return (
    <div className="landing">
      <nav className="lnav">
        <a className="brand" href="/">nextpath</a>
        <a className="lnav-cta" href="#hero-form">무료로 시작</a>
      </nav>

      <header className="hero">
        <div className="hero-copy">
          <p className="eyebrow">학교 · 전공 · 학번만 고르면</p>
          <h1>나와 같은 자리에 있었던 사람들은 <em>어디로</em> 갔을까?</h1>
          <p className="lead">같은 학교, 같은 전공, 비슷한 시기에 시작한 사람들이 실제로 간 길을 보여드려요. 답답했던 내 방향, 이 중에 있을지도 몰라요.</p>
          <ul className="reasons">
            <li>추천이 아니라 실제로 간 길이에요</li>
            <li>로그인은 카카오로 3초, 무료예요</li>
            <li>광고 · 영업 연락은 절대 없어요</li>
          </ul>
        </div>
        <HeroForm institutions={options.institutions} majors={options.majors} />
      </header>

      <a className="reward" href="#hero-form">
        <span className="badge">100% 지급</span>
        <span><b>지금 가입하면 3튜브</b> · 깊은 분석을 3번 무료로 열어볼 수 있어요</span>
        <span aria-hidden="true">›</span>
      </a>

      <section className="lsec worries-sec">
        <p className="eyebrow">이런 생각, 해본 적 있죠?</p>
        <div className="bubbles">
          {WORRIES.map((w) => <p key={w} className="bubble">{w}</p>)}
        </div>
        <p className="stat"><b>10명 중 7명</b>의 대학생이 아직 직무를 정하지 못했어요.<span className="src">헬로마이미 소개서</span></p>
      </section>

      <section className="lsec">
        <InsightGallery />
      </section>

      <section className="lsec offer">
        <div className="offer-copy">
          <p className="eyebrow">로그인 한 번으로</p>
          <h2>이걸 전부 무료로 받아요</h2>
          <p className="sub">드는 건 카카오 로그인 3초와 고르기 4번이에요.</p>
        </div>
        <ul className="ticket">
          {FREE.map((f) => (
            <li key={f.b} className={f.soon ? "soon" : ""}>
              <b>{f.b}</b><span>{f.s}</span><em>{f.soon ? "준비 중" : "무료"}</em>
            </li>
          ))}
        </ul>
      </section>

      <section className="lsec">
        <p className="eyebrow">조건을 바꾸면 바로 바뀌어요</p>
        <h2>비교할 사람은 내가 정해요</h2>
        <p className="sub">학교, 전공, 졸업 연도를 바꿀 때마다 나와 비슷한 사람이 다시 골라지고 결과도 바로 바뀌어요. 사람이 너무 적으면 어떤 조건을 넓혔는지 숨기지 않고 알려드려요. 직접 눌러보세요.</p>
        <ConditionDemo />
      </section>

      <section className="lsec">
        <p className="eyebrow">이용 과정</p>
        <h2>30초면 충분해요</h2>
        <ol className="process">
          <li><b>학교 · 전공 · 학번 고르기</b><span>10초면 돼요. 일하는 중이면 지금 직무를 더해요.</span></li>
          <li><b>나와 같은 자리였던 사람 찾기</b><span>몇 명이, 몇 가지 길로 나뉘었는지 바로 알려드려요.</span></li>
          <li><b>카카오로 3초 로그인</b><span>무료예요. 입력한 내용은 그대로 이어져요.</span></li>
          <li><b>어디로, 어떻게 갔는지 보기</b><span>궁금한 길 하나를 고르면 실제 경로와 걸린 시간이 열려요.</span></li>
        </ol>
      </section>

      <section className="lsec">
        <p className="eyebrow">믿을 수 있게</p>
        <h2>숫자를 숨기는 규칙이 있어요</h2>
        <div className="trust">
          <div><b>5명 미만은 숨겨요</b><span>작은 그룹은 "기타"로 묶어서 누군지 드러나지 않게 해요.</span></div>
          <div><b>넓힌 조건은 공개해요</b><span>"졸업 ±2년"처럼 비교 범위를 넓히면 항상 표시해요.</span></div>
          <div><b>입력은 나만 봐요</b><span>학교·회사는 비슷한 사람을 찾는 데만 쓰고 공개하지 않아요.</span></div>
          <div><b>모르면 비워둬요</b><span>추측해서 채운 숫자는 보여주지 않아요.</span></div>
        </div>
      </section>

      <section className="lsec philosophy">
        <p className="eyebrow">곧 열려요</p>
        <h2>배움은 상대적이에요</h2>
        <p className="lead">10년 차 전문가가 아니어도 괜찮아요. 내가 고민하는 그 선택을 <b>한 걸음 먼저</b> 해본 사람이 가장 잘 도와줄 수 있어요. nextpath는 데이터로 그 사람을 찾아 연결해 드릴 거예요. 도와준 사람은 튜브를 받아요.</p>
      </section>

      <section className="lsec">
        <p className="eyebrow">자주 묻는 질문</p>
        <h2>궁금한 점</h2>
        <div className="faq">
          <details><summary>정말 무료인가요?</summary><p>네. 내 진로 지도와 궁금한 길의 경로는 무료예요. 회사 규모·산업 같은 깊은 분석은 튜브로 여는데, 가입하면 3튜브를 바로 드려요. 튜브는 지금 돈으로 팔지 않아요.</p></details>
          <details><summary>왜 로그인해야 하나요?</summary><p>학교·전공·경력처럼 민감할 수 있는 정보를 다루기 때문에, 본인 확인과 동의를 받은 뒤에 결과를 보여드려요. 로그인하면 입력한 내용이 저장돼서 다시 쓰지 않아도 돼요.</p></details>
          <details><summary>내 정보가 다른 사람에게 보이나요?</summary><p>아니요. 결과는 모두 익명 통계이고, 5명 미만 그룹은 숨겨요. 학교·회사·연도는 나와 비슷한 사람을 찾는 데만 써요.</p></details>
          <details><summary>데이터는 어디서 오나요?</summary><p>정식 서비스에서는 가입하고 경력을 입력·인증한 사람들의 기록으로 계산해요. 지금 테스트 기간에는 시뮬레이션 데이터로 보여드리고, 모든 결과에 SIMULATION 표시가 붙어요.</p></details>
          <details><summary>먼저 간 사람에게 직접 물어볼 수 있나요?</summary><p>준비 중이에요. 내가 궁금한 길을 한 걸음 먼저 간 사람을 데이터로 찾아 연결해 드릴 거예요.</p></details>
        </div>
      </section>

      <section className="final">
        <h2>이 중에 내 길도 있을까요?</h2>
        <p className="sub">무료예요. 카카오로 3초면 확인할 수 있어요.</p>
        <div className="hero-ctas">
          <a className="cta" href="#hero-form">학교 · 전공 고르러 가기</a>
          <a className="cta ghost" href="/start?type=pro">일하고 있어요</a>
        </div>
      </section>

      <StickyCta />

      <footer className="lfoot">
        <span>nextpath · Hello My Me</span>
        <span>테스트 기간에는 시뮬레이션 데이터로 결과를 보여드려요. 랜딩의 숫자는 모두 예시예요.</span>
      </footer>
    </div>
  );
}
