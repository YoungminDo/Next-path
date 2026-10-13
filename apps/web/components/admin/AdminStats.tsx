"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { AdminError, loadStats, type AdminRange, type AdminStats as Stats, type Daily, type Named } from "@/lib/admin";

/* Team dashboard. One filter row scopes everything below it; each chart has a table twin; colors
   follow the dataviz method (single hue for one series, validated categorical slots for three). */

const RANGES: { key: AdminRange; label: string }[] = [
  { key: "today", label: "오늘" }, { key: "7d", label: "최근 7일" }, { key: "30d", label: "최근 30일" },
  { key: "all", label: "전체" },
];
const SERIES: { key: keyof Omit<Daily, "day">; label: string; color: string }[] = [
  { key: "landing", label: "방문", color: "var(--viz-1)" },
  { key: "input_completed", label: "입력 완료", color: "var(--viz-2)" },
  { key: "signup", label: "로그인 완료", color: "var(--viz-3)" },
];
const DESIRED: Record<string, string> = {
  CHOSEN: "희망 직무 고름", NONE: "아직 없어요", KEEP_CURRENT: "지금 직무 유지", UNSURE: "모르겠어요",
  SKIPPED: "답하지 않음",
};
const KIND: Record<string, string> = { INSTITUTION: "학교", MAJOR: "전공", ROLE: "직무" };
const DEV_LOGIN = process.env.NEXT_PUBLIC_ENABLE_DEV_LOGIN === "true";

const fmt = (n: number | null | undefined) => (n == null ? "–" : n.toLocaleString("ko-KR"));
const pct = (a: number, b: number) => (b > 0 ? `${Math.round((a / b) * 1000) / 10}%` : "–");

