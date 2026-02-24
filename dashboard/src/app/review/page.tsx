"use client";

import Link from "next/link";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { useReviewAgentActivity, useReviewEvidence } from "@/lib/queries";

const REVIEW_VIEWS = [
  {
    href: "/review/strategy",
    title: "Strategy Timeline",
    description: "Version-by-version field deltas and judge precision trends.",
  },
  {
    href: "/review/evidence",
    title: "Evidence Browser",
    description: "Inspect HIT / NOT_FOUND rows with outlier flags and provenance.",
  },
  {
    href: "/review/coverage",
    title: "Coverage Heatmap",
    description: "Template-family x concept coverage matrix from persisted evidence.",
  },
  {
    href: "/review/judge",
    title: "Judge History",
    description: "Track strict and weighted precision across strategy versions.",
  },
  {
    href: "/review/activity",
    title: "Agent Activity",
    description: "Checkpoint status, stale detection, and current family workload.",
  },
];

export default function ReviewOpsHomePage() {
  const activity = useReviewAgentActivity(60);
  const evidence = useReviewEvidence({ limit: 1, offset: 0 });
  const loading =
    (activity.isLoading && !activity.data) || (evidence.isLoading && !evidence.data);

  return (
    <ViewContainer
      title="Review Operations"
      subtitle="Human-in-the-loop validation console for strategy quality, evidence quality, and swarm execution health."
    >
      {loading ? (
        <LoadingState message="Loading review summary..." />
      ) : (
        <>
          <KpiCardGrid className="mb-4">
            <KpiCard title="Evidence Rows" value={evidence.data?.rows_matched ?? 0} color="blue" />
            <KpiCard title="Families" value={activity.data?.total ?? 0} color="green" />
            <KpiCard
              title="Stale Agents"
              value={activity.data?.stale_count ?? 0}
              color={(activity.data?.stale_count ?? 0) > 0 ? "red" : "green"}
            />
          </KpiCardGrid>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {REVIEW_VIEWS.map((view) => (
              <Link
                key={view.href}
                href={view.href}
                className="rounded-md border border-border bg-surface-secondary p-4 transition-colors hover:bg-surface-tertiary"
              >
                <div className="text-sm font-semibold text-text-primary">{view.title}</div>
                <div className="mt-1 text-xs text-text-muted">{view.description}</div>
              </Link>
            ))}
          </div>
        </>
      )}
    </ViewContainer>
  );
}
