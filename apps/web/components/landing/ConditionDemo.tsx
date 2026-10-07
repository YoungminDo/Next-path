"use client";

import { useMemo, useState } from "react";

/* Example screen for the landing page. Numbers are illustrative and labelled as such; the
   real product computes them from the cohort engine. The point is to show that every
   condition re-cuts the comparison group, and that narrowing too far is handled openly. */

type Major = "경영학" | "컴퓨터공학" | "심리학";
const MAJORS: Major[] = ["경영학", "컴퓨터공학", "심리학"];
const SCHOOLS = ["A대학교", "B대학교"] as const;
type School = (typeof SCHOOLS)[number];

const BASE: Record<Major, [string, number][]> = {
  경영학: [["마케팅", 24], ["전략·기획", 18], ["재무·금융", 15], ["프로덕트", 13], ["영업·사업개발", 12], ["기타", 18]],
  컴퓨터공학: [["개발·엔지니어링", 46], ["데이터·AI", 19], ["프로덕트", 11], ["컨설팅", 6], ["창업", 5], ["기타", 13]],
  심리학: [["HR·조직", 21], ["마케팅", 17], ["리서치", 16], ["프로덕트", 12], ["공공·행정", 9], ["기타", 25]],
};
// How each condition tilts the example (school culture, cohort year trend).
const SCHOOL_TILT: Record<School, Record<string, number>> = {
  A대학교: { "전략·기획": 4, 컨설팅: 3, "재무·금융": 2 },
  B대학교: { 프로덕트: 4, "데이터·AI": 4, 창업: 2 },
};

function demo(school: School, major: Major, year: number, women: boolean) {
  const recent = (year - 2016) / 8; // 0..1, later cohorts lean to product/data
  const rows = BASE[major].map(([label, v]) => {
    let w = v + (SCHOOL_TILT[school][label] ?? 0);
    if (label === "프로덕트" || label === "데이터·AI") w += 6 * recent;
    if (label === "재무·금융" || label === "영업·사업개발") w -= 3 * recent;
    return [label, Math.max(w, 1)] as [string, number];
  });
  const total = rows.reduce((s, [, w]) => s + w, 0);
  const shares = rows.map(([l, w]) => [l, w / total] as [string, number]);
  const others = shares.filter(([l]) => l === "기타");
  const ranked = shares.filter(([l]) => l !== "기타").sort((a, b) => b[1] - a[1]);

  const exact = Math.round((school === "A대학교" ? 38 : 26) * (major === "심리학" ? 0.7 : 1));
  const widened = Math.round(exact * 11 + (year % 7) * 9);
  const genderN = Math.round(widened * 0.46);
  const reasons = ["졸업 ±2년"];
  let n = widened;
  if (women) {
    if (genderN >= 50) n = genderN;
    else reasons.push("성별 조건 제외");
  }
  return { exact, n, reasons, rows: [...ranked.slice(0, 5), ...others], genderDropped: women && genderN < 50 };
}

export default function ConditionDemo() {
  const [school, setSchool] = useState<School>("A대학교");
  const [major, setMajor] = useState<Major>("경영학");
  const [year, setYear] = useState(2022);
  const [women, setWomen] = useState(false);
  const d = useMemo(() => demo(school, major, year, women), [school, major, year, women]);
  const max = Math.max(...d.rows.map(([, s]) => s));

  return (
    <div className="demo">
      <div className="demo-controls" aria-label="조건">
        <Group label="학교">
          {SCHOOLS.map((s) => (
            <button key={s} className="chip" aria-pressed={school === s} onClick={() => setSchool(s)}>{s}</button>
          ))}
        </Group>
        <Group label="전공">
          {MAJORS.map((m) => (
            <button key={m} className="chip" aria-pressed={major === m} onClick={() => setMajor(m)}>{m}</button>
          ))}
        </Group>
        <Group label={`졸업 ${year}년`}>
          <input type="range" min={2016} max={2024} value={year} aria-label="졸업 연도"
                 onChange={(e) => setYear(Number(e.target.value))} />
        </Group>
        <Group label="더 비슷하게">
          <button className="chip" aria-pressed={women} onClick={() => setWomen(!women)}>여성만 보기</button>
        </Group>
      </div>

      <div className="demo-phone" aria-live="polite">
        <span className="badge sim">예시 화면 · 실제 숫자 아님</span>
        <span className="badge">{d.reasons.join(" · ")}</span>
        <div><span className="big">{d.n}</span><b> 명</b></div>
        <p className="sub">나와 같은 출발점의 사람들이 처음 간 길</p>
        <div className="bars flat">
          {d.rows.map(([label, share], i) => (
            <div key={label} className="bar">
              <span>{label}</span>
              <span className="track">
                <i className={label === "기타" ? "g" : i === 0 ? "" : "m"} style={{ width: `${(share / max) * 100}%` }} />
              </span>
              <b>{Math.round(share * 100)}%</b>
            </div>
          ))}
        </div>
        <p className="hint">
          {d.genderDropped
            ? "여성만으로는 50명이 안 돼서, 개인이 드러나지 않도록 성별 조건을 빼고 보여드려요."
            : `딱 같은 사람은 ${d.exact}명이라, 졸업 ±2년까지 넓혀서 봤어요.`}
        </p>
      </div>
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="demo-group">
      <span className="demo-label">{label}</span>
      <div className="chips">{children}</div>
    </div>
  );
}
