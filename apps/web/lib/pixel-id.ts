/** Meta dataset "NEXTPATH웹" (Events Manager, made 2026-10-14; docs/11). Public: it ships in every page.
 * NEXT_PUBLIC_META_PIXEL_ID overrides it, and "off" turns the pixel and its privacy-policy section off. */
const env = process.env.NEXT_PUBLIC_META_PIXEL_ID;

export const META_PIXEL_ID: string | null = env === "off" ? null : env || "1422190370051636";
