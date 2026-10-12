import type { Metadata } from "next";

import AdminStats from "@/components/admin/AdminStats";

// Team only: never indexed, never cached (the API also refuses anyone not on the admin list).
export const metadata: Metadata = { title: "nextpath · 팀 대시보드", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";

export default function AdminPage() {
  return <AdminStats />;
}
