"use client";

import { useEffect } from "react";

import { track, type FunnelEvent } from "@/lib/track";

/** Fires one funnel event when a server-rendered page is shown. */
export default function TrackView({ name }: { name: FunnelEvent }) {
  useEffect(() => track(name), [name]);
  return null;
}
