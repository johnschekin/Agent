"use client";

import { useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useEdgeCases } from "@/lib/queries";
import { formatNumber, formatCurrencyMM } from "@/lib/formatters";
import { cn } from "@/lib/cn";
import { SEVERITY_COLORS } from "@/lib/colors";
import type { EdgeCaseRecord } from "@/lib/types";

// --- Category labels ---

const CATEGORY_LABELS: Record<string, string> = {
  missing_sections: "Missing Sections",
  low_definitions: "Low Definitions",
  extreme_word_count: "Extreme Word Count",
  zero_clauses: "Zero Clauses",
  extreme_facility: "Extreme Facility Size",
};

// --- Edge case row ---

function EdgeCaseRow({
  item,
  onDocClick,
}: {
  item: EdgeCaseRecord;
  onDocClick: (docId: string) => void;
}) {
  return (
    <tr
      className="border-t border-border hover:bg-surface-tertiary/50 cursor-pointer transition-colors"
      onClick={() => onDocClick(item.doc_id)}
    >
      <td className="px-3 py-2">
        <button
          className="text-accent-blue hover:underline text-xs font-mono"
          onClick={(e) => {
            e.stopPropagation();
            onDocClick(item.doc_id);
          }}
          title={`Open ${item.doc_id} in Explorer`}
        >
          {item.doc_id.slice(0, 16)}
        </button>
      </td>
      <td className="px-3 py-2 text-text-secondary text-xs truncate max-w-[160px]">
        {item.borrower || "\u2014"}
      </td>
      <td className="px-3 py-2">
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-tertiary text-text-secondary border border-border">
          {CATEGORY_LABELS[item.category] ?? item.category}
        </span>
      </td>
      <td className="px-3 py-2">
        <span
          className={cn(
            "inline-block px-1.5 py-0.5 rounded text-[10px] font-medium",
            SEVERITY_COLORS[item.severity] ?? SEVERITY_COLORS.low
          )}
        >
          {item.severity}
        </span>
      </td>
      <td className="px-3 py-2 text-xs text-text-secondary">
        {item.doc_type}
      </td>
      <td className="px-3 py-2 text-xs text-text-secondary">
        {item.market_segment}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.word_count)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.section_count)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.definition_count)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {item.facility_size_mm != null ? formatCurrencyMM(item.facility_size_mm) : "\u2014"}
      </td>
    </tr>
  );
}

// --- Main page ---

