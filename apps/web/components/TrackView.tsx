"use client";

import { useEffect } from "react";

import { pixel } from "@/lib/pixel";
import { track, type FunnelEvent } from "@/lib/track";

/** Fires one funnel event when a server-rendered page is shown (the landing also counts as a
 *  Meta pixel PageView when the pixel is on). */
export default function TrackView({ name }: { name: FunnelEvent }) {
  useEffect(() => {
    track(name);
    if (name === "landing_viewed") pixel("PageView");
  }, [name]);
  return null;
}
