import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "nextpath · 나와 비슷한 선배들의 실제 경로",
  description: "학교·전공·연도만 넣으면, 비슷한 선배들이 실제로 고른 다음 선택을 숫자로 보여드려요.",
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
