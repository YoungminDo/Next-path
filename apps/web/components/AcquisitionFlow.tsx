"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { Options } from "@/lib/server/options";
import {
  acq,
  api,
  ApiError,
  errorMessage,
  pending,
  type Cell,
  type CohortFilters,
  type DesiredStatus,
  type EmploymentType,
  type ImportedEdu,
  type ImportRead,
  type Institution,
  type InterviewStatus,
  type MyResult,
  type Node,
  type PastJob,
  type CardType,
  type PayableInsight,
  type ProfileChange,
  type QueryResult,
  type StepResult,
  type TeaserResult,
  type Unlisted,
} from "@/lib/api";
import { ImportedJobs, ImportEntry, importRows, ImportReview, ImportUpload, toPastJob } from "@/components/ImportFlow";
import NodeSelect from "@/components/NodeSelect";
import SearchSelect, { type Picked } from "@/components/SearchSelect";
import { inAppBrowser, isInternal, track } from "@/lib/track";
import BusinessInfo from "@/components/BusinessInfo";
import ResultCards, { OpenButton } from "@/components/ResultCards";
import { buyCard } from "@/lib/pay";
import { YEARS } from "@/lib/years";

/* Order (product decision): input -> teaser (how many people, how many directions) -> login ->
   every distribution, intent and path. The server enforces the same gate: before login it only
   answers the teaser. Tone: "people who stood where I stand", never "seniors". */
type Screen =
  | "start" | "upload" | "s_edu" | "p_now" | "finding" | "gate" | "interview"
  | "s_result" | "s_intent" | "p_next" | "p_first" | "p_similar" | "me" | "m_upload" | "m_review"
  | "m_changes";
type UserType = "STUDENT" | "PROFESSIONAL";

const DEV_LOGIN = process.env.NEXT_PUBLIC_ENABLE_DEV_LOGIN === "true";
const RESULT_SCREENS = new Set<Screen>(["s_result", "s_intent", "p_next", "p_first", "p_similar", "me"]);
const CONSENT_VERSION = process.env.NEXT_PUBLIC_CONSENT_POLICY_VERSION ?? "career_terms_v1";

const INTERVIEW_SKIPPED = "hellomyme.interview_skipped";
// The version of the interview consent wording shown in InterviewStep; change both together.
const INTERVIEW_CONSENT_VERSION = "interview_contact_v1";
const SIZES: Record<string, string> = {
  ENTERPRISE: "대기업", LARGE: "대형", MID: "중견", SMALL: "소형", MICRO: "초소형",
  OTHER: "기타",
};
const LOGIN_ERRORS: Record<string, string> = {
  kakao_denied: "카카오 로그인이 취소됐어요.",
  no_hmm_session: "로그인 정보를 받지 못했어요. 다시 시도해 주세요.",
  hmm_token_rejected: "로그인이 만료됐어요. 다시 시도해 주세요.",
};

/** A school or major outside the pick list is kept as typed (`*_raw`, no id). */
type Edu = { institution_id: string; institution_raw: string; major_node_id: string; major_raw: string;
  admission_year: string; graduation_year: string };
const EMPTY_EDU: Edu = { institution_id: "", institution_raw: "", major_node_id: "", major_raw: "",
  admission_year: "", graduation_year: "" };

/** The undergraduate degree if the file shows one (the cohort is built on it). */
function pickEducation(list: ImportedEdu[]): ImportedEdu | undefined {
  const undergrad = (e: ImportedEdu) => /학사|학부|bachelor|\bb\.?a\b|\bb\.?s\b|\bb\.?eng/i.test(e.degree ?? "");
  const graduate = (e: ImportedEdu) => /석사|박사|master|ph\.?d|mba|대학원|graduate/i.test(`${e.degree ?? ""} ${e.school ?? ""}`);
  return list.find(undergrad) ?? list.find((e) => !graduate(e) && /대학|university|college/i.test(e.school ?? ""))
    ?? list.find((e) => !graduate(e)) ?? list[0];
}

/** Typed names the server could not match, with what was typed: said next to every result. */
type Unl = { kinds: Unlisted; institution: string; major: string };
function unlistedNote(u?: Unl): string | null {
  if (!u) return null;
  const school = u.kinds.includes("institution") && u.institution;
  const major = u.kinds.includes("major") && u.major;
  if (school && major) return `‘${u.institution}’·‘${u.major}’ 기록은 아직 모으는 중이라 다른 학교·다른 전공 사람들까지 포함해서 찾았어요.`;
  if (school) return `‘${u.institution}’ 기록은 아직 모으는 중이라 다른 학교 사람들까지 포함해서 찾았어요.`;
  if (major) return `‘${u.major}’ 기록은 아직 모으는 중이라 다른 전공 사람들까지 포함해서 찾았어요.`;
  return null;
}
/** Desired role answer: up to three roles (listed or typed), or an explicit "none yet" /
 * "stay in my role". Nothing chosen (status null) means the question was skipped. */
type Desired = { roles: Picked[]; status: DesiredStatus | null };
const NO_DESIRED: Desired = { roles: [], status: null };
/** Months, the written title and the employment type come only from a resume (kept until the
    year they belong to is changed). */
type Job = { organization_name: string; role_node_id: string; start_year: string; end_year: string;
  organization_id?: string | null; role_raw?: string | null; start_month?: number | null;
  end_month?: number | null; employment_type?: EmploymentType | null };
const emptyJob: Job = { organization_name: "", role_node_id: "", start_year: "", end_year: "" };

function cellLabel(c: Cell, professional: boolean) {
  if (c.code === "STAYED") return professional ? "지금 직무 유지" : "그대로";
  return c.label ?? c.code;
}

/** Korean particle 으로/로 by the last syllable (ㄹ or no final consonant -> 로). */
export function ro(word: string): string {
  const last = word.trim().slice(-1);
  const c = last.charCodeAt(0) - 0xac00;
  if (c >= 0 && c <= 11171) {
    const jong = c % 28;
    return `${word}${jong === 0 || jong === 8 ? "로" : "으로"}`;
  }
  // Read aloud: M/N (엠, 엔) and 0/3/6 (영, 삼, 육) end in a consonant other than ㄹ.
  return `${word}${/[mn036]/i.test(last) ? "으로" : "로"}`;
}

/** How far the group's years reach from the answer (0 = the same year), or null when that
 * year is not part of the group at all. */
function spread(range: { from: number | null; to: number | null } | null | undefined, year: number) {
  if (!range || !year) return null;
  return Math.max(Math.abs((range.from ?? year) - year), Math.abs((range.to ?? year) - year));
}

