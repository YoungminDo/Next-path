"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

/* Searchable pick list for schools and majors. Matches anywhere in the name, ignores spaces and
   case, and understands initial consonants ("ㄱㄹㄷ" → 고려대학교). When nothing in the list is
   what they mean, the typed text is accepted as is: the server leaves that dimension out of the
   comparison and keeps the name for standardisation. */

export type Item = { id: string; label: string; group?: string | null; keywords?: string[] };
export type Picked = { id: string | null; label: string };

const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";

function initials(s: string): string {
  return [...s].map((ch) => {
    const code = ch.charCodeAt(0) - 0xac00;
    return code >= 0 && code < 11172 ? CHO[Math.floor(code / 588)] : ch;
  }).join("");
}

const norm = (s: string) => s.toLowerCase().replace(/[\s·・,./()\[\]_&+-]+/g, "");

function matches(item: Item, q: string): boolean {
  const query = norm(q);
  if (!query) return true;
  const hay = [item.label, item.group ?? "", ...(item.keywords ?? [])].map(norm);
  if (hay.some((h) => h.includes(query))) return true;
  return [...query].every((c) => CHO.includes(c)) && hay.some((h) => initials(h).includes(query));
}

export default function SearchSelect(props: {
  items: Item[];
  value: Picked | null;
  onChange: (v: Picked | null) => void;
  placeholder: string;
  ariaLabel: string;
  noun: string; // "학교" | "전공", used in the free-text option
  inputId?: string;
}) {
  const { items, value, onChange, placeholder, ariaLabel, noun } = props;
  const [query, setQuery] = useState(value?.label ?? "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const box = useRef<HTMLDivElement>(null);
  // A value set from outside (e.g. answers carried over from the landing) shows up in the box.
  useEffect(() => {
    if (!open) setQuery(value?.label ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value?.id, value?.label]);

  const shown = useMemo(() => items.filter((i) => matches(i, query)).slice(0, 8), [items, query]);
  const typed = query.trim();
  const exact = items.find((i) => norm(i.label) === norm(typed));
  // Only initial consonants ("ㄱㄹ") is a search, never a name to keep.
  const jamoOnly = [...norm(typed)].every((c) => CHO.includes(c));
  const options: (Item | { id: null; label: string })[] = [
    ...shown,
    ...(typed && !exact && !jamoOnly ? [{ id: null, label: typed }] : []),
  ];

  function pick(o: Item | { id: null; label: string }) {
    setQuery(o.label);
    setOpen(false);
    onChange({ id: o.id, label: o.label });
  }

  function commitTyped() {
    // Leaving the field: an exact name counts as picked, anything else typed is kept as typed.
    if (!typed) {
      if (value) onChange(null);
      return;
    }
    if (value && norm(value.label) === norm(typed)) return;
    if (exact) pick(exact);
    else if (!jamoOnly) pick({ id: null, label: typed });
  }

  return (
    <div className="search-select" ref={box}>
      <input
        id={props.inputId}
        role="combobox"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && options[active] ? `${listId}-${active}` : undefined}
        autoComplete="off"
        placeholder={placeholder}
        value={query}
        onFocus={() => { setOpen(true); setActive(0); }}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); }}
        onBlur={() => { setOpen(false); commitTyped(); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, options.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === "Enter" && open && options[active]) { e.preventDefault(); pick(options[active]); }
          else if (e.key === "Escape") setOpen(false);
        }}
      />
      {value && value.id === null && !open && (
        <span className="search-select-note">목록에 없어서 입력한 이름 그대로 쓸게요</span>
      )}
      {open && options.length > 0 && (
        <ul className="search-select-list" id={listId} role="listbox">
          {options.map((o, i) => (
            <li key={o.id ?? `typed-${o.label}`} id={`${listId}-${i}`} role="option" aria-selected={i === active}
                className={i === active ? "active" : undefined}
                onMouseDown={(e) => { e.preventDefault(); pick(o); }}
                onMouseEnter={() => setActive(i)}>
              {o.id === null
                ? <span className="typed">‘{o.label}’ 그대로 입력 <small>목록에 없는 {noun}</small></span>
                : <>{o.label}{"group" in o && o.group ? <small>{o.group}</small> : null}</>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
