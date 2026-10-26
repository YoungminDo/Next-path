/** Funnel events for the demand test (POST /analytics/events through the same-origin proxy).
 * Anonymous: a random session id, first-touch utm/referrer (and whether an ad click id came along, or the
 * answers were handed over from an in-app browser), never names or free text about a
 * person. Visiting once with ?internal=1 marks this browser as the team's, so the funnel
 * query can leave it out. Tracking never breaks the page: every failure is swallowed. */
import { anonymousSession } from "@/lib/api";

export type FunnelEvent =
  | "landing_viewed" | "career_input_started" | "career_input_completed" | "login_wall_viewed"
  | "login_clicked" | "signup_completed" | "result_step_viewed" | "result_left"
  | "intent_selected" | "unlock_purchased" | "school_requested" | "desired_role_selected"
  | "interview_step_viewed" | "interview_skipped" | "interview_code_sent" | "interview_submitted"
  | "interview_withdrawn" | "import_viewed" | "import_uploaded" | "import_parsed" | "import_confirmed"
  | "payment_started" | "payment_failed" | "credit_purchased"
  | "checkout_viewed" | "checkout_completed" | "checkout_cancelled" | "login_consent_missing"
  | "alert_step_viewed" | "alert_code_sent" | "alert_subscribed" | "alert_skipped" | "alert_withdrawn";

const TOUCH = "hellomyme.touch";

/** The app whose built-in browser shows the page (a DM link opens inside Instagram), or null. */
export function inAppBrowser(): string | null {
  try {
    const ua = navigator.userAgent;
    if (/Instagram/i.test(ua)) return "instagram";
    if (/Barcelona/i.test(ua)) return "threads";
    if (/FBAN|FBAV|FB_IAB|FBIOS/i.test(ua)) return "facebook";
    if (/KAKAOTALK/i.test(ua)) return "kakaotalk";
    if (/NAVER\(inapp|whale\/[\d.]+ .*inapp/i.test(ua)) return "naver";
    if (/ Line\//i.test(ua)) return "line";
    return null;
  } catch {
    return null;
  }
}
const INTERNAL = "hellomyme.internal";

function store(key: string, value?: string): string | null {
  try {
    if (value !== undefined) localStorage.setItem(key, value);
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

// This page's first touch, for when the in-app browser swaps the storage under it (see anonymousSession).
let pageTouch: Record<string, string> | null = null;

/** First visit's channel, kept so later steps (and the login round trip) carry it. */
function attribution(): Record<string, string> {
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("internal") === "1") store(INTERNAL, "1");
    if (params.get("internal") === "0") localStorage.removeItem(INTERNAL);
    const saved = store(TOUCH);
    if (saved) return (pageTouch = JSON.parse(saved) as Record<string, string>);
    if (pageTouch) {
      store(TOUCH, JSON.stringify(pageTouch));
      return pageTouch;
    }
    const touch: Record<string, string> = {};
    for (const k of ["utm_source", "utm_medium", "utm_campaign", "utm_content", "ref"]) {
      const v = params.get(k);
      if (v) touch[k] = v.slice(0, 100);
    }
    if (document.referrer) {
      const host = new URL(document.referrer).host;
      if (host && host !== window.location.host) touch.referrer = host;
    }
    // In-app browsers often send no referrer: the app itself tells where the visit came from.
    const app = inAppBrowser();
    if (app) touch.in_app = app;
    // Meta adds fbclid to real ad clicks only (its ad review opens the page without it). Only the fact
    // is kept, never the id, so paid visits can be told from review visits (docs/10 §사람이 아닌 방문).
    if (params.get("fbclid")) touch.fbclid = "1";
    // The phone's browser opened from an in-app browser with the answers: the same person, not a new visit.
    if (params.get("handoff") === "1") touch.handoff = "1";
    store(TOUCH, JSON.stringify(touch));
    return (pageTouch = touch);
  } catch {
    return {};
  }
}

/** Automated browsers and crawlers (Meta's ad review, link checkers): kept, but left out of statistics. */
function automated(): boolean {
  try {
    if (navigator.webdriver) return true;
    return /bot|crawler|spider|facebookexternalhit|facebot|headlesschrome|lighthouse/i.test(navigator.userAgent);
  } catch {
    return false;
  }
}

/** The team's own browser (?internal=1): drafts and events are kept but left out of statistics. */
export function isInternal(): boolean {
  attribution(); // reads ?internal=1 / ?internal=0 on the first call of a page
  return store(INTERNAL) === "1";
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
        ...(automated() ? { bot: true } : {}),
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
