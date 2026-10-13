"use client";

import type { Cell, QueryResult } from "@/lib/api";

/* The member's result as insight cards, in the landing gallery's look (.gcard) but with their
   own numbers: their school·major is open; "다른 학교, 같은 과" opens with 튜브 and is drawn next to
   their school. Colours: s1 = my school, s2 = other schools, gray = folded rest. */

type Row = { key: string; label: string; share: number };

function rows(r: QueryResult, label: (c: Cell) => string, max = 5): Row[] {
  const top = r.cells.slice(0, max).map((c) => ({ key: c.key, label: label(c), share: c.share }));
  const rest = 1 - top.reduce((s, x) => s + x.share, 0);
  return rest > 0.005 ? [...top, { key: "_rest", label: "기타", share: rest }] : top;
}

const pct = (x: number) => Math.round(x * 100);

function Bars({ data }: { data: Row[] }) {
  const max = Math.max(...data.map((d) => d.share), 0.01);
  const h = data.length * 28 + 4;
  return (
    <svg viewBox={`0 0 300 ${h}`} className="gchart" role="img"
         aria-label={data.map((d) => `${d.label} ${pct(d.share)}%`).join(", ")}>
      {data.map((d, i) => {
        const y = 4 + i * 28;
        const w = Math.max(2, (d.share / max) * 168);
        return (
          <g key={d.key}>
            <text x="0" y={y + 13} className="lbl">{d.label.length > 8 ? `${d.label.slice(0, 8)}…` : d.label}</text>
            <rect x="92" y={y + 2} width={w} height="16" rx="4"
                  className={`grow ${d.key === "_rest" ? "other" : i === 0 ? "s1" : "s1soft"}`}
                  style={{ animationDelay: `${i * 70}ms` }} />
            <text x={92 + w + 6} y={y + 14} className="val">{pct(d.share)}%</text>
          </g>
        );
      })}
    </svg>
  );
}

function Paired({ data }: { data: { key: string; label: string; own: number | null; other: number | null }[] }) {
  const max = Math.max(...data.flatMap((d) => [d.own ?? 0, d.other ?? 0]), 0.01);
  const h = data.length * 40 + 24;
  return (
    <svg viewBox={`0 0 300 ${h}`} className="gchart" role="img"
         aria-label={data.map((d) => `${d.label} 우리 학교 ${d.own == null ? "-" : pct(d.own) + "%"}, 다른 학교 ${d.other == null ? "-" : pct(d.other) + "%"}`).join("; ")}>
      <g transform="translate(92 8)">
        <rect width="9" height="9" rx="2" y="-8" className="s1" /><text x="13" className="ax">우리 학교</text>
        <rect x="76" width="9" height="9" rx="2" y="-8" className="s2" /><text x="89" className="ax">다른 학교</text>
      </g>
      {data.map((d, i) => {
        const y = 22 + i * 40;
        const bar = (v: number | null, dy: number, cls: string) => {
          const w = v == null ? 0 : Math.max(2, (v / max) * 160);
          return (
            <g>
              {v != null && <rect x="92" y={y + dy} width={w} height="12" rx="3" className={`grow ${cls}`}
                                  style={{ animationDelay: `${i * 90}ms` }} />}
              <text x={92 + w + 6} y={y + dy + 10} className="val">{v == null ? "–" : `${pct(v)}%`}</text>
            </g>
          );
        };
        return (
          <g key={d.key}>
            <text x="0" y={y + 17} className="lbl">{d.label.length > 8 ? `${d.label.slice(0, 8)}…` : d.label}</text>
            {bar(d.own, 2, "s1")}
            {bar(d.other, 17, "s2")}
          </g>
        );
      })}
    </svg>
  );
}

/** Before a payment (전자상거래법 §17②5): a digital card opens at once, so it cannot be
 *  withdrawn after; the free card is the preview. */
export function PayNote() {
  return (
    <p className="paynote">
      결제하면 바로 열리는 디지털 콘텐츠라 결제 후에는 청약철회가 제한돼요. 무료 카드로 먼저 확인할 수 있어요.{" "}
      <a href="/terms" target="_blank" rel="noreferrer">이용약관</a>
    </p>
  );
}

