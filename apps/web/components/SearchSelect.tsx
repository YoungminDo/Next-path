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
// How people write a name that the list keeps shorter: "경영학" + 과 / 학과 / 학부 / 전공.
const SUFFIXES = ["과", "학과", "학부", "전공", "계열"];

/** Same entry, written as the list writes it, as one of its aliases, or the list name plus a
 * usual suffix ("경영학과" for 경영학). */
function same(item: Item, q: string): boolean {
  const query = norm(q);
  if (!query) return false;
  return [item.label, ...(item.keywords ?? [])].map(norm).some(
    (n) => n === query || (query.startsWith(n) && SUFFIXES.includes(query.slice(n.length))));
}

/** Lower is better; null = no match. Exact names first, then names that start with the query,
 * then names that contain it, then aliases, then the group or initial consonants. */
function rank(item: Item, q: string): number | null {
  const query = norm(q);
  if (!query) return 5;
  if (same(item, q)) return 0;
  const label = norm(item.label);
  if (label.startsWith(query)) return 1;
  if (label.includes(query)) return 2;
  if ((item.keywords ?? []).map(norm).some((k) => k.includes(query) || (query.startsWith(k) &&
      SUFFIXES.includes(query.slice(k.length))))) return 3;
  const hay = [item.label, item.group ?? "", ...(item.keywords ?? [])].map(norm);
  if (hay.some((h) => h.includes(query))) return 4;
  if ([...query].every((c) => CHO.includes(c)) && hay.some((h) => initials(h).includes(query))) return 4;
  return null;
}

/** Nothing matches: list entries that share the start of the name (after the usual suffix), so
 * "경영정보학과" offers 경영학. Never picked for them; "그대로 입력" stays available. */
function similar(items: Item[], q: string): Item[] {
  let base = norm(q);
  for (const s of [...SUFFIXES].sort((a, b) => b.length - a.length)) {
    if (base.endsWith(s) && base.length > s.length + 1) { base = base.slice(0, -s.length); break; }
  }
  if (base.endsWith("학") && base.length > 2) base = base.slice(0, -1);
  for (let len = base.length - 1; len >= 2; len -= 1) {
    const head = base.slice(0, len);
    const found = items.filter((i) => [i.label, ...(i.keywords ?? [])].some((n) => norm(n).startsWith(head)));
    if (found.length) return found.slice(0, 3);
  }
  return [];
}

type Option = (Item & { similar?: boolean }) | { id: null; label: string };

function optionBody(o: Option, noun: string) {
  if (o.id === null) return <span className="typed">‘{o.label}’ 그대로 입력 <small>목록에 없는 {noun}</small></span>;
  const hint = "similar" in o && o.similar ? `비슷한 ${noun}` : o.group;
  return <>{o.label}{hint ? <small>{hint}</small> : null}</>;
}

