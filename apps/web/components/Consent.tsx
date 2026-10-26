"use client";

import { useId, useState, type ReactNode } from "react";

/* Consent rows in plain words: one short line per consent, the legally required notice (purpose,
   items, recipient, retention, the right to refuse; PIPA §15②, §17②, §28-8②) one tap away under
   "보기". Required and optional are marked and asked separately (§22①); nothing is ticked for the
   person. Change a consent's wording version together with its text. */

export function ConsentAll({ checked, onChange, note }: {
  checked: boolean; onChange: (v: boolean) => void; note?: string;
}) {
  const id = useId();
  return (
    <label className="consent-all-row" htmlFor={id}>
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span><b>모두 동의하기</b>{note && <small>{note}</small>}</span>
    </label>
  );
}

export function ConsentItem({ required, title, checked, onChange, children }: {
  required: boolean; title: string; checked: boolean; onChange: (v: boolean) => void; children: ReactNode;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <div className="consent-item">
      <div className="consent-item-row">
        <label htmlFor={id}>
          <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
          <span><span className={required ? "consent-tag" : "consent-tag opt"}>{required ? "필수" : "선택"}</span>{title}</span>
        </label>
        <button type="button" className="consent-view" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "접기" : "보기"}
        </button>
      </div>
      {open && <div className="consent-body">{children}</div>}
    </div>
  );
}

/** The consent rows in one quiet box. */
export function ConsentBox({ children }: { children: ReactNode }) {
  return <div className="consent-box">{children}</div>;
}