export default function AdminStats() {
  const [range, setRange] = useState<AdminRange>("7d");
  const [withTeam, setWithTeam] = useState(false);
  const [data, setData] = useState<Stats>();
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState<AdminError>();
  const [failed, setFailed] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setFailed(false);
    loadStats(range, withTeam)
      .then((d) => { setData(d); setDenied(undefined); })
      .catch((e) => (e instanceof AdminError ? setDenied(e) : setFailed(true)))
      .finally(() => setLoading(false));
  }, [range, withTeam]);
  useEffect(load, [load]);

  if (denied?.status === 401) {
    return (
      <main className="admin">
        <h1 className="admin-title">nextpath 팀 대시보드</h1>
        <p className="sub">팀원 계정으로 로그인하면 수요 테스트 숫자를 볼 수 있어요.</p>
        <a className="cta kakao admin-login" href="/auth/hmm/start?next=/admin">카카오로 로그인</a>
        {DEV_LOGIN && (
          <button className="cta ghost admin-login" onClick={async () => { await fetch("/auth/dev", { method: "POST" }); load(); }}>
            개발용 로그인
          </button>
        )}
      </main>
    );
  }
  if (denied?.status === 403) {
    const copy = async () => {
      try { await navigator.clipboard.writeText(denied.accountId ?? ""); setCopied(true); } catch { /* no clipboard */ }
    };
    return (
      <main className="admin">
        <h1 className="admin-title">nextpath 팀 대시보드</h1>
        <p className="sub">이 계정은 아직 팀 대시보드를 볼 수 없어요. 아래 계정 번호를 관리자에게 전달해 주세요.</p>
        <p className="admin-id"><code>{denied.accountId}</code>
          <button className="link" onClick={copy}>{copied ? "복사했어요" : "복사"}</button></p>
        <button className="link" onClick={async () => { await fetch("/auth/logout", { method: "POST" }); load(); }}>
          다른 계정으로 로그인
        </button>
      </main>
    );
  }

  const f = data?.funnel ?? [];
  const step = (key: string) => f.find((s) => s.key === key)?.people ?? 0;

  return (
    <main className="admin">
      <header className="admin-head">
        <div>
          <h1 className="admin-title">nextpath 팀 대시보드</h1>
          <p className="hint">사람 수 = 브라우저(익명 세션) 수 · 한국 시간 기준{data?.since ? ` · ${new Date(data.since).toLocaleDateString("ko-KR")}부터` : ""}</p>
        </div>
        <button className="link" onClick={async () => { await fetch("/auth/logout", { method: "POST" }); load(); }}>로그아웃</button>
      </header>

      <div className="admin-filters" role="group" aria-label="기간">
        {RANGES.map((r) => (
          <button key={r.key} className="chip" aria-pressed={range === r.key} onClick={() => setRange(r.key)}>{r.label}</button>
        ))}
        <label className="check admin-team">
          <input type="checkbox" checked={withTeam} onChange={(e) => setWithTeam(e.target.checked)} /> 팀 기록 포함
        </label>
        <button className="link" onClick={load} disabled={loading}>새로고침</button>
      </div>
      {failed && <p className="error" role="alert">숫자를 불러오지 못했어요. 새로고침을 눌러 주세요.</p>}
      {!data && loading && <p className="hint">불러오는 중…</p>}

      {data && (
        <div className={loading ? "admin-body refreshing" : "admin-body"} aria-busy={loading}>
          <section className="kpis">
            <Kpi label="방문" value={step("landing")} />
            <Kpi label="학교 정보 입력 완료" value={step("input_completed")} sub={`방문 대비 ${pct(step("input_completed"), step("landing"))}`} />
            <Kpi label="로그인 완료" value={step("signup")} sub={`미리보기 대비 ${pct(step("signup"), step("preview"))}`} />
            <Kpi label="인터뷰 신청" value={data.interview.applied_in_range} sub={`누적 ${fmt(data.interview.applied)}명`} />
          </section>

          <Card title="퍼널" note="단계마다 따로 셉니다. /start로 바로 들어온 사람은 랜딩을 거치지 않아 100%를 넘을 수 있어요."
                table={<Table head={["단계", "사람", "방문 대비", "이전 단계 대비"]} rows={f.map((s, i) => [
                  s.label, fmt(s.people), pct(s.people, f[0]?.people ?? 0), i ? pct(s.people, f[i - 1].people) : "–"])} />}>
            <Bars items={f.map((s, i) => ({ label: s.label, value: s.people,
              end: `${fmt(s.people)}명 · ${pct(s.people, f[0]?.people ?? 0)}`,
              detail: i ? `이전 단계 대비 ${pct(s.people, f[i - 1].people)}` : "첫 단계" }))} />
          </Card>

          <Card title="날짜별 추이" table={<Table head={["날짜", ...SERIES.map((s) => s.label)]}
                rows={data.daily.map((d) => [d.day, ...SERIES.map((s) => fmt(d[s.key]))])} />}>
            {data.daily.length ? <Trend days={data.daily} /> : <p className="hint">아직 기록이 없어요.</p>}
          </Card>

          <Card title="입력한 사람" note="저장된 입력(DB) 기준. 가입하지 않고 떠난 사람도 포함돼요.">
            <div className="mini-kpis">
              <Mini label="입력한 사람" value={data.inputs.people} />
              <Mini label="직장인" value={data.inputs.professionals} />
              <Mini label="목록 밖 학교" value={data.inputs.unlisted_school} />
              <Mini label="목록 밖 전공" value={data.inputs.unlisted_major} />
              <Mini label="로그인으로 연결" value={data.inputs.linked} />
            </div>
            <div className="grid2">
              <NamedTable title="학교" items={data.schools} />
              <NamedTable title="전공" items={data.majors} />
            </div>
            <h4 className="admin-sub">학교 × 전공</h4>
            <Table text={2} head={["학교", "전공", "사람"]} rows={data.combos.map((c) => [c.school ?? "–", c.major ?? "–", fmt(c.people)])} />
          </Card>

          <Card title="희망 직무" note="질문이 생긴 뒤(10/12) 저장된 입력 기준. ‘답하지 않음’은 질문을 건너뛴 사람이에요."
                table={<Table head={["응답", "사람"]} rows={data.desired_status.map((d) => [DESIRED[d.status] ?? d.status, fmt(d.people)])} />}>
            {data.desired_status.length ? (
              <Bars items={data.desired_status.map((d) => ({ label: DESIRED[d.status] ?? d.status, value: d.people,
                end: `${fmt(d.people)}명 · ${pct(d.people, data.desired_status.reduce((a, x) => a + x.people, 0))}` }))} />
            ) : <p className="hint">아직 응답이 없어요.</p>}
            <h4 className="admin-sub">고른 직무</h4>
            <Table head={["직무", "사람", "1순위"]} rows={data.desired_roles.map((r) => [
              <NameCell key={r.name} item={r} />, fmt(r.people), fmt(r.first_choice)])} />
          </Card>

          <Card title="채널" note="첫 방문의 utm_source → 인앱 앱(instagram 등) → 이전 사이트 순으로 정해요.">
            <Table head={["채널", "방문", "입력 완료", "로그인", "결과 확인", "입력률"]} rows={data.channels.map((c) => [
              c.channel, fmt(c.landing), fmt(c.input_completed), fmt(c.signup), fmt(c.result), pct(c.input_completed, c.landing)])} />
          </Card>

          <Card title="결과 화면에 머문 시간">
            <Table head={["화면", "조회", "중앙값"]} rows={data.dwell.map((d) => [
              d.label, fmt(d.views), d.median_seconds == null ? "–" : `${Math.round(d.median_seconds)}초`])} />
          </Card>

          <Card title="표준화 대기 (전체 기간)" note="목록에 없어 직접 입력한 이름. 철자만 다른 이름은 묶어서 셉니다.">
            <Table text={2} head={["종류", "가장 많이 쓴 이름", "사람", "철자"]} rows={data.backlog.map((b) => [
              KIND[b.kind] ?? b.kind, b.name, fmt(b.people), `${b.spellings}가지`])} />
          </Card>

          <Card title="진로 인터뷰" note="번호는 이 화면에 나오지 않아요. 신청 수는 계정 기준(팀 계정 포함).">
            <div className="mini-kpis">
              <Mini label="초대 화면 본 사람" value={data.interview.shown} />
              <Mini label="다음에 할게요" value={data.interview.skipped} />
              <Mini label="신청 (기간)" value={data.interview.applied_in_range} />
              <Mini label="신청 중 (누적)" value={data.interview.applied} />
              <Mini label="번호 인증됨" value={data.interview.verified} />
              <Mini label="철회" value={data.interview.withdrawn} />
            </div>
          </Card>

          <Card title="이력서·캡처로 시작" note={`파일은 저장하지 않아요. 비용은 정가 기준 추정치예요 (약 $${data.imports.est_cost_usd.toFixed(2)}).`}>
            <div className="mini-kpis">
              <Mini label="읽기 요청" value={data.imports.reads} />
              <Mini label="로그인 전" value={data.imports.before_login} />
              <Mini label="읽기 성공" value={data.imports.parsed} />
              <Mini label="경력 문서 아님" value={data.imports.not_career} />
              <Mini label="실패" value={data.imports.failed} />
              <Mini label="미리보기까지" value={data.imports.drafts} />
              <Mini label="로그인까지" value={data.imports.signed_up} />
            </div>
          </Card>
        </div>
      )}
    </main>
  );
}

