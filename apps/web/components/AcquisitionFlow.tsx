"use client";

import { useEffect, useMemo, useState } from "react";

import type { Options } from "@/lib/server/options";
import {
  acq,
  api,
  ApiError,
  pending,
  type Cell,
  type MyResult,
  type Node,
  type QueryResult,
  type StepResult,
  type TeaserResult,
} from "@/lib/api";

/* Order (product decision): input -> teaser (how many people, how many directions) -> login ->
   every distribution, intent and path. The server enforces the same gate: before login it only
   answers the teaser. Tone: "people who stood where I stand", never "seniors". */
type Screen =
  | "start" | "s_edu" | "p_now" | "gate"
  | "s_result" | "s_intent" | "p_next" | "p_first" | "p_similar" | "me";
type UserType = "STUDENT" | "PROFESSIONAL";

const DEV_LOGIN = process.env.NEXT_PUBLIC_ENABLE_DEV_LOGIN === "true";
const CONSENT_VERSION = process.env.NEXT_PUBLIC_CONSENT_POLICY_VERSION ?? "career_terms_v1";
const THIS_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 30 }, (_, i) => THIS_YEAR + 4 - i);

const REASONS: Record<string, string> = {
  WIDEN_GRADUATION_YEAR_2Y: "졸업 ±2년",
  WIDEN_ADMISSION_YEAR_2Y: "입학 ±2년",
  BROADEN_MAJOR_1_LEVEL: "비슷한 전공 계열",
  DROP_GENDER: "성별 조건 제외",
  DROP_ADMISSION_YEAR: "입학연도 제외",
  DROP_GRADUATION_YEAR: "졸업연도 제외",
  DROP_INSTITUTION: "다른 학교 포함",
};
const SIZES: Record<string, string> = {
  ENTERPRISE: "대기업", LARGE: "대형", MID: "중견", SMALL: "소형", MICRO: "초소형",
  OTHER: "기타",
};
const LOGIN_ERRORS: Record<string, string> = {
  kakao_denied: "카카오 로그인이 취소됐어요.",
  no_hmm_session: "로그인 정보를 받지 못했어요. 다시 시도해 주세요.",
  hmm_token_rejected: "로그인이 만료됐어요. 다시 시도해 주세요.",
};

type Edu = { institution_id: string; major_node_id: string; admission_year: string; graduation_year: string };
type Job = { organization_name: string; role_node_id: string; start_year: string; end_year: string };
const emptyJob: Job = { organization_name: "", role_node_id: "", start_year: "", end_year: "" };

function cellLabel(c: Cell, professional: boolean) {
  if (c.code === "STAYED") return professional ? "지금 직무 유지" : "그대로";
  return c.label ?? c.code;
}

/** Korean particle 으로/로 by the last syllable (ㄹ or no final consonant -> 로). */
export function ro(word: string): string {
  const c = word.charCodeAt(word.length - 1) - 0xac00;
  if (c < 0 || c > 11171) return `${word}(으)로`;
  const jong = c % 28;
  return `${word}${jong === 0 || jong === 8 ? "로" : "으로"}`;
}

function reasonText(reasons: string[]) {
  return reasons.map((r) => REASONS[r] ?? r).join(" · ");
}

/** One sentence that says what the bars mean, leaning on how many paths there were. */
function conclusion(r: QueryResult & { n_directions?: number | null }, professional: boolean): string | null {
  if (r.suppressed) return null;
  const moves = r.cells.filter((c) => c.code !== "STAYED");
  const stayed = r.cells.find((c) => c.code === "STAYED");
  const top = moves[0];
  if (!top) return null;
  const pct = (x: number) => Math.round(x * 100);
  const dirs = r.n_directions ?? moves.length;
  if (professional && stayed) {
    return `${100 - pct(stayed.share)}%는 다른 길로 움직였고, 가장 많이 간 곳은 ${top.label}(${pct(top.share)}%)예요.`;
  }
  return dirs > 1
    ? `가장 많이 간 길은 ${top.label}(${pct(top.share)}%)이지만, 나머지 ${100 - pct(top.share)}%는 다른 ${dirs - 1}가지 길을 골랐어요.`
    : `모두 ${ro(top.label ?? "")} 갔어요.`;
}

