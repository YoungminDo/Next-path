"use client";

import { useEffect, useState } from "react";

import { inAppBrowser, track } from "@/lib/track";

/* Login first on /alert (owner decision 2026-10-26): the Kakao button is the landing's button. After
   the login the flow asks for the resume (AcquisitionFlow, ALERT_ENTRY), and the career-data consent
   is asked where the records are saved, not here: nothing about the person is kept by the login. */

const ALERT_ENTRY = "hellomyme.entry"; // same key as AcquisitionFlow
const LOGIN_PENDING = "hellomyme.login_pending"; // same key as AcquisitionFlow: back without a login
const DEV_LOGIN = process.env.NEXT_PUBLIC_ENABLE_DEV_LOGIN === "true";

export default function KakaoStart({ surface, label = "카카오로 3초 만에 시작하기" }: {
  surface: "hero" | "bar"; label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [returned, setReturned] = useState(false);
  const [app, setApp] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    setApp(inAppBrowser());
    // Back from the Kakao page without a login (often an in-app browser): free the button, say what to do.
    const onShow = (e: PageTransitionEvent) => {
      if (!e.persisted) return;
      setBusy(false);
      try {
        const at = Number(sessionStorage.getItem(LOGIN_PENDING) || 0);
        if (at > 0 && Date.now() - at < 30 * 60 * 1000) setReturned(true);
      } catch { /* private mode */ }
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  const start = () => {
    setBusy(true);
    try {
      localStorage.setItem(ALERT_ENTRY, "alert");
      sessionStorage.setItem(LOGIN_PENDING, String(Date.now()));
    } catch { /* private mode */ }
    track("login_clicked", { surface: `alert_${surface}`, provider: "KAKAO", again: returned || undefined });
    window.location.href = "/auth/hmm/start";
  };
  const dev = async () => {
    try { localStorage.setItem(ALERT_ENTRY, "alert"); } catch { /* private mode */ }
    await fetch("/auth/dev", { method: "POST" });
    window.location.href = "/start?login=success";
  };
  const external = app && app !== "kakaotalk";

  return (
    <div className="al-kakao">
      <button className="al-cta kakao" disabled={busy} onClick={start}>
        <KakaoMark />{label}
      </button>
      {surface === "hero" && returned && (external ? (
        <div className="al-help" role="status">
          <b>카카오 로그인이 안 열렸나요?</b>
          <p>앱 안에서는 카카오 로그인이 막힐 때가 있어요. 화면 오른쪽 위 <b>⋯</b>를 누르고 <b>‘외부 브라우저로 열기’</b>를 골라 주세요.</p>
          <button className="al-link" type="button" onClick={() => {
            void navigator.clipboard?.writeText(window.location.href).then(() => setCopied(true), () => undefined);
          }}>{copied ? "복사했어요 · Safari나 Chrome 주소창에 붙여 넣어 주세요" : "주소 복사하기"}</button>
        </div>
      ) : (
        <p className="al-help" role="status">카카오 로그인이 끝나지 않았어요. 버튼을 한 번 더 눌러 주세요.</p>
      ))}
      {surface === "hero" && DEV_LOGIN && <button className="al-link" onClick={() => void dev()}>개발용 로그인</button>}
    </div>
  );
}

function KakaoMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" style={{ marginRight: 8 }}>
      <path fill="currentColor" d="M12 3C6.48 3 2 6.48 2 10.77c0 2.77 1.86 5.2 4.66 6.57-.2.75-.74 2.7-.85 3.12-.13.52.19.51.4.37.17-.11 2.66-1.8 3.73-2.53.67.1 1.36.15 2.06.15 5.52 0 10-3.48 10-7.68S17.52 3 12 3Z" />
    </svg>
  );
}
