"use client";

import { useEffect, useState } from "react";

import { decideReview, loadReviews, type AdminReview } from "@/lib/admin";

/* Review queue: approve or hide a member's own review. The text is never edited here; the landing
   shows approved, publish-consented reviews as written, and only once enough are approved. */

const STATE: Record<AdminReview["state"], string> = { PENDING: "확인 전", APPROVED: "공개", HIDDEN: "숨김" };
const SURFACE: Record<AdminReview["surface"], string> = { FIT: "1차 분석", ALERT: "공고 알림" };

export default function AdminReviews() {
  const [rows, setRows] = useState<AdminReview[]>();
  const [busy, setBusy] = useState<string>();
  const [err, setErr] = useState(false);
  useEffect(() => { loadReviews().then(setRows).catch(() => setErr(true)); }, []);
  const decide = async (id: string, d: "APPROVED" | "HIDDEN") => {
    setBusy(id);
    setErr(false);
    try { setRows(await decideReview(id, d)); } catch { setErr(true); } finally { setBusy(undefined); }
  };
  const approved = rows?.filter((r) => r.state === "APPROVED" && r.publish).length ?? 0;
  return (
    <section className="card admin-card">
      <h3>이용 후기</h3>
      <p className="hint">회원이 직접 쓴 글이에요. 고칠 수 없고, 공개 동의한 글만 공개할 수 있어요.
        공개 {approved}건 · 5건이 되면 /alert에 실려요.</p>
      {err && <p className="error" role="alert">후기를 불러오지 못했어요.</p>}
      {rows && !rows.length && <p className="hint">아직 후기가 없어요.</p>}
      {rows && rows.length > 0 && (
        <ul className="admin-reviews">
          {rows.map((r) => (
            <li key={r.review_id}>
              <p>{r.body}</p>
              <p className="hint">
                {SURFACE[r.surface]} · {new Date(r.created_at).toLocaleDateString("ko-KR")} ·{" "}
                {r.publish ? "공개 동의" : "공개 동의 안 함"} · <b>{STATE[r.state]}</b>
              </p>
              <div className="admin-review-acts">
                {r.publish && r.state !== "APPROVED" && (
                  <button className="chip" disabled={busy === r.review_id} onClick={() => decide(r.review_id, "APPROVED")}>공개</button>
                )}
                {r.state !== "HIDDEN" && (
                  <button className="chip" disabled={busy === r.review_id} onClick={() => decide(r.review_id, "HIDDEN")}>숨김</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
