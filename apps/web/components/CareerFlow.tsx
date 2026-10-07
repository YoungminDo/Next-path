"use client";

import { useEffect, useState } from "react";

import {
  api,
  ApiError,
  pending,
  type CareerMap,
  type Distribution,
  type Teaser,
  type TaxonomyItem,
} from "@/lib/api";

type UserType = "STUDENT" | "JOB_SEEKER" | "PROFESSIONAL";
type Step = "type" | "input" | "teaser" | "map";

const INSIGHT_LABELS: Record<string, string> = {
  PATH_DEEP_DIVE: "이 미래 자세히 열어보기",
  COMPANY_BREAKDOWN: "어떤 회사로 갔는지 열어보기",
  REPRESENTATIVE_PATHS: "대표 경로 열어보기",
  TIMING_TENURE: "언제 움직였는지 열어보기",
};
const LOGIN_ERRORS: Record<string, string> = {
  kakao_denied: "카카오 로그인이 취소됐어요.",
  no_hmm_session: "로그인 정보를 받지 못했어요. 다시 시도해 주세요.",
  hmm_token_rejected: "로그인이 만료됐어요. 다시 시도해 주세요.",
};
const DEV_LOGIN = process.env.NEXT_PUBLIC_ENABLE_DEV_LOGIN === "true";
const CONSENT_VERSION = process.env.NEXT_PUBLIC_CONSENT_POLICY_VERSION ?? "career_terms_v1";

