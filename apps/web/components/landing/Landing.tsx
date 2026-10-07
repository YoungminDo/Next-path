import ConditionDemo from "./ConditionDemo";

/* Landing (/). One promise at the top, HeyDealer style: three inputs -> one concrete answer.
   Then: whose worry it is, what you get (visually), that conditions re-cut the answer live,
   why it is safe, and the "one step ahead" idea. CTAs go straight into the flow. */

const STUDENT_WORRIES = [
  "내 전공으로 갈 수 있는 길이 뭐가 있지?",
  "같은 과 선배들은 졸업하고 다 어디 갔을까?",
  "PM 하고 싶은데, 경영학과에서 간 사람이 있긴 해?",
  "남들은 첫 직장을 어떻게 골랐는지 알고 싶어",
];
const PRO_WORRIES = [
  "마케터 4년 차, 이대로 계속 가도 될까?",
  "나랑 비슷하게 시작한 사람들은 지금 뭐 하지?",
  "영업에서 기획으로 옮긴 사람, 얼마나 걸렸을까?",
];

export default function Landing() {
  return (
    <div className="landing">
      <nav className="lnav">
        <a className="brand" href="/">nextpath</a>
        <a className="lnav-cta" href="/start">시작하기</a>
      </nav>

      <header className="hero">
        <p className="eyebrow">학교 · 전공 · 학번만 입력하면</p>
        <h1>
          나와 비슷한 선배 <em>418명</em>이<br />실제로 어디로 갔는지<br />30초 만에 보여드려요
        </h1>
        <p className="lead">추천이나 예측이 아니에요. 같은 학교, 같은 전공, 비슷한 학번 선배들이 실제로 고른 길을 숫자로 보여드려요.</p>
        <div className="hero-ctas">
          <a className="cta" href="/start?type=student">학생이에요 · 선배 찾기</a>
          <a className="cta ghost" href="/start?type=pro">일하고 있어요 · 다음 보기</a>
        </div>
        <p className="hint">가입 없이 결과까지 바로 · 입력한 정보는 다른 사람에게 보이지 않아요</p>

        <div className="formula" aria-label="입력 3개로 얻는 결과">
          <div className="inputs">
            <span className="pill">고려대학교</span><span className="plus">+</span>
            <span className="pill">경영학과</span><span className="plus">+</span>
            <span className="pill">20학번 · 24년 졸업</span>
          </div>
          <span className="arrow" aria-hidden="true">↓</span>
          <div className="answer">
            <span className="small">비슷한 선배</span>
            <span className="big">418명</span>
            <span className="small">첫 직무 1위 마케팅 24% · 프로덕트로 간 선배 63명</span>
          </div>
          <span className="example">예시 화면</span>
        </div>
      </header>

      <section className="lsec">
        <p className="eyebrow">이런 고민, 하고 있죠?</p>
        <h2>정보는 많은데,<br />"나 같은 사람"의 답은 없었어요</h2>
        <div className="worries">
          <div>
            <h3>학생 · 취업 준비 중</h3>
            {STUDENT_WORRIES.map((w) => <p key={w} className="bubble">{w}</p>)}
          </div>
          <div>
            <h3>지금 일하는 중</h3>
            {PRO_WORRIES.map((w) => <p key={w} className="bubble">{w}</p>)}
          </div>
        </div>
        <p className="stat"><b>10명 중 7명</b>의 대학생이 아직 직무를 정하지 못했어요.<span className="src">헬로마이미 소개서</span></p>
        <p className="sub">채용 공고는 회사가 원하는 걸 말하고, 커뮤니티는 한 사람의 이야기를 말해요. 나와 같은 출발점에서 실제로 어디까지 갔는지는 아무도 모아서 보여주지 않았어요.</p>
      </section>

      <section className="lsec">
        <p className="eyebrow">이렇게 해결해요</p>
        <h2>세 번만 고르면 끝</h2>
        <ol className="steps">
          <li><b>입력 3개</b><span>학교, 전공, 입학·졸업 연도. 직장인은 지금 직무를 더해요.</span></li>
          <li><b>비슷한 선배 N명</b><span>그 사람들이 첫 직장에서, 다음 이직에서 실제로 고른 길을 보여드려요.</span></li>
          <li><b>궁금한 길 하나</b><span>고른 길로 간 선배들의 경로와 걸린 시간을 열어드려요.</span></li>
        </ol>
      </section>

      <section className="lsec">
        <p className="eyebrow">무엇을 보게 되나요</p>
        <h2>네 가지를 숫자와 그림으로</h2>
        <div className="outputs">
          <article className="out">
            <h3>첫 직무 분포</h3>
            <p className="sub">비슷한 선배들이 처음 간 직무 Top 5</p>
            <div className="bars flat">
              {[["마케팅", 92, 24], ["전략·기획", 70, 18], ["재무·금융", 58, 15]].map(([l, w, p], i) => (
                <div key={l} className="bar"><span>{l}</span>
                  <span className="track"><i className={i ? "m" : ""} style={{ width: `${w}%` }} /></span><b>{p}%</b></div>
              ))}
            </div>
          </article>
          <article className="out">
            <h3>실제 경로</h3>
            <p className="sub">그 길에 도착하기까지 거친 순서</p>
            <div className="path"><span>경영</span><span>사업개발</span><span className="hl">PM</span></div>
            <div className="path"><span>경영</span><span>마케팅</span><span className="hl">PO</span></div>
            <p className="small muted">21명 · 14명</p>
          </article>
          <article className="out">
            <h3>걸린 시간</h3>
            <p className="sub">첫 직장부터 그 직무까지</p>
            <p><span className="big">2.1</span><b> 년</b></p>
            <p className="small muted">중간값 · 절반은 이보다 빨랐어요</p>
          </article>
          <article className="out">
            <h3>도착한 회사</h3>
            <p className="sub">회사 규모와 산업 <span className="tube-tag">튜브로 열기</span></p>
            <div className="sizes"><span style={{ flex: 8 }}>대기업</span><span style={{ flex: 5 }}>중견</span><span style={{ flex: 3 }}>스타트업</span></div>
          </article>
        </div>
      </section>

      <section className="lsec">
        <p className="eyebrow">조건을 바꾸면 바로 바뀌어요</p>
        <h2>비교 그룹은 내가 정해요</h2>
        <p className="sub">학교, 전공, 졸업 연도를 바꿀 때마다 비교하는 선배가 다시 골라지고 결과도 바로 바뀌어요. 너무 좁혀서 사람이 적으면 어떤 조건을 넓혔는지 숨기지 않고 알려드려요. 직접 눌러보세요.</p>
        <ConditionDemo />
      </section>

      <section className="lsec">
        <p className="eyebrow">일하는 중이라면</p>
        <h2>나랑 같은 두 걸음을 걸은 사람들의<br />세 번째 걸음</h2>
        <div className="pro">
          <div className="path big-path"><span>영업</span><span>마케팅</span><span className="hl">?</span></div>
          <div className="bars flat">
            {[["지금 직무 유지", 80, 38], ["프로덕트", 48, 22], ["데이터·AI", 30, 14], ["창업", 20, 9]].map(([l, w, p], i) => (
              <div key={l} className="bar"><span>{l}</span>
                <span className="track"><i className={i ? "m" : ""} style={{ width: `${w}%` }} /></span><b>{p}%</b></div>
            ))}
          </div>
          <p className="small muted">예시 화면 · 첫 직장과 지금 직무가 같은 사람 127명 기준</p>
        </div>
      </section>

      <section className="lsec">
        <p className="eyebrow">믿을 수 있게</p>
        <h2>숫자를 숨기는 규칙이 있어요</h2>
        <div className="trust">
          <div><b>5명 미만은 숨겨요</b><span>작은 그룹은 "기타"로 묶어서 누군지 드러나지 않게 해요.</span></div>
          <div><b>넓힌 조건은 공개해요</b><span>"졸업 ±2년"처럼 비교 범위를 넓히면 항상 표시해요.</span></div>
          <div><b>입력은 나만 봐요</b><span>학교·회사는 비슷한 사람을 고르는 데만 쓰고 공개하지 않아요.</span></div>
          <div><b>모르면 비워둬요</b><span>추측해서 채운 숫자는 보여주지 않아요.</span></div>
        </div>
      </section>

      <section className="lsec philosophy">
        <p className="eyebrow">곧 열려요</p>
        <h2>배움은 상대적이에요</h2>
        <p className="lead">10년 차 전문가가 아니어도 괜찮아요. 내가 고민하는 그 선택을 <b>한 걸음 먼저</b> 해본 사람이 가장 잘 도와줄 수 있어요. nextpath는 데이터로 그 사람을 찾아 연결해 드릴 거예요. 도와준 선배는 튜브를 받아요.</p>
      </section>

      <section className="final">
        <h2>내 선배들은 어디로 갔을까?</h2>
        <p className="sub">입력 3개, 30초면 충분해요</p>
        <div className="hero-ctas">
          <a className="cta" href="/start?type=student">학생이에요</a>
          <a className="cta ghost" href="/start?type=pro">일하고 있어요</a>
        </div>
      </section>

      <footer className="lfoot">
        <span>nextpath · Hello My Me</span>
        <span>테스트 기간에는 시뮬레이션 데이터로 결과를 보여드려요.</span>
      </footer>
    </div>
  );
}
