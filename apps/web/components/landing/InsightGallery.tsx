"use client";

import { useEffect, useRef, useState } from "react";

/* Benchmark: mobileindex.com/dashboard. Many different insights, each its own chart type, so
   the visitor keeps wondering "what would mine look like?". One fixed sentence with a phrase
   that changes, the matching card highlighted. Every number here is an example and labelled.
   Colours: validated categorical slots (s1 teal, s2 blue, s3 orange), max three series, the
   rest folded into gray "기타". Text always uses text tokens, never the series colour. */

type Insight = { key: string; phrase: string; title: string; tag: string; takeaway: string; locked?: boolean };

const INSIGHTS: Insight[] = [
  { key: "first", phrase: "같은 과 사람들의 첫 직무", title: "같은 과 사람들은 처음에 어디로 갔을까", tag: "First Job",
    takeaway: "1위도 24%뿐이에요. 나머지는 11가지 다른 길로 갔어요." },
  { key: "rank", phrase: "요즘 치고 올라오는 직무", title: "최근 3년, 치고 올라온 첫 직무", tag: "Trend",
    takeaway: "데이터·AI가 3계단 올라왔어요." },
  { key: "share", phrase: "우리 과 졸업생이 나뉜 길", title: "경영학과 졸업생은 어디로 나뉘었을까", tag: "Share",
    takeaway: "같은 과에서도 12가지 길로 나뉘었어요." },
  { key: "time", phrase: "PM이 되기까지 걸린 시간", title: "PM이 되기까지 몇 년 걸렸을까", tag: "Timing",
    takeaway: "절반은 졸업 후 2.1년 안에 PM이 됐어요." },
  { key: "flow", phrase: "마케팅을 떠난 사람들의 행선지", title: "마케팅을 떠난 사람은 어디로 갔을까", tag: "Flow",
    takeaway: "3명 중 1명은 프로덕트로 갔어요." },
  { key: "tenure", phrase: "가장 많이 옮긴 연차", title: "몇 년 차에 처음 옮겼을까", tag: "Tenure",
    takeaway: "가장 많이 옮긴 건 3년 차였어요 (27%)." },
  { key: "cohort", phrase: "학번별로 달라진 첫 직무", title: "학번이 바뀌면 첫 직무도 바뀔까", tag: "Cohort",
    takeaway: "데이터·AI는 12학번 6% → 20학번 21%로 늘었어요." },
  { key: "company", phrase: "도착한 회사의 규모", title: "그 길에 도착한 회사는 어디였을까", tag: "Company", locked: true,
    takeaway: "프로덕트로 간 사람의 35%는 스타트업에 도착했어요." },
  { key: "compare", phrase: "학교에 따라 달라진 길", title: "같은 전공, 학교가 다르면 달라질까", tag: "Compare",
    takeaway: "같은 전공이어도 B대학교는 프로덕트가 2배 가까이 많았어요." },
];

