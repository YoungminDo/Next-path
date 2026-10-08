"use client";

import { useEffect, useMemo, useState } from "react";

import { acq, type Node } from "@/lib/api";

/* HeyDealer pattern: the answer starts inside the hero. Four picks, one button, and the flow
   opens directly on the teaser and the free login. If the API is unreachable the button still opens the flow. */

const THIS_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 22 }, (_, i) => THIS_YEAR + 4 - i);

export default function HeroForm(props: { institutions: { id: string; name: string }[]; majors: Node[] }) {
  const [institutions, setInstitutions] = useState(props.institutions);
  const [majors, setMajors] = useState<Node[]>(props.majors);
  const [f, setF] = useState({ inst: "", major: "", adm: "", grad: "" });
  // "error": the API did not answer; "empty": it answered but has no data yet.
  const preloaded = props.institutions.length > 0 && props.majors.length > 0;
  const [status, setStatus] = useState<"loading" | "ok" | "error" | "empty">(preloaded ? "ok" : "loading");

  useEffect(() => {
    if (preloaded) return; // already in the HTML
    Promise.all([acq.institutions(), acq.majors(3)])
      .then(([i, m]) => {
        setInstitutions(i);
        setMajors(m);
        setStatus(i.length && m.length ? "ok" : "empty");
      })
      .catch(() => setStatus("error"));
  }, [preloaded]);

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
      {status === "error" && <p className="heroform-warn" role="status">서버에 연결하지 못했어요. 잠시 후 새로고침해 주세요.</p>}
      {status === "empty" && <p className="heroform-warn" role="status">학교·전공 데이터를 준비하고 있어요. 잠시 후 다시 와주세요.</p>}
      <button className="cta" type="submit">나와 같은 자리였던 사람들 보기</button>
      <p className="heroform-note">카카오로 3초 · 무료 · 광고 연락 없음</p>
      <a className="heroform-alt" href="/start?type=pro">지금 일하고 있어요 →</a>
    </form>
  );
}
