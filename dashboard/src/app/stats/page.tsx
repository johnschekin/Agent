"use client";

import { useState } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { HistogramChart } from "@/components/charts/HistogramChart";
import { HBarChart } from "@/components/charts/HBarChart";
import { useMetricStats } from "@/lib/queries";
import { formatNumber, formatCompact, formatCurrencyMM } from "@/lib/formatters";
import { METRICS, GROUP_OPTIONS, metricLabel, metricFormatter } from "@/lib/metrics";
import type { GroupStats, OutlierRecord } from "@/lib/types";
import { cn } from "@/lib/cn";

// --- GroupStatsTable ---

function GroupStatsTable({
  groups,
  metric,
}: {
  groups: GroupStats[];
  metric: string;
}) {
  const fmt = metric === "facility_size_mm" ? formatCurrencyMM : formatCompact;

  return (
    <div className="overflow-auto max-h-[400px]">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-surface-tertiary">
          <tr className="text-left text-xs text-text-muted uppercase">
            <th className="px-3 py-2">Group</th>
            <th className="px-3 py-2 text-right">Count</th>
            <th className="px-3 py-2 text-right">Mean</th>
            <th className="px-3 py-2 text-right">Median</th>
            <th className="px-3 py-2 text-right">StdDev</th>
            <th className="px-3 py-2 text-right">Min</th>
            <th className="px-3 py-2 text-right">Max</th>
            <th className="px-3 py-2 text-right">P5</th>
            <th className="px-3 py-2 text-right">P95</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g, idx) => (
            <tr
              key={g.group || `__empty_${idx}`}
              className="border-t border-border hover:bg-surface-tertiary/50"
            >
              <td
                className="px-3 py-2 text-text-primary font-medium truncate max-w-[200px]"
                title={g.group.replace(/_/g, " ") || "(empty)"}
              >
                {g.group ? g.group.replace(/_/g, " ") : "(empty)"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {formatNumber(g.count)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{fmt(g.mean)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmt(g.median)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmt(g.stdev)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmt(g.min)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmt(g.max)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmt(g.p5)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmt(g.p95)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- OutlierTable ---

function OutlierTable({
  outliers,
  metric,
}: {
  outliers: OutlierRecord[];
  metric: string;
}) {
  const fmt = metric === "facility_size_mm" ? formatCurrencyMM : formatCompact;
  const hasGroupColumn = outliers.some((o) => o.group !== null);

  if (outliers.length === 0) {
    return (
      <div className="text-center text-text-muted text-sm py-8">
        No outliers detected
      </div>
    );
  }

  return (
    <div className="overflow-auto max-h-[300px]">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-surface-tertiary">
          <tr className="text-left text-xs text-text-muted uppercase">
            <th className="px-3 py-2">Doc ID</th>
            <th className="px-3 py-2">Borrower</th>
            <th className="px-3 py-2 text-right">Value</th>
            <th className="px-3 py-2 text-center">Direction</th>
            {hasGroupColumn && <th className="px-3 py-2">Group</th>}
          </tr>
        </thead>
        <tbody>
          {outliers.map((o, idx) => (
            <tr
              key={`${o.doc_id}_${o.direction}_${idx}`}
              className="border-t border-border hover:bg-surface-tertiary/50"
            >
              <td className="px-3 py-2 font-mono text-xs text-text-secondary truncate max-w-[160px]">
                {o.doc_id}
              </td>
              <td className="px-3 py-2 text-text-primary truncate max-w-[200px]">
                {o.borrower}
              </td>
              <td className="px-3 py-2 text-right tabular-nums font-medium">
                {fmt(o.value)}
              </td>
              <td className="px-3 py-2 text-center">
                <span
                  className={cn(
                    "inline-block px-2 py-0.5 rounded text-xs font-medium",
                    o.direction === "high"
                      ? "bg-accent-red/20 text-accent-red"
                      : "bg-accent-blue/20 text-accent-blue"
                  )}
                >
                  {o.direction}
                </span>
              </td>
              {hasGroupColumn && (
                <td className="px-3 py-2 text-text-secondary text-xs">
                  {o.group?.replace(/_/g, " ") ?? "\u2014"}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- StatsPage ---

export default function StatsPage() {
  const [metric, setMetric] = useState("word_count");
  const [groupBy, setGroupBy] = useState("");
  const [cohortOnly, setCohortOnly] = useState(true);

  const stats = useMetricStats({
    metric,
    groupBy: groupBy || undefined,
    cohortOnly,
    bins: 30,
  });

  const selectClass =
    "bg-surface-tertiary border border-border rounded-sm px-2 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-blue";

  const data = stats.data;
  const overall = data?.overall;
  const fmt = metric === "facility_size_mm" ? formatCurrencyMM : formatCompact;

  return (
    <ViewContainer title="Corpus Statistics">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          Metric
          <select
            aria-label="Metric"
            className={selectClass}
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
          >
            {METRICS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          Group By
          <select
            aria-label="Group by"
            className={selectClass}
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value)}
          >
            {GROUP_OPTIONS.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={cohortOnly}
            onChange={(e) => setCohortOnly(e.target.checked)}
            className="accent-accent-blue"
          />
          Cohort Only
        </label>
      </div>

      {/* M13: Stale data indicator */}
      {stats.isPlaceholderData && (
        <div className="text-xs text-text-muted mb-2 animate-pulse">
          Updating\u2026
        </div>
      )}

      {stats.isLoading && !data && (
        <LoadingState message="Computing statistics..." />
      )}

      {stats.error && !data && (
        <EmptyState
          title="Failed to load"
          message="Statistics query failed. Make sure the API server is running."
        />
      )}

      {data && !overall && (
        <EmptyState
          title="No Data"
          message={`No values found for ${metricLabel(metric)}.`}
        />
      )}

      {data && overall && (
        <div className={cn(stats.isPlaceholderData && "opacity-60 transition-opacity")}>
          {/* KPI cards */}
          <KpiCardGrid>
            <KpiCard title="Count" value={formatNumber(overall.count)} color="blue" />
            <KpiCard title="Mean" value={fmt(overall.mean)} />
            <KpiCard title="Median" value={fmt(overall.median)} color="green" />
            <KpiCard title="Std Dev" value={fmt(overall.stdev)} />
            <KpiCard title="Min" value={fmt(overall.min)} />
            <KpiCard title="Max" value={fmt(overall.max)} />
          </KpiCardGrid>

          {/* Distribution + Group medians */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
            <ChartCard title={`${metricLabel(metric)} Distribution`}>
              {data.histogram.length > 0 ? (
                <HistogramChart
                  data={data.histogram}
                  xLabel={metricLabel(metric)}
                  tooltipFormatter={metricFormatter(metric)}
                />
              ) : (
                <EmptyState title="No histogram data" message="" />
              )}
            </ChartCard>

            {data.groups.length > 0 ? (
              <ChartCard title={`Median ${metricLabel(metric)} by Group`}>
                <HBarChart
                  data={data.groups
                    .slice(0, 20)
                    .map((g) => ({
                      name: g.group ? g.group.replace(/_/g, " ") : "(empty)",
                      value: g.median,
                    }))}
                  tooltipFormatter={metricFormatter(metric)}
                />
              </ChartCard>
            ) : (
              <ChartCard title="Group Comparison">
                <EmptyState
                  title="No grouping selected"
                  message="Select a Group By option to see comparisons."
                />
              </ChartCard>
            )}
          </div>

          {/* Group stats table */}
          {data.groups.length > 0 && (
            <div className="mb-4">
              <ChartCard title="Statistics by Group" height="auto">
                <GroupStatsTable groups={data.groups} metric={metric} />
              </ChartCard>
            </div>
          )}

          {/* Outliers */}
          <ChartCard
            title={`Outlier Detection (IQR \u00D7 1.5)`}
            height="auto"
          >
            <div className="px-2 py-1 mb-2 text-xs text-text-muted">
              Fences: [{fmt(data.fences.lower)}, {fmt(data.fences.upper)}]
              {" \u2014 "}
              {data.outliers.length} outlier{data.outliers.length !== 1 ? "s" : ""} found
            </div>
            <OutlierTable outliers={data.outliers} metric={metric} />
          </ChartCard>
        </div>
      )}
    </ViewContainer>
  );
}