export default function InsightGallery() {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const strip = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = setInterval(() => setActive((i) => (i + 1) % INSIGHTS.length), 3500);
    return () => clearInterval(t);
  }, [paused]);

  // On the phone strip, bring the active card into view by scrolling the strip only.
  useEffect(() => {
    const el = strip.current;
    const card = el?.children[active] as HTMLElement | undefined;
    if (!el || !card || el.scrollWidth <= el.clientWidth) return;
    el.scrollTo({ left: card.offsetLeft - el.offsetLeft - 16, behavior: "smooth" });
  }, [active]);

  return (
    <div className="gallery">
      <div className="gallery-head">
        <p className="eyebrow">아직 감으로 정하고 있나요?</p>
        <h2 className="carousel-title">
          오직 nextpath에서만 볼 수 있는<br />
          <span className="hl-chip" aria-live="polite">{INSIGHTS[active].phrase}</span>
        </h2>
        <div className="dots" role="tablist" aria-label="인사이트">
          {INSIGHTS.map((s, n) => (
            <button key={s.key} role="tab" aria-selected={n === active} aria-label={s.phrase}
                    className={n === active ? "dot on" : "dot"} onClick={() => { setActive(n); setPaused(true); }} />
          ))}
        </div>
        <p className="sub">아래 숫자는 예시예요. 내 학교 · 전공 · 학번을 넣으면 내 조건으로 다시 계산돼요.</p>
      </div>
      <div className="ggrid" ref={strip} onPointerDown={() => setPaused(true)}
           onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
        {INSIGHTS.map((s, n) => (
          <article key={s.key} className={n === active ? "gcard on" : "gcard"} onMouseEnter={() => setActive(n)}>
            <header>
              <h3>{s.title}</h3>
              <span className={s.locked ? "tag lock" : "tag"}>{s.locked ? "튜브로 열기" : s.tag}</span>
            </header>
            <Chart kind={s.key} />
            <p className="takeaway">{s.takeaway}</p>
            <footer><span>예시 데이터</span><a href="#hero-form">내 조건으로 보기 →</a></footer>
          </article>
        ))}
      </div>
    </div>
  );
}

function Chart({ kind }: { kind: string }) {
  switch (kind) {
    case "first": return <FirstJob />;
    case "rank": return <Ranking />;
    case "share": return <Donut />;
    case "time": return <Timeline />;
    case "flow": return <Flow />;
    case "tenure": return <Tenure />;
    case "cohort": return <CohortLines />;
    case "company": return <Stacked />;
    default: return <Dumbbell />;
  }
}

/** Bar with only the data end rounded, anchored to the baseline. */
function vbar(x: number, y: number, w: number, h: number, r = 4) {
  const rr = Math.min(r, h, w / 2);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}
function hbar(x: number, y: number, w: number, h: number, r = 4) {
  const rr = Math.min(r, w, h / 2);
  return `M${x},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h - rr} Q${x + w},${y + h} ${x + w - rr},${y + h} H${x} Z`;
}

function FirstJob() {
  const rows: [string, number][] = [["마케팅", 24], ["전략·기획", 18], ["재무·금융", 15], ["프로덕트", 13], ["영업·사업개발", 12], ["기타 7개", 18]];
  const max = 24;
  return (
    <svg viewBox="0 0 300 168" className="gchart" role="img" aria-label="첫 직무 비율: 마케팅 24%, 전략·기획 18%, 재무·금융 15%, 프로덕트 13%, 영업·사업개발 12%, 기타 18%">
      {rows.map(([l, v], i) => {
        const y = 8 + i * 26;
        const w = (v / max) * 170;
        return (
          <g key={l}>
            <text x="0" y={y + 13} className="lbl">{l}</text>
            <path d={hbar(86, y + 2, w, 16)} className={i === 0 ? "s1" : l.startsWith("기타") ? "other" : "s1soft"}>
              <title>{`${l} ${v}%`}</title>
            </path>
            <text x={86 + w + 6} y={y + 14} className="val">{v}%</text>
          </g>
        );
      })}
    </svg>
  );
}

function Ranking() {
  const rows: [string, number, number][] = [["개발·엔지니어링", 21, 0], ["데이터·AI", 17, 3], ["프로덕트", 14, 2], ["마케팅", 12, -2], ["재무·금융", 9, -1], ["컨설팅", 7, 1]];
  return (
    <ol className="rank" aria-label="최근 3년 첫 직무 순위와 그 이전 대비 변동">
      {rows.map(([l, v, d], i) => (
        <li key={l}>
          <b>{i + 1}</b><span>{l}</span><em>{v}%</em>
          <i className={d > 0 ? "up" : d < 0 ? "down" : ""}>{d > 0 ? `▲ ${d}` : d < 0 ? `▼ ${-d}` : "-"}</i>
        </li>
      ))}
    </ol>
  );
}

