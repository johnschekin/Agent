import { redirect } from "next/navigation";

export default function StrategiesPage() {
  redirect("/links?tab=rules");
}
