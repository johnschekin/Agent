import { redirect } from "next/navigation";

export default function ReviewOpsHomePage() {
  redirect("/links?tab=dashboard");
}
