"use client";

import { useEffect, useRef, useState } from "react";

import { acq, ApiError, errorMessage } from "@/lib/api";
import { track } from "@/lib/track";

/* Toss Payments sends the buyer here with paymentKey, orderId and amount. Nothing is credited
   until our server confirms the payment with Toss; then the card it was bought for opens and
   the result screen comes back. */
export default function PaySuccess() {
  const [state, setState] = useState<"confirming" | "done" | "error">("confirming");
  const [message, setMessage] = useState("");
  const once = useRef(false);

  useEffect(() => {
    if (once.current) return;
    once.current = true;
    const q = new URLSearchParams(window.location.search);
    const orderId = q.get("orderId") ?? "";
    const paymentKey = q.get("paymentKey") ?? "";
    const amount = Number(q.get("amount"));
    if (!orderId || !paymentKey || !amount) {
      setState("error");
      setMessage("결제 정보가 없어요.");
      return;
    }
    acq.confirmPayment(orderId, paymentKey, amount)
      .then((r) => {
        track("credit_purchased", { insight: r.insight_type, amount, opened: r.opened });
        setState("done");
        window.location.replace("/start");
      })
      .catch((e) => {
        const text = errorMessage(e);
        track("payment_failed", { stage: "confirm", status: e instanceof ApiError ? e.status : null });
        setState("error");
        setMessage(text ?? "결제를 확인하지 못했어요. 결제가 됐는데 열리지 않았다면 branden@da-sh.io로 알려주세요. 바로 환불해 드려요.");
      });
  }, []);

  return (
    <main className="app">
      <section className="screen">
        {state === "confirming" && <h2>결제를 확인하고 있어요…</h2>}
        {state === "done" && <h2>결제됐어요. 카드를 열고 있어요…</h2>}
        {state === "error" && (
          <>
            <h2>결제를 마치지 못했어요</h2>
            <p className="sub">{message}</p>
            <a className="cta" href="/start">결과로 돌아가기</a>
          </>
        )}
      </section>
    </main>
  );
}