function Donut() {
  const data: [string, number, string][] = [["마케팅", 24, "s1"], ["전략·기획", 18, "s2"], ["재무·금융", 15, "s3"], ["기타 9개", 43, "other"]];
  const r = 50, C = 2 * Math.PI * r;
  let cum = 0;
  return (
    <svg viewBox="0 0 300 168" className="gchart" role="img" aria-label="경영학과 졸업생 첫 직무: 마케팅 24%, 전략·기획 18%, 재무·금융 15%, 기타 9개 직무 43%">
      <g transform="translate(78 84) rotate(-90)">
        {data.map(([l, v, c]) => {
          const len = (v / 100) * C - 2.5;
          const el = (
            <circle key={l} r={r} fill="none" className={`ring ${c}`} strokeWidth="22"
                    strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-cum}>
              <title>{`${l} ${v}%`}</title>
            </circle>
          );
          cum += (v / 100) * C;
          return el;
        })}
      </g>
      <text x="78" y="80" textAnchor="middle" className="big-in">12가지</text>
      <text x="78" y="98" textAnchor="middle" className="ax">길로 나뉨</text>
      {data.map(([l, v, c], i) => (
        <g key={l} transform={`translate(160 ${40 + i * 26})`}>
          <rect width="10" height="10" rx="2" y="-9" className={c} />
          <text x="16" className="lbl">{l}</text>
          <text x="130" textAnchor="end" className="val">{v}%</text>
        </g>
      ))}
    </svg>
  );
}

