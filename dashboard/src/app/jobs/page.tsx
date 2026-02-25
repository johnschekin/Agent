"use client";

import { useCallback, useRef } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useJobs, useCancelJob } from "@/lib/queries";
import { formatNumber } from "@/lib/formatters";
import { cn } from "@/lib/cn";
import type { Job, JobStatus } from "@/lib/types";

// --- Status badge ---

const STATUS_STYLES: Record<JobStatus, string> = {
  pending: "bg-surface-3 text-text-muted border border-border",
  running: "bg-accent-blue/20 text-accent-blue",
  completed: "bg-accent-green/20 text-accent-green",
  failed: "bg-accent-red/20 text-accent-red",
  cancelled: "bg-surface-3 text-text-muted border border-border",
};

// L4 RT2 FIX: Prefix symbols for accessibility (not color-only)
const STATUS_ICONS: Record<JobStatus, string> = {
  pending: "\u25CB",     // ○
  running: "\u25B6",     // ▶
  completed: "\u2713",   // ✓
  failed: "\u2717",      // ✗
  cancelled: "\u2014",   // —
};

function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span className={cn("inline-block px-1.5 py-0.5 rounded text-[10px] font-medium", STATUS_STYLES[status])}>
      {STATUS_ICONS[status]} {status}
    </span>
  );
}

// --- Progress bar ---

function ProgressBar({ progress, status }: { progress: number; status: JobStatus }) {
  const color =
    status === "completed"
      ? "#22C55E"
      : status === "failed"
        ? "#EF4444"
        : status === "cancelled"
          ? "#738091"
          : "#3B82F6";

  return (
    <div className="w-24 h-1.5 bg-surface-3 rounded-full overflow-hidden">
      <div
        className={cn(
          "h-full rounded-full transition-all duration-500",
          status === "running" && "animate-pulse"
        )}
        style={{
          width: `${Math.min(100, progress * 100)}%`,
          backgroundColor: color,
        }}
      />
    </div>
  );
}

// --- Time formatting ---

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return date.toLocaleDateString();
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "\u2014";
  const startDate = new Date(start);
  const endDate = end ? new Date(end) : new Date();
  const diffMs = endDate.getTime() - startDate.getTime();
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

// --- Job type labels ---

const JOB_TYPE_LABELS: Record<string, string> = {
  pattern_test: "Pattern Test",
  dna_discover: "DNA Discovery",
  heading_discover: "Heading Discovery",
  coverage: "Coverage Analysis",
  clause_search: "Clause Search",
};

// --- Job row ---

function JobRow({
  job,
  onCancel,
}: {
  job: Job;
  onCancel: (jobId: string) => void;
}) {
  return (
    <tr className="border-t border-border hover:bg-surface-3/50 transition-colors">
      <td className="px-3 py-2 text-xs font-mono text-text-muted">
        {job.job_id}
      </td>
      <td className="px-3 py-2 text-xs">
        {JOB_TYPE_LABELS[job.job_type] ?? job.job_type}
      </td>
      <td className="px-3 py-2">
        <StatusBadge status={job.status} />
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <ProgressBar progress={job.progress} status={job.status} />
          <span className="text-[10px] text-text-muted tabular-nums">
            {Math.round(job.progress * 100)}%
          </span>
        </div>
      </td>
      <td className="px-3 py-2 text-xs text-text-secondary truncate max-w-[200px]" title={job.progress_message}>
        {job.progress_message}
      </td>
      <td className="px-3 py-2 text-xs text-text-muted">
        {formatRelativeTime(job.submitted_at)}
      </td>
      <td className="px-3 py-2 text-xs text-text-muted tabular-nums">
        {formatDuration(job.started_at, job.completed_at)}
      </td>
      <td className="px-3 py-2">
        {(job.status === "pending" || job.status === "running") && (
          <button
            onClick={() => onCancel(job.job_id)}
            className="text-xs text-accent-red hover:underline"
          >
            Cancel
          </button>
        )}
        {job.status === "failed" && job.error && (
          <span className="text-xs text-accent-red" title={job.error}>
            Error
          </span>
        )}
        {job.status === "completed" && job.result_summary && (
          <span className="text-xs text-accent-green" title={JSON.stringify(job.result_summary)}>
            Done
          </span>
        )}
      </td>
    </tr>
  );
}

// --- Main page ---

export default function JobsPage() {
  // Poll every 5 seconds for active jobs
  const jobs = useJobs(undefined, 5_000);
  const cancelMutation = useCancelJob();

  // H5 FIX: Use ref for refetch to avoid recreating callback every poll cycle
  const refetchRef = useRef(jobs.refetch);
  refetchRef.current = jobs.refetch;

  const handleCancel = useCallback(
    (jobId: string) => {
      cancelMutation.mutate(jobId, {
        onSuccess: () => {
          refetchRef.current();
        },
      });
    },
    [cancelMutation]
  );

  const data = jobs.data;

  // Compute stats
  const activeCount = data?.jobs.filter((j) => j.status === "running").length ?? 0;
  const pendingCount = data?.jobs.filter((j) => j.status === "pending").length ?? 0;
  const completedCount = data?.jobs.filter((j) => j.status === "completed").length ?? 0;
  const failedCount = data?.jobs.filter((j) => j.status === "failed").length ?? 0;

  return (
    <ViewContainer title="Jobs">
      {/* KPIs */}
      <KpiCardGrid className="mb-4">
        <KpiCard title="Active" value={formatNumber(activeCount)} color="blue" />
        <KpiCard title="Queued" value={formatNumber(pendingCount)} />
        <KpiCard title="Completed" value={formatNumber(completedCount)} color="green" />
        <KpiCard title="Failed" value={formatNumber(failedCount)} color="red" />
        <KpiCard title="Total" value={data ? formatNumber(data.total) : "\u2014"} />
      </KpiCardGrid>

      {/* Loading */}
      {jobs.isLoading && !data && <LoadingState message="Loading jobs..." />}
      {jobs.error && !data && (
        <EmptyState title="Failed to load" message="Check the API server is running." />
      )}

      {/* Job queue */}
      {data && (
        <ChartCard title="" height="auto">
          {data.jobs.length === 0 ? (
            <EmptyState
              title="No jobs"
              message="Background jobs submitted from Discovery Lab views will appear here."
            />
          ) : (
            <div className="overflow-auto max-h-[600px]">
              <table className="w-full text-sm" aria-label="Background jobs">
                <thead className="sticky top-0 bg-surface-3 z-10">
                  <tr className="text-left text-xs text-text-muted uppercase">
                    <th className="px-3 py-2">Job ID</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Progress</th>
                    <th className="px-3 py-2">Message</th>
                    <th className="px-3 py-2">Submitted</th>
                    <th className="px-3 py-2">Duration</th>
                    <th className="px-3 py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.jobs.map((job) => (
                    <JobRow
                      key={job.job_id}
                      job={job}
                      onCancel={handleCancel}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ChartCard>
      )}
    </ViewContainer>
  );
}
