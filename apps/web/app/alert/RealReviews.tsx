"use client";

import { useEffect, useState } from "react";

import { acq, type PublicReview } from "@/lib/api";

import Feed from "./Feed";

/* Members' own reviews, as written (migration 0045). The API returns none until enough are approved,
   and then the section appears; until then nothing here is shown. */

const month = (m: string) => `${m.slice(0, 4)}년 ${Number(m.slice(5, 7))}월`;

export default function RealReviews() {
  const [reviews, setReviews] = useState<PublicReview[]>([]);
  useEffect(() => { acq.reviews().then((r) => setReviews(r.reviews)).catch(() => setReviews([])); }, []);
  if (!reviews.length) return null;
  return (
    <section className="al-sec al-g">
      <p className="al-eyebrow">이용 후기</p>
      <h2>먼저 써 본 분들의 이야기</h2>
      <p className="al-sub">써 주신 글 그대로예요. 공개에 동의하고 팀이 확인한 후기만 실어요.</p>
      <Feed label="이용 후기" items={reviews.map((r, i) => ({
        key: `${i}-${r.month}`, quote: r.body, meta: `${r.label} · ${month(r.month)}` }))} />
    </section>
  );
}