export default function SearchSelect(props: {
  items: Item[];
  value: Picked | null;
  onChange: (v: Picked | null) => void;
  placeholder: string;
  ariaLabel: string;
  noun: string; // "학교" | "전공", used in the free-text option
  inputId?: string;
  invalid?: boolean;
  suggestSimilar?: boolean; // when nothing matches, offer entries that start the same way
  clearOnPick?: boolean; // an "add one more" box: empty again (and still focused) after a pick
  onType?: () => void; // a letter typed (before anything is picked)
}) {
  const { items, value, onChange, placeholder, ariaLabel, noun } = props;
  const [query, setQuery] = useState(value?.label ?? "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const box = useRef<HTMLDivElement>(null);
  // Leaving the field hides the list but keeps its space, unchanged, for a moment: collapsing (or
  // re-filtering) at once would move the button below it while it is being pressed, and the
  // press would land on nothing.
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [closing, setClosing] = useState(false);
  const frozen = useRef<Option[]>([]);
  useEffect(() => () => { if (closeTimer.current) clearTimeout(closeTimer.current); }, []);
  // A value set from outside (e.g. answers carried over from the landing) shows up in the box.
  useEffect(() => {
    if (!open) setQuery(value?.label ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value?.id, value?.label]);

  const shown = useMemo(() => items
    .map((item, i) => ({ item, i, r: rank(item, query) }))
    .filter((x) => x.r !== null)
    .sort((a, b) => (a.r! - b.r!) || (a.i - b.i))
    .slice(0, 8)
    .map((x) => x.item), [items, query]);
  const typed = query.trim();
  const exact = items.find((i) => same(i, typed));
  // Only initial consonants ("ㄱㄹ") is a search, never a name to keep.
  const jamoOnly = [...norm(typed)].every((c) => CHO.includes(c));
  const near = useMemo(() => (props.suggestSimilar && shown.length === 0 && typed && !jamoOnly
    ? similar(items, typed).map((i) => ({ ...i, similar: true })) : []), [props.suggestSimilar, shown.length, typed, jamoOnly, items]);
  // Suggestions come after "그대로 입력": Enter (or the phone's enter key) keeps what was typed and
  // never swaps it for a guess.
  const options: Option[] = [
    ...shown,
    ...(typed && !exact && !jamoOnly ? [{ id: null, label: typed }] : []),
    ...near,
  ];

  function pick(o: Option) {
    setQuery(props.clearOnPick ? "" : o.label);
    onChange({ id: o.id, label: o.label });
  }

  function commitTyped() {
    // Leaving the field: an exact name, or a partial one that fits exactly one entry ("고려" →
    // 고려대학교), counts as picked. Text that fits nothing in the list is kept as typed. Text
    // that fits several entries stays unpicked: they choose one (or "그대로 입력") explicitly.
    if (!typed) {
      if (value) onChange(null);
      return;
    }
    if (value && norm(value.label) === norm(typed)) return;
    const byName = items.filter((i) => [i.label, ...(i.keywords ?? [])].some((n) => norm(n).includes(norm(typed))));
    if (exact) pick(exact);
    else if (byName.length === 1) pick(byName[0]);
    else if (shown.length === 1) pick(shown[0]);
    else if (shown.length === 0 && !jamoOnly) pick({ id: null, label: typed });
    else if (value) onChange(null);
  }

  return (
    <div className={props.invalid ? "search-select invalid" : "search-select"} ref={box}>
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
        onFocus={() => {
          if (closeTimer.current) clearTimeout(closeTimer.current);
          setClosing(false);
          setOpen(true);
          setActive(0);
        }}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); props.onType?.(); }}
        onBlur={() => {
          frozen.current = open ? options : [];
          setClosing(open);
          setOpen(false);
          commitTyped(); // the value is settled now, before any button press is handled
          closeTimer.current = setTimeout(() => setClosing(false), 300);
        }}
        onKeyDown={(e) => {
          if (e.nativeEvent.isComposing) return; // Korean IME: Enter that only finishes a syllable
          if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, options.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === "Enter" && open && options[active]) { e.preventDefault(); pick(options[active]); setOpen(false); }
          else if (e.key === "Escape") setOpen(false);
        }}
      />
      {value && value.id === null && !open && !closing && (
        <span className="search-select-note">목록에 없어서 입력한 이름 그대로 쓸게요</span>
      )}
      {!value && typed && !open && !closing && shown.length > 1 && (
        <span className="search-select-note">목록에서 하나를 골라주세요</span>
      )}
      {closing && frozen.current.length > 0 && (
        <ul className="search-select-list" aria-hidden="true" style={{ visibility: "hidden" }}>
          {frozen.current.map((o) => <li key={o.id ?? `typed-${o.label}`}>{optionBody(o, noun)}</li>)}
        </ul>
      )}
      {open && options.length > 0 && (
        <ul className="search-select-list" id={listId} role="listbox">
          {options.map((o, i) => (
            <li key={o.id ?? `typed-${o.label}`} id={`${listId}-${i}`} role="option" aria-selected={i === active}
                className={i === active ? "active" : undefined}
                onMouseDown={(e) => { e.preventDefault(); pick(o); setOpen(false); }}
                onMouseEnter={() => setActive(i)}>
              {optionBody(o, noun)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
