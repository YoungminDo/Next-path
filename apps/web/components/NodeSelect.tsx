"use client";

import { useMemo } from "react";

import type { Node } from "@/lib/api";

/** A role (or major) pick list grouped by parent. */
export default function NodeSelect({ nodes, value, onChange, empty = "선택", ariaLabel, id, invalid }: {
  nodes: Node[]; value: string; onChange: (v: string) => void; empty?: string; ariaLabel?: string;
  id?: string; invalid?: boolean;
}) {
  const groups = useMemo(() => {
    const g = new Map<string, Node[]>();
    nodes.forEach((n) => g.set(n.parent_label ?? "", [...(g.get(n.parent_label ?? "") ?? []), n]));
    return [...g.entries()];
  }, [nodes]);
  return (
    <select id={id} value={value} aria-label={ariaLabel} aria-invalid={invalid || undefined}
            onChange={(e) => onChange(e.target.value)}>
      <option value="">{empty}</option>
      {groups.map(([parent, list]) => (
        <optgroup key={parent} label={parent}>
          {list.map((n) => <option key={n.node_id} value={n.node_id}>{n.label}</option>)}
        </optgroup>
      ))}
    </select>
  );
}
