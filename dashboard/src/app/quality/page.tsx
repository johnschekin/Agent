"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { HBarChart } from "@/components/charts/HBarChart";
import { useQualitySummary, useQualityAnomalies } from "@/lib/queries";
import { formatNumber, formatPercent } from "@/lib/formatters";
import { cn } from "@/lib/cn";
import { CHART_COLORS, SEVERITY_COLORS } from "@/lib/colors";
import type { AnomalyRecord } from "@/lib/types";

// --- Anomaly type labels ---

const ANOMALY_LABELS: Record<string, string> = {
  no_sections: "No Sections",
  no_definitions: "No Definitions",
  extreme_word_count: "Extreme Word Count",
  zero_clauses: "Zero Clauses",
};

// --- Anomaly filter tabs ---

const ANOMALY_TABS = [
  { key: "all", label: "All" },
  { key: "no_sections", label: "No Sections" },
  { key: "no_definitions", label: "No Definitions" },
  { key: "extreme_word_count", label: "Extreme Word Count" },
  { key: "zero_clauses", label: "Zero Clauses" },
];

// --- Anomaly row ---

function AnomalyRow({
  anomaly,
  onDocClick,
}: {
  anomaly: AnomalyRecord;
  onDocClick: (docId: string) => void;
}) {
  return (
    <tr
      className="border-t border-border hover:bg-surface-tertiary/50 cursor-pointer transition-colors"
      onClick={() => onDocClick(anomaly.doc_id)}
    >
      <td className="px-3 py-2">
        <button
          className="text-accent-blue hover:underline text-xs font-mono"
          onClick={(e) => {
            e.stopPropagation();
            onDocClick(anomaly.doc_id);
          }}
          title={`Open ${anomaly.doc_id} in Explorer`}
        >
          {anomaly.doc_id.slice(0, 16)}
        </button>
      </td>
      <td className="px-3 py-2 text-text-secondary text-xs truncate max-w-[180px]">
        {anomaly.borrower || "\u2014"}
      </td>
      <td className="px-3 py-2">
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-tertiary text-text-secondary border border-border">
          {ANOMALY_LABELS[anomaly.anomaly_type] ?? anomaly.anomaly_type}
        </span>
      </td>
      <td className="px-3 py-2">
        <span
          className={cn(
            "inline-block px-1.5 py-0.5 rounded text-[10px] font-medium",
            SEVERITY_COLORS[anomaly.severity] ?? SEVERITY_COLORS.low
          )}
        >
          {anomaly.severity}
        </span>
      </td>
      <td className="px-3 py-2 text-xs text-text-secondary truncate max-w-[260px]" title={anomaly.detail}>
        {anomaly.detail}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(anomaly.word_count)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(anomaly.section_count)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(anomaly.definition_count)}
      </td>
    </tr>
  );
}

// --- Main page ---