/** What the number counts, in words, from the group actually used (after any widening), shown
 * right under the number so a big or a round number is never read as more than it is. */
export function basisText(f: CohortFilters | undefined, reasons: string[],
                          years: { admission_year?: number | string; graduation_year?: number | string },
                          professional: boolean): string | null {
  if (!f) return null;
  const parts = professional ? ["같은 직무"] : [];
  const sim = f.similar ?? {};
  parts.push(sim.region ? `${sim.region} 지역 학교` : f.institution_ids?.length ? "같은 학교" : "여러 학교");
  const family = reasons.includes("BROADEN_MAJOR_1_LEVEL") || sim.major === "FAMILY";
  parts.push(!f.majors?.length ? "여러 전공"
    : family ? "비슷한 전공 계열" : sim.major ? "비슷한 전공" : "같은 전공");
  const g = spread(f.graduation_year, Number(years.graduation_year));
  const a = professional ? null : spread(f.admission_year, Number(years.admission_year));
  if (g === null && a === null) parts.push("모든 학번");
  else if (g !== null && a !== null) parts.push(Math.max(g, a) === 0 ? "같은 학번" : `비슷한 학번(±${Math.max(g, a)}년)`);
  else if (g !== null) parts.push(g === 0 ? "같은 졸업 연도" : `졸업 ±${g}년`);
  else parts.push(a === 0 ? "같은 입학 연도" : `입학 ±${a}년`);
  return parts.join(" · ");
}