function Timeline() {
  const pts: [number, number][] = [[0, 0.04], [6, 0.06], [12, 0.1], [18, 0.16], [24, 0.3], [30, 0.47], [36, 0.58], [42, 0.64], [48, 0.68]];
  const L = 34, R = 292, T = 12, B = 140;
  const x = (m: number) => L + (m / 48) * (R - L);
  const y = (v: number) => T + (1 - v / 0.8) * (B - T);
  const line = pts.map(([m, v], n) => `${n ? "L" : "M"}${x(m).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const mark = 25;
  const markY = y(0.3 + (0.47 - 0.3) * (1 / 6));
  return (
    <svg viewBox="0 0 300 168" className="gchart" role="img" aria-label="졸업 후 개월 수별 PM 전환 누적 비율. 중간값 25개월(2.1년)">
      {[0, 0.4, 0.8].map((v) => (
        <g key={v}>
          <line x1={L} x2={R} y1={y(v)} y2={y(v)} className="grid" />
          <text x={L - 6} y={y(v) + 4} textAnchor="end" className="ax">{Math.round(v * 100)}%</text>
        </g>
      ))}
      {[0, 12, 24, 36, 48].map((m) => (
        <text key={m} x={x(m)} y={B + 18} textAnchor="middle" className="ax">{m === 0 ? "졸업" : `${m / 12}년`}</text>
      ))}
      <path d={`${line} L${x(48)},${y(0)} L${x(0)},${y(0)} Z`} className="s1 area" />
      <path d={line} className="line s1-stroke" />
      <line x1={x(mark)} x2={x(mark)} y1={T} y2={y(0)} className="marker" />
      <circle cx={x(mark)} cy={markY} r="5" className="s1 dot-ring" />
      <rect x={x(mark) + 6} y={T} width="74" height="20" rx="6" className="note-bg" />
      <text x={x(mark) + 43} y={T + 14} textAnchor="middle" className="note">중간값 2.1년</text>
    </svg>
  );
}

function Flow() {
  const out: [string, number][] = [["프로덕트", 31], ["데이터·AI", 25], ["전략·기획", 19], ["영업·사업개발", 14], ["기타", 11]];
  const s = 1.16, gap = 6, top = 22, xl = 20, xr = 168;
  let cl = 0, cr = 0;
  return (
    <svg viewBox="0 0 300 168" className="gchart" role="img" aria-label="마케팅을 떠난 사람의 다음 직무: 프로덕트 31%, 데이터·AI 25%, 전략·기획 19%, 영업·사업개발 14%, 기타 11%">
      <path d={`M${xl - 8},${top} H${xl} V${top + 100 * s} H${xl - 8} Z`} className="s1" />
      <text x={xl - 8} y={top - 9} className="lbl">마케팅에서 옮긴 사람</text>
      {out.map(([l, v], i) => {
        const h = v * s;
        const y0 = top + cl * s, y1 = y0 + h;
        const Y0 = top + cr * s + i * gap;
        cl += v; cr += v;
        const mid = (xl + xr) / 2;
        return (
          <g key={l}>
            <path d={`M${xl},${y0} C${mid},${y0} ${mid},${Y0} ${xr},${Y0} L${xr},${Y0 + h} C${mid},${Y0 + h} ${mid},${y1} ${xl},${y1} Z`}
                  className={l === "기타" ? "band other" : i === 0 ? "band s1 strong" : "band s1"}>
              <title>{`마케팅 → ${l} ${v}%`}</title>
            </path>
            <path d={`M${xr},${Y0} H${xr + 6} V${Y0 + h} H${xr} Z`} className={l === "기타" ? "other" : "s1"} />
            <text x={xr + 12} y={Y0 + h / 2 + 4} className="lbl">{l} <tspan className="val">{v}%</tspan></text>
          </g>
        );
      })}
    </svg>
  );
}

function Tenure() {
  const v = [8, 19, 27, 18, 11, 7, 5, 5];
  const L = 22, B = 136, H = 112, w = 270 / v.length;
  return (
    <svg viewBox="0 0 300 168" className="gchart" role="img" aria-label="처음 옮긴 연차 분포: 1년 8%, 2년 19%, 3년 27%, 4년 18%, 5년 11%, 6년 7%, 7년 5%, 8년 이상 5%">
      <line x1={L} x2={L + 270} y1={B} y2={B} className="grid" />
      {v.map((n, i) => {
        const h = (n / 30) * H;
        const x = L + i * w + 3;
        return (
          <g key={i}>
            <path d={vbar(x, B - h, w - 6, h)} className={i === 2 ? "s1" : "s1soft"}><title>{`${i + 1}년 차 ${n}%`}</title></path>
            <text x={x + (w - 6) / 2} y={B + 16} textAnchor="middle" className="ax">{i === 7 ? "8+" : i + 1}</text>
            {i === 2 && <text x={x + (w - 6) / 2} y={B - h - 6} textAnchor="middle" className="val">{n}%</text>}
          </g>
        );
      })}
      <text x={L + 270} y={B + 30} textAnchor="end" className="ax">년 차</text>
    </svg>
  );
}

function CohortLines() {
  const xs = ["12", "14", "16", "18", "20"];
  const series: [string, number[], string][] = [
    ["데이터·AI", [6, 9, 13, 17, 21], "s1"],
    ["재무·금융", [19, 17, 15, 12, 10], "s2"],
    ["마케팅", [15, 16, 16, 15, 14], "s3"],
  ];
  const L = 28, R = 210, T = 12, B = 136;
  const x = (i: number) => L + (i / (xs.length - 1)) * (R - L);
  const y = (v: number) => T + (1 - v / 25) * (B - T);
  return (
    <svg viewBox="0 0 300 168" className="gchart" role="img" aria-label="학번별 첫 직무 비율. 데이터·AI 6%에서 21%, 재무·금융 19%에서 10%, 마케팅 15%에서 14%">
      {[0, 10, 20].map((v) => (
        <g key={v}>
          <line x1={L} x2={R} y1={y(v)} y2={y(v)} className="grid" />
          <text x={L - 6} y={y(v) + 4} textAnchor="end" className="ax">{v}%</text>
        </g>
      ))}
      {xs.map((t, i) => <text key={t} x={x(i)} y={B + 18} textAnchor="middle" className="ax">{t}학번</text>)}
      {series.map(([name, vals, c]) => (
        <g key={name}>
          <path d={vals.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ")} className={`line ${c}-stroke`} />
          {vals.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r="4" className={`${c} dot-ring`}><title>{`${name} ${xs[i]}학번 ${v}%`}</title></circle>)}
          <rect x={R + 10} y={y(vals[4]) - 6} width="8" height="8" rx="2" className={c} />
          <text x={R + 22} y={y(vals[4]) + 2} className="lbl">{name} <tspan className="val">{vals[4]}%</tspan></text>
        </g>
      ))}
    </svg>
  );
}

function Stacked() {
  const cats: [string, string][] = [["대기업", "s1"], ["중견", "s2"], ["스타트업", "s3"]];
  const rows: [string, number[]][] = [["프로덕트", [38, 27, 35]], ["마케팅", [45, 30, 25]], ["데이터·AI", [41, 22, 37]]];
  const X = 72, Wd = 222;
  return (
    <svg viewBox="0 0 300 168" className="gchart" role="img" aria-label="직무별 도착 회사 규모. 프로덕트 대기업 38 중견 27 스타트업 35, 마케팅 45 30 25, 데이터·AI 41 22 37 (%)">
      {cats.map(([c, cls], i) => (
        <g key={c} transform={`translate(${X + i * 74} 12)`}>
          <rect width="10" height="10" rx="2" y="-8" className={cls} />
          <text x="15" y="1" className="lbl">{c}</text>
        </g>
      ))}
      {rows.map(([r, v], ri) => {
        let cx = X;
        const y = 34 + ri * 42;
        return (
          <g key={r}>
            <text x="0" y={y + 15} className="lbl">{r}</text>
            {v.map((p, i) => {
              const w = (p / 100) * Wd - (i < 2 ? 2 : 0);
              const el = (
                <rect key={i} x={cx} y={y} width={w} height="22" rx={i === 0 || i === 2 ? 4 : 0} className={cats[i][1]}>
                  <title>{`${r} · ${cats[i][0]} ${p}%`}</title>
                </rect>
              );
              cx += (p / 100) * Wd;
              return el;
            })}
            <text x={X + Wd} y={y + 36} textAnchor="end" className="ax">스타트업 {v[2]}%</text>
          </g>
        );
      })}
    </svg>
  );
}

function Dumbbell() {
  const rows: [string, number, number][] = [["컨설팅", 14, 6], ["프로덕트", 9, 16], ["공공·행정", 4, 11]];
  const X0 = 84, X1 = 280, x = (v: number) => X0 + (v / 20) * (X1 - X0);
  return (
    <svg viewBox="0 0 300 168" className="gchart" role="img" aria-label="같은 전공의 학교별 첫 직무 비율. 컨설팅 A대 14% B대 6%, 프로덕트 A대 9% B대 16%, 공공·행정 A대 4% B대 11%">
      <g transform="translate(84 12)">
        <circle r="5" cy="-3" className="s1" /><text x="10" y="1" className="lbl">A대학교</text>
        <circle r="5" cx="84" cy="-3" className="s2" /><text x="94" y="1" className="lbl">B대학교</text>
      </g>
      {[0, 10, 20].map((v) => (
        <g key={v}>
          <line x1={x(v)} x2={x(v)} y1={30} y2={142} className="grid" />
          <text x={x(v)} y={158} textAnchor="middle" className="ax">{v}%</text>
        </g>
      ))}
      {rows.map(([r, a, b], i) => {
        const y = 50 + i * 38;
        return (
          <g key={r}>
            <text x="0" y={y + 4} className="lbl">{r}</text>
            <line x1={x(Math.min(a, b))} x2={x(Math.max(a, b))} y1={y} y2={y} className="connector" />
            <circle cx={x(a)} cy={y} r="6" className="s1 dot-ring"><title>{`${r} A대학교 ${a}%`}</title></circle>
            <circle cx={x(b)} cy={y} r="6" className="s2 dot-ring"><title>{`${r} B대학교 ${b}%`}</title></circle>
          </g>
        );
      })}
    </svg>
  );
}
