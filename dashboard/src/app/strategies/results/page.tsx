import { redirect } from "next/navigation";

export default function StrategyResultsPage() {
  redirect("/links?tab=dashboard");
}