/** Said when the group had to be widened; the exact-match count only when it can be told. */
function widenedText(exactN: number | null | undefined): string {
  if (exactN === 0) return "딱 같은 사람은 아직 없어서, 비슷한 사람까지 넓혀서 찾았어요";
  return exactN ? `딱 같은 사람은 ${exactN}명이라, 비슷한 사람까지 넓혀서 찾았어요`
    : "딱 같은 사람이 적어서, 비슷한 사람까지 넓혀서 찾았어요";
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

export default function AcquisitionFlow({ initial, startOn }: { initial?: Options; startOn?: "upload" }) {
  const [screen, setScreen] = useState<Screen>(startOn ?? "start");
  const [userType, setUserType] = useState<UserType>("STUDENT");
  const [institutions, setInstitutions] = useState<Institution[]>(initial?.institutions ?? []);
  const [majors, setMajors] = useState<Node[]>(initial?.majors ?? []);
  const [roles, setRoles] = useState<Node[]>(initial?.roles ?? []);
  const [middleRoles, setMiddleRoles] = useState<Node[]>(initial?.middleRoles ?? []);
  const [edu, setEdu] = useState<Edu>(EMPTY_EDU);
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
  const [unl, setUnl] = useState<Unl>();
  const app = useMemo(() => (typeof window === "undefined" ? null : inAppBrowser()), []);
  // Desired role (optional, on the preview): kept in a ref too, so a save always sends the latest.
  const [desired, setDesired] = useState<Desired>(NO_DESIRED);
  const desiredRef = useRef<Desired>(NO_DESIRED);
  const desiredDirty = useRef(false);
  const desiredTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const desiredSaving = useRef<Promise<unknown> | null>(null);
  // Interview invitation (optional, after login), then the result they were waiting for.
  const [interview, setInterview] = useState<InterviewStatus>();
  // A returning member's new answers that differ from their profile: they choose at login.
  const [changes, setChanges] = useState<{ draftId: string; items: ProfileChange[] }>();
  const afterInterview = useRef<(() => Promise<void>) | null>(null);
  // Resume / capture import: which read filled the form, and the other jobs it showed.
  const [importId, setImportId] = useState<string>();
  const [others, setOthers] = useState<ReturnType<typeof importRows>>([]);
  const [memberRead, setMemberRead] = useState<ImportRead>();
  const importFrom = useRef<Screen>("me");
  const [notice, setNotice] = useState<{ screen: Screen; text: string }>();

  const professional = userType === "PROFESSIONAL";

  // Funnel: which result steps people reach and how long they stay on each (docs/10).
  const shownAt = useRef<{ screen: Screen; at: number } | null>(null);
  const fromPop = useRef(false); // the screen change came from the browser's back button
  const depth = useRef(0); // history entries this page pushed
  const backRef = useRef<Partial<Record<Screen, Screen>>>({});
  useEffect(() => {
    const prev = shownAt.current;
    const now = Date.now();
    shownAt.current = { screen, at: now };
    const seconds = prev ? Math.round((now - prev.at) / 1000) : null;
    if (RESULT_SCREENS.has(screen)) {
      track("result_step_viewed", { screen, user_type: userType, previous: prev?.screen ?? null,
                                    seconds_on_previous: seconds });
    }
    // Every screen change is a step in the browser's history too, so the phone's back button
    // walks back through the flow instead of leaving it (in-app browsers included).
    if (prev && !fromPop.current && screen !== "finding") {
      // The browser's own pushState with a null state: Next.js patches window.history.pushState
      // and would treat the entry as its own (on back it re-renders the route, wiping the
      // answers), while it leaves null-state entries alone and only our handler moves the screen.
      History.prototype.pushState.call(window.history, null, "");
      depth.current += 1;
    }
    fromPop.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screen]);
  useEffect(() => {
    const onPop = () => {
      depth.current = Math.max(0, depth.current - 1);
      fromPop.current = true;
      setScreen((cur) => backRef.current[cur] ?? cur);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const started = useRef(false);
  const markStarted = () => {
    if (started.current) return;
    started.current = true;
    track("career_input_started", { surface: "flow", user_type: userType });
  };
  const answer = (next: Edu) => { markStarted(); setEdu(next); };
  useEffect(() => {
    // Back from the login page via the back/forward cache: the page is restored as it was left,
    // with the Kakao button still waiting. Make it usable again.
    const restored = (e: PageTransitionEvent) => { if (e.persisted) setBusy(false); };
    window.addEventListener("pageshow", restored);
    return () => window.removeEventListener("pageshow", restored);
  }, []);
  useEffect(() => {
    const leave = () => {
      const cur = shownAt.current;
      if (cur && RESULT_SCREENS.has(cur.screen)) {
        track("result_left", { screen: cur.screen, seconds: Math.round((Date.now() - cur.at) / 1000) });
      }
    };
    window.addEventListener("pagehide", leave);
    return () => window.removeEventListener("pagehide", leave);
  }, []);

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
    // The landing passes what was already answered: never ask for it again.
    const fromHero: Edu = {
      institution_id: params.get("inst") ?? "", institution_raw: params.get("inst_raw") ?? "",
      major_node_id: params.get("major") ?? "", major_raw: params.get("major_raw") ?? "",
      admission_year: params.get("adm") ?? "", graduation_year: params.get("grad") ?? "",
    };
    const eduDone = (fromHero.institution_id || fromHero.institution_raw) && (fromHero.major_node_id || fromHero.major_raw)
      && fromHero.admission_year && fromHero.graduation_year;
    if (type === "pro") {
      setUserType("PROFESSIONAL");
      setEdu(fromHero);
      const heroJob: Job = { ...emptyJob, role_node_id: params.get("role") ?? "", start_year: params.get("start") ?? "" };
      setCurrent(heroJob);
      if (eduDone && heroJob.role_node_id && heroJob.start_year) {
        // Everything answered on the landing (현직자 tab): straight to the result preview.
        setScreen("finding");
        run(async () => {
          try {
            await toTeaser(fromHero, "PROFESSIONAL", heroJob);
          } catch (e) {
            setScreen("p_now"); // answers stay filled in; the error says what to change
            throw e;
          }
        })();
        return;
      }
      setScreen("p_now");
    }
    if (type === "upload" || startOn === "upload") {
      // A member opening the upload link fills in their own profile instead (straight away, so a
      // quick upload never takes the before-login path).
      if (!pending.member()) { setScreen("upload"); return; }
      setScreen("m_upload");
      acq.me().then(async (m) => {
        const pro = m.profile.user_type === "PROFESSIONAL";
        setMe(m);
        setUserType(pro ? "PROFESSIONAL" : "STUDENT");
        importFrom.current = m.intent ? "me" : pro ? "p_next" : "s_result";
        if (!m.intent) setBase(await acq.meStep(pro ? "next_roles" : "first_roles"));
      }).catch((e) => {
        if (e instanceof ApiError && (e.status === 401 || e.status === 404)) pending.member(null);
        setScreen("upload");
      });
      return;
    }
    if (type === "student") {
      setEdu(fromHero);
      if (eduDone) {
        // All four answers: straight to the result preview, with a "finding" screen meanwhile.
        setScreen("finding");
        run(async () => {
          try {
            await toTeaser(fromHero, "STUDENT");
          } catch (e) {
            setScreen("s_edu"); // answers stay filled in; the error says what to change
            throw e;
          }
        })();
        return;
      }
      setScreen("s_edu");
    }
    // Already a member on this browser: continue where they are (anonymous visitors skip the call).
    if (pending.member()) {
      acq.me().then((m) => resumeMember(m)).catch((e) => {
        if (e instanceof ApiError && (e.status === 401 || e.status === 404)) pending.member(null);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Jobs read from a file: the earliest kept job before the current one (not an internship)
      is the first job when it has a role; the rest go as they are. */
  function fromFile(type: UserType) {
    const kept = others.filter((o) => o.keep && o.x.start_year);
    const startOf = (y: number | null, m?: number | null) => (y ?? 0) * 12 + (m ?? 1);
    const currentStart = startOf(Number(current.start_year) || null, current.start_month);
    const earlier = kept.filter((o) => o.x.employment_type !== "INTERN" && !o.x.is_current &&
      (type !== "PROFESSIONAL" || startOf(o.x.start_year, o.x.start_month) <= currentStart))
      .sort((a, b) => startOf(a.x.start_year, a.x.start_month) - startOf(b.x.start_year, b.x.start_month));
    const first = type === "PROFESSIONAL" && earlier[0]?.role ? earlier[0] : undefined;
    return {
      first_job: first ? toPastJob(first.x, first.role) : null,
      first_job_is_current: type === "PROFESSIONAL" && earlier.length === 0,
      other_jobs: kept.filter((o) => o !== first).map((o) => toPastJob(o.x, o.role))
        .filter((j): j is PastJob => j !== null),
    };
  }

  function payload(e: Edu, type: UserType, cur: Job = current) {
    const job = (j: Job) => ({
      organization_id: j.organization_id ?? null,
      organization_name: j.organization_name || null,
      role_node_id: j.role_node_id,
      role_raw: j.role_raw ?? null,
      start_year: Number(j.start_year),
      end_year: j.end_year ? Number(j.end_year) : null,
      start_month: j.start_month ?? null,
      end_month: j.end_year ? j.end_month ?? null : null,
      employment_type: j.employment_type ?? null,
    });
    const file = importId ? fromFile(type) : null;
    return {
      user_type: type,
      education: {
        institution_id: e.institution_id || null,
        institution_raw: e.institution_id ? null : e.institution_raw || null,
        major_node_id: e.major_node_id || null,
        major_raw: e.major_node_id ? null : e.major_raw || null,
        admission_year: Number(e.admission_year),
        graduation_year: Number(e.graduation_year),
      },
      current_job: type === "PROFESSIONAL" && cur.role_node_id ? job(cur) : null,
      first_job: file?.first_job ? { ...file.first_job, role_node_id: file.first_job.role_node_id! } : null,
      first_job_is_current: file?.first_job_is_current ?? false,
      other_jobs: file?.other_jobs ?? [],
      import_attempt_id: importId ?? null,
      intents: [],
      desired_roles: desiredRef.current.roles.map((r) => ({ role_node_id: r.id, role_raw: r.id ? null : r.label })),
      // KEEP_CURRENT is a professional's answer: a student who switched type keeps nothing of it.
      desired_role_status: desiredRef.current.status === "KEEP_CURRENT" && type !== "PROFESSIONAL"
        ? null : desiredRef.current.status,
    };
  }

  function changeDesired(next: Desired) {
    setDesired(next);
    desiredRef.current = next;
    desiredDirty.current = true;
    if (desiredTimer.current) clearTimeout(desiredTimer.current);
    desiredTimer.current = setTimeout(() => void flushDesired(), 600);
  }

  /** Save a changed desired-role answer now (also right before leaving for login). */
  function flushDesired(): Promise<unknown> {
    if (desiredTimer.current) clearTimeout(desiredTimer.current);
    desiredTimer.current = null;
    if (!desiredDirty.current || !draftId) return desiredSaving.current ?? Promise.resolve();
    desiredDirty.current = false;
    const d = desiredRef.current;
    desiredSaving.current = acq.saveDraft(payload(edu, userType), draftId, isInternal())
      .then(() => track("desired_role_selected", {
        user_type: userType, status: d.status, n_roles: d.roles.length,
        n_listed: d.roles.filter((r) => r.id).length, n_typed: d.roles.filter((r) => !r.id).length,
      }))
      .catch(() => { desiredDirty.current = true; });
    return desiredSaving.current;
  }
  const settle = (p: Promise<unknown>, ms: number) =>
    Promise.race([p, new Promise((done) => setTimeout(done, ms))]);

  async function toTeaser(e: Edu, type: UserType, cur: Job = current) {
    const d = await acq.saveDraft(payload(e, type, cur), draftId, isInternal());
    setDraftId(d.draft_id);
    setUnl({ kinds: d.unlisted ?? [], institution: e.institution_raw, major: e.major_raw });
    track("career_input_completed", {
      user_type: type,
      institution_id: e.institution_id || null,
      institution_name: institutions.find((i) => i.id === e.institution_id)?.name ?? (e.institution_raw || null),
      institution_listed: Boolean(e.institution_id) || !(d.unlisted ?? []).includes("institution"),
      major_node_id: e.major_node_id || null,
      major_label: majors.find((m) => m.node_id === e.major_node_id)?.label ?? (e.major_raw || null),
      major_listed: Boolean(e.major_node_id) || !(d.unlisted ?? []).includes("major"),
      admission_year: Number(e.admission_year), graduation_year: Number(e.graduation_year),
      current_role_node_id: type === "PROFESSIONAL" ? cur.role_node_id || null : null,
      from_file: Boolean(importId),
    });
    if (importId) {
      track("import_confirmed", { member: false, user_type: type, other_jobs: others.filter((o) => o.keep).length,
                                  roles_picked: others.filter((o) => o.keep && o.role).length });
    }
    const t = await acq.teaser(d.draft_id);
    setTeaser(t);
    track("login_wall_viewed", { user_type: type, effective_n: t.base.effective_n,
                                 suppressed: t.base.suppressed, n_directions: t.n_directions });
    setScreen("gate");
  }

  async function resumeMember(m: MyResult) {
    setMe(m);
    pending.member("1");
    const pe = (m.profile.education ?? {}) as { institution_raw?: string | null; major_raw?: string | null };
    setUnl({ kinds: m.unlisted ?? [], institution: pe.institution_raw ?? "", major: pe.major_raw ?? "" });
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
    let differs: ProfileChange[] = [];
    if (saved && version) {
      try {
        differs = (await api.mergeDraft(saved, version)).changes ?? [];
      } catch (e) {
        // 409: this account already has a profile; continue with it.
        if (!(e instanceof ApiError && e.status === 409)) throw e;
      }
      pending.draftId(null);
      pending.consentVersion(null);
    }
    track("signup_completed", { merged_draft: Boolean(saved && version) });
    if (saved && differs.length) {
      // Already a member with other answers on record: show before/after, they decide.
      setChanges({ draftId: saved, items: differs });
      setScreen("m_changes");
      return;
    }
    await afterLogin();
  }

  const decideChanges = (apply: boolean) => run(async () => {
    if (apply && changes) await acq.applyDraft(changes.draftId);
    setChanges(undefined);
    await afterLogin();
  })();

  async function afterLogin() {
    let m: MyResult;
    try {
      m = await acq.me();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError("아직 저장된 정보가 없어요. 처음부터 입력해 주세요.");
        setScreen("start");
        return;
      }
      throw e;
    }
    // Right after login, once: the optional interview invitation, then the result.
    const iv = await acq.interview().catch(() => null);
    let skipped = false;
    try { skipped = localStorage.getItem(INTERVIEW_SKIPPED) === "1"; } catch { /* private mode */ }
    if (iv && iv.enabled && iv.status === "NONE" && !skipped) {
      setInterview(iv);
      afterInterview.current = () => resumeMember(m);
      pending.member("1");
      track("interview_step_viewed", { surface: "after_login", user_type: m.profile.user_type });
      setScreen("interview");
      return;
    }
    await resumeMember(m);
  }

  const openInterview = run(async () => {
    setInterview(await acq.interview());
    afterInterview.current = async () => { setMe(await acq.me()); setScreen("me"); };
    track("interview_step_viewed", { surface: "result", user_type: userType });
    setScreen("interview");
  });
  const leaveInterview = (status?: InterviewStatus) => {
    if (status) setInterview(status);
    else {
      track("interview_skipped", { user_type: userType });
      try { localStorage.setItem(INTERVIEW_SKIPPED, "1"); } catch { /* private mode */ }
    }
    const next = afterInterview.current;
    afterInterview.current = null;
    run(async () => { if (next) await next(); else setScreen("me"); })();
  };

  const eduReady = (edu.institution_id || edu.institution_raw) && (edu.major_node_id || edu.major_raw) &&
    edu.admission_year && edu.graduation_year &&
    Number(edu.admission_year) <= Number(edu.graduation_year);

  /** Fill the form from a read file; the person checks it on the same screen as typing by hand. */
  function applyRead(r: ImportRead) {
    markStarted();
    const cur = r.experiences.find((x) => x.is_current && !x.is_career_break && x.employment_type !== "INTERN"
      && x.start_year);
    const e = pickEducation(r.education);
    const inst = e?.suggested_institution_id && institutions.some((i) => i.id === e.suggested_institution_id)
      ? e.suggested_institution_id : "";
    const major = e?.suggested_major_node_id && majors.some((m) => m.node_id === e.suggested_major_node_id)
      ? e.suggested_major_node_id : "";
    setEdu({
      institution_id: inst, institution_raw: inst ? "" : e?.school ?? "",
      major_node_id: major, major_raw: major ? "" : e?.major ?? "",
      admission_year: e?.start_year ? String(e.start_year) : "",
      graduation_year: e?.end_year ? String(e.end_year) : "",
    });
    const listed = new Set(roles.map((n) => n.node_id));
    if (cur) {
      setCurrent({
        organization_name: cur.company ?? "", organization_id: cur.suggested_organization_id,
        role_node_id: cur.suggested_role_node_id && listed.has(cur.suggested_role_node_id) ? cur.suggested_role_node_id : "",
        role_raw: cur.title, start_year: String(cur.start_year), start_month: cur.start_month, end_year: "",
        employment_type: cur.employment_type,
      });
    }
    setOthers(importRows(r, roles, cur ? [cur] : []));
    setImportId(r.import_attempt_id);
    setUserType(cur ? "PROFESSIONAL" : "STUDENT");
    setScreen(cur ? "p_now" : "s_edu");
  }

  // A member fills in the rest of their career from a file, then sees the result again.
  const openImport = () => { importFrom.current = screen; setNotice(undefined); setScreen("m_upload"); };
  const memberAdded = (added: number) => run(async () => {
    const back = importFrom.current;
    setMe(await acq.me());
    if (back === "p_next" || back === "s_result") setBase(await acq.meStep(professional ? "next_roles" : "first_roles"));
    setNotice({ screen: back, text: added ? `경력 ${added}개를 더했어요. 더한 경력으로 다시 계산했어요.`
      : "새로 더할 경력이 없었어요. 이미 모두 있어요." });
    setMemberRead(undefined);
    setScreen(back);
  })();
  const profile = me?.profile as { first_job?: unknown; first_job_is_current?: boolean } | undefined;
  // A first job before the current one is already on record (e.g. read from a resume): no need
  // to ask for it. One job only (first = current) still asks, as typing by hand always did.
  const hasFirst = Boolean(profile?.first_job) && profile?.first_job_is_current !== true;
  const toSimilar = run(async () => {
    setSimilar(await acq.meStep("similar_paths"));
    setScreen("p_similar");
  });

  const submitInput = run(() => toTeaser(edu, userType));
  const kakao = async () => {
    track("login_clicked", { user_type: userType, provider: "KAKAO" });
    setBusy(true);
    await settle(flushDesired(), 1500); // a desired role picked a moment ago is saved first
    rememberDraft();
    window.location.href = "/auth/hmm/start";
  };
  const devLogin = run(async () => {
    await settle(flushDesired(), 1500);
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
    track("intent_selected", { user_type: userType, target_kind: intent === "UNDECIDED" ? "UNDECIDED" : "ROLE",
                               target_node_id: intent === "UNDECIDED" ? null : intent });
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
    const u = await acq.unlock();
    if (u.unlocked) track("unlock_purchased", { insight: "PATH_DEEP_DIVE", charged: u.charged ?? null });
    setMe(await acq.me());
  });
  // No 튜브 left: the card is bought (990원) in the Toss Payments window; /pay/success opens it.
  const buy = (insight: PayableInsight) => run(async () => {
    try {
      await buyCard(insight, isInternal());
    } catch (e) {
      const code = (e as { code?: string } | null)?.code;
      if (code === "USER_CANCEL" || code === "PAY_PROCESS_CANCELED") {
        track("payment_failed", { stage: "window", code });
        return;
      }
      throw e;
    }
  })();
  const unlockCard = (card: CardType) => run(async () => {
    const u = await acq.unlockCard(card);
    if (u.unlocked) track("unlock_purchased", { insight: card, charged: u.charged ?? null });
    else setNotice({ screen: "me", text: "이 카드는 기록이 아직 적어서 열지 않았어요. 튜브는 그대로예요." });
    setMe(await acq.me());
  })();
  const unlockCompare = run(async () => {
    const u = await acq.unlockCompare();
    if (u.unlocked) track("unlock_purchased", { insight: "SCHOOL_COMPARE", charged: u.charged ?? null });
    else setNotice({ screen: "me", text: "다른 학교 기록이 아직 적어서 열지 않았어요. 튜브는 그대로예요." });
    setMe(await acq.me());
  });
  // School and major as the member gave them, for the result cards' titles.
  const meEdu = (me?.profile.education ?? {}) as { institution_id?: string | null; institution_raw?: string | null;
    major_node_id?: string | null; major_raw?: string | null };
  const meNames = {
    school: institutions.find((i) => i.id === meEdu.institution_id)?.name ?? meEdu.institution_raw ?? null,
    major: majors.find((m) => m.node_id === meEdu.major_node_id)?.label ?? meEdu.major_raw ?? null,
  };

  const back: Partial<Record<Screen, Screen>> = {
    upload: "start", s_edu: importId ? "upload" : "start", p_now: importId ? "upload" : "start",
    gate: professional ? "p_now" : "s_edu",
    s_intent: "s_result", p_first: "p_next", p_similar: hasFirst ? "p_next" : "p_first",
    m_upload: importFrom.current, m_review: "m_upload",
  };
  backRef.current = back;
  const goBack = () => {
    if (depth.current > 0) window.history.back(); // the popstate handler moves the screen
    else setScreen(back[screen]!);
  };
  const n = teaser?.base.effective_n ?? 0;
  const note = unlistedNote(unl);
  // Years for the basis line: the answers on this page, or the member's saved profile.
  const profileEdu = (me?.profile.education ?? {}) as { admission_year?: number; graduation_year?: number };
  const years = edu.graduation_year ? edu : profileEdu;
  const teaserBasis = teaser && basisText(teaser.base.effective_filters, teaser.base.fallback_reason, years, professional);
  const startCaption = (f?: CohortFilters) =>
    professional ? "나와 같은 자리에 있었던 사람"
      : f && !f.institution_ids?.length && !f.majors?.length ? "나와 학번이 비슷한 사람"
        : f?.similar ? "나와 비슷한 출발점에서 시작한 사람" : "나와 같은 출발점에서 시작한 사람";

  return (
    <main className="app">
      <header className="top">
        {back[screen] ? (
          <button className="link" onClick={goBack} aria-label="뒤로">←</button>
        ) : <a className="brand" href="/">nextpath</a>}
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {notice?.screen === screen && <p className="notice" role="status">{notice.text}</p>}

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
          <button className="option upload-option" onClick={() => setScreen("upload")}>
            <b>이력서·링*드인 캡처로 시작하기</b>
            <small>기존 만들어둔 이력서, 링*드인 캡처 등을 올리시면 됩니다</small>
          </button>
        </section>
      )}

      {screen === "upload" && (
        <ImportUpload member={false} onRead={applyRead} onManual={() => setScreen("start")} />
      )}
      {screen === "m_upload" && (
        <ImportUpload member onRead={(r) => { setMemberRead(r); setScreen("m_review"); }}
                      onManual={() => setScreen(importFrom.current)} />
      )}
      {screen === "m_review" && memberRead && <ImportReview read={memberRead} roles={roles} onDone={memberAdded} />}

      {screen === "finding" && (
        <section className="screen" aria-busy="true">
          <Progress value={0.66} />
          <h2>나와 같은 자리였던 사람들을 찾고 있어요</h2>
          <p className="sub">입력한 학교·전공·학번으로 비슷한 사람을 고르는 중이에요.</p>
        </section>
      )}

      {(screen === "s_edu" || screen === "p_now") && (
        <section className="screen">
          <Progress value={0.33} />
          <h2>{professional ? "학교와 지금 하는 일을 알려주세요" : "학교와 전공을 알려주세요"}</h2>
          {importId && <p className="hint">올린 파일에서 읽은 내용이에요. 틀린 곳은 고쳐 주세요.</p>}
          <Field label="학교">
            <SearchSelect ariaLabel="학교" noun="학교" placeholder="학교 검색 (예: 고려대, ㄱㄹㄷ)"
                          items={institutions.map((i) => ({ id: i.id, label: i.name, keywords: i.aliases ?? [] }))}
                          value={edu.institution_id
                            ? { id: edu.institution_id, label: institutions.find((i) => i.id === edu.institution_id)?.name ?? "" }
                            : edu.institution_raw ? { id: null, label: edu.institution_raw } : null}
                          onChange={(v) => {
                            answer({ ...edu, institution_id: v?.id ?? "", institution_raw: v && !v.id ? v.label : "" });
                            if (v && !v.id) track("school_requested", { kind: "school", name: v.label, surface: "flow" });
                          }} />
          </Field>
          <Field label="전공">
            <SearchSelect ariaLabel="전공" noun="전공" placeholder="전공 검색 (예: 경영, 컴퓨터)"
                          items={majors.map((n) => ({ id: n.node_id, label: n.label, group: n.parent_label,
                                                      keywords: n.aliases ?? [] }))}
                          value={edu.major_node_id
                            ? { id: edu.major_node_id, label: majors.find((m) => m.node_id === edu.major_node_id)?.label ?? "" }
                            : edu.major_raw ? { id: null, label: edu.major_raw } : null}
                          onChange={(v) => {
                            answer({ ...edu, major_node_id: v?.id ?? "", major_raw: v && !v.id ? v.label : "" });
                            if (v && !v.id) track("school_requested", { kind: "major", name: v.label, surface: "flow" });
                          }} suggestSimilar />
          </Field>
          <div className="pair">
            <Field label="입학">
              <YearSelect value={edu.admission_year} onChange={(v) => answer({ ...edu, admission_year: v })} />
            </Field>
            <Field label="졸업 (예정)">
              <YearSelect value={edu.graduation_year} onChange={(v) => answer({ ...edu, graduation_year: v })} />
            </Field>
          </div>
          {professional && (
            <JobFields job={current} roles={roles} onChange={(j) => { markStarted(); setCurrent(j); }}
                       labels={{ role: "지금 직무", start: "입사" }} />
          )}
          {importId && others.length > 0 && (
            <>
              <h3 className="imported-title">파일에서 읽은 다른 경력</h3>
              <p className="hint">남길 경력만 체크해 주세요. 직무는 읽은 내용으로 골라뒀어요. 다르면 바꿔 주세요. 로그인하면 내 경력으로 저장돼요.</p>
              <ImportedJobs rows={others} roles={roles} onChange={setOthers} />
            </>
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
          {teaser.base.suppressed || teaser.n_directions === 0 ? (
            <>
              <h2>{teaser.base.suppressed ? "아직 나와 비슷한 사람이 적어요" : "아직 이 조건으로 간 길 기록이 없어요"}</h2>
              <p className="sub">
                {teaser.base.suppressed
                  ? "한 사람 한 사람이 드러나지 않도록, 비슷한 사람이 충분히 모이기 전에는 결과를 만들지 않아요."
                  : "비슷한 사람은 찾았지만 첫 직장 기록이 아직 모이지 않았어요."}
                {" "}연도나 전공을 바꿔서 다시 찾아볼 수 있어요.
              </p>
              {note && <p className="hint">{note}</p>}
              <button className="cta ghost" onClick={() => setScreen(professional ? "p_now" : "s_edu")}>조건 바꾸기</button>
            </>
          ) : (
            <>
              <span className="badge">찾았어요</span>
              <div className="lock">
                <span className="small">{startCaption(teaser.base.effective_filters)}</span>
                <span className="lockbig">{n.toLocaleString()}명</span>
                {teaserBasis && <span className="basis">{teaserBasis}</span>}
                {teaser.n_directions != null && (
                  <span className="small">
                    {professional
                      ? <>지금 자리에 남거나 <b>{teaser.n_directions}가지 길</b>로 옮겼어요</>
                      : teaser.n_directions > 1
                        ? <>이 사람들은 <b>{teaser.n_directions}가지 길</b>로 나뉘었어요</>
                        : <>이 사람들은 <b>한 가지 길</b>로 모였어요</>}
                  </span>
                )}
              </div>
              {note && <p className="hint">{note}</p>}
              {teaser.base.fallback_reason.length > 0 && (
                <p className="hint">{widenedText(teaser.base.exact_n)}</p>
              )}
              <div className="blur" aria-hidden="true">
                {[88, 64, 52, 40, 30].slice(0, Math.max(2, Math.min(5, (teaser.n_directions ?? 4) + 1))).map((w, i) => (
                  <div key={i} className="bar"><span>●●●●</span><span className="track"><i className={i ? "m" : ""} style={{ width: `${w}%` }} /></span><b>●●%</b></div>
                ))}
              </div>
              <h2 className="gate-title">이 중에 내 길도 있을까요?</h2>
              <p className="sub">어디로 갔는지는 로그인하면 바로 보여드려요. 입력한 내용은 그대로 이어져요.</p>
              <DesiredPicker roles={[...middleRoles, ...roles]} professional={professional}
                             value={desired} onChange={changeDesired} />
              <label className="check">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>
                  입력한 학교·경력 정보를 HMM 계정과 연결해 결과 제공과 익명 통계에 쓰는 것에 동의해요.
                  {" "}<a href="/privacy" target="_blank" rel="noreferrer">개인정보처리방침</a>
                </span>
              </label>
              <button className="cta kakao" disabled={!consent || busy} onClick={() => void kakao()}>카카오로 3초 만에 보기</button>
              {app && app !== "kakaotalk" && (
                <p className="hint">로그인이 잘 안 되면 화면 위 ⋯ 메뉴에서 ‘외부 브라우저로 열기’를 눌러 주세요. 입력한 내용은 그대로 이어져요.</p>
              )}
              {DEV_LOGIN && <button className="cta ghost" disabled={!consent || busy} onClick={devLogin}>개발용 로그인</button>}
            </>
          )}
        </section>
      )}

      {screen === "m_changes" && changes && (
        <section className="screen">
          <h2>지난번과 달라진 정보가 있어요</h2>
          <p className="sub">방금 입력한 내용으로 바꿀까요? 바꿔도 지난 기록은 지우지 않고 남겨둬요.</p>
          <ul className="changes">
            {changes.items.map((c) => (
              <li key={c.field}>
                <b>{CHANGE_LABELS[c.field]}</b>
                <span className="before">지난번: {c.before ?? "없음"}</span>
                <span className="after">이번: {c.after ?? "없음"}</span>
              </li>
            ))}
          </ul>
          <button className="cta" disabled={busy} onClick={() => decideChanges(true)}>이걸로 바꾸기</button>
          <button className="cta ghost" disabled={busy} onClick={() => decideChanges(false)}>지난번 그대로 볼게요</button>
        </section>
      )}

      {screen === "interview" && interview && (
        <InterviewStep status={interview} userType={userType} onDone={leaveInterview} onSkip={() => leaveInterview()} />
      )}

      {(screen === "s_result" || screen === "p_next") && base && (
        <section className="screen">
          <ResultCount r={base.result} note={note} basis={basisText(base.result.effective_filters, base.result.fallback_reason, years, professional)}
                       caption={professional ? "나와 같은 자리에 있었던 사람들이 고른 다음" : "나와 같은 출발점의 사람들이 처음 간 길"} />
          <Bars r={base.result} professional={professional} />
          {conclusion(base.result, professional) && <p className="conclusion">{conclusion(base.result, professional)}</p>}
          <Share r={base.result} professional={professional} />
          <button className="cta" disabled={busy || (base.result.suppressed && !professional)}
                  onClick={() => (professional && hasFirst ? toSimilar() : setScreen(professional ? "p_first" : "s_intent"))}>
            {professional ? (hasFirst ? "나와 같은 경로를 걸은 사람 보기" : "첫 직장도 넣고 더 비슷한 사람 보기")
              : "이 중에 끌리는 길이 있어요"}
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
              <ResultCount r={similar.result} caption="나와 같은 두 걸음을 걸은 사람"
                           basis={basisText(similar.result.effective_filters, similar.result.fallback_reason, years, true)} />
            )
          )}
          <h2>{professional ? "어떤 다음이 궁금해요?" : "이 중에 끌리는 길이 있나요?"}</h2>
          <p className="sub">하나만 골라주세요. 그 길로 간 사람들이 걸어간 경로를 보여드릴게요</p>
          <IntentChips middleRoles={middleRoles} top={(similar && !similar.result.suppressed ? similar : base)?.result}
                       value={intent} onChange={setIntent} />
          <button className="option muted" aria-pressed={intent === "UNDECIDED"}
                  onClick={() => setIntent("UNDECIDED")}>
            {professional ? "아직 모르겠어요 (괜찮아요, 많이 간 길부터 보여드릴게요)"
              : "아직 모르겠어요 (괜찮아요, 대학생 10명 중 7명이 그래요)"}
          </button>
          <button className="cta" disabled={busy || !intent} onClick={submitIntent}>
            {intent && intent !== "UNDECIDED"
              ? `${ro(middleRoles.find((r) => r.node_id === intent)?.label ?? "")} 간 길 보기`
              : "가장 많이 간 길부터 보기"}
          </button>
        </section>
      )}

      {screen === "me" && me && <MyScreen me={me} busy={busy} onUnlock={unlock} onUnlockCompare={unlockCompare} onUnlockCard={unlockCard}
                                          onBuy={buy}
                                          names={meNames} onChangeIntent={changeIntent}
                                          onInterview={openInterview} onImport={openImport} />}
      <BusinessInfo />
    </main>
  );
}

const CHANGE_LABELS: Record<ProfileChange["field"], string> = {
  user_type: "지금 상태", education: "학교·전공", current_job: "지금 하는 일",
};

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
               onChange={(e) => onChange({ ...job, organization_name: e.target.value, organization_id: null })} />
        <datalist id={listId}>{orgs.map((o) => <option key={o.id} value={o.name} />)}</datalist>
      </Field>
      <Field label={props.labels.role}>
        <NodeSelect nodes={props.roles} value={job.role_node_id} onChange={(v) => onChange({ ...job, role_node_id: v })} />
      </Field>
      <div className="pair">
        <Field label={props.labels.start}>
          <YearSelect value={job.start_year} onChange={(v) => onChange({ ...job, start_year: v, start_month: null })} />
        </Field>
        {props.withEnd && (
          <Field label={props.labels.end ?? "종료"}>
            <YearSelect value={job.end_year} onChange={(v) => onChange({ ...job, end_year: v, end_month: null })} />
          </Field>
        )}
      </div>
    </>
  );
}

function ResultCount({ r, caption, note, basis }: {
  r: QueryResult; caption: string; note?: string | null; basis?: string | null;
}) {
  // Small exact groups are not told; nobody at all (0) is.
  const told = r.exact_n === 0 || r.exact_n >= (r.min_cell_n ?? 5) ? r.exact_n : null;
  return (
    <div className="count">
      {!r.suppressed && <div><span className="big">{r.effective_n.toLocaleString()}</span><b> 명</b></div>}
      {!r.suppressed && basis && <p className="basis">{basis}</p>}
      <p className="sub">{caption}</p>
      {note && <p className="hint">{note}</p>}
      {r.fallback_reason.length > 0 && <p className="hint">{widenedText(told)}</p>}
    </div>
  );
}

function Bars({ r, professional }: { r: QueryResult; professional: boolean }) {
  if (r.suppressed) {
    return <p className="empty">아직 비교할 수 있는 사람이 {r.threshold}명보다 적어요. 숫자는 보여드리지 않아요.</p>;
  }
  if (r.cells.length === 0) {
    return <p className="empty">비슷한 사람은 찾았지만, 간 길 기록이 아직 모이지 않았어요.</p>;
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

function MyScreen({ me, busy, onUnlock, onUnlockCompare, onUnlockCard, onBuy, names, onChangeIntent, onInterview,
  onImport }: {
  me: MyResult; busy: boolean; onUnlock: () => void; onUnlockCompare: () => void;
  onUnlockCard: (card: CardType) => void;
  onBuy: (insight: PayableInsight) => void;
  names: { school: string | null; major: string | null }; onChangeIntent: () => void; onInterview: () => void;
  onImport: () => void;
}) {
  const p = me.intent_paths.paths;
  const professional = me.profile.user_type === "PROFESSIONAL";
  return (
    <section className="screen">
      <div className="row-between">
        <span className="badge">입력하신 내용을 이어왔어요</span>
        <span className="tube" aria-label={`보유 튜브 ${me.balance_tube}개`}>{me.balance_tube} 튜브</span>
      </div>
      <ResultCards base={me.base} compare={me.compare} cards={me.cards ?? []} professional={professional}
                   school={names.school}
                   major={names.major} label={(c) => cellLabel(c, professional)}
                   takeaway={conclusion(me.base, professional)} busy={busy} balance={me.balance_tube}
                   payments={me.payments} onUnlockCompare={onUnlockCompare}
                   onBuyCompare={() => onBuy("SCHOOL_COMPARE")} onUnlockCard={onUnlockCard}
                   onBuyCard={(card) => onBuy(card)} />
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
                <OpenButton cost={me.deep_dive.cost_tube} balance={me.balance_tube} payments={me.payments}
                            busy={busy} onTube={onUnlock} onBuy={() => onBuy("PATH_DEEP_DIVE")} />
              </>
            ) : (
              <p className="sub">이 결과는 깊은 분석을 하기엔 인원이 적어요.</p>
            )}
          </div>
          <p className="conclusion">이 사람들도 처음엔 나와 같은 자리였어요.</p>
          <button className="cta ghost" onClick={onChangeIntent}>다른 길도 보기</button>
        </>
      )}
      <ImportEntry onOpen={onImport} />
      <InterviewEntry onOpen={onInterview} />
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

function DesiredPicker({ roles, professional, value, onChange }: {
  roles: Node[]; professional: boolean; value: Desired; onChange: (d: Desired) => void;
}) {
  const items = useMemo(() => {
    const seen = new Set<string>();
    return roles.filter((r) => !seen.has(r.node_id) && seen.add(r.node_id))
      .map((r) => ({ id: r.node_id, label: r.label, group: r.depth <= 2 ? "직무 분야" : r.parent_label,
                     keywords: r.aliases ?? [] }));
  }, [roles]);
  const add = (v: Picked | null) => {
    if (!v) return;
    const dup = value.roles.some((r) => (v.id ? r.id === v.id : !r.id && r.label === v.label));
    if (!dup) onChange({ roles: [...value.roles, v].slice(0, 3), status: "CHOSEN" });
  };
  const remove = (i: number) => {
    const rest = value.roles.filter((_, j) => j !== i);
    onChange({ roles: rest, status: rest.length ? "CHOSEN" : null });
  };
  const toggle = (s: DesiredStatus) => onChange(value.status === s ? NO_DESIRED : { roles: [], status: s });
  return (
    <div className="desired">
      <p className="desired-q">{professional ? "옮기고 싶은 직무가 있어요?" : "어떤 일을 하고 싶어요?"}
        <small> 선택 · 최대 3개</small></p>
      {value.roles.length > 0 && (
        <div className="chips">
          {value.roles.map((r, i) => (
            <button key={r.id ?? `typed-${r.label}`} className="chip" aria-pressed="true"
                    aria-label={`${r.label} 빼기`} onClick={() => remove(i)}>{r.label} ✕</button>
          ))}
        </div>
      )}
      {value.roles.length < 3 && (
        <SearchSelect ariaLabel="희망 직무" noun="직무" placeholder="직무 검색 (예: 마케팅, 개발)"
                      items={items} value={null} onChange={add} suggestSimilar clearOnPick />
      )}
      <div className="chips">
        <button className="chip" aria-pressed={value.status === "NONE"} onClick={() => toggle("NONE")}>아직 없어요</button>
        {professional && (
          <button className="chip" aria-pressed={value.status === "KEEP_CURRENT"}
                  onClick={() => toggle("KEEP_CURRENT")}>지금 직무 유지</button>
        )}
      </div>
    </div>
  );
}

const phoneDigits = (p: string) => p.replace(/[^0-9]/g, "");

function InterviewStep({ status, userType, onDone, onSkip }: {
  status: InterviewStatus; userType: UserType; onDone: (s: InterviewStatus) => void; onSkip: () => void;
}) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const needCode = status.verification_required;
  const phoneOk = /^01[016789][0-9]{7,8}$/.test(phoneDigits(phone));
  const act = (fn: () => Promise<void>) => async () => {
    setErr(undefined);
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setErr(errorMessage(e) ?? "잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  };
  const sendCode = act(async () => {
    await acq.interviewCode(phone);
    setSent(true);
    track("interview_code_sent", { user_type: userType });
  });
  const submit = act(async () => {
    const s = await acq.interviewApply(phone, needCode ? code : null, INTERVIEW_CONSENT_VERSION);
    track("interview_submitted", { user_type: userType, verified: s.verified });
    onDone(s);
  });
  return (
    <section className="screen">
      <span className="badge">선택</span>
      <h2>진로 인터뷰에 참여해 주실래요?</h2>
      <p className="sub">30분 정도, 지금 하고 있는 고민을 들려주세요. 나와 같은 자리였던 사람들의 길을 더 정확하게 보여드리는 데 써요.</p>
      {status.reward_text && <p className="conclusion">{status.reward_text}</p>}
      <Field label="휴대전화번호">
        <input type="tel" inputMode="numeric" autoComplete="tel" placeholder="010-1234-5678" value={phone}
               onChange={(e) => { setPhone(e.target.value); setSent(false); setCode(""); }} />
      </Field>
      {needCode && (sent ? (
        <Field label="인증번호 (3분 안에 입력)">
          <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="6자리" value={code}
                 onChange={(e) => setCode(phoneDigits(e.target.value).slice(0, 6))} />
        </Field>
      ) : (
        <button className="cta ghost" disabled={!phoneOk || busy} onClick={sendCode}>인증번호 받기</button>
      ))}
      <label className="check consent-detail">
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        <span>
          <b>[선택] 인터뷰 연락을 위한 개인정보 수집·이용 동의</b><br />
          목적: 진로 인터뷰(유저 인터뷰) 참여 연락 · 항목: 휴대전화번호 ·
          보유 기간: 동의한 날부터 1년 (그 전에 철회하면 바로 삭제)<br />
          동의하지 않아도 되고, 동의하지 않아도 서비스는 그대로 이용할 수 있어요.
        </span>
      </label>
      {err && <p className="error" role="alert">{err}</p>}
      {sent && needCode && <button className="link" disabled={busy} onClick={sendCode}>인증번호 다시 받기</button>}
      <button className="cta" disabled={busy || !phoneOk || !agree || (needCode && (!sent || code.length !== 6))}
              onClick={submit}>인터뷰 신청하기</button>
      <button className="cta ghost" disabled={busy} onClick={onSkip}>다음에 할게요</button>
    </section>
  );
}

/** On the result: invite again later (if skipped), or show the request and let them withdraw. */
function InterviewEntry({ onOpen }: { onOpen: () => void }) {
  const [s, setS] = useState<InterviewStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => { acq.interview().then(setS).catch(() => setS(null)); }, []);
  if (!s) return null;
  if (s.status === "APPLIED") {
    const withdraw = async () => {
      setBusy(true);
      setFailed(false);
      try {
        setS(await acq.interviewWithdraw());
        track("interview_withdrawn", {});
      } catch {
        setFailed(true);
      } finally {
        setBusy(false);
      }
    };
    return (
      <>
        <p className="hint">진로 인터뷰 신청 완료 ({s.phone_masked}) · {" "}
          <button className="link" disabled={busy} onClick={withdraw}>신청 취소하고 번호 지우기</button></p>
        {failed && <p className="error" role="alert">취소하지 못했어요. 잠시 후 다시 눌러 주세요.</p>}
      </>
    );
  }
  if (!s.enabled) return null;
  return <button className="link share" onClick={onOpen}>진로 인터뷰 참여하기 (30분)</button>;
}