export default function EdgeCasesPage() {
  const router = useRouter();
  const [category, setCategory] = useState("all");
  const [cohortOnly, setCohortOnly] = useState(true);
  const [page, setPage] = useState(0);

  const edgeCases = useEdgeCases({
    category,
    page,
    pageSize: 50,
    cohortOnly,
  });

  const handleDocClick = useCallback(
    (docId: string) => {
      router.push(`/explorer?selected=${encodeURIComponent(docId)}`);
    },
    [router]
  );

  const handleCategoryChange = useCallback((key: string) => {
    setCategory(key);
    setPage(0);
  }, []);

  const data = edgeCases.data;
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;

  // Global total from category sums (not data.total which is filtered)
  const globalTotal = useMemo(() => {
    if (!data) return 0;
    return data.categories.reduce((sum, c) => sum + c.count, 0);
  }, [data]);

  // Build category pill data from API response (categories are always global counts)
  const categoryPills = useMemo(() => {
    if (!data) return [];
    const countMap = new Map<string, number>();
    for (const c of data.categories) {
      countMap.set(c.category, c.count);
    }
    return [
      { key: "all", label: "All", count: globalTotal },
      ...Object.entries(CATEGORY_LABELS).map(([key, label]) => ({
        key,
        label,
        count: countMap.get(key) ?? 0,
      })),
    ];
  }, [data, globalTotal]);

  return (
    <ViewContainer title="Edge Case Inspector">
      {/* Controls */}
      <div className="flex items-center gap-3 mb-4">
        <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={cohortOnly}
            onChange={(e) => {
              setCohortOnly(e.target.checked);
              setPage(0);
            }}
            className="accent-accent-blue"
          />
          Cohort Only
        </label>
      </div>

      {/* KPI cards — show counts per category when data is loaded */}
      <KpiCardGrid className="mb-4">
        <KpiCard
          title="Total Edge Cases"
          value={data ? formatNumber(globalTotal) : "\u2014"}
          color="orange"
        />
        <KpiCard
          title="Missing Sections"
          value={
            data
              ? formatNumber(
                  data.categories.find((c) => c.category === "missing_sections")
                    ?.count ?? 0
                )
              : "\u2014"
          }
          color="red"
        />
        <KpiCard
          title="Low Definitions"
          value={
            data
              ? formatNumber(
                  data.categories.find(
                    (c) => c.category === "low_definitions"
                  )?.count ?? 0
                )
              : "\u2014"
          }
          color="orange"
        />
        <KpiCard
          title="Zero Clauses"
          value={
            data
              ? formatNumber(
                  data.categories.find((c) => c.category === "zero_clauses")
                    ?.count ?? 0
                )
              : "\u2014"
          }
          color="orange"
        />
        <KpiCard
          title="Extreme Word Count"
          value={
            data
              ? formatNumber(
                  data.categories.find(
                    (c) => c.category === "extreme_word_count"
                  )?.count ?? 0
                )
              : "\u2014"
          }
        />
        <KpiCard
          title="Extreme Facility"
          value={
            data
              ? formatNumber(
                  data.categories.find(
                    (c) => c.category === "extreme_facility"
                  )?.count ?? 0
                )
              : "\u2014"
          }
        />
      </KpiCardGrid>

      {edgeCases.isLoading && !data && (
        <LoadingState message="Detecting edge cases..." />
      )}

      {edgeCases.error && !data && (
        <EmptyState
          title="Failed to load"
          message="Edge case detection query failed. Check the API server."
        />
      )}

      {data && (
        <ChartCard title="" height="auto">
          {/* Category filter pills */}
          <div className="flex flex-wrap gap-1.5 mb-3">
            {categoryPills.map((pill) => (
              <button
                key={pill.key}
                onClick={() => handleCategoryChange(pill.key)}
                className={cn(
                  "px-2.5 py-1 rounded-sm text-xs font-medium transition-colors",
                  category === pill.key
                    ? "bg-accent-blue/20 text-accent-blue"
                    : "bg-surface-tertiary text-text-muted hover:text-text-secondary border border-border"
                )}
              >
                {pill.label}
                <span className="ml-1 text-[10px] opacity-70">
                  {pill.count}
                </span>
              </button>
            ))}
          </div>

          {/* Stale indicator */}
          {edgeCases.isPlaceholderData && (
            <div className="text-xs text-text-muted mb-2 animate-pulse">
              Updating&hellip;
            </div>
          )}

          {/* Table */}
          {data.cases.length === 0 ? (
            <EmptyState
              title="No edge cases"
              message={
                category === "all"
                  ? "No edge cases detected in the corpus."
                  : `No documents with "${CATEGORY_LABELS[category] ?? category}" issues.`
              }
            />
          ) : (
            <div
              className={cn(
                edgeCases.isPlaceholderData && "opacity-60 transition-opacity"
              )}
            >
              <div className="overflow-auto max-h-[500px]">
                <table
                  className="w-full text-sm"
                  aria-label="Edge case documents"
                >
                  <thead className="sticky top-0 bg-surface-tertiary z-10">
                    <tr className="text-left text-xs text-text-muted uppercase">
                      <th className="px-3 py-2">Doc ID</th>
                      <th className="px-3 py-2">Borrower</th>
                      <th className="px-3 py-2">Category</th>
                      <th className="px-3 py-2">Severity</th>
                      <th className="px-3 py-2">Doc Type</th>
                      <th className="px-3 py-2">Segment</th>
                      <th className="px-3 py-2 text-right">Words</th>
                      <th className="px-3 py-2 text-right">Sections</th>
                      <th className="px-3 py-2 text-right">Definitions</th>
                      <th className="px-3 py-2 text-right">Facility</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.cases.map((c, i) => (
                      <EdgeCaseRow
                        key={`${c.doc_id}_${c.category}_${i}`}
                        item={c}
                        onDocClick={handleDocClick}
                      />
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
                  <span className="text-xs text-text-muted">
                    {formatNumber(data.total)} edge cases total
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage((p) => Math.max(0, p - 1))}
                      disabled={page === 0}
                      className="px-2 py-1 text-xs rounded-sm bg-surface-tertiary text-text-secondary hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed border border-border"
                    >
                      Previous
                    </button>
                    <span className="text-xs text-text-muted tabular-nums">
                      Page {page + 1} of {totalPages}
                    </span>
                    <button
                      onClick={() =>
                        setPage((p) => Math.min(totalPages - 1, p + 1))
                      }
                      disabled={page >= totalPages - 1}
                      className="px-2 py-1 text-xs rounded-sm bg-surface-tertiary text-text-secondary hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed border border-border"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </ChartCard>
      )}
    </ViewContainer>
  );
}
