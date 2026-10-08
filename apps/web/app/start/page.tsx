import AcquisitionFlow from "@/components/AcquisitionFlow";
import { loadOptions } from "@/lib/server/options";

export const metadata = { title: "nextpath · 나와 같은 자리였던 사람들" };
export const revalidate = 600;

export default async function Start() {
  return <AcquisitionFlow initial={await loadOptions()} />;
}
