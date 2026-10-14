/** Meta pixel for ad measurement (docs/11): off unless NEXT_PUBLIC_META_PIXEL_ID is set, and never
 * for the team's own browsers (?internal=1). Only three standard events, no personal data:
 * PageView (landing), Lead (answers entered), CompleteRegistration (a new member). Automatic
 * event detection is off, so the pixel reads no button text or page content; pages that carry
 * answers in the address are cleaned before anything is sent (AcquisitionFlow). */
import { isInternal } from "@/lib/track";

const PIXEL_ID = process.env.NEXT_PUBLIC_META_PIXEL_ID;

type Fbq = ((...args: unknown[]) => void) & { queue?: unknown[][]; loaded?: boolean; version?: string;
  callMethod?: (...args: unknown[]) => void; push?: unknown };
type PixelEvent = "PageView" | "Lead" | "CompleteRegistration";

let ready = false;

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
    document.head.appendChild(s);
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
