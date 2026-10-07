import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, serverConfig } from "@/lib/server/config";

/**
 * POST /auth/logout — end the career-service session only. HMM ID's SSO cookie is left to
 * HMM ID: other DA-SH services share it.
 */
export async function POST(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (token) {
    await fetch(`${serverConfig.apiUrl}/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    }).catch(() => undefined);
  }
  const res = new NextResponse(null, { status: 204 });
  res.cookies.delete(SESSION_COOKIE);
  return res;
}
