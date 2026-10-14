/** Meta pixel for ad measurement (docs/11): dataset NEXTPATH웹 (lib/pixel-id.ts), never for the
 * team's own browsers (?internal=1). Only three standard events, no personal data:
 * PageView (landing), Lead (answers entered), CompleteRegistration (a new member). Automatic
 * event detection is off, so the pixel reads no button text or page content; pages that carry
 * answers in the address are cleaned before anything is sent (AcquisitionFlow). */
import { META_PIXEL_ID as PIXEL_ID } from "@/lib/pixel-id";
import { isInternal } from "@/lib/track";

type Fbq = ((...args: unknown[]) => void) & { queue?: unknown[][]; loaded?: boolean; version?: string;
  callMethod?: (...args: unknown[]) => void; push?: unknown };
type PixelEvent = "PageView" | "Lead" | "CompleteRegistration";

let ready = false;
// fbevents.js loading state, so callers can wait until queued events have left (pixelSettled).
let script: "none" | "loading" | "loaded" | "failed" = "none";
let loadedAt = 0;

function load(): Fbq | null {
  const w = window as unknown as { fbq?: Fbq; _fbq?: Fbq };
  if (!w.fbq) {
    // Meta's standard stub: queue calls until fbevents.js arrives.
    const f: Fbq = (...args: unknown[]) => {
      if (f.callMethod) f.callMethod(...args);
      else f.queue!.push(args);
    };
    f.queue = [];
    f.loaded = true;
    f.version = "2.0";
    f.push = f;
    w.fbq = f;
    w._fbq = f;
    const s = document.createElement("script");
    s.async = true;
    s.src = "https://connect.facebook.net/en_US/fbevents.js";
    s.onload = () => { script = "loaded"; loadedAt = Date.now(); };
    s.onerror = () => { script = "failed"; };
    script = "loading";
    document.head.appendChild(s);
  } else if (script === "none") {
    script = "loaded"; // someone else's pixel code already runs on this page
  }
  if (!ready) {
    w.fbq!("set", "autoConfig", false, PIXEL_ID);
    w.fbq!("init", PIXEL_ID);
    ready = true;
  }
  return w.fbq!;
}

/** True when the pixel may run in this browser. */
export function pixelEnabled(): boolean {
  return Boolean(PIXEL_ID) && typeof window !== "undefined" && !isInternal();
}

export function pixel(event: PixelEvent, eventId?: string) {
  try {
    if (!pixelEnabled()) return;
    load()?.("track", event, {}, eventId ? { eventID: eventId } : undefined);
  } catch {
    /* measurement never breaks the product */
  }
}

/** Resolves once no queued pixel event can still read the page address: right away when the pixel is
 *  off or never started, otherwise at least 1 s from now and 3 s after fbevents.js loaded (or as soon
 *  as it failed to load). If the script is still loading after 15 s it never resolves, so whatever the
 *  caller wanted to put in the address is simply skipped. */
export function pixelSettled(): Promise<void> {
  if (!pixelEnabled() || script === "none" || script === "failed") return Promise.resolve();
  const start = Date.now();
  return new Promise((resolve) => {
    const tick = () => {
      const now = Date.now();
      if (script === "failed" && now - start >= 1000) return resolve();
      if (script === "loaded" && now - start >= 1000 && now - loadedAt >= 3000) return resolve();
      if (now - start < 15000) setTimeout(tick, 250);
    };
    tick();
  });
}
