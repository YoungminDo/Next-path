"use client";

import { useEffect, useRef, useState } from "react";

/* A card feed for the /alert landing: a new card slides in on top every few seconds and the oldest
   one fades out under the edge. Motion only: no time stamps, names or "방금" labels, so it never claims
   activity that is not happening. Starts when scrolled into view, pauses while the tab is hidden or
   the pointer is on it, and stays still for people who ask for reduced motion. */

export type FeedItem = { key: string; quote: string; meta: string };

export default function Feed({ items, visible = 3, every = 2800, label }: {
  items: FeedItem[]; visible?: number; every?: number; label: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  // `head` = how many cards have come in so far; the newest is items[(head - 1) % n].
  const [head, setHead] = useState(Math.min(visible, items.length));
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const cycles = items.length > visible;

  useEffect(() => {
    const el = box.current;
    if (!el || !cycles || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const io = new IntersectionObserver(([e]) => setRunning(e.isIntersecting), { threshold: 0.3 });
    io.observe(el);
    return () => io.disconnect();
  }, [cycles]);

  useEffect(() => {
    if (!running || paused) return;
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") setHead((h) => h + 1);
    }, every);
    return () => window.clearInterval(t);
  }, [running, paused, every]);

  const n = items.length;
  // Newest first; one extra card under the fading edge so the last one leaves smoothly.
  const shown = Array.from({ length: Math.min(n, visible + (cycles ? 1 : 0)) }, (_, i) => head - 1 - i)
    .filter((k) => k >= 0)
    .map((k) => ({ k, item: items[k % n] }));
  const first = head === Math.min(visible, n); // the opening cards appear without the slide-in

  return (
    <div ref={box} className={cycles ? "al-feed cycles" : "al-feed"} aria-label={label}
         onPointerEnter={() => setPaused(true)} onPointerLeave={() => setPaused(false)}
         onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
      <ul>
        {shown.map(({ k, item }, i) => (
          <li key={k} className={`al-feed-item${!first && i === 0 ? " in" : ""}${cycles && i === visible ? " out" : ""}`}
              aria-hidden={cycles && i === visible ? true : undefined}>
            <div className="al-feed-clip">
              <div className="al-feed-card">
                <p>&ldquo;{item.quote}&rdquo;</p>
                <span className="al-feed-meta">{item.meta}</span>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
