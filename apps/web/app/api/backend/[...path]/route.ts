import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, serverConfig } from "@/lib/server/config";

/**
 * Same-origin proxy to FastAPI. The browser never holds the session token: it lives in an
 * HttpOnly cookie and is turned into `Authorization: Bearer` here.
 */
const FORWARDED_HEADERS = ["content-type", "x-anonymous-session", "idempotency-key"];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  // Cookie-authenticated writes must come from our own pages (SameSite=Lax + Origin check).
  const origin = req.headers.get("origin");
  if (req.method !== "GET" && origin && origin !== req.nextUrl.origin) {
    return NextResponse.json({ detail: "cross-origin request refused" }, { status: 403 });
  }
  const { path } = await ctx.params;
  const target = new URL(`${serverConfig.apiUrl}/${path.map(encodeURIComponent).join("/")}`);
  target.search = req.nextUrl.search;

  const headers: Record<string, string> = {};
  for (const name of FORWARDED_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers[name] = value;
  }
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (token) headers.authorization = `Bearer ${token}`;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: req.method === "GET" ? undefined : await req.text(),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "api unreachable" }, { status: 502 });
  }
  const body = upstream.status === 204 ? null : await upstream.arrayBuffer();
  const res = new NextResponse(body, { status: upstream.status });
  const type = upstream.headers.get("content-type");
  if (type) res.headers.set("content-type", type);
  // Public pick lists carry a CDN cache header from the API; everything else stays uncached.
  const cache = upstream.headers.get("cache-control");
  if (req.method === "GET" && !token && cache?.includes("public")) res.headers.set("cache-control", cache);
  if (upstream.status === 401 && token) res.cookies.delete(SESSION_COOKIE);
  return res;
}

export const GET = proxy;
export const POST = proxy;
