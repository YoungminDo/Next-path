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
