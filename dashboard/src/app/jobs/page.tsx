import { redirect } from "next/navigation";

export default function JobsPage() {
  redirect("/links?tab=dashboard");
}
