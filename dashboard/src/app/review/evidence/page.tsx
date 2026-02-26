import { redirect } from "next/navigation";

export default function ReviewEvidencePage() {
  redirect("/links?tab=review");
}
