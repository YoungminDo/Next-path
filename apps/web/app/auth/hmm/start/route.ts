import { NextRequest, NextResponse } from "next/server";

import { NEXT_COOKIE, NEXT_PATHS, appOrigin, serverConfig, sessionCookieOptions } from "@/lib/server/config";

/**
 * GET /auth/hmm/start — hand the browser to HMM ID, which runs the Kakao OAuth flow and sets
 * `dash-access-token` on the shared domain before redirecting back to /auth/hmm/callback.
 */
export function GET(req: NextRequest) {
  const callback = `${appOrigin(req.nextUrl.origin)}/auth/hmm/callback`;
  const url = new URL("/api/oauth/kakao/start", serverConfig.hmmIdBaseUrl);
  url.searchParams.set("redirect_uri", callback);
  const prompt = req.nextUrl.searchParams.get("prompt");
  if (prompt === "select_account") url.searchParams.set("prompt", prompt);
  const res = NextResponse.redirect(url);
  // The callback URL registered with HMM ID stays the same; where to land afterwards rides along
  // in a short-lived cookie, and only known paths are accepted.
  const next = req.nextUrl.searchParams.get("next");
  if (next && NEXT_PATHS.includes(next)) res.cookies.set(NEXT_COOKIE, next, { ...sessionCookieOptions(), maxAge: 600 });
  else res.cookies.delete(NEXT_COOKIE);
  return res;
}
