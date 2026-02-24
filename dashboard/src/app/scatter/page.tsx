"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ScatterPlot } from "@/components/charts/ScatterChart";
import { HistogramChart } from "@/components/charts/HistogramChart";
import { useScatter, useDistribution } from "@/lib/queries";
import { formatNumber, formatCompact } from "@/lib/formatters";
import {
  METRICS,
  COLOR_OPTIONS,
  CATEGORICAL_COLORS,
  metricLabel,
  metricFormatter,
} from "@/lib/metrics";
import { cn } from "@/lib/cn";
import type { ScatterPoint } from "@/lib/types";

/** Get the display-formatted KPI value, respecting metric type. */
function formatKpiValue(metric: string, value: number): string {
  const fmt = metricFormatter(metric);
  return fmt ? fmt(value) : formatCompact(value);
}

export default function ScatterPage() {
  const router = useRouter();
  const [xMetric, setXMetric] = useState("definition_count");
  const [yMetric, setYMetric] = useState("word_count");
  const [colorMetric, setColorMetric] = useState("");
  const [cohortOnly, setCohortOnly] = useState(true);
  const [logX, setLogX] = useState(false);
  const [logY, setLogY] = useState(false);

  const scatter = useScatter({
    x: xMetric,
    y: yMetric,
    color: colorMetric || undefined,
    cohortOnly,
    limit: 5000,
  });

  // Linked histograms
  const xDist = useDistribution(xMetric, 30, cohortOnly);
  const yDist = useDistribution(yMetric, 30, cohortOnly);

  const handlePointClick = useCallback(
    (point: ScatterPoint) => {
      router.push(`/explorer?selected=${encodeURIComponent(point.doc_id)}`);
    },
    [router]
  );

  const selectClass =
    "bg-surface-tertiary border border-border rounded-sm px-2 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-blue";

  return (
    <ViewContainer title="Scatter Analysis">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          X Axis
          <select
            aria-label="X axis metric"
            className={selectClass}
            value={xMetric}
            onChange={(e) => setXMetric(e.target.value)}
          >
            {METRICS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          Y Axis
          <select
            aria-label="Y axis metric"
            className={selectClass}
            value={yMetric}
            onChange={(e) => setYMetric(e.target.value)}
          >
            {METRICS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          Color
          <select
            aria-label="Color dimension"
            className={selectClass}
            value={colorMetric}
            onChange={(e) => setColorMetric(e.target.value)}
          >
            {COLOR_OPTIONS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <div className="flex items-center gap-3 ml-2">
          <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={logX}
              onChange={(e) => setLogX(e.target.checked)}
              className="accent-accent-blue"
            />
            Log X
          </label>
          <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={logY}
              onChange={(e) => setLogY(e.target.checked)}
              className="accent-accent-blue"
            />
            Log Y
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
      </div>

      {/* M13: Stale data indicator */}
      {scatter.isPlaceholderData && (
        <div className="text-xs text-text-muted mb-2 animate-pulse">
          Updating\u2026
        </div>
      )}

      {/* M12: Always render KPI grid to prevent layout shift */}
      <KpiCardGrid className="mb-4">
        <KpiCard
          title="Points"
          value={scatter.data ? formatNumber(scatter.data.total_points) : "\u2014"}
        />
        <KpiCard
          title={`${metricLabel(xMetric)} Mean`}
          value={scatter.data ? formatKpiValue(xMetric, scatter.data.x_stats.mean) : "\u2014"}
        />
        <KpiCard
          title={`${metricLabel(yMetric)} Mean`}
          value={scatter.data ? formatKpiValue(yMetric, scatter.data.y_stats.mean) : "\u2014"}
        />
        <KpiCard
          title={`${metricLabel(xMetric)} Median`}
          value={scatter.data ? formatKpiValue(xMetric, scatter.data.x_stats.median) : "\u2014"}
        />
      </KpiCardGrid>

      {/* Main scatter chart */}
      <div className={cn(scatter.isPlaceholderData && "opacity-60 transition-opacity")}>
        <ChartCard title="Scatter Plot" height="500px">
          {scatter.error ? (
            <EmptyState title="Failed to load" message="Scatter query failed" />
          ) : scatter.isLoading && !scatter.data ? (
            <LoadingState />
          ) : scatter.data ? (
            <ScatterPlot
              data={scatter.data.points}
              xName={metricLabel(xMetric)}
              yName={metricLabel(yMetric)}
              colorLabel={colorMetric ? metricLabel(colorMetric) : undefined}
              colorCategorical={CATEGORICAL_COLORS.has(colorMetric)}
              logScaleX={logX}
              logScaleY={logY}
              xFormatter={metricFormatter(xMetric)}
              yFormatter={metricFormatter(yMetric)}
              onPointClick={handlePointClick}
            />
          ) : null}
        </ChartCard>
      </div>

      {/* Linked distributions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
        <ChartCard title={`${metricLabel(xMetric)} Distribution`}>
          {xDist.data?.histogram ? (
            <HistogramChart
              data={xDist.data.histogram}
              xLabel={metricLabel(xMetric)}
              tooltipFormatter={metricFormatter(xMetric)}
            />
          ) : xDist.error ? (
            <EmptyState title="Failed to load" message="" />
          ) : (
            <LoadingState />
          )}
        </ChartCard>
        <ChartCard title={`${metricLabel(yMetric)} Distribution`}>
          {yDist.data?.histogram ? (
            <HistogramChart
              data={yDist.data.histogram}
              xLabel={metricLabel(yMetric)}
              color="#27AE60"
              tooltipFormatter={metricFormatter(yMetric)}
            />
          ) : yDist.error ? (
            <EmptyState title="Failed to load" message="" />
          ) : (
            <LoadingState />
          )}
        </ChartCard>
      </div>
    </ViewContainer>
  );
}
