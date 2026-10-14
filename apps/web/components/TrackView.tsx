"use client";

import { useEffect } from "react";

import { pixel } from "@/lib/pixel";
import { track, type FunnelEvent } from "@/lib/track";

/** Fires one funnel event when a server-rendered page is shown (the landing also counts as a
 *  Meta pixel PageView when the pixel is on). A page an app loads ahead of the tap (in-app browsers,
 *  prerendering) is hidden until then: it counts only once someone sees it. */
export default function TrackView({ name, variant }: { name: FunnelEvent; variant?: string }) {
  useEffect(() => {
    const send = () => {
      track(name, variant ? { variant } : {});
      if (name === "landing_viewed") pixel("PageView");
    };
    if (document.visibilityState !== "hidden") {
      send();
      return;
    }
    const onShow = () => {
      if (document.visibilityState === "hidden") return;
      document.removeEventListener("visibilitychange", onShow);
      send();
    };
    document.addEventListener("visibilitychange", onShow);
    return () => document.removeEventListener("visibilitychange", onShow);
  }, [name, variant]);
  return null;
}