function Kpi({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{fmt(value)}</span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

function Mini({ label, value }: { label: string; value: number }) {
  return <div className="mini"><span>{label}</span><b>{fmt(value)}</b></div>;
}

function Card({ title, note, table, children }: {
  title: string; note?: string; table?: React.ReactNode; children: React.ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="card admin-card">
      <div className="row-between">
        <h3>{title}</h3>
        {table && <button className="link" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>{asTable ? "차트로 보기" : "표로 보기"}</button>}
      </div>
      {note && <p className="hint">{note}</p>}
      {asTable && table ? table : children}
    </section>
  );
}

/** Text columns (the first `text` columns) align left, numbers right. */
function Table({ head, rows, text = 1 }: { head: string[]; rows: React.ReactNode[][]; text?: number }) {
  if (!rows.length) return <p className="hint">아직 기록이 없어요.</p>;
  const cls = (j: number) => (j >= text ? "num" : undefined);
  return (
    <div className="atable-wrap">
      <table className="atable">
        <thead><tr>{head.map((h, j) => <th key={h} className={cls(j)}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => (
          <tr key={i}>{r.map((c, j) => <td key={j} className={cls(j)}>{c}</td>)}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function NameCell({ item }: { item: Named }) {
  return <>{item.name}{!item.listed && <span className="tag">목록 밖</span>}</>;
}

function NamedTable({ title, items }: { title: string; items: Named[] }) {
  return (
    <div>
      <h4 className="admin-sub">{title}</h4>
      <Table head={[title, "사람"]} rows={items.map((s) => [<NameCell key={s.name} item={s} />, fmt(s.people)])} />
    </div>
  );
}

/** One series, so one hue for every bar; the value sits at the bar's end, details on hover/focus. */
function Bars({ items }: { items: { label: string; value: number; end: string; detail?: string }[] }) {
  const [tip, setTip] = useState<{ i: number; x: number; y: number }>();
  const box = useRef<HTMLDivElement>(null);
  const max = Math.max(...items.map((i) => i.value), 1);
  const show = (i: number, el: HTMLElement) => {
    const b = box.current?.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (b) setTip({ i, x: r.left - b.left + 8, y: r.top - b.top - 6 });
  };
  return (
    <div className="hbars" ref={box} onPointerLeave={() => setTip(undefined)}>
      {items.map((it, i) => (
        <div key={it.label} className="hbar" tabIndex={0} aria-label={`${it.label} ${it.end}${it.detail ? `, ${it.detail}` : ""}`}
             onPointerEnter={(e) => show(i, e.currentTarget)} onFocus={(e) => show(i, e.currentTarget)}
             onBlur={() => setTip(undefined)}>
          <span className="hbar-label">{it.label}</span>
          <span className="hbar-track">
            <i style={{ width: `${(it.value / max) * 100}%` }} className={tip?.i === i ? "on" : undefined} />
          </span>
          <span className="hbar-end">{it.end}</span>
        </div>
      ))}
      {tip && items[tip.i] && (
        <div className="viz-tip" style={{ left: tip.x, top: tip.y }} role="status">
          <b>{items[tip.i].end}</b>
          <span>{items[tip.i].label}{items[tip.i].detail ? ` · ${items[tip.i].detail}` : ""}</span>
        </div>
      )}
    </div>
  );
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function niceMax(v: number) {
  if (v <= 4) return 4;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v) ?? v;
}

/** Three series, one axis (all are people per day). Crosshair + tooltip; legend always shown. */
function Trend({ days }: { days: Daily[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [at, setAt] = useState<number | null>(null);
  const H = 220, M = { l: 36, r: 56, t: 12, b: 28 };
  const w = Math.max(width - M.l - M.r, 10), h = H - M.t - M.b;
  const top = niceMax(Math.max(...days.flatMap((d) => SERIES.map((s) => d[s.key])), 1));
  const x = (i: number) => M.l + (days.length === 1 ? w / 2 : (i / (days.length - 1)) * w);
  const y = (v: number) => M.t + h - (v / top) * h;
  const ticks = [0, top / 2, top];
  const last = days.length - 1;
  // Direct end labels only while they don't collide; otherwise the legend and tooltip carry it.
  const ends = SERIES.map((s) => y(days[last][s.key])).sort((a, b) => a - b);
  const labelled = ends.every((v, i) => i === 0 || v - ends[i - 1] >= 14);
  const xTicks = days.length <= 2 ? days.map((_, i) => i) : [0, Math.floor(last / 2), last];
  const pick = (clientX: number, el: Element) => {
    const r = el.getBoundingClientRect();
    const i = days.length === 1 ? 0 : Math.round(((clientX - r.left - M.l) / w) * last);
    setAt(Math.max(0, Math.min(last, i)));
  };
  const md = (d: string) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`;
  return (
    <div className="trend" ref={ref}>
      <div className="legend">{SERIES.map((s) => (
        <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>
      ))}</div>
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label="날짜별 방문, 입력 완료, 로그인 완료 추이"
             tabIndex={0} onPointerMove={(e) => pick(e.clientX, e.currentTarget)} onPointerLeave={() => setAt(null)}
             onKeyDown={(e) => {
               if (e.key === "ArrowRight") setAt((a) => Math.min(last, (a ?? -1) + 1));
               if (e.key === "ArrowLeft") setAt((a) => Math.max(0, (a ?? last + 1) - 1));
             }} onBlur={() => setAt(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.l} x2={M.l + w} y1={y(t)} y2={y(t)} className="grid" />
              <text x={M.l - 6} y={y(t) + 4} textAnchor="end" className="tick">{fmt(Math.round(t))}</text>
            </g>
          ))}
          {xTicks.map((i) => (
            <text key={i} x={x(i)} y={H - 8} textAnchor={i === 0 && days.length > 1 ? "start" : i === last && days.length > 1 ? "end" : "middle"}
                  className="tick">{md(days[i].day)}</text>
          ))}
          {SERIES.map((s) => (
            <g key={s.key}>
              {days.length > 1 && (
                <polyline fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
                          points={days.map((d, i) => `${x(i)},${y(d[s.key])}`).join(" ")} />
              )}
              <circle cx={x(last)} cy={y(days[last][s.key])} r={4} fill={s.color} className="ring" />
              {labelled && (
                <text x={x(last) + 8} y={y(days[last][s.key]) + 4} className="end">{fmt(days[last][s.key])}</text>
              )}
            </g>
          ))}
          {at !== null && (
            <g>
              <line x1={x(at)} x2={x(at)} y1={M.t} y2={M.t + h} className="cross" />
              {SERIES.map((s) => <circle key={s.key} cx={x(at)} cy={y(days[at][s.key])} r={4} fill={s.color} className="ring" />)}
            </g>
          )}
        </svg>
      )}
      {at !== null && (
        <div className="viz-tip" role="status"
             style={{ left: Math.min(Math.max(x(at) - 60, 0), Math.max(width - 140, 0)), top: 28 }}>
          <span>{days[at].day}</span>
          {SERIES.map((s) => (
            <span key={s.key} className="tip-row"><i style={{ background: s.color }} /><b>{fmt(days[at][s.key])}</b> {s.label}</span>
          ))}
        </div>
      )}
    </div>
  );
}
