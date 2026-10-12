"use client";

import { useEffect, useState } from "react";

import SearchSelect, { type Picked } from "@/components/SearchSelect";
import { acq, type Node } from "@/lib/api";
import { track } from "@/lib/track";

/* HeyDealer pattern: the answer starts inside the hero. Four answers, one button, and the flow
   opens directly on the teaser and the free login. School and major are searchable; a name that
   is not in the list is accepted as typed. If the API is unreachable the button still opens the flow. */

const THIS_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 22 }, (_, i) => THIS_YEAR + 4 - i);

export default function HeroForm(props: { institutions: { id: string; name: string }[]; majors: Node[] }) {
  const [institutions, setInstitutions] = useState(props.institutions);
  const [majors, setMajors] = useState<Node[]>(props.majors);
  const [inst, setInst] = useState<Picked | null>(null);
  const [major, setMajor] = useState<Picked | null>(null);
  const [years, setYears] = useState({ adm: "", grad: "" });
  const [started, setStarted] = useState(false);
  const touched = () => {
    if (started) return;
    setStarted(true);
    track("career_input_started", { surface: "hero" });
  };
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

  function picked(kind: "school" | "major", v: Picked | null) {
    touched();
    (kind === "school" ? setInst : setMajor)(v);
    // A name outside the list is a demand signal even if they stop here.
    if (v && v.id === null) track("school_requested", { kind, name: v.label, surface: "hero" });
  }

  const ready = inst && major && years.adm && years.grad && Number(years.adm) <= Number(years.grad);
  const params = new URLSearchParams({ type: "student" });
  if (ready) {
    params.set(inst.id ? "inst" : "inst_raw", inst.id ?? inst.label);
    params.set(major.id ? "major" : "major_raw", major.id ?? major.label);
    params.set("adm", years.adm);
    params.set("grad", years.grad);
  }
  const href = `/start?${params.toString()}`;

  return (
    <form id="hero-form" className="heroform" onSubmit={(e) => { e.preventDefault(); window.location.href = href; }}>
      <p className="heroform-title">무료로 내 진로 지도 받기</p>
      <SearchSelect inputId="hero-inst" ariaLabel="학교" noun="학교" placeholder="학교 검색 (예: 고려대, ㄱㄹㄷ)"
                    items={institutions.map((i) => ({ id: i.id, label: i.name }))}
                    value={inst} onChange={(v) => picked("school", v)} />
      <SearchSelect inputId="hero-major" ariaLabel="전공" noun="전공" placeholder="전공 검색 (예: 경영, 컴퓨터)"
                    items={majors.map((n) => ({ id: n.node_id, label: n.label, group: n.parent_label,
                                                keywords: n.matched_alias ? [n.matched_alias] : [] }))}
                    value={major} onChange={(v) => picked("major", v)} />
      <div className="pair">
        <select id="hero-adm" aria-label="입학 연도" value={years.adm}
                onChange={(e) => { touched(); setYears({ ...years, adm: e.target.value }); }}>
          <option value="">입학 연도</option>
          {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <select id="hero-grad" aria-label="졸업 연도" value={years.grad}
                onChange={(e) => { touched(); setYears({ ...years, grad: e.target.value }); }}>
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