export default function AcquisitionFlow({ initial }: { initial?: Options }) {
  const [screen, setScreen] = useState<Screen>("start");
  const [userType, setUserType] = useState<UserType>("STUDENT");
  const [institutions, setInstitutions] = useState<{ id: string; name: string }[]>(initial?.institutions ?? []);
  const [majors, setMajors] = useState<Node[]>(initial?.majors ?? []);
  const [roles, setRoles] = useState<Node[]>(initial?.roles ?? []);
  const [middleRoles, setMiddleRoles] = useState<Node[]>(initial?.middleRoles ?? []);
  const [edu, setEdu] = useState<Edu>({ institution_id: "", major_node_id: "", admission_year: "", graduation_year: "" });
  const [current, setCurrent] = useState<Job>(emptyJob);
  const [first, setFirst] = useState<Job>(emptyJob);
  const [firstIsCurrent, setFirstIsCurrent] = useState(false);
  const [intent, setIntent] = useState<string>(""); // node id or "UNDECIDED"
  const [draftId, setDraftId] = useState<string>();
  const [teaser, setTeaser] = useState<TeaserResult>();
  const [base, setBase] = useState<StepResult>();
  const [similar, setSimilar] = useState<StepResult>();
  const [consent, setConsent] = useState(false);
  const [me, setMe] = useState<MyResult>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const professional = userType === "PROFESSIONAL";
  const simulation = (me?.data_basis ?? base?.data_basis ?? teaser?.data_basis) === "SIMULATION";

  const run = (fn: () => Promise<void>) => () => {
    setError(undefined);
    setBusy(true);
    fn()
      .catch((e) => setError(e instanceof ApiError ? friendly(e) : "연결이 불안정해요. 잠시 후 다시 시도해 주세요."))
      .finally(() => setBusy(false));
  };

  useEffect(() => {
    const preloaded = initial && initial.institutions.length && initial.majors.length &&
      initial.roles.length && initial.middleRoles.length;
    if (!preloaded) Promise.all([acq.institutions(), acq.majors(3), acq.roles(3), acq.roles(2)])
      .then(([i, m, r, r2]) => {
        setInstitutions(i);
        setMajors(m);
        setRoles(r);
        setMiddleRoles(r2);
        if (!i.length || !m.length) setError("학교·전공 데이터를 준비하고 있어요. 잠시 후 다시 와주세요.");
      })
      .catch(() => setError("서버에 연결하지 못했어요. 잠시 후 새로고침해 주세요."));
    const params = new URLSearchParams(window.location.search);
    const loginError = params.get("login_error");
    const loggedIn = params.get("login") === "success";
    if (loginError || loggedIn) window.history.replaceState(null, "", window.location.pathname);
    if (loginError) setError(LOGIN_ERRORS[loginError] ?? `로그인에 실패했어요 (${loginError}).`);
    if (loggedIn) {
      run(finishLogin)();
      return;
    }
    const type = params.get("type");
    if (type === "pro") { setUserType("PROFESSIONAL"); setScreen("p_now"); }
    if (type === "student") {
      setScreen("s_edu");
      // The landing hero passes the four answers: go straight to the teaser.
      const fromHero: Edu = {
        institution_id: params.get("inst") ?? "", major_node_id: params.get("major") ?? "",
        admission_year: params.get("adm") ?? "", graduation_year: params.get("grad") ?? "",
      };
      if (Object.values(fromHero).every(Boolean)) {
        setEdu(fromHero);
        run(() => toTeaser(fromHero, "STUDENT"))();
        return;
      }
    }
    // Already a member: continue where they are.
    acq.me().then((m) => resumeMember(m)).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function payload(e: Edu, type: UserType) {
    const job = (j: Job) => ({
      organization_name: j.organization_name || null,
      role_node_id: j.role_node_id,
      start_year: Number(j.start_year),
      end_year: j.end_year ? Number(j.end_year) : null,
    });
    return {
      user_type: type,
      education: {
        institution_id: e.institution_id,
        major_node_id: e.major_node_id,
        admission_year: Number(e.admission_year),
        graduation_year: Number(e.graduation_year),
      },
      current_job: type === "PROFESSIONAL" && current.role_node_id ? job(current) : null,
      first_job: null,
      first_job_is_current: false,
      intents: [],
    };
  }

  async function toTeaser(e: Edu, type: UserType) {
    const d = await acq.saveDraft(payload(e, type), draftId);
    setDraftId(d.draft_id);
    setTeaser(await acq.teaser(d.draft_id));
    setScreen("gate");
  }

  async function resumeMember(m: MyResult) {
    setMe(m);
    const pro = m.profile.user_type === "PROFESSIONAL";
    setUserType(pro ? "PROFESSIONAL" : "STUDENT");
    if (m.intent) {
      setScreen("me");
      return;
    }
    setBase(await acq.meStep(pro ? "next_roles" : "first_roles"));
    setScreen(pro ? "p_next" : "s_result");
  }

  /** HMM ID login leaves the page: remember which draft to merge on the way back. */
  function rememberDraft() {
    if (!draftId) return;
    pending.draftId(draftId);
    pending.consentVersion(CONSENT_VERSION);
  }

  async function finishLogin() {
    const saved = pending.draftId();
    const version = pending.consentVersion();
    if (saved && version) {
      try {
        await api.mergeDraft(saved, version);
      } catch (e) {
        // 409: this account already has a profile; continue with it.
        if (!(e instanceof ApiError && e.status === 409)) throw e;
      }
      pending.draftId(null);
      pending.consentVersion(null);
    }
    try {
      await resumeMember(await acq.me());
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError("아직 저장된 정보가 없어요. 처음부터 입력해 주세요.");
        setScreen("start");
      } else throw e;
    }
  }

  const eduReady = edu.institution_id && edu.major_node_id && edu.admission_year && edu.graduation_year &&
    Number(edu.admission_year) <= Number(edu.graduation_year);

  const submitInput = run(() => toTeaser(edu, userType));
  const kakao = () => {
    rememberDraft();
    window.location.href = "/auth/hmm/start";
  };
  const devLogin = run(async () => {
    rememberDraft();
    await api.devLogin();
    await finishLogin();
  });
  const submitFirst = run(async () => {
    if (!firstIsCurrent) {
      await acq.addJob({
        organization_name: first.organization_name || null, role_node_id: first.role_node_id,
        start_year: Number(first.start_year), end_year: first.end_year ? Number(first.end_year) : null,
      });
      setSimilar(await acq.meStep("similar_paths"));
    } else setSimilar(undefined);
    setScreen("p_similar");
  });
  const submitIntent = run(async () => {
    await acq.setIntent({
      surface: professional ? "PROFESSIONAL_NEXT_ROLE" : "STUDENT_FIRST_ROLE",
      target_kind: intent === "UNDECIDED" ? "UNDECIDED" : "ROLE",
      target_node_id: intent === "UNDECIDED" ? null : intent,
    });
    setMe(await acq.me());
    setScreen("me");
  });
  const changeIntent = run(async () => {
    if (!base) setBase(await acq.meStep(professional ? "next_roles" : "first_roles"));
    setIntent("");
    setScreen(professional ? "p_similar" : "s_intent");
  });
  const unlock = run(async () => {
    await acq.unlock();
    setMe(await acq.me());
  });

  const back: Partial<Record<Screen, Screen>> = {
    s_edu: "start", p_now: "start", gate: professional ? "p_now" : "s_edu",
    s_intent: "s_result", p_first: "p_next", p_similar: "p_first",
  };
  const n = teaser?.base.effective_n ?? 0;

  return (
    <main className="app">
      <header className="top">
        {back[screen] ? (
          <button className="link" onClick={() => setScreen(back[screen]!)} aria-label="뒤로">←</button>
        ) : <a className="brand" href="/">nextpath</a>}
        {simulation && <span className="badge sim">SIMULATION · 테스트 데이터</span>}
      </header>
      {error && <p className="error" role="alert">{error}</p>}

      {screen === "start" && (
        <section className="screen">
          <h1>나와 같은 자리에 있었던 사람들은<br />어디로 갔을까</h1>
          <p className="sub">지금 내 상황을 골라주세요</p>
          <div className="options">
            <button className="option" onClick={() => { setUserType("STUDENT"); setScreen("s_edu"); }}>
              학생 · 취업 준비 중
            </button>
            <button className="option" onClick={() => { setUserType("PROFESSIONAL"); setScreen("p_now"); }}>
              지금 일하고 있어요
            </button>
          </div>
        </section>
      )}

      {(screen === "s_edu" || screen === "p_now") && (
        <section className="screen">
          <Progress value={0.33} />
          <h2>{professional ? "학교와 지금 하는 일을 알려주세요" : "학교와 전공을 알려주세요"}</h2>
          <Field label="학교">
            <select value={edu.institution_id} onChange={(e) => setEdu({ ...edu, institution_id: e.target.value })}>
              <option value="">선택</option>
              {institutions.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
            </select>
          </Field>
          <Field label="전공">
            <NodeSelect nodes={majors} value={edu.major_node_id} onChange={(v) => setEdu({ ...edu, major_node_id: v })} />
          </Field>
          <div className="pair">
            <Field label="입학">
              <YearSelect value={edu.admission_year} onChange={(v) => setEdu({ ...edu, admission_year: v })} />
            </Field>
            <Field label="졸업 (예정)">
              <YearSelect value={edu.graduation_year} onChange={(v) => setEdu({ ...edu, graduation_year: v })} />
            </Field>
          </div>
          {professional && (
            <JobFields job={current} roles={roles} onChange={setCurrent} labels={{ role: "지금 직무", start: "입사" }} />
          )}
          <p className="hint">입력한 내용은 나와 비슷한 사람을 찾는 데만 써요. 다른 사람에게 보이지 않아요.</p>
          <button className="cta" disabled={busy || !eduReady || (professional && !(current.role_node_id && current.start_year))}
                  onClick={submitInput}>
            나와 비슷한 사람 찾기
          </button>
        </section>
      )}

      {screen === "gate" && teaser && (
        <section className="screen">
          {teaser.base.suppressed ? (
            <>
              <h2>아직 나와 비슷한 사람이 적어요</h2>
              <p className="sub">개인이 드러나지 않도록 {n}명 이하일 때는 결과를 만들지 않아요. 연도나 전공을 바꿔서 다시 찾아볼 수 있어요.</p>
              <button className="cta ghost" onClick={() => setScreen(professional ? "p_now" : "s_edu")}>조건 바꾸기</button>
            </>
          ) : (
            <>
              <span className="badge">찾았어요</span>
              <div className="lock">
                <span className="small">{professional ? "나와 같은 자리에 있었던 사람" : "나와 같은 출발점에서 시작한 사람"}</span>
                <span className="lockbig">{n.toLocaleString()}명</span>
                {teaser.n_directions != null && (
                  <span className="small">이 사람들은 <b>{teaser.n_directions}가지 길</b>로 나뉘었어요</span>
                )}
              </div>
              {teaser.base.fallback_reason.length > 0 && (
                <p className="hint">딱 같은 사람은 {teaser.base.exact_n}명이라, {reasonText(teaser.base.fallback_reason)}까지 넓혀서 찾았어요</p>
              )}
              <div className="blur" aria-hidden="true">
                {[88, 64, 52, 40, 30].map((w, i) => (
                  <div key={i} className="bar"><span>●●●●</span><span className="track"><i className={i ? "m" : ""} style={{ width: `${w}%` }} /></span><b>●●%</b></div>
                ))}
              </div>
              <h2 className="gate-title">이 중에 내 길도 있을까요?</h2>
              <p className="sub">어디로 갔는지는 로그인하면 바로 보여드려요. 입력한 내용은 그대로 이어져요.</p>
              <label className="check">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                입력한 학교·경력 정보를 HMM 계정과 연결해 결과 제공과 익명 통계에 쓰는 것에 동의해요.
              </label>
              <button className="cta kakao" disabled={!consent || busy} onClick={kakao}>카카오로 3초 만에 보기</button>
              {DEV_LOGIN && <button className="cta ghost" disabled={!consent || busy} onClick={devLogin}>개발용 로그인</button>}
            </>
          )}
        </section>
      )}

      {(screen === "s_result" || screen === "p_next") && base && (
        <section className="screen">
          <ResultCount r={base.result}
                       caption={professional ? "나와 같은 자리에 있었던 사람들이 고른 다음" : "나와 같은 출발점의 사람들이 처음 간 길"} />
          <Bars r={base.result} professional={professional} />
          {conclusion(base.result, professional) && <p className="conclusion">{conclusion(base.result, professional)}</p>}
          <Share r={base.result} professional={professional} />
          <button className="cta" disabled={base.result.suppressed && !professional}
                  onClick={() => setScreen(professional ? "p_first" : "s_intent")}>
            {professional ? "첫 직장도 넣고 더 비슷한 사람 보기" : "이 중에 끌리는 길이 있어요"}
          </button>
        </section>
      )}

      {screen === "p_first" && (
        <section className="screen">
          <h2>첫 직장은 어디였어요?</h2>
          <label className="check">
            <input type="checkbox" checked={firstIsCurrent} onChange={(e) => setFirstIsCurrent(e.target.checked)} />
            지금 직장이 첫 직장이에요
          </label>
          {!firstIsCurrent && (
            <JobFields job={first} roles={roles} onChange={setFirst} withEnd
                       labels={{ role: "첫 직무", start: "입사", end: "퇴사" }} />
          )}
          <button className="cta" disabled={busy || (!firstIsCurrent && !(first.role_node_id && first.start_year))}
                  onClick={submitFirst}>경로 맞춰보기</button>
        </section>
      )}

      {(screen === "s_intent" || screen === "p_similar") && (
        <section className="screen">
          {screen === "p_similar" && similar && (
            similar.result.suppressed ? (
              <p className="sub">나와 같은 두 걸음을 걸은 사람은 아직 적어요. 지금 직무가 같은 사람 기준으로 보여드릴게요.</p>
            ) : (
              <ResultCount r={similar.result} caption="나와 같은 두 걸음을 걸은 사람" />
            )
          )}
          <h2>{professional ? "어떤 다음이 궁금해요?" : "이 중에 끌리는 길이 있나요?"}</h2>
          <p className="sub">하나만 골라주세요. 그 길로 간 사람들이 걸어간 경로를 보여드릴게요</p>
          <IntentChips middleRoles={middleRoles} top={(similar && !similar.result.suppressed ? similar : base)?.result}
                       value={intent} onChange={setIntent} />
          <button className="option muted" aria-pressed={intent === "UNDECIDED"}
                  onClick={() => setIntent("UNDECIDED")}>아직 모르겠어요 (괜찮아요, 대학생 10명 중 7명이 그래요)</button>
          <button className="cta" disabled={busy || !intent} onClick={submitIntent}>
            {intent && intent !== "UNDECIDED"
              ? `${ro(middleRoles.find((r) => r.node_id === intent)?.label ?? "")} 간 길 보기`
              : "가장 많이 간 길부터 보기"}
          </button>
        </section>
      )}

      {screen === "me" && me && <MyScreen me={me} busy={busy} onUnlock={unlock} onChangeIntent={changeIntent} />}
    </main>
  );
}

function friendly(e: ApiError) {
  if (e.status === 402) return "튜브가 부족해요. 프로필을 채우면 튜브를 받을 수 있어요.";
  if (e.status === 422) return "입력한 내용을 다시 확인해 주세요.";
  if (e.status === 404) return "입력 정보가 만료됐어요. 처음부터 다시 시작해 주세요.";
  return "잠시 후 다시 시도해 주세요.";
}

function Progress({ value }: { value: number }) {
  return <div className="progress"><i style={{ width: `${value * 100}%` }} /></div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>;
}

function YearSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">연도</option>
      {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
    </select>
  );
}

function NodeSelect({ nodes, value, onChange }: { nodes: Node[]; value: string; onChange: (v: string) => void }) {
  const groups = useMemo(() => {
    const g = new Map<string, Node[]>();
    nodes.forEach((n) => g.set(n.parent_label ?? "", [...(g.get(n.parent_label ?? "") ?? []), n]));
    return [...g.entries()];
  }, [nodes]);
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">선택</option>
      {groups.map(([parent, list]) => (
        <optgroup key={parent} label={parent}>
          {list.map((n) => <option key={n.node_id} value={n.node_id}>{n.label}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

function JobFields(props: {
  job: Job; roles: Node[]; onChange: (j: Job) => void; withEnd?: boolean;
  labels: { role: string; start: string; end?: string };
}) {
  const { job, onChange } = props;
  const [orgs, setOrgs] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    if (job.organization_name.length < 1) return;
    const t = setTimeout(() => acq.organizations(job.organization_name).then(setOrgs).catch(() => undefined), 200);
    return () => clearTimeout(t);
  }, [job.organization_name]);
  const listId = useMemo(() => `orgs-${Math.random().toString(36).slice(2)}`, []);
  return (
    <>
      <Field label="회사 (선택)">
        <input list={listId} value={job.organization_name} placeholder="회사명"
               onChange={(e) => onChange({ ...job, organization_name: e.target.value })} />
        <datalist id={listId}>{orgs.map((o) => <option key={o.id} value={o.name} />)}</datalist>
      </Field>
      <Field label={props.labels.role}>
        <NodeSelect nodes={props.roles} value={job.role_node_id} onChange={(v) => onChange({ ...job, role_node_id: v })} />
      </Field>
      <div className="pair">
        <Field label={props.labels.start}>
          <YearSelect value={job.start_year} onChange={(v) => onChange({ ...job, start_year: v })} />
        </Field>
        {props.withEnd && (
          <Field label={props.labels.end ?? "종료"}>
            <YearSelect value={job.end_year} onChange={(v) => onChange({ ...job, end_year: v })} />
          </Field>
        )}
      </div>
    </>
  );
}

function ResultCount({ r, caption }: { r: QueryResult; caption: string }) {
  return (
    <div className="count">
      {r.fallback_reason.length > 0 && <span className="badge">{reasonText(r.fallback_reason)}</span>}
      <div><span className="big">{r.effective_n.toLocaleString()}</span><b> 명</b></div>
      <p className="sub">{caption}</p>
      {r.fallback_reason.length > 0 && (
        <p className="hint">딱 같은 사람은 {r.exact_n}명이라, {reasonText(r.fallback_reason)}까지 넓혀서 봤어요</p>
      )}
    </div>
  );
}

function Bars({ r, professional }: { r: QueryResult; professional: boolean }) {
  if (r.suppressed) {
    return <p className="empty">아직 비교할 수 있는 사람이 {r.threshold}명보다 적어요. 숫자는 보여드리지 않아요.</p>;
  }
  const top = r.cells.slice(0, 5);
  const max = Math.max(...top.map((c) => c.share), 0.01);
  return (
    <div className="bars">
      {top.map((c, i) => (
        <div key={c.key} className="bar">
          <span>{cellLabel(c, professional)}</span>
          <span className="track"><i className={i === 0 ? "" : "m"} style={{ width: `${(c.share / max) * 100}%` }} /></span>
          <b>{Math.round(c.share * 100)}%</b>
        </div>
      ))}
      {r.other?.suppressed && <p className="hint">작은 그룹은 개인이 드러나지 않도록 묶어서 숨겼어요.</p>}
    </div>
  );
}

function Share({ r, professional }: { r: QueryResult; professional: boolean }) {
  const [copied, setCopied] = useState(false);
  if (r.suppressed || !r.cells[0]) return null;
  const top = r.cells[0];
  const text = `나와 같은 자리에 있었던 ${r.effective_n}명 중 ${Math.round(top.share * 100)}%는 ` +
    `${professional ? `${cellLabel(top, professional)}를 골랐대` : `${ro(cellLabel(top, professional))} 갔대`}. 너랑 비슷한 사람들은? `;
  const share = async () => {
    const url = window.location.origin;
    try {
      if (navigator.share) await navigator.share({ text, url });
      else {
        await navigator.clipboard.writeText(text + url);
        setCopied(true);
      }
    } catch {
      /* user cancelled */
    }
  };
  return <button className="link share" onClick={share}>{copied ? "링크를 복사했어요" : "친구에게 공유하기"}</button>;
}

function IntentChips(props: { middleRoles: Node[]; top?: QueryResult; value: string; onChange: (v: string) => void }) {
  const first = (props.top?.cells ?? []).filter((c) => c.code !== "STAYED").map((c) => c.key);
  const ordered = [
    ...first.map((id) => props.middleRoles.find((r) => r.node_id === id)).filter(Boolean) as Node[],
    ...props.middleRoles.filter((r) => !first.includes(r.node_id)),
  ];
  return (
    <div className="chips">
      {ordered.map((r) => (
        <button key={r.node_id} className="chip" aria-pressed={props.value === r.node_id}
                onClick={() => props.onChange(r.node_id)}>{r.label}</button>
      ))}
    </div>
  );
}

function months(m: number) {
  if (m <= 0) return "바로";
  if (m < 12) return `${Math.round(m)}개월`;
  return `${(m / 12).toFixed(1)}년`;
}

function MyScreen({ me, busy, onUnlock, onChangeIntent }: {
  me: MyResult; busy: boolean; onUnlock: () => void; onChangeIntent: () => void;
}) {
  const p = me.intent_paths.paths;
  const professional = me.profile.user_type === "PROFESSIONAL";
  return (
    <section className="screen">
      <div className="row-between">
        <span className="badge">입력하신 내용을 이어왔어요</span>
        <span className="tube">{me.balance_tube}</span>
      </div>
      {!p || p.suppressed ? (
        <>
          <h2>이 길로 간 사람은 아직 적어요</h2>
          <p className="sub">개인이 드러나지 않도록 {p?.min_cell_n ?? 5}명 미만은 보여드리지 않아요.</p>
          <button className="cta ghost" onClick={onChangeIntent}>다른 길 보기</button>
        </>
      ) : (
        <>
          {me.intent_paths.target_basis === "MOST_COMMON" && <p className="hint">가장 많이 간 길부터 보여드릴게요</p>}
          <h2>나와 같은 자리에서 {ro(p.target.label)} 간 {p.n_people}명이 걸어간 길</h2>
          {p.median_months != null && (p.median_months <= 0 ? (
            <p className="sub">절반 이상이 {professional && p.from ? "옮기자마자" : "첫 직장부터"} 바로 이 길로 갔어요</p>
          ) : (
            <p className="sub">{professional && p.from ? `${p.from.label}에서 옮기기까지` : "첫 직장부터 이 길까지"} 중간값 <b>{months(p.median_months)}</b> 걸렸어요</p>
          ))}
          {(p.paths ?? []).map((x, i) => (
            <div key={i} className="pathcard">
              <div className="path">
                {x.path.map((s, j) => (
                  <span key={s.node_id + j} className={j === x.path.length - 1 ? "hl" : ""}>{s.label}</span>
                ))}
              </div>
              <span className="small">{x.n}명 · {Math.round(x.share * 100)}%</span>
            </div>
          ))}
          {(p.n_paths ?? 0) > (p.n_paths_shown ?? 0) && (
            <p className="hint">나머지 {(p.n_paths ?? 0) - (p.n_paths_shown ?? 0)}개 경로는 인원이 적어 묶었어요 ({p.min_cell_n}명 미만 숨김)</p>
          )}
          <div className="deep">
            <h3>깊은 분석</h3>
            {me.deep_dive.unlocked && me.deep_dive.content ? (
              <div className="grid2">
                <Breakdown title="도착한 회사 규모" items={me.deep_dive.content.company_size.map((i) => ({ ...i, label: SIZES[i.key] ?? i.key }))} />
                <Breakdown title="도착한 산업" items={me.deep_dive.content.industry.map((i) => ({ ...i, label: i.key === "OTHER" ? "기타" : i.label }))} />
              </div>
            ) : me.deep_dive.available ? (
              <>
                <p className="sub">이 길에 도착한 회사 규모와 산업을 열어볼 수 있어요.</p>
                <button className="cta" disabled={busy} onClick={onUnlock}>{me.deep_dive.cost_tube} 튜브로 열기</button>
              </>
            ) : (
              <p className="sub">이 결과는 깊은 분석을 하기엔 인원이 적어요.</p>
            )}
          </div>
          <p className="conclusion">이 사람들도 처음엔 나와 같은 자리였어요.</p>
          <button className="cta ghost" onClick={onChangeIntent}>다른 길도 보기</button>
        </>
      )}
      <p className="hint">한 걸음 먼저 간 사람과의 연결은 실제 가입·인증한 사람만으로 준비 중이에요. 테스트 데이터는 사람으로 표시되지 않아요.</p>
    </section>
  );
}

function Breakdown({ title, items }: { title: string; items: { key: string; label: string | null; n: number }[] }) {
  const total = items.reduce((s, i) => s + i.n, 0) || 1;
  return (
    <div className="card">
      <h4>{title}</h4>
      {items.map((i) => (
        <div key={i.key} className="bar">
          <span>{i.label ?? i.key}</span>
          <span className="track"><i style={{ width: `${(i.n / total) * 100}%` }} /></span>
          <b>{i.n}</b>
        </div>
      ))}
    </div>
  );
}
