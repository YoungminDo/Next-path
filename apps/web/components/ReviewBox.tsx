"use client";

import { useEffect, useState } from "react";

import { ConsentBox, ConsentItem } from "@/components/Consent";
import { acq, errorMessage, type ReviewStatus, type ReviewSurface } from "@/lib/api";
import { track } from "@/lib/track";

/* A member's own review after a step of /alert (migration 0045). Showing it on the landing is an
   optional, separate consent; without it the review only helps the team. The team approves or hides
   it and never edits it; the landing shows the words as written, the step and the month, no name. */

// The server refuses any other version (config review_consent_version; change both together).
export const REVIEW_CONSENT_VERSION = "review_publish_v1";
const MIN = 10;
const MAX = 300;
const LABELS: Record<ReviewSurface, string> = { FIT: "1차 분석을 받은 분", ALERT: "공고 알림을 받은 분" };
const ASK: Record<ReviewSurface, string> = { FIT: "1차 분석, 어떠셨어요?", ALERT: "공고 알림, 어떠셨어요?" };

export default function ReviewBox({ surface }: { surface: ReviewSurface }) {
  const [s, setS] = useState<ReviewStatus | null>(null);
  const [body, setBody] = useState("");
  const [publish, setPublish] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const [thanks, setThanks] = useState(false);
  useEffect(() => {
    acq.review().then((r) => {
      setS(r);
      if (r.enabled && !r.review) track("review_viewed", { surface });
    }).catch(() => setS(null));
  }, [surface]);
  if (!s || (!s.enabled && !s.review)) return null;

  const act = (fn: () => Promise<void>) => async () => {
    setErr(undefined);
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setErr(errorMessage(e) ?? "잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  };

  if (s.review) {
    const del = act(async () => {
      setS(await acq.reviewDelete());
      setThanks(false);
      track("review_deleted", { surface });
    });
    const note = !s.review.publish ? "서비스를 고치는 데만 써요. 페이지에는 싣지 않아요."
      : s.review.state === "HIDDEN" ? "이번 후기는 페이지에 싣지 않기로 했어요."
      : "팀이 확인한 뒤 서비스 페이지에 그대로 실려요. 이름은 보이지 않아요.";
    return (
      <div className="card review-box">
        <b>{thanks ? "후기 고마워요!" : "남겨주신 후기"}</b>
        <blockquote className="review-quote">{s.review.body}</blockquote>
        <p className="hint">{note} · <button className="link" disabled={busy} onClick={del}>후기 지우기</button></p>
        {err && <p className="error" role="alert">{err}</p>}
      </div>
    );
  }

  const length = body.trim().length;
  const submit = act(async () => {
    setS(await acq.reviewSubmit(surface, body, publish ? REVIEW_CONSENT_VERSION : null));
    setThanks(true);
    track("review_submitted", { surface, publish, length });
  });
  return (
    <div className="card review-box">
      <b>{ASK[surface]}</b>
      <p className="hint">한두 줄이면 충분해요. 좋았던 점도, 아쉬운 점도 그대로 적어 주세요.</p>
      <label className="field">
        <span className="sr-only">후기</span>
        <textarea rows={3} maxLength={MAX} value={body} placeholder="예: 보완점이 구체적이라 바로 고칠 수 있었어요"
                  onChange={(e) => setBody(e.target.value)} />
      </label>
      <p className="hint review-count">{length}/{MAX}자</p>
      <ConsentBox>
        <ConsentItem required={false} title="후기를 서비스 페이지에 싣기" checked={publish} onChange={setPublish}>
          <ul>
            <li>싣는 것: 쓴 글 그대로, &lsquo;{LABELS[surface]}&rsquo;, 쓴 달 (이름·연락처는 싣지 않아요)</li>
            <li>목적: 서비스 소개 페이지에 이용 후기 싣기</li>
            <li>보관: 후기를 지울 때까지. 지우면 바로 내려요.</li>
            <li>팀이 확인한 뒤 실려요. 글은 고치지 않아요.</li>
            <li>동의하지 않아도 후기를 남길 수 있어요. 그때는 서비스를 고치는 데만 써요.</li>
          </ul>
        </ConsentItem>
      </ConsentBox>
      {err && <p className="error" role="alert">{err}</p>}
      <button className="cta ghost" disabled={busy || length < MIN} onClick={submit}>
        {length < MIN ? `${MIN}자 이상 써 주세요` : "후기 남기기"}
      </button>
    </div>
  );
}