export default function CareerFlow() {
  const [step, setStep] = useState<Step>("type");
  const [userType, setUserType] = useState<UserType>("STUDENT");
  const [institutions, setInstitutions] = useState<TaxonomyItem[]>([]);
  const [majors, setMajors] = useState<TaxonomyItem[]>([]);
  const [roles, setRoles] = useState<TaxonomyItem[]>([]);
  const [form, setForm] = useState({ institution: "", major: "", year: "", role: "", start: "" });
  const [draftId, setDraftId] = useState<string>();
  const [teaser, setTeaser] = useState<Teaser>();
  const [consent, setConsent] = useState(false);
  const [map, setMap] = useState<CareerMap>();
  const [balance, setBalance] = useState<number>();
  const [insight, setInsight] = useState<Record<string, unknown>>();
  const [error, setError] = useState<string>();

  const run = (fn: () => Promise<void>) => () => {
    setError(undefined);
    fn().catch((e) => setError(String(e)));
  };

  async function showMap() {
    setMap(await api.careerMap());
    setBalance((await api.credits()).balance_tube);
    setStep("map");
  }

  /** After login (HMM ID redirect or dev login): merge the saved draft, then open the map. */
  async function finishLogin() {
    const savedDraft = pending.draftId();
    const consentVersion = pending.consentVersion();
    if (savedDraft && consentVersion) {
      await api.mergeDraft(savedDraft, consentVersion);
      pending.draftId(null);
      pending.consentVersion(null);
    }
    try {
      await showMap();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError("아직 저장된 경력이 없어요. 먼저 입력해 주세요.");
        setStep("type");
      } else {
        throw e;
      }
    }
  }

  useEffect(() => {
    Promise.all([api.taxonomy("institutions"), api.taxonomy("majors"), api.taxonomy("roles")])
      .then(([i, m, r]) => {
        setInstitutions(i);
        setMajors(m);
        setRoles(r);
      })
      .catch((e) => setError(String(e)));

    const params = new URLSearchParams(window.location.search);
    const loginError = params.get("login_error");
    const loggedIn = params.get("login") === "success";
    if (loginError || loggedIn) window.history.replaceState(null, "", window.location.pathname);
    if (loginError) setError(LOGIN_ERRORS[loginError] ?? `로그인에 실패했어요 (${loginError}).`);
    if (loggedIn) finishLogin().catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submitDraft = run(async () => {
    const events =
      userType === "PROFESSIONAL" && form.role
        ? [{ event_type: "EMPLOYMENT", role_id: form.role, start_date: form.start || null, is_current: true }]
        : [];
    const payload = {
      user_type: userType,
      education: {
        institution_id: form.institution || null,
        major_id: form.major || null,
        graduation_year: form.year ? Number(form.year) : null,
      },
      career_events: events,
    };
    const draft = await api.saveDraft(payload, draftId);
    setDraftId(draft.draft_id);
    setTeaser(await api.teaser(draft.draft_id));
    setStep("teaser");
  });

  /** Remember what to merge, because the HMM ID login leaves this page. */
  function rememberDraft() {
    if (!draftId) return;
    pending.draftId(draftId);
    pending.consentVersion(CONSENT_VERSION);
  }

  const kakaoLogin = () => {
    rememberDraft();
    window.location.href = "/auth/hmm/start";
  };

  const devLogin = run(async () => {
    rememberDraft();
    await api.devLogin();
    await finishLogin();
  });

  const unlock = (type: string) =>
    run(async () => {
      const res = await api.unlock(type);
      setInsight(res.insight);
      await showMap();
    })();

  return (
    <main className="container">
      <h1>나와 비슷한 사람들의 다음은?</h1>
      {error && <p className="error">{error}</p>}

      {step === "type" && (
        <section className="card">
          <h2>지금 나는</h2>
          <div className="row">
            {(["STUDENT", "JOB_SEEKER", "PROFESSIONAL"] as UserType[]).map((t) => (
              <button
                key={t}
                className={userType === t ? "primary" : ""}
                onClick={() => {
                  setUserType(t);
                  setStep("input");
                }}
              >
                {{ STUDENT: "학생", JOB_SEEKER: "취준생", PROFESSIONAL: "현직자" }[t]}
              </button>
            ))}
          </div>
        </section>
      )}

      {step === "input" && (
        <section className="card">
          <h2>학교·학과·졸업년도</h2>
          <Select label="학교" items={institutions} value={form.institution}
                  onChange={(v) => setForm({ ...form, institution: v })} />
          <Select label="학과" items={majors} value={form.major}
                  onChange={(v) => setForm({ ...form, major: v })} />
          <label>
            졸업(예정)년도
            <input inputMode="numeric" value={form.year}
                   onChange={(e) => setForm({ ...form, year: e.target.value })} />
          </label>
          {userType === "PROFESSIONAL" && (
            <>
              <Select label="현재 직무" items={roles} value={form.role}
                      onChange={(v) => setForm({ ...form, role: v })} />
              <label>
                시작일
                <input type="date" value={form.start}
                       onChange={(e) => setForm({ ...form, start: e.target.value })} />
              </label>
            </>
          )}
          <button className="primary" onClick={submitDraft}>나와 비슷한 사람들의 다음은?</button>
        </section>
      )}

      {step === "teaser" && teaser && (
        <section className="card">
          <Notice text={teaser.notice} />
          {teaser.available ? (
            <p>
              <strong>{teaser.cohort_label}</strong> 기준으로 {teaser.cohort_size_band}명의 실제 선택을
              찾았어요.
            </p>
          ) : (
            <p>아직 비교할 수 있는 사람이 충분하지 않아요.</p>
          )}
          <p className="muted">입력한 내용은 저장돼 있어요. 로그인하면 바로 이어서 볼 수 있어요.</p>
          <label className="consent">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            입력한 학교·경력 정보를 HMM 계정과 연결해 Career Map 제공에 사용하는 것에 동의해요.
          </label>
          <div className="row">
            <button className="kakao" disabled={!consent} onClick={kakaoLogin}>
              카카오로 계속하기
            </button>
            {DEV_LOGIN && (
              <button disabled={!consent} onClick={devLogin}>
                개발용 로그인
              </button>
            )}
          </div>
        </section>
      )}

      {step === "map" && map && (
        <section className="card">
          <Notice text={map.notice} />
          <p className="muted">
            비교 그룹: {map.cohort.label} · {map.cohort.effective_n}명 · 보유 {balance ?? 0} 튜브
          </p>
          {map.suppressed ? (
            <p>{map.message ?? "아직 비교할 수 있는 사람이 충분하지 않아요."}</p>
          ) : (
            <>
              <Dist title="다음 직무" data={map.next_job_family} />
              <Dist title="다음 산업" data={map.next_industry} />
              <Dist title="다음 회사 규모" data={map.next_company_size} />
              <div className="row">
                {map.unlocks?.filter((u) => u.available).map((u) => (
                  <button key={u.insight_type} onClick={() => unlock(u.insight_type)}>
                    {INSIGHT_LABELS[u.insight_type]} {u.unlocked ? "✓" : `· ${u.cost_tube} 튜브`}
                  </button>
                ))}
              </div>
              {insight && <pre className="insight">{JSON.stringify(insight, null, 2)}</pre>}
            </>
          )}
        </section>
      )}
    </main>
  );
}

function Select(props: { label: string; items: TaxonomyItem[]; value: string; onChange: (v: string) => void }) {
  return (
    <label>
      {props.label}
      <select value={props.value} onChange={(e) => props.onChange(e.target.value)}>
        <option value="">선택</option>
        {props.items.map((i) => (
          <option key={i.id} value={i.id}>
            {i.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function Notice({ text }: { text: string | null }) {
  return text ? <p className="notice">{text}</p> : null;
}

function Dist({ title, data }: { title: string; data?: Distribution }) {
  if (!data?.length) return null;
  return (
    <div className="dist">
      <h3>{title}</h3>
      {data.map((d) => (
        <div key={String(d.value)} className="bar">
          <span>{d.value === "OTHER" ? "기타" : d.value}</span>
          <div style={{ width: `${d.share_pct}%` }} />
          <em>{d.share_pct}%</em>
        </div>
      ))}
    </div>
  );
}
