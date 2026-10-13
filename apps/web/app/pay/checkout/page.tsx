"use client";

import { useEffect, useRef, useState } from "react";

import BusinessInfo from "@/components/BusinessInfo";
import { CARD_NAMES } from "@/components/ResultCards";
import { acq, errorMessage, type PayOrder, type TestMethod } from "@/lib/api";
import { track } from "@/lib/track";

/* The payment-intent test (docs/10 §결과 카드와 결제): while real payments are not connected, a
   card past the free one is "bought" here. This page asks for no payment details and charges
   nothing. Pressing 결제하기 is what is measured; right after it the person is told that nothing
   was charged, and 1 튜브 is gifted that opens the card. Our own design, not a payment company's. */

const METHODS: { key: TestMethod; label: string }[] = [
  { key: "CARD", label: "신용·체크카드" },
  { key: "EASY_PAY", label: "간편결제" },
  { key: "TRANSFER", label: "계좌이체" },
];

type Done = { gifted: boolean; opened: boolean; balance: number };

export default function Checkout() {
  const [order, setOrder] = useState<PayOrder | null>(null);
  const [method, setMethod] = useState<TestMethod>("CARD");
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<Done | null>(null);
  const once = useRef(false);

  useEffect(() => {
    if (once.current) return;
    once.current = true;
    const id = new URLSearchParams(window.location.search).get("order") ?? "";
    if (!id) {
      setError("주문 정보가 없어요.");
      return;
    }
    acq.order(id)
      .then((o) => {
        if (o.mode !== "TEST") {
          window.location.replace("/start");
          return;
        }
        setOrder(o);
        if (o.status === "TEST_COMPLETED") {
          // Back on a finished order (reload): the same answer again, nothing recorded twice.
          acq.testComplete(o.order_id, "CARD")
            .then((r) => setDone({ gifted: r.gifted, opened: r.opened, balance: r.balance_tube }))
            .catch(() => window.location.replace("/start"));
        } else {
          track("checkout_viewed", { insight: o.insight_type, amount: o.amount });
        }
      })
      .catch((e) => setError(errorMessage(e) ?? "주문을 불러오지 못했어요."));
  }, []);

  const pay = () => {
    if (!order || !agreed || busy) return;
    setBusy(true);
    setError("");
    track("checkout_completed", { insight: order.insight_type, amount: order.amount, method });
    acq.testComplete(order.order_id, method)
      .then((r) => setDone({ gifted: r.gifted, opened: r.opened, balance: r.balance_tube }))
      .catch((e) => setError(errorMessage(e) ?? "잠시 후 다시 시도해 주세요."))
      .finally(() => setBusy(false));
  };

  const cancel = () => {
    if (order) track("checkout_cancelled", { insight: order.insight_type });
    window.location.assign("/start");
  };

  if (done) {
    return (
      <main className="app">
        <section className="screen checkout-done">
          <div className="gift" aria-hidden="true">🎁</div>
          <h2>실제로 결제되지 않았어요</h2>
          <p className="sub">
            nextpath는 아직 정식 결제를 준비하고 있어요. 방금 누르신 결제는 진행되지 않았고, 돈도 나가지 않았어요.
          </p>
          {done.gifted ? (
            <p className="sub">
              열어보려던 마음에 감사해서 <b>튜브 1개를 선물</b>로 드렸어요.
              {done.opened ? " 그 튜브로 카드를 열었어요." : " 이 카드는 기록이 아직 적어 열지 않았고, 튜브는 그대로 남아 있어요."}
            </p>
          ) : (
            <p className="sub">선물 튜브는 한 사람에 10개까지라 이번엔 드리지 못했어요.</p>
          )}
          <a className="cta" href="/start">{done.opened ? "열린 카드 보러 가기" : "결과로 돌아가기"}</a>
        </section>
      </main>
    );
  }

  return (
    <main className="app checkout">
      <section className="screen">
        <p className="brand">nextpath</p>
        <h2>결제하기</h2>
        {error && <p className="error">{error}</p>}
        {order && (
          <>
            <div className="co-box">
              <p className="co-label">주문 상품</p>
              <p className="co-item">{CARD_NAMES[order.insight_type] ?? order.order_name}</p>
              <p className="co-meta">결과 카드 1장 열기 (튜브 {order.credit_amount}개)</p>
              <div className="co-total"><span>결제 금액</span><b>{order.amount.toLocaleString()}원</b></div>
              <p className="co-meta">부가세 포함</p>
            </div>
            <fieldset className="co-box co-methods">
              <legend className="co-label">결제 수단</legend>
              {METHODS.map((m) => (
                <label key={m.key} className={method === m.key ? "on" : ""}>
                  <input type="radio" name="method" value={m.key} checked={method === m.key}
                         onChange={() => setMethod(m.key)} />
                  {m.label}
                </label>
              ))}
            </fieldset>
            <label className="check">
              <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              <span>
                주문 내용을 확인했어요. 결제 즉시 열리는 디지털 콘텐츠라 열린 뒤에는 청약철회가 제한돼요.{" "}
                <a href="/terms" target="_blank" rel="noreferrer">이용약관</a>
              </span>
            </label>
            <button className="cta" disabled={!agreed || busy} onClick={pay}>
              {busy ? "처리하고 있어요…" : `${order.amount.toLocaleString()}원 결제하기`}
            </button>
            <button className="cta ghost" disabled={busy} onClick={cancel}>취소</button>
          </>
        )}
        {!order && !error && <p className="sub">주문을 불러오고 있어요…</p>}
        {!order && error && <a className="cta" href="/start">결과로 돌아가기</a>}
        <BusinessInfo />
      </section>
    </main>
  );
}
