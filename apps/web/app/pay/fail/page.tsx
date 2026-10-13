"use client";

import { useEffect, useState } from "react";

import { track } from "@/lib/track";

/* Toss Payments sends the buyer here when the payment did not go through (closed window,
   declined card): nothing was charged. */
export default function PayFail() {
  const [message, setMessage] = useState("");
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const code = q.get("code");
    track("payment_failed", { stage: "window", code });
    setMessage(code === "PAY_PROCESS_CANCELED" || code === "USER_CANCEL"
      ? "결제를 취소했어요. 결제된 금액은 없어요."
      : q.get("message") ?? "결제가 되지 않았어요. 결제된 금액은 없어요.");
  }, []);
  return (
    <main className="app">
      <section className="screen">
        <h2>결제가 되지 않았어요</h2>
        <p className="sub">{message}</p>
        <a className="cta" href="/start">결과로 돌아가기</a>
      </section>
    </main>
  );
}
