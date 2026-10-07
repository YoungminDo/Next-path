/** Browser-side API client. Calls go through the same-origin proxy (/api/backend), where the
 * HttpOnly session cookie is turned into an Authorization header. */

export type Distribution = { value: string | number; n: number; share_pct: number }[];

export type Teaser = {
  available: boolean;
  cohort_label: string;
  cohort_size_band: string | null;
  data_basis: "SIMULATION" | "OBSERVED";
  notice: string | null;
};

export type CareerMap = {
  cohort: { label: string; is_exact: boolean; effective_n: number; fallback_level: number };
  data_basis: "SIMULATION" | "OBSERVED";
  notice: string | null;
  suppressed: boolean;
  message?: string;
  anchor?: string;
  basis_n?: number;
  next_job_family?: Distribution;
  next_industry?: Distribution;
  next_company_size?: Distribution;
  unlocks?: { insight_type: string; unlocked: boolean; available: boolean; cost_tube: number | null }[];
};

export type TaxonomyItem = { id: string; name: string };

export class ApiError extends Error {
  constructor(public status: number, body: string) {
    super(`${status} ${body}`);
  }
}

const KEYS = { anon: "hellomyme.anon", draft: "hellomyme.draft", consent: "hellomyme.consent" };

function local(key: string, value?: string | null): string | null {
  try {
    if (value === null) localStorage.removeItem(key);
    else if (value !== undefined) localStorage.setItem(key, value);
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function anonymousSession(): string {
  return local(KEYS.anon) ?? local(KEYS.anon, crypto.randomUUID().replace(/-/g, ""))!;
}

export const pending = {
  draftId: (v?: string | null) => local(KEYS.draft, v),
  consentVersion: (v?: string | null) => local(KEYS.consent, v),
};

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/backend${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Anonymous-Session": anonymousSession(),
      ...(init.headers as Record<string, string>),
    },
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}

// --- acquisition (v1.4) -------------------------------------------------------------------

export type Node = { node_id: string; code: string; label: string; depth: number;
  parent_label: string | null; matched_alias: string | null };
export type Cell = { key: string; code: string; label: string | null; depth: number | null;
  n: number; share: number };
export type QueryResult = {
  exact_n: number; effective_n: number; fallback_reason: string[]; suppressed: boolean;
  cells: Cell[]; other: { n: number | null; share: number | null; suppressed?: boolean } | null;
  threshold: number; time_window: { start: string | null; end: string };
};
export type PathSummary = {
  target: { node_id: string; label: string }; from: { node_id: string; label: string } | null;
  suppressed: boolean; min_cell_n: number; n_people: number | null; n_paths: number | null;
  n_paths_shown: number | null; median_months: number | null;
  paths?: { path: { node_id: string; label: string }[]; n: number; share: number }[];
  other_n?: number | null;
};
export type IntentResult = {
  step: "intent_paths"; cohort_basis: string; target_basis: "INTENT" | "MOST_COMMON" | "NONE";
  base: { effective_n: number; fallback_reason: string[]; suppressed: boolean };
  paths: PathSummary | null; data_basis: "SIMULATION" | "OBSERVED";
};
export type StepResult = { step: string; result: QueryResult; data_basis: "SIMULATION" | "OBSERVED" };
export type DeepDiveItem = { key: string; label: string | null; n: number };
export type MyResult = {
  profile: Record<string, unknown>; intent: { target_kind: string; target_node_id: string | null } | null;
  base: QueryResult; intent_paths: IntentResult;
  deep_dive: { unlocked: boolean; available: boolean; cost_tube: number | null;
    content: { company_size: DeepDiveItem[]; industry: DeepDiveItem[] } | null };
  balance_tube: number; data_basis: "SIMULATION" | "OBSERVED";
};
export type AcqStep = "first_roles" | "next_roles" | "similar_paths";
export type TeaserResult = {
  step: "teaser"; n_directions: number | null; data_basis: "SIMULATION" | "OBSERVED";
  base: { effective_n: number; exact_n: number; fallback_reason: string[]; suppressed: boolean };
};
export type Intent = { surface: "STUDENT_FIRST_ROLE" | "PROFESSIONAL_NEXT_ROLE";
  target_kind: "ROLE" | "UNDECIDED"; target_node_id: string | null };

export const acq = {
  institutions: () => call<{ id: string; name: string; region: string | null }[]>("/acq/options/institutions"),
  majors: (depth?: number) => call<Node[]>(`/acq/options/majors${depth ? `?depth=${depth}` : ""}`),
  roles: (depth?: number) => call<Node[]>(`/acq/options/roles${depth ? `?depth=${depth}` : ""}`),
  organizations: (q: string) =>
    call<{ id: string; name: string }[]>(`/acq/options/organizations?q=${encodeURIComponent(q)}`),
  saveDraft: (payload: unknown, draftId?: string) =>
    call<{ draft_id: string }>("/acq/draft", {
      method: "POST",
      body: JSON.stringify({ draft_id: draftId ?? null, payload }),
    }),
  /** Before login only the teaser exists: how many people, how many directions. */
  teaser: (draftId: string) =>
    call<TeaserResult>(`/acq/draft/${draftId}/result`, { method: "POST", body: JSON.stringify({ step: "teaser" }) }),
  me: () => call<MyResult>("/acq/me"),
  meStep: (step: AcqStep) => call<StepResult>(`/acq/me/step/${step}`),
  addJob: (job: unknown) =>
    call<{ work_event_id: string | null; replayed: boolean }>("/acq/me/jobs", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ job }),
    }),
  setIntent: (intent: Intent) =>
    call<{ intent_event_ids: string[] }>("/acq/me/intent", { method: "POST", body: JSON.stringify({ intent }) }),
  unlock: () =>
    call<{ unlocked: boolean; charged?: boolean; balance_tube?: number;
      content?: MyResult["deep_dive"]["content"] }>("/acq/me/unlock", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
};

export const api = {
  taxonomy: (kind: "institutions" | "majors" | "roles") => call<TaxonomyItem[]>(`/taxonomy/${kind}`),
  saveDraft: (payload: unknown, draftId?: string) =>
    call<{ draft_id: string }>("/career/draft", {
      method: "POST",
      body: JSON.stringify({ draft_id: draftId, payload }),
    }),
  teaser: (draftId: string) =>
    call<Teaser>("/career/draft/query", { method: "POST", body: JSON.stringify({ draft_id: draftId }) }),
  mergeDraft: (draftId: string, consentPolicyVersion: string) =>
    call<{ person_id: string }>("/auth/merge-draft", {
      method: "POST",
      headers: { "Idempotency-Key": `merge-${draftId}` },
      body: JSON.stringify({ draft_id: draftId, consent_policy_version: consentPolicyVersion }),
    }),
  careerMap: () => call<CareerMap>("/career/map"),
  credits: () => call<{ balance_tube: number }>("/credits"),
  unlock: (insightType: string) =>
    call<{ unlocked: boolean; insight: Record<string, unknown> }>("/career/unlock", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ insight_type: insightType }),
    }),
  devLogin: async () => {
    const res = await fetch("/auth/dev", { method: "POST" });
    if (!res.ok) throw new ApiError(res.status, await res.text());
  },
  logout: () => fetch("/auth/logout", { method: "POST" }),
};
