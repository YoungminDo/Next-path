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
