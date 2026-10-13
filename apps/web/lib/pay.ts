"use client";

import { acq, type PayableInsight } from "@/lib/api";
import { track } from "@/lib/track";

/** Open the Toss Payments window for one card (990원 = 1 튜브). The page then moves to
 *  /pay/success, which confirms on our server and opens the card, or to /pay/fail. */
export async function buyCard(insight: PayableInsight, internal: boolean): Promise<void> {
  const clientKey = process.env.NEXT_PUBLIC_TOSS_CLIENT_KEY;
  if (!clientKey) throw new Error("결제를 준비하고 있어요. 잠시 후 다시 시도해 주세요.");
  const order = await acq.createOrder(insight, internal);
  track("payment_started", { insight, amount: order.amount });
  const { loadTossPayments } = await import("@tosspayments/tosspayments-sdk");
  const toss = await loadTossPayments(clientKey);
  await toss.payment({ customerKey: order.customer_key }).requestPayment({
    method: "CARD",
    amount: { currency: "KRW", value: order.amount },
    orderId: order.order_id,
    orderName: order.order_name,
    successUrl: `${window.location.origin}/pay/success`,
    failUrl: `${window.location.origin}/pay/fail`,
  });
}
