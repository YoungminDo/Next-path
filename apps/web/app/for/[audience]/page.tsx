import { notFound } from "next/navigation";

import Landing, { type Audience } from "@/components/landing/Landing";
import { loadOptions } from "@/lib/server/options";

/* The landing for one ad audience (docs/11). Visitors reach it through the rewrite in
   next.config.ts while their address stays "/?utm_campaign=…", so it is not indexed on its own. */

const AUDIENCES: Audience[] = ["seeker", "pro"];

export const revalidate = 600;
export const dynamicParams = false;
export const metadata = { robots: { index: false } };

export function generateStaticParams() {
  return AUDIENCES.map((audience) => ({ audience }));
}

export default async function AudienceLanding({ params }: { params: Promise<{ audience: string }> }) {
  const { audience } = await params;
  if (!AUDIENCES.includes(audience as Audience)) notFound();
  return <Landing options={await loadOptions()} audience={audience as Audience} />;
}
