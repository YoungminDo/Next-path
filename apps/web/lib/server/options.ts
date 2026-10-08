import "server-only";

import type { Node } from "@/lib/api";
import { serverConfig } from "@/lib/server/config";

/** Pick lists rendered into the page HTML, so the dropdowns are filled on first paint.
 * Refreshed every 10 minutes (ISR). If the API cannot be reached the lists are empty and the
 * browser fetches them itself. */
export type Options = {
  institutions: { id: string; name: string; region: string | null }[];
  majors: Node[];
  roles: Node[];
  middleRoles: Node[];
};

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${serverConfig.apiUrl}${path}`, {
      next: { revalidate: 600 },
      signal: AbortSignal.timeout(5000),
    });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

export async function loadOptions(): Promise<Options> {
  const [institutions, majors, roles, middleRoles] = await Promise.all([
    get<Options["institutions"]>("/acq/options/institutions"),
    get<Node[]>("/acq/options/majors?depth=3"),
    get<Node[]>("/acq/options/roles?depth=3"),
    get<Node[]>("/acq/options/roles?depth=2"),
  ]);
  return {
    institutions: institutions ?? [], majors: majors ?? [], roles: roles ?? [], middleRoles: middleRoles ?? [],
  };
}
