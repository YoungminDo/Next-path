import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "HELLOMYME Career",
  description: "나와 비슷한 사람들의 실제 다음 선택을 탐색하세요.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
