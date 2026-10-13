import AcquisitionFlow from "@/components/AcquisitionFlow";
import { loadOptions } from "@/lib/server/options";

/** Short link for posts and reels (nextpath.da-sh.io/upload): opens on the upload, no detour. */
export const metadata = { title: "nextpath · 이력서·캡처로 시작하기" };
export const revalidate = 600;

export default async function Upload() {
  return <AcquisitionFlow initial={await loadOptions()} startOn="upload" />;
}
