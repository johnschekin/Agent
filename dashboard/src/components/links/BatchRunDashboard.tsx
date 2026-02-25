"use client";

import { useMemo } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import {
  useAnalyticsDashboard,
  useLinkRuns,
  useDriftAlerts,
  useSubmitLinkJobMutation,
} from "@/lib/queries";

interface BatchRunDashboardProps {
  className?: string;
}

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d ago`;
}

export function BatchRunDashboard({ className }: BatchRunDashboardProps) {
  const { data: analytics, isLoading: analyticsLoading } = useAnalyticsDashboard();
  const { data: runsData } = useLinkRuns();
  const { data: alertsData } = useDriftAlerts();
  const submitJobMut = useSubmitLinkJobMutation();

  const runs = runsData?.runs ?? [];
  const alerts = alertsData?.alerts ?? [];
  const unacknowledgedAlerts = alerts.filter((a) => !a.resolved);

  // Compute coverage % from links_by_status: accepted / total
  const coverageDisplay = useMemo(() => {
    const totalLinks = analytics?.total_links ?? 0;
    if (totalLinks === 0) return "\u2014";
    const accepted =
      analytics?.links_by_status?.find((s) => s.status === "accepted")?.count ?? 0;
    const pct = (accepted / totalLinks) * 100;
    return `${pct.toFixed(1)}%`;
  }, [analytics]);

  // Build a lookup: family_id -> most recent run for that family
  const latestRunByFamily = useMemo(() => {
    const map = new Map<string, (typeof runs)[number]>();
    for (const run of runs) {
      const existing = map.get(run.family_id);
      if (!existing || new Date(run.started_at) > new Date(existing.started_at)) {
        map.set(run.family_id, run);
      }
    }
    return map;
  }, [runs]);

  // Build a lookup: family_id -> pending count from links_by_status per-family (approximate)
  // Since analytics.links_by_status is global, we derive pending count from runs data
  const pendingByFamily = useMemo(() => {
    const map = new Map<string, number>();
    for (const run of runs) {
      if (run.status === "running") {
        map.set(run.family_id, (map.get(run.family_id) ?? 0) + 1);
      }
    }
    return map;
  }, [runs]);

  // Coverage by family: links_created / corpus_doc_count from the latest run
  const coverageByFamily = useMemo(() => {
    const map = new Map<string, number | null>();
    latestRunByFamily.forEach((run, fid) => {
      if (run.corpus_doc_count > 0 && run.status === "completed") {
        map.set(fid, (run.links_created / run.corpus_doc_count) * 100);
      } else {
        map.set(fid, null);
      }
    });
    return map;
  }, [latestRunByFamily]);

  const matrixFamilies = useMemo(() => {
    const fromAnalytics = analytics?.links_by_family ?? [];
    if (fromAnalytics.length > 0) {
      return fromAnalytics.map((family) => ({
        family_id: family.family_id,
        count: family.count,
      }));
    }
    const fromRuns = Array.from(latestRunByFamily.entries()).map(([familyId, run]) => ({
      family_id: familyId,
      count: Number(run.links_created ?? 0),
    }));
    if (fromRuns.length > 0) return fromRuns;
    const fromAlerts = Array.from(
      new Set(alerts.filter((a) => !a.resolved).map((a) => a.family_id)),
    ).map((familyId) => ({ family_id: familyId, count: 0 }));
    if (fromAlerts.length > 0) return fromAlerts;
    return [{ family_id: "unassigned", count: 0 }];
  }, [analytics, latestRunByFamily, alerts]);

  // Most recent run overall for staleness indicator
  const mostRecentRun = useMemo(() => {
    if (runs.length === 0) return null;
    return runs.reduce((latest, run) =>
      new Date(run.started_at) > new Date(latest.started_at) ? run : latest,
    );
  }, [runs]);

  return (
    <div className={cn("space-y-4", className)} data-testid="batch-run-dashboard">
      {/* KPI row */}
      <KpiCardGrid className="grid-cols-2 md:grid-cols-4">
        <KpiCard
          title="Total Links"
          value={analytics?.total_links ?? 0}
          color="blue"
        />
        <KpiCard
          title="Coverage %"
          value={coverageDisplay}
          color="green"
        />
        <KpiCard
          title="Pending Review"
          value={
            analytics?.links_by_status?.find((s) => s.status === "pending_review")?.count ?? 0
          }
          color="orange"
        />
        <KpiCard
          title="Drift Alerts"
          value={unacknowledgedAlerts.length}
          color="red"
        />
      </KpiCardGrid>

      {/* Family matrix */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
            Family Matrix
          </h4>
          <button
            type="button"
            onClick={() =>
              submitJobMut.mutate({ job_type: "batch_run", params: {} })
            }
            disabled={submitJobMut.isPending}
            className="px-3 py-1.5 bg-accent-blue text-white text-xs rounded-lg hover:opacity-90 disabled:opacity-50"
            data-testid="run-all-rules-btn"
          >
            {submitJobMut.isPending ? "Submitting..." : "Run All Rules"}
          </button>
        </div>

        {/* Staleness indicator */}
        {mostRecentRun && (
          <p
            className="text-xs text-text-muted mb-2"
            data-testid="staleness-indicator"
          >
            Last batch run: {timeAgo(mostRecentRun.started_at)}
            {mostRecentRun.completed_at
              ? ` (completed ${timeAgo(mostRecentRun.completed_at)})`
              : mostRecentRun.status === "running"
                ? " (still running)"
                : ""}
          </p>
        )}

        {analyticsLoading ? (
          <p className="text-sm text-text-muted py-6 text-center">Loading analytics...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse" data-testid="family-matrix">
              <thead>
                <tr>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Family
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Links
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Coverage %
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Pending
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Status
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Last Run
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Drift
                  </th>
                </tr>
              </thead>
              <tbody>
                {matrixFamilies.map((fam) => {
                  const familyAlerts = alerts.filter((a) => a.family_id === fam.family_id && !a.resolved);
                  const latestRun = latestRunByFamily.get(fam.family_id);
                  const coverage = coverageByFamily.get(fam.family_id);
                  const pending = pendingByFamily.get(fam.family_id) ?? 0;
                  return (
                    <tr
                      key={fam.family_id}
                      className="border-b border-border/30 hover:bg-surface-2/50"
                      data-testid={`matrix-family-${fam.family_id}`}
                    >
                      <td className="px-3 py-2 text-sm text-text-primary">{fam.family_id}</td>
                      <td className="px-3 py-2 text-sm text-text-primary text-right tabular-nums">
                        {fam.count}
                      </td>
                      <td
                        className="px-3 py-2 text-sm text-text-primary text-right tabular-nums"
                        data-testid={`matrix-coverage-${fam.family_id}`}
                      >
                        {coverage != null ? `${coverage.toFixed(1)}%` : "\u2014"}
                      </td>
                      <td
                        className="px-3 py-2 text-sm text-right tabular-nums"
                        data-testid={`matrix-pending-${fam.family_id}`}
                      >
                        {pending > 0 ? (
                          <Badge variant="orange">{pending} running</Badge>
                        ) : (
                          <span className="text-text-muted">\u2014</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {latestRun ? (
                          <Badge
                            variant={
                              latestRun.status === "completed"
                                ? "green"
                                : latestRun.status === "running"
                                  ? "blue"
                                  : "red"
                            }
                          >
                            {latestRun.status}
                          </Badge>
                        ) : (
                          <span className="text-xs text-text-muted">\u2014</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs text-text-muted text-right tabular-nums">
                        {latestRun ? timeAgo(latestRun.started_at) : "\u2014"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {familyAlerts.length > 0 ? (
                          <Badge variant="red">{familyAlerts.length} alerts</Badge>
                        ) : (
                          <span className="text-xs text-text-muted">\u2014</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent runs */}
      {runs.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
            Recent Runs
          </h4>
          <div className="space-y-1">
            {runs.slice(0, 5).map((run) => (
              <div
                key={run.run_id}
                className="flex items-center justify-between px-3 py-2 bg-surface-2 rounded-lg"
                data-testid={`run-${run.run_id}`}
              >
                <div className="flex items-center gap-2">
                  <Badge variant={run.status === "completed" ? "green" : run.status === "running" ? "blue" : "red"}>
                    {run.status}
                  </Badge>
                  <span className="text-xs text-text-primary">{run.family_id}</span>
                  <span className="text-xs text-text-muted">{run.run_type}</span>
                </div>
                <span className="text-xs text-text-muted tabular-nums">
                  {run.links_created} links
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
