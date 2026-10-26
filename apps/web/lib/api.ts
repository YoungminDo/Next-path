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

const KEYS = { anon: "hellomyme.anon", draft: "hellomyme.draft", consent: "hellomyme.consent",
  member: "hellomyme.member" };

function local(key: string, value?: string | null): string | null {
  try {
    if (value === null) localStorage.removeItem(key);
    else if (value !== undefined) localStorage.setItem(key, value);
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

// The id this page has already used. Instagram's in-app browser can load the landing ahead of the tap
// and then hand the page fresh storage: without this the next event would start a second "browser"
// for the same person (docs/10 §방문).
let pageSession: string | null = null;

export function anonymousSession(): string {
  const saved = local(KEYS.anon);
  pageSession = saved ?? pageSession ?? crypto.randomUUID().replace(/-/g, "");
  if (saved !== pageSession) local(KEYS.anon, pageSession);
  return pageSession;
}

export const pending = {
  draftId: (v?: string | null) => local(KEYS.draft, v),
  consentVersion: (v?: string | null) => local(KEYS.consent, v),
  /** Set after a login on this browser: only then is the member's result looked up on load. */
  member: (v?: string | null) => local(KEYS.member, v),
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
  parent_label: string | null; matched_alias: string | null; aliases?: string[] };
export type Institution = { id: string; name: string; region?: string | null; aliases?: string[] };
/** Answers that were typed names the list does not know: that dimension was left out. */
export type Unlisted = ("institution" | "major")[];
export type Cell = { key: string; code: string; label: string | null; depth: number | null;
  n: number; share: number };
/** The group actually used, after any widening: what the number counts. */
export type CohortFilters = {
  institution_ids?: string[]; majors?: { node_id: string; code: string; label: string }[];
  admission_year?: { from: number | null; to: number | null } | null;
  graduation_year?: { from: number | null; to: number | null } | null;
  /** What stood in for a typed name the list does not know: its region, or listed majors close
   * to it (SIMILAR) or the family it names (FAMILY). */
  similar?: { region?: string; major?: "SIMILAR" | "FAMILY" };
};
export type QueryResult = {
  exact_n: number; effective_n: number; fallback_reason: string[]; suppressed: boolean;
  effective_filters?: CohortFilters;
  cells: Cell[]; other: { n: number | null; share: number | null; suppressed?: boolean } | null;
  threshold: number; min_cell_n?: number; time_window: { start: string | null; end: string };
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
export type StepResult = { step: string; result: QueryResult; data_basis: "SIMULATION" | "OBSERVED";
  unlisted?: Unlisted };
export type DeepDiveItem = { key: string; label: string | null; n: number };
export type MyResult = {
  profile: Record<string, unknown>; intent: { target_kind: string; target_node_id: string | null } | null;
  base: QueryResult; intent_paths: IntentResult;
  deep_dive: { unlocked: boolean; available: boolean; cost_tube: number | null;
    content: { company_size: DeepDiveItem[]; industry: DeepDiveItem[] } | null };
  /** Other schools, same major: a 튜브 product; the result only once opened. */
  compare: { available: boolean; unlocked: boolean; cost_tube: number | null; result: QueryResult | null };
  /** More result cards on the same cohort (1 튜브 each); the numbers only once opened. */
  cards: ResultCard[];
  /** Paid cards: with no 튜브 left a card opens for price_krw. TOSS = Toss Payments; TEST = the
   *  payment-intent test (our checkout, nothing charged, a 튜브 gifted). */
  payments: Payments;
  balance_tube: number; data_basis: "SIMULATION" | "OBSERVED"; unlisted?: Unlisted;
};
export type AcqStep = "first_roles" | "next_roles" | "similar_paths";
export type TeaserResult = {
  step: "teaser"; n_directions: number | null; data_basis: "SIMULATION" | "OBSERVED";
  // Sizes are withheld (null) when the group is too small to describe.
  base: { effective_n: number | null; exact_n: number | null; fallback_reason: string[]; suppressed: boolean;
    effective_filters?: CohortFilters };
  unlisted?: Unlisted;
};
export type DesiredRole = { role_node_id: string | null; role_raw: string | null };
export type CardType = "FIRST_COMPANY_SIZE" | "SIZE_MOVE" | "FIRST_JOB_TENURE" | "JOB_MOVES" | "ROLE_NOW"
  | "NEXT_COMPANY_SIZE" | "ROLE_SIZE_MOVE" | "ROLE_SWITCH" | "ROLE_TENURE" | "ROLE_JOB_MOVES";
export type ResultCard = { type: CardType; available: boolean; unlocked: boolean; cost_tube: number | null;
  result: QueryResult | null };
export type Payments = { enabled: boolean; mode: "TOSS" | "TEST" | null; price_krw: number | null };
/** Cards that can be bought (one 튜브 each, 990원 when no 튜브 is left). */
export type PayableInsight = "SCHOOL_COMPARE" | "PATH_DEEP_DIVE" | CardType;
export type PayOrder = { order_id: string; mode: "TOSS" | "TEST"; status: "CREATED" | "PAID" | "FAILED" | "TEST_COMPLETED";
  amount: number; credit_amount: number; order_name: string; insight_type: PayableInsight };
export type TestMethod = "CARD" | "EASY_PAY" | "TRANSFER";
/** What a returning member's new answers would change in their profile (labels for display). */
export type ProfileChange = { field: "user_type" | "education" | "current_job"; before: string | null; after: string | null };
export type DesiredStatus = "CHOSEN" | "NONE" | "UNSURE" | "KEEP_CURRENT";
export type InterviewStatus = {
  enabled: boolean;
  status: "NONE" | "APPLIED" | "WITHDRAWN"; phone_masked: string | null; verified: boolean;
  verification_required: boolean; consent_text_version: string; reward_text: string | null;
};
export type JobAlertStatus = {
  enabled: boolean;
  status: "NONE" | "SUBSCRIBED" | "WITHDRAWN"; phone_masked: string | null; verified: boolean;
  verification_required: boolean; consent_text_version: string; marketing: boolean;
};
export type FitAnalysis = {
  analysis_id: string; created_at: string; summary: string;
  fits: { role_code: string | null; role_name: string; level: "HIGH" | "MEDIUM"; reason: string }[];
  company_types: string[];
  gaps: string[];
};
export type FitStatus = { enabled: boolean; consent_text_version: string; latest: FitAnalysis | null };
export type CoachingStatus = {
  enabled: boolean; consent_text_version: string;
  products: { sku: string; name: string; amount_krw: number }[];
  request: { sku: string; name: string; amount_krw: number; requested_at: string; phone_masked: string | null } | null;
};
export type ReviewSurface = "FIT" | "ALERT";
export type ReviewStatus = {
  enabled: boolean; consent_text_version: string;
  review: { surface: ReviewSurface; body: string; publish: boolean; created_at: string;
    state: "PENDING" | "APPROVED" | "HIDDEN" } | null;
};
/** An approved review as the landing may show it: the member's own words, the step and the month only. */
export type PublicReview = { surface: ReviewSurface; label: string; body: string; month: string };
export type EmploymentType = "FULL_TIME" | "PART_TIME" | "CONTRACT" | "INTERN";
export type ImportStatus = { enabled: boolean; consent_text_version: string;
  stats_consent_text_version: string; max_files: number; remaining_today: number };
/** One experience as the reader saw it, with what the lists matched (the person decides). */
export type ImportedJob = {
  company: string | null; title: string | null; employment_type: EmploymentType | null;
  start_year: number | null; start_month: number | null; end_year: number | null; end_month: number | null;
  is_current: boolean; suggested_role_node_id: string | null; suggested_organization_id: string | null;
  /** A gap year, 안식년 or career break: shown, never saved as a job. */
  is_career_break?: boolean;
  already_saved: boolean;
};
export type ImportedEdu = {
  school: string | null; major: string | null; degree: string | null; start_year: number | null;
  end_year: number | null; suggested_institution_id: string | null; suggested_major_node_id: string | null;
};
export type ImportRead = { import_attempt_id: string; source_kind: "LINKEDIN" | "RESUME" | "OTHER";
  experiences: ImportedJob[]; education: ImportedEdu[] };
/** A job from the file as the person confirmed it (the role pick is optional). */
export type PastJob = {
  organization_id: string | null; organization_name: string | null; role_node_id: string | null;
  role_raw: string | null; start_year: number; start_month: number | null; end_year: number | null;
  end_month: number | null; employment_type: EmploymentType | null; is_current: boolean;
};
export type Intent = { surface: "STUDENT_FIRST_ROLE" | "PROFESSIONAL_NEXT_ROLE";
  target_kind: "ROLE" | "UNDECIDED"; target_node_id: string | null };

export const acq = {
  institutions: () => call<Institution[]>("/acq/options/institutions"),
  majors: (depth?: number) => call<Node[]>(`/acq/options/majors${depth ? `?depth=${depth}` : ""}`),
  roles: (depth?: number) => call<Node[]>(`/acq/options/roles${depth ? `?depth=${depth}` : ""}`),
  organizations: (q: string) =>
    call<{ id: string; name: string }[]>(`/acq/options/organizations?q=${encodeURIComponent(q)}`),
  saveDraft: (payload: unknown, draftId?: string, internal = false) =>
    call<{ draft_id: string; unlisted?: Unlisted; revision?: number }>("/acq/draft", {
      method: "POST",
      body: JSON.stringify({ draft_id: draftId ?? null, payload, internal }),
    }),
  /** Before login only the teaser exists: how many people, how many directions. */
  teaser: (draftId: string) =>
    call<TeaserResult>(`/acq/draft/${draftId}/result`, { method: "POST", body: JSON.stringify({ step: "teaser" }) }),
  me: () => call<MyResult>("/acq/me"),
  /** A returning member applies the answers they just gave (shown before/after at login). */
  applyDraft: (draftId: string) => call<{ applied: string[] }>("/acq/me/apply-draft", {
    method: "POST", body: JSON.stringify({ draft_id: draftId }) }),
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
  createOrder: (insightType: PayableInsight, internal: boolean) =>
    call<{ order_id: string; amount: number; order_name: string; customer_key: string; insight_type: PayableInsight;
      mode: "TOSS" | "TEST" }>(
      "/acq/me/payments", { method: "POST", body: JSON.stringify({ insight_type: insightType, internal }) }),
  order: (orderId: string) => call<PayOrder>(`/acq/me/payments/${encodeURIComponent(orderId)}`),
  /** The test checkout's 결제하기: nothing is charged; a 튜브 is gifted and opens the card. */
  testComplete: (orderId: string, method: TestMethod) =>
    call<{ completed: boolean; gifted: boolean; opened: boolean; insight_type: PayableInsight; balance_tube: number }>(
      "/acq/me/payments/test-complete", { method: "POST", body: JSON.stringify({ order_id: orderId, method }) }),
  unlockCard: (card: CardType) =>
    call<{ unlocked: boolean; charged?: boolean; balance_tube?: number; result?: QueryResult }>(
      `/acq/me/cards/${card}/unlock`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() } }),
  confirmPayment: (orderId: string, paymentKey: string, amount: number) =>
    call<{ paid: boolean; opened: boolean; insight_type: PayableInsight; balance_tube: number }>(
      "/acq/me/payments/confirm", { method: "POST",
        body: JSON.stringify({ order_id: orderId, payment_key: paymentKey, amount }) }),
  unlockCompare: () =>
    call<{ unlocked: boolean; charged?: boolean; balance_tube?: number; result?: QueryResult }>(
      "/acq/me/unlock/compare", { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() } }),
  interview: () => call<InterviewStatus>("/acq/me/interview"),
  interviewCode: (phone: string) =>
    call<{ sent: boolean; expires_in: number; phone_masked: string }>("/acq/me/interview/code", {
      method: "POST", body: JSON.stringify({ phone }),
    }),
  interviewApply: (phone: string, code: string | null, consentTextVersion: string) =>
    call<InterviewStatus>("/acq/me/interview", {
      method: "POST",
      body: JSON.stringify({ phone, code, consent: true, consent_text_version: consentTextVersion }),
    }),
  interviewWithdraw: () => call<InterviewStatus>("/acq/me/interview", { method: "DELETE" }),
  jobAlert: () => call<JobAlertStatus>("/acq/me/job-alert"),
  jobAlertCode: (phone: string) =>
    call<{ sent: boolean; expires_in: number; phone_masked: string }>("/acq/me/job-alert/code", {
      method: "POST", body: JSON.stringify({ phone }),
    }),
  jobAlertSubscribe: (phone: string, code: string | null, consentTextVersion: string, marketing: boolean) =>
    call<JobAlertStatus>("/acq/me/job-alert", {
      method: "POST",
      body: JSON.stringify({ phone, code, consent: true, consent_text_version: consentTextVersion, marketing }),
    }),
  jobAlertWithdraw: () => call<JobAlertStatus>("/acq/me/job-alert", { method: "DELETE" }),
  fit: () => call<FitStatus>("/acq/me/fit"),
  /** The model answers in 10-30 s; a rerun with the same records returns the stored answer. */
  fitRun: (consentTextVersion: string) =>
    call<FitAnalysis>("/acq/me/fit", {
      method: "POST", body: JSON.stringify({ consent: true, consent_text_version: consentTextVersion }),
    }),
  coaching: () => call<CoachingStatus>("/acq/me/coaching"),
  coachingRequest: (sku: string, phone: string, consentTextVersion: string) =>
    call<CoachingStatus>("/acq/me/coaching", {
      method: "POST",
      body: JSON.stringify({ sku, phone, consent: true, consent_text_version: consentTextVersion }),
    }),
  coachingCancel: () => call<CoachingStatus>("/acq/me/coaching", { method: "DELETE" }),
  /** Empty until enough reviews are approved (the small-number rule). */
  reviews: () => call<{ reviews: PublicReview[] }>("/acq/reviews"),
  review: () => call<ReviewStatus>("/acq/me/review"),
  reviewSubmit: (surface: ReviewSurface, body: string, consentTextVersion: string | null) =>
    call<ReviewStatus>("/acq/me/review", {
      method: "POST",
      body: JSON.stringify({ surface, body, publish: consentTextVersion !== null,
                             consent_text_version: consentTextVersion }),
    }),
  reviewDelete: () => call<ReviewStatus>("/acq/me/review", { method: "DELETE" }),
  importStatus: () => call<ImportStatus>("/acq/import"),
  /** Reads the person's own files (never stored). Before login the rows only prefill the form. */
  importParse: (files: { media_type: string; data: string }[], consentTextVersion: string,
                statsConsentVersion: string | null, internal: boolean) =>
    call<ImportRead>("/acq/import/parse", {
      method: "POST",
      body: JSON.stringify({
        files, consent: true, consent_text_version: consentTextVersion,
        stats_consent: statsConsentVersion !== null, stats_consent_text_version: statsConsentVersion, internal,
      }),
    }),
  importConfirm: (importAttemptId: string, jobs: PastJob[]) =>
    call<{ added: number; skipped: number; replayed: boolean }>("/acq/me/import/confirm", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ import_attempt_id: importAttemptId, jobs }),
    }),
};

/** The message of an API error body ({"detail": {"message": ...}}), if any. */
export function errorMessage(e: unknown): string | null {
  if (!(e instanceof ApiError)) return null;
  try {
    const d = JSON.parse(e.message.slice(e.message.indexOf(" ") + 1)).detail;
    return typeof d === "object" && d && typeof d.message === "string" ? d.message : null;
  } catch {
    return null;
  }
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
    call<{ person_id: string; merged: boolean; changes?: ProfileChange[] }>("/auth/merge-draft", {
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