/** Open with a 튜브 when there is one; otherwise buy it (990원) when payments are on. */
export function OpenButton({ cost, balance, payments, busy, onTube, onBuy }: {
  cost: number | null; balance: number; payments: { enabled: boolean; price_krw: number | null };
  busy: boolean; onTube: () => void; onBuy: () => void;
}) {
  if (balance >= (cost ?? 1)) {
    return <button className="cta" disabled={busy} onClick={onTube}>{cost} 튜브로 열기</button>;
  }
  if (payments.enabled && payments.price_krw) {
    return (
      <>
        <button className="cta" disabled={busy} onClick={onBuy}>{payments.price_krw.toLocaleString()}원으로 열기</button>
        <PayNote />
      </>
    );
  }
  return <button className="cta" disabled>튜브가 부족해요</button>;
}

export default function ResultCards({ base, compare, professional, school, major, label, takeaway, busy,
  balance, payments, onUnlockCompare, onBuyCompare }: {
  base: QueryResult;
  compare: { available: boolean; unlocked: boolean; cost_tube: number | null; result: QueryResult | null };
  professional: boolean; school: string | null; major: string | null;
  label: (c: Cell) => string; takeaway: string | null; busy: boolean;
  balance: number; payments: { enabled: boolean; price_krw: number | null };
  onUnlockCompare: () => void; onBuyCompare: () => void;
}) {
  if (base.suppressed) return null;
  const mine = rows(base, label);
  const other = compare.result && !compare.result.suppressed ? compare.result : null;
  const where = [school, major].filter(Boolean).join(" ");
  const paired = other ? (() => {
    const share = (r: QueryResult, key: string) => r.cells.find((c) => c.key === key)?.share ?? null;
    const keys = [...base.cells.slice(0, 4).map((c) => c.key),
                  ...other.cells.map((c) => c.key).filter((k) => !base.cells.slice(0, 4).some((c) => c.key === k))]
      .slice(0, 5);
    return keys.map((k) => {
      const c = base.cells.find((x) => x.key === k) ?? other.cells.find((x) => x.key === k)!;
      return { key: k, label: label(c), own: share(base, k), other: share(other, k) };
    });
  })() : null;
  const gap = paired?.filter((d) => d.own != null && d.other != null)
    .map((d) => ({ ...d, diff: pct(d.other!) - pct(d.own!) }))
    .sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff))[0];
  return (
    <div className="ggrid rcards">
      <article className="gcard on">
        <header>
          <h3>{professional ? "나와 같은 직무였던 사람들은 다음에 어디로 갔을까"
            : `${where || "나와 같은 출발점"} 사람들은 처음에 어디로 갔을까`}</h3>
          <span className="tag">{professional ? "Next" : "First Job"}</span>
        </header>
        <Bars data={mine} />
        {takeaway && <p className="takeaway">{takeaway}</p>}
        <footer><span>{base.effective_n.toLocaleString()}명 기준</span><span className="free">무료</span></footer>
      </article>
      {compare.available && (
        <article className="gcard">
          <header>
            <h3>{`다른 학교 ${major ?? "같은 과"} 사람들은 ${professional ? "다음에" : "처음에"} 어디로 갔을까`}</h3>
            <span className={compare.unlocked ? "tag" : "tag lock"}>{compare.unlocked ? "Compare" : "튜브로 열기"}</span>
          </header>
          {other && paired ? (
            <>
              <Paired data={paired} />
              {gap && gap.diff !== 0 && (
                <p className="takeaway">
                  다른 학교에서는 {gap.label} 비율이 {Math.abs(gap.diff)}%p {gap.diff > 0 ? "더 높았어요" : "더 낮았어요"}.
                </p>
              )}
              <footer><span>다른 학교 {other.effective_n.toLocaleString()}명 기준</span><span /></footer>
            </>
          ) : compare.unlocked ? (
            <p className="sub">다른 학교의 같은 과 기록이 아직 적어서 비교할 수 없어요.</p>
          ) : (
            <>
              <div className="locked-chart" aria-hidden="true">
                {[78, 60, 46, 34, 22].map((w, i) => (
                  <div key={i} className="lrow"><i style={{ width: `${w}%` }} /><i className="o" style={{ width: `${w * 0.8 + (i % 2 ? 12 : -8)}%` }} /></div>
                ))}
              </div>
              <p className="takeaway">우리 학교와 다른 학교, 같은 과의 길을 나란히 비교해요.</p>
              <OpenButton cost={compare.cost_tube} balance={balance} payments={payments} busy={busy}
                          onTube={onUnlockCompare} onBuy={onBuyCompare} />
              <footer>
                <span>{balance >= (compare.cost_tube ?? 1) ? "가입 선물 튜브로 열 수 있어요" : "다른 학교 기록이 적으면 튜브를 쓰지 않아요"}</span><span />
              </footer>
            </>
          )}
        </article>
      )}
    </div>
  );
}
