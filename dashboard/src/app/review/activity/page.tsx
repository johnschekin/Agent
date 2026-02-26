import { redirect } from "next/navigation";

export default function ReviewAgentActivityPage() {
  redirect("/links?tab=dashboard");
}