export default function QualityPage() {
  const router = useRouter();
  const [anomalyFilter, setAnomalyFilter] = useState("all");
  const [anomalyPage, setAnomalyPage] = useState(0);

  const summary = useQualitySummary();
  const anomalies = useQualityAnomalies({
    anomalyType: anomalyFilter,
    page: anomalyPage,
    pageSize: 50,
  });

  const handleDocClick = useCallback(
    (docId: string) => {
      router.push(`/explorer?selected=${encodeURIComponent(docId)}`);
    },
    [router]
  );

  const handleTabChange = useCallback((key: string) => {
    setAnomalyFilter(key);
    setAnomalyPage(0);
  }, []);

  const data = summary.data;
  const anomalyData = anomalies.data;
  const totalAnomalyPages = anomalyData
    ? Math.ceil(anomalyData.total / anomalyData.page_size)
    : 0;

  return (
    <ViewContainer title="Parsing Quality">
      {/* KPI cards — always render with placeholders to prevent layout shift */}
      <KpiCardGrid className="mb-4">
        <KpiCard
          title="Parse Success"
          value={data ? formatPercent(data.parse_success_rate) : "\u2014"}
          color="green"
        />
        <KpiCard
          title="Section Extraction"
          value={data ? formatPercent(data.section_extraction_rate) : "\u2014"}
          color="blue"
        />
        <KpiCard
          title="Clause Extraction"
          value={data ? formatPercent(data.clause_extraction_rate) : "\u2014"}
          color="blue"
        />
        <KpiCard
          title="Definition Extraction"
          value={data ? formatPercent(data.definition_extraction_rate) : "\u2014"}
          color="blue"
        />
        <KpiCard
          title="Total Anomalies"
          value={
            data
              ? formatNumber(
                  data.anomaly_counts.no_sections +
                    data.anomaly_counts.no_definitions +
                    data.anomaly_counts.extreme_word_count +
                    data.anomaly_counts.zero_clauses
                )
              : "\u2014"
          }
          color="orange"
        />
        <KpiCard
          title="Total Documents"
          value={data ? formatNumber(data.total_docs) : "\u2014"}
        />
      </KpiCardGrid>

      {summary.isLoading && !data && (
        <LoadingState message="Loading quality metrics..." />
      )}

      {summary.error && !data && (
        <EmptyState
          title="Failed to load"
          message="Quality summary query failed. Check the API server."
        />
      )}

      {data && (
        <>
          {/* Charts row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
            {/* Anomaly distribution */}
            <ChartCard title="Anomaly Distribution">
              <HBarChart
                data={[
                  {
                    name: "No Sections",
                    value: data.anomaly_counts.no_sections,
                  },
                  {
                    name: "No Definitions",
                    value: data.anomaly_counts.no_definitions,
                  },
                  {
                    name: "Extreme Word Count",
                    value: data.anomaly_counts.extreme_word_count,
                  },
                  {
                    name: "Zero Clauses",
                    value: data.anomaly_counts.zero_clauses,
                  },
                ]}
                color={CHART_COLORS.orange}
              />
            </ChartCard>

            {/* Parse rates by doc type */}
            <ChartCard title="Section Extraction Rate by Doc Type">
              {data.by_doc_type.length > 0 ? (
                <HBarChart
                  data={data.by_doc_type.map((dt) => ({
                    name:
                      dt.doc_type.length > 20
                        ? dt.doc_type.slice(0, 20) + "\u2026"
                        : dt.doc_type,
                    fullName: `${dt.doc_type} (${dt.total} docs)`,
                    value: dt.section_rate,
                  }))}
                  color={CHART_COLORS.green}
                  tooltipFormatter={(v) => `${v.toFixed(1)}%`}
                />
              ) : (
                <EmptyState title="No data" message="" />
              )}
            </ChartCard>
          </div>

          {/* Anomaly table with filter tabs */}
          <ChartCard title="Anomalous Documents" height="auto">
            {/* Filter tabs */}
            <div className="flex flex-wrap gap-1.5 mb-3">
              {ANOMALY_TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => handleTabChange(tab.key)}
                  className={cn(
                    "px-2.5 py-1 rounded-sm text-xs font-medium transition-colors",
                    anomalyFilter === tab.key
                      ? "bg-accent-blue/20 text-accent-blue"
                      : "bg-surface-tertiary text-text-muted hover:text-text-secondary border border-border"
                  )}
                >
                  {tab.label}
                  {data && tab.key in data.anomaly_counts && (
                    <span className="ml-1 text-[10px] opacity-70">
                      {data.anomaly_counts[
                        tab.key as keyof typeof data.anomaly_counts
                      ]}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Stale indicator */}
            {anomalies.isPlaceholderData && (
              <div className="text-xs text-text-muted mb-2 animate-pulse">
                Updating&hellip;
              </div>
            )}

            {/* Loading / error / empty / table */}
            {anomalies.isLoading && !anomalyData ? (
              <LoadingState message="Loading anomalies..." />
            ) : anomalies.error && !anomalyData ? (
              <EmptyState
                title="Failed to load"
                message="Anomaly query failed."
              />
            ) : anomalyData && anomalyData.anomalies.length === 0 ? (
              <EmptyState
                title="No anomalies"
                message={
                  anomalyFilter === "all"
                    ? "No parsing anomalies detected in the corpus."
                    : `No documents with "${ANOMALY_LABELS[anomalyFilter] ?? anomalyFilter}" anomaly.`
                }
              />
            ) : anomalyData ? (
              <div
                className={cn(
                  anomalies.isPlaceholderData &&
                    "opacity-60 transition-opacity"
                )}
              >
                <div className="overflow-auto max-h-[500px]">
                  <table
                    className="w-full text-sm"
                    aria-label="Anomalous documents"
                  >
                    <thead className="sticky top-0 bg-surface-tertiary z-10">
                      <tr className="text-left text-xs text-text-muted uppercase">
                        <th className="px-3 py-2">Doc ID</th>
                        <th className="px-3 py-2">Borrower</th>
                        <th className="px-3 py-2">Anomaly</th>
                        <th className="px-3 py-2">Severity</th>
                        <th className="px-3 py-2">Detail</th>
                        <th className="px-3 py-2 text-right">Words</th>
                        <th className="px-3 py-2 text-right">Sections</th>
                        <th className="px-3 py-2 text-right">Definitions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {anomalyData.anomalies.map((a, i) => (
                        <AnomalyRow
                          key={`${a.doc_id}_${a.anomaly_type}_${i}`}
                          anomaly={a}
                          onDocClick={handleDocClick}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                {totalAnomalyPages > 1 && (
                  <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
                    <span className="text-xs text-text-muted">
                      {formatNumber(anomalyData.total)} anomalies total
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() =>
                          setAnomalyPage((p) => Math.max(0, p - 1))
                        }
                        disabled={anomalyPage === 0}
                        className="px-2 py-1 text-xs rounded-sm bg-surface-tertiary text-text-secondary hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed border border-border"
                      >
                        Previous
                      </button>
                      <span className="text-xs text-text-muted tabular-nums">
                        Page {anomalyPage + 1} of {totalAnomalyPages}
                      </span>
                      <button
                        onClick={() =>
                          setAnomalyPage((p) =>
                            Math.min(totalAnomalyPages - 1, p + 1)
                          )
                        }
                        disabled={anomalyPage >= totalAnomalyPages - 1}
                        className="px-2 py-1 text-xs rounded-sm bg-surface-tertiary text-text-secondary hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed border border-border"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </ChartCard>
        </>
      )}
    </ViewContainer>
  );
}
