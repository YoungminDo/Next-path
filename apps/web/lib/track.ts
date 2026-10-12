/** Funnel events for the demand test (POST /analytics/events through the same-origin proxy).
 * Anonymous: a random session id, first-touch utm/referrer, never names or free text about a
 * person. Visiting once with ?internal=1 marks this browser as the team's, so the funnel
 * query can leave it out. Tracking never breaks the page: every failure is swallowed. */
import { anonymousSession } from "@/lib/api";

export type FunnelEvent =
  | "landing_viewed" | "career_input_started" | "career_input_completed" | "login_wall_viewed"
  | "login_clicked" | "signup_completed" | "result_step_viewed" | "result_left"
  | "intent_selected" | "unlock_purchased" | "school_requested";

const TOUCH = "hellomyme.touch";
const INTERNAL = "hellomyme.internal";

function store(key: string, value?: string): string | null {
  try {
    if (value !== undefined) localStorage.setItem(key, value);
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** First visit's channel, kept so later steps (and the login round trip) carry it. */
function attribution(): Record<string, string> {
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("internal") === "1") store(INTERNAL, "1");
    if (params.get("internal") === "0") localStorage.removeItem(INTERNAL);
    const saved = store(TOUCH);
    if (saved) return JSON.parse(saved);
    const touch: Record<string, string> = {};
    for (const k of ["utm_source", "utm_medium", "utm_campaign", "utm_content", "ref"]) {
      const v = params.get(k);
      if (v) touch[k] = v.slice(0, 100);
    }
    if (document.referrer) {
      const host = new URL(document.referrer).host;
      if (host && host !== window.location.host) touch.referrer = host;
    }
    store(TOUCH, JSON.stringify(touch));
    return touch;
  } catch {
    return {};
  }
}

export function track(name: FunnelEvent, properties: Record<string, unknown> = {}) {
  try {
    const body = JSON.stringify({
      event_name: name,
      occurred_at: new Date().toISOString(),
      anonymous_session_id: anonymousSession(),
      properties: {
        ...properties,
        ...attribution(),
        path: window.location.pathname,
        mobile: window.matchMedia("(max-width: 640px)").matches,
        ...(store(INTERNAL) === "1" ? { internal: true } : {}),
      },
    });
    // keepalive lets the last event of a page (result_left) still arrive while it unloads.
    void fetch("/api/backend/analytics/events", {
      method: "POST", body, keepalive: true, headers: { "Content-Type": "application/json" },
    }).catch(() => undefined);
  } catch {
    /* never let measurement break the product */
  }
}
