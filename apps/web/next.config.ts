import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Ads per audience (docs/11: utm_campaign np_<date>_<audience>) open the landing written for
  // that audience; the address stays "/?utm_…", so tracking and the pixel see the same page.
  async rewrites() {
    return {
      beforeFiles: (["pro", "seeker"] as const).map((audience) => ({
        source: "/",
        has: [{ type: "query" as const, key: "utm_campaign", value: `.*_${audience}` }],
        destination: `/for/${audience}`,
      })),
      afterFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;
