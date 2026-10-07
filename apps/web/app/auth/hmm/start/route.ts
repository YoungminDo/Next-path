import { NextRequest, NextResponse } from "next/server";

import { appOrigin, serverConfig } from "@/lib/server/config";

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
  return NextResponse.redirect(url);
}
