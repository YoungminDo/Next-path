import { NextRequest, NextResponse } from "next/server";

import {
  HMM_ID_COOKIE,
  SESSION_COOKIE,
  appOrigin,
  serverConfig,
  sessionCookieOptions,
} from "@/lib/server/config";

/**
 * GET /auth/hmm/callback — HMM ID returns here after Kakao login.
 *
 * HMM ID puts the result in the HttpOnly `dash-access-token` cookie (never in the URL). We
 * read it server-side, let FastAPI verify it with HMM ID (`/api/v1/auth/me`), and keep only
 * our own opaque session cookie. On failure HMM ID appends `?error=<reason>`.
 */
export async function GET(req: NextRequest) {
  const home = new URL("/", appOrigin(req.nextUrl.origin));
  const fail = (reason: string) => {
    home.searchParams.set("login_error", reason);
    const res = NextResponse.redirect(home);
    res.cookies.delete(SESSION_COOKIE);
    return res;
  };

  const idpError = req.nextUrl.searchParams.get("error");
  if (idpError) return fail(idpError);

  const dashToken = req.cookies.get(HMM_ID_COOKIE)?.value;
  if (!dashToken) return fail("no_hmm_session");

  let login: Response;
  try {
    login = await fetch(`${serverConfig.apiUrl}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: "HMM_ID", token: dashToken }),
      cache: "no-store",
    });
  } catch {
    return fail("api_unreachable");
  }
  if (login.status === 401) return fail("hmm_token_rejected");
  if (!login.ok) return fail("login_unavailable");

  const session = (await login.json()) as { session_token: string; expires_at: string };
  home.searchParams.set("login", "success");
  const res = NextResponse.redirect(home);
  res.cookies.set(SESSION_COOKIE, session.session_token, sessionCookieOptions(session.expires_at));
  return res;
}
