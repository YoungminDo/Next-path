"use client";

import { useEffect, useState } from "react";

import NodeSelect from "@/components/NodeSelect";
import SearchSelect, { type Picked } from "@/components/SearchSelect";
import { acq, type Institution, type Node } from "@/lib/api";
import { track } from "@/lib/track";
import { YEARS } from "@/lib/years";

/* HeyDealer pattern: the answer starts inside the hero. Two tabs (학생·취준생 / 현직자·경력자): four
   answers, plus the current role and start year for people who work; one button, and the flow
   opens directly on the teaser and the free login. School and major are searchable; a name that
   is not in the list is accepted as typed. If the API is unreachable the button still opens the flow. */

type Tab = "student" | "pro";


export default function HeroForm(props: { institutions: Institution[]; majors: Node[]; roles: Node[];
                                          initialTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(props.initialTab ?? "student");
  const [job, setJob] = useState({ role: "", start: "" });
  const [institutions, setInstitutions] = useState(props.institutions);
  const [majors, setMajors] = useState<Node[]>(props.majors);
  const [roles, setRoles] = useState<Node[]>(props.roles);
  const [inst, setInst] = useState<Picked | null>(null);
  const [major, setMajor] = useState<Picked | null>(null);
  const [years, setYears] = useState({ adm: "", grad: "" });
  const [started, setStarted] = useState(false);
  const [tried, setTried] = useState(false); // pressed the button with something missing
  const touched = () => {
    if (started) return;
    setStarted(true);
    track("career_input_started", { surface: "hero" });
  };
  // "error": the API did not answer; "empty": it answered but has no data yet.
  const preloaded = props.institutions.length > 0 && props.majors.length > 0;
  const [status, setStatus] = useState<"loading" | "ok" | "error" | "empty">(preloaded ? "ok" : "loading");

  useEffect(() => {
    // The 현직자 tab needs the role list; a page built while the API was down has none.
    if (!props.roles.length) acq.roles(3).then(setRoles).catch(() => undefined);
  }, [props.roles.length]);

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

  const pro = tab === "pro";
  const yearsOk = years.adm && years.grad && Number(years.adm) <= Number(years.grad);
  const ready = inst && major && yearsOk && (!pro || (job.role && job.start));
  // What is still missing, in form order, so the button can point at it instead of leaving.
  const missing = [
    !inst && { id: "hero-inst", label: "학교" },
    !major && { id: "hero-major", label: "전공" },
    !years.adm && { id: "hero-adm", label: "입학 연도" },
    !years.grad && { id: "hero-grad", label: "졸업 연도" },
    pro && !job.role && { id: "hero-role", label: "지금 직무" },
    pro && !job.start && { id: "hero-start", label: "입사 연도" },
  ].filter(Boolean) as { id: string; label: string }[];
  const params = new URLSearchParams({ type: pro ? "pro" : "student" });
  if (ready) {
    params.set(inst.id ? "inst" : "inst_raw", inst.id ?? inst.label);
    params.set(major.id ? "major" : "major_raw", major.id ?? major.label);
    params.set("adm", years.adm);
    params.set("grad", years.grad);
    if (pro) {
      params.set("role", job.role);
      params.set("start", job.start);
    }
  }
  const href = `/start?${params.toString()}`;

  return (
    <form id="hero-form" className="heroform" onSubmit={(e) => {
      e.preventDefault();
      if (ready) {
        window.location.href = href;
        return;
      }
      setTried(true);
      document.getElementById(missing[0]?.id ?? "hero-adm")?.focus();
    }}>
      <p className="heroform-title">무료로 내 진로 지도 받기</p>
      <div className="herotabs" role="tablist" aria-label="지금 나는">
        {([["student", "학생·취준생"], ["pro", "현직자·경력자"]] as [Tab, string][]).map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key}
                  onClick={() => { setTab(key); setTried(false); }}>{label}</button>
        ))}
      </div>
      <SearchSelect inputId="hero-inst" ariaLabel="학교" noun="학교" placeholder="학교 검색 (예: 고려대, ㄱㄹㄷ)"
                    items={institutions.map((i) => ({ id: i.id, label: i.name, keywords: i.aliases ?? [] }))}
                    value={inst} onChange={(v) => picked("school", v)} invalid={tried && !inst} onType={touched} />
      <SearchSelect inputId="hero-major" ariaLabel="전공" noun="전공" placeholder="전공 검색 (예: 경영, 컴퓨터)"
                    items={majors.map((n) => ({ id: n.node_id, label: n.label, group: n.parent_label,
                                                keywords: n.aliases ?? [] }))}
                    value={major} onChange={(v) => picked("major", v)} invalid={tried && !major} suggestSimilar
                    onType={touched} />
      <div className="pair">
        <select id="hero-adm" aria-label="입학 연도" value={years.adm} aria-invalid={tried && !years.adm}
                onChange={(e) => { touched(); setYears({ ...years, adm: e.target.value }); }}>
          <option value="">입학 연도</option>
          {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <select id="hero-grad" aria-label="졸업 연도" value={years.grad} aria-invalid={tried && !years.grad}
                onChange={(e) => { touched(); setYears({ ...years, grad: e.target.value }); }}>
          <option value="">{pro ? "졸업 연도" : "졸업 (예정)"}</option>
          {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
      {pro && (
        <div className="pair">
          <NodeSelect id="hero-role" nodes={roles} value={job.role} empty="지금 직무" ariaLabel="지금 직무"
                      invalid={tried && !job.role} onChange={(v) => { touched(); setJob({ ...job, role: v }); }} />
          <select id="hero-start" aria-label="입사 연도" value={job.start} aria-invalid={tried && !job.start}
                  onChange={(e) => { touched(); setJob({ ...job, start: e.target.value }); }}>
            <option value="">입사 연도</option>
            {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
      )}
      {status === "error" && <p className="heroform-warn" role="status">서버에 연결하지 못했어요. 잠시 후 새로고침해 주세요.</p>}
      {status === "empty" && <p className="heroform-warn" role="status">학교·전공 데이터를 준비하고 있어요. 잠시 후 다시 와주세요.</p>}
      <button className="cta" type="submit">나와 같은 자리였던 사람들 보기</button>
      {tried && !ready && (
        <p className="heroform-warn" role="alert">
          {missing.length
            ? `${missing.map((m) => m.label).join(", ")}만 고르면 바로 볼 수 있어요`
            : "졸업 연도가 입학 연도보다 빨라요"}
        </p>
      )}
      <p className="heroform-note">카카오로 3초 · 무료</p>
      <a className="heroform-upload" href="/upload">
        <b>이력서·링*드인 캡처로 시작하기</b>
        <span>기존 만들어둔 이력서, 링*드인 캡처 등을 올리시면 됩니다.</span>
      </a>
    </form>
  );
}
