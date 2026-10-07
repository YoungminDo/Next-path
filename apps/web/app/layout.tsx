import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "nextpath · 나와 같은 자리에 있었던 사람들은 어디로 갔을까",
  description: "학교·전공·학번만 고르면, 나와 같은 자리에 있었던 사람들이 실제로 간 길을 보여드려요.",
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
