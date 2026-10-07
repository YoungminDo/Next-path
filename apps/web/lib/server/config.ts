import "server-only";

/** Server-side configuration. None of these values reach the browser bundle. */
export const serverConfig = {
  /** FastAPI base URL (private network or managed backend). */
  apiUrl: process.env.HELLOMYME_API_URL ?? "http://localhost:8000",
  /** HMM ID — the company identity provider that runs Kakao login. */
  hmmIdBaseUrl: process.env.HMM_ID_BASE_URL ?? "https://id.da-sh.io",
  /** Public origin of this web app, registered as an SP in hmm-id (sp-registry.ts). */
  appOrigin: process.env.APP_ORIGIN,
  /** DEV login is for local development only and is refused in production builds. */
  devLoginEnabled:
    process.env.NODE_ENV !== "production" && process.env.ENABLE_DEV_LOGIN === "true",
};

/** Our own session cookie (opaque token issued by FastAPI). HMM ID's cookie is never copied. */
export const SESSION_COOKIE = "hmc_session";
/** Set by HMM ID on the shared .da-sh.io domain after Kakao login. */
export const HMM_ID_COOKIE = "dash-access-token";

export function sessionCookieOptions(expiresAt?: string) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    ...(expiresAt ? { expires: new Date(expiresAt) } : {}),
  };
}

export function appOrigin(requestOrigin: string): string {
  return serverConfig.appOrigin ?? requestOrigin;
}
