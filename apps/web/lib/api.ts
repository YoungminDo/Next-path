const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

function anonymousSession(): string {
  const key = "hellomyme.anon";
  let value = localStorage.getItem(key);
  if (!value) {
    value = crypto.randomUUID().replace(/-/g, "");
    localStorage.setItem(key, value);
  }
  return value;
}

async function call<T>(path: string, init: RequestInit & { token?: string } = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Anonymous-Session": anonymousSession(),
    ...(init.headers as Record<string, string>),
  };
  if (init.token) headers.Authorization = `Bearer ${init.token}`;
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  taxonomy: (kind: "institutions" | "majors" | "roles") =>
    call<TaxonomyItem[]>(`/taxonomy/${kind}`),
  saveDraft: (payload: unknown, draftId?: string) =>
    call<{ draft_id: string }>("/career/draft", {
      method: "POST",
      body: JSON.stringify({ draft_id: draftId, payload }),
    }),
  teaser: (draftId: string) =>
    call<Teaser>("/career/draft/query", { method: "POST", body: JSON.stringify({ draft_id: draftId }) }),
  login: (provider: string, token: string) =>
    call<{ session_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ provider, token }),
    }),
  mergeDraft: (token: string, draftId: string) =>
    call<{ person_id: string }>("/auth/merge-draft", {
      method: "POST",
      token,
      headers: { "Idempotency-Key": `merge-${draftId}` },
      body: JSON.stringify({ draft_id: draftId }),
    }),
  careerMap: (token: string) => call<CareerMap>("/career/map", { token }),
  credits: (token: string) => call<{ balance_tube: number }>("/credits", { token }),
  unlock: (token: string, insightType: string) =>
    call<{ unlocked: boolean; insight: Record<string, unknown> }>("/career/unlock", {
      method: "POST",
      token,
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ insight_type: insightType }),
    }),
};
