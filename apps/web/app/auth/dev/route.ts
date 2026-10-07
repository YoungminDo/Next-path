import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, serverConfig, sessionCookieOptions } from "@/lib/server/config";

/** POST /auth/dev — local development login (no Kakao). Disabled in production builds. */
export async function POST(req: NextRequest) {
  if (!serverConfig.devLoginEnabled) return new NextResponse(null, { status: 404 });
  const origin = req.headers.get("origin");
  if (origin && origin !== req.nextUrl.origin) return new NextResponse(null, { status: 403 });
  const login = await fetch(`${serverConfig.apiUrl}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: "DEV", token: `dev:${crypto.randomUUID()}` }),
    cache: "no-store",
  });
  if (!login.ok) return NextResponse.json({ error: "dev login failed" }, { status: 502 });
  const session = (await login.json()) as { session_token: string; expires_at: string };
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, session.session_token, sessionCookieOptions(session.expires_at));
  return res;
}
