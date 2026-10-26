/** Team dashboard data (GET /admin/stats through the same-origin proxy). Counts only. */
import { ApiError } from "@/lib/api";

export type AdminRange = "today" | "7d" | "30d" | "all";
export type FunnelStep = { key: string; label: string; people: number };
export type Daily = { day: string; landing: number; input_completed: number; signup: number };
export type Named = { name: string; listed: boolean; people: number };
export type AdminStats = {
  range: AdminRange; with_team: boolean; since: string | null;
  funnel: FunnelStep[];
  daily: Daily[];
  channels: { channel: string; landing: number; input_completed: number; signup: number; result: number }[];
  campaigns: { source: string | null; campaign: string; visits: number; inputs: number; login_clicks: number;
    new_members: number }[];
  dwell: { screen: string; label: string; views: number; median_seconds: number | null }[];
  inputs: { people: number; professionals: number; unlisted_school: number; unlisted_major: number; linked: number };
  schools: Named[];
  majors: Named[];
  combos: { school: string | null; major: string | null; people: number }[];
  desired_status: { status: "CHOSEN" | "NONE" | "UNSURE" | "KEEP_CURRENT" | "SKIPPED"; people: number }[];
  desired_roles: (Named & { first_choice: number })[];
  backlog: { kind: "INSTITUTION" | "MAJOR" | "ROLE"; name: string; people: number; spellings: number }[];
  interview: { applied: number; verified: number; withdrawn: number; applied_in_range: number;
    shown: number; skipped: number; submitted: number };
  imports: { reads: number; before_login: number; parsed: number; not_career: number; failed: number;
    input_tokens: number; output_tokens: number; drafts: number; signed_up: number; est_cost_usd: number;
    stats_consented: number; experiences_kept: number };
  /** Paid cards and the payment-intent test, per card. */
  pay: {
    cards: { card: string; unlocked: number; orders: number; buyers: number; test_completed: number;
      paid: number; paid_krw: number }[];
    checkout: { started: number; viewed: number; completed: number; cancelled: number };
  };
  /** The login gate: Kakao pressed before the consent box was ticked, and then pressed with it. */
  gate: { consent_missing: number; then_clicked: number };
  /** /alert, login first: the landing's browsers, step by step to the resume, the alert and the analysis. */
  alert: FunnelStep[];
};

/** 401: not logged in. 403: logged in, not on the admin list (the body says the account id). */
export class AdminError extends Error {
  constructor(public status: number, public accountId: string | null) {
    super(`admin ${status}`);
  }
}

export async function loadStats(range: AdminRange, withTeam: boolean): Promise<AdminStats> {
  const q = new URLSearchParams({ range, with_team: String(withTeam) });
  const res = await fetch(`/api/backend/admin/stats?${q}`, { cache: "no-store" });
  if (res.status === 401 || res.status === 403) {
    let id: string | null = null;
    try { id = (await res.json()).detail?.account_id ?? null; } catch { /* no body */ }
    throw new AdminError(res.status, id);
  }
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<AdminStats>;
}

/** The review queue: members' own texts, newest first, publish-consented pending ones on top. */
export type AdminReview = { review_id: string; surface: "FIT" | "ALERT"; body: string; publish: boolean;
  created_at: string; state: "PENDING" | "APPROVED" | "HIDDEN" };

async function reviewsCall(path: string, init?: RequestInit): Promise<AdminReview[]> {
  const res = await fetch(`/api/backend/admin/reviews${path}`, { cache: "no-store", ...init });
  if (res.status === 401 || res.status === 403) throw new AdminError(res.status, null);
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return ((await res.json()) as { reviews: AdminReview[] }).reviews;
}

export const loadReviews = () => reviewsCall("");
export const decideReview = (id: string, decision: "APPROVED" | "HIDDEN") =>
  reviewsCall(`/${id}`, { method: "POST", headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ decision }) });
