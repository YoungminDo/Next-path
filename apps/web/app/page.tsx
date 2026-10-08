import Landing from "@/components/landing/Landing";
import { loadOptions } from "@/lib/server/options";

export const revalidate = 600;

export default async function Home() {
  return <Landing options={await loadOptions()} />;
}
