import type { Metadata } from "next";

import "./globals.css";

const TITLE = "나와 같은 자리에 있었던 사람들은 어디로 갔을까?";
const DESCRIPTION = "학교·전공·학번만 고르면, 나와 같은 출발점의 사람들이 간 길을 보여드려요. 무료 · 카카오로 3초.";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.APP_ORIGIN ?? "https://nextpath.da-sh.io"),
  title: `nextpath · ${TITLE}`,
  description: DESCRIPTION,
  // The preview card a DM or a post shows for the link (Instagram, KakaoTalk, Threads …).
  openGraph: {
    type: "website", locale: "ko_KR", siteName: "nextpath", url: "/",
    title: TITLE, description: DESCRIPTION,
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "나와 같은 자리에 있었던 사람들은 어디로 갔을까?" }],
  },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION, images: ["/og.png"] },
};

export const viewport = { width: "device-width", initialScale: 1, viewportFit: "cover", themeColor: "#21D7C8" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <head>
        <link rel="stylesheet" crossOrigin="anonymous"
              href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" />
      </head>
      <body>{children}</body>
    </html>
  );
}
