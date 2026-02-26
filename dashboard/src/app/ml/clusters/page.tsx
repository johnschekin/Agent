import { redirect } from "next/navigation";

export default function ClustersPage() {
  redirect("/links?tab=query");
}
