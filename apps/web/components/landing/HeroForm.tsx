"use client";

import { useEffect, useMemo, useState } from "react";

import { acq, type Node } from "@/lib/api";

/* HeyDealer pattern: the answer starts inside the hero. Four picks, one button, and the flow
   opens directly on the teaser and the free login. If the API is unreachable the button still opens the flow. */

const THIS_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 22 }, (_, i) => THIS_YEAR + 4 - i);

export default function HeroForm() {
  const [institutions, setInstitutions] = useState<{ id: string; name: string }[]>([]);
  const [majors, setMajors] = useState<Node[]>([]);
  const [f, setF] = useState({ inst: "", major: "", adm: "", grad: "" });

  useEffect(() => {
    acq.institutions().then(setInstitutions).catch(() => undefined);
    acq.majors(3).then(setMajors).catch(() => undefined);
  }, []);

  const groups = useMemo(() => {
    const g = new Map<string, Node[]>();
    majors.forEach((n) => g.set(n.parent_label ?? "", [...(g.get(n.parent_label ?? "") ?? []), n]));
    return [...g.entries()];
  }, [majors]);

  const ready = f.inst && f.major && f.adm && f.grad && Number(f.adm) <= Number(f.grad);
  const href = ready
    ? `/start?${new URLSearchParams({ type: "student", ...f }).toString()}`
    : "/start?type=student";

  return (
    <form id="hero-form" className="heroform" onSubmit={(e) => { e.preventDefault(); window.location.href = href; }}>
      <p className="heroform-title">무료로 내 진로 지도 받기</p>
      <select id="hero-inst" aria-label="학교" value={f.inst} onChange={(e) => setF({ ...f, inst: e.target.value })}>
        <option value="">학교 선택</option>
        {institutions.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
      </select>
      <select id="hero-major" aria-label="전공" value={f.major} onChange={(e) => setF({ ...f, major: e.target.value })}>
        <option value="">전공 선택</option>
        {groups.map(([parent, list]) => (
          <optgroup key={parent} label={parent}>
            {list.map((n) => <option key={n.node_id} value={n.node_id}>{n.label}</option>)}
          </optgroup>
        ))}
      </select>
      <div className="pair">
        <select id="hero-adm" aria-label="입학 연도" value={f.adm} onChange={(e) => setF({ ...f, adm: e.target.value })}>
          <option value="">입학 연도</option>
          {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <select id="hero-grad" aria-label="졸업 연도" value={f.grad} onChange={(e) => setF({ ...f, grad: e.target.value })}>
          <option value="">졸업 (예정)</option>
          {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
      <button className="cta" type="submit">나와 같은 자리였던 사람들 보기</button>
      <p className="heroform-note">카카오로 3초 · 무료 · 광고 연락 없음</p>
      <a className="heroform-alt" href="/start?type=pro">지금 일하고 있어요 →</a>
    </form>
  );
}
