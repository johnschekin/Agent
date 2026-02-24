"use client";

import { useState, useCallback } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { HBarChart } from "@/components/charts/HBarChart";
import { useCoverage } from "@/lib/queries";
import { formatNumber, formatPercent, validateRegexPatterns, formatApiError } from "@/lib/formatters";
import { cn, SELECT_CLASS } from "@/lib/cn";
import { CHART_COLORS } from "@/lib/colors";
import type { CoverageGroup } from "@/lib/types";

// --- Coverage row ---

function CoverageRow({ item }: { item: CoverageGroup }) {
  const color =
    item.hit_rate >= 80
      ? "bg-accent-green/20 text-accent-green"
      : item.hit_rate >= 50
        ? "bg-accent-orange/20 text-accent-orange"
        : "bg-accent-red/20 text-accent-red";
  return (
    <tr className="border-t border-border hover:bg-surface-tertiary/50 transition-colors">
      <td className="px-3 py-2 text-xs">{item.group}</td>
      <td className="px-3 py-2">
        <span className={cn("inline-block px-1.5 py-0.5 rounded text-[10px] font-medium", color)}>
          {formatPercent(item.hit_rate)}
        </span>
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.hits)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.total)}
      </td>
      <td className="px-3 py-2">
        <div className="w-20 h-1.5 bg-surface-tertiary rounded-full overflow-hidden">
          <div
            className="h-full rounded-full"
            style={{
              width: `${Math.min(100, item.hit_rate)}%`,
              backgroundColor:
                item.hit_rate >= 80 ? "#27AE60" : item.hit_rate >= 50 ? "#D9822B" : "#DB3737",
            }}
          />
        </div>
      </td>
    </tr>
  );
}

const GROUP_BY_OPTIONS = [
  { value: "doc_type", label: "Doc Type" },
  { value: "market_segment", label: "Market Segment" },
  { value: "template_family", label: "Template Family" },
  { value: "admin_agent", label: "Admin Agent" },
];

// --- Main page ---

export default function CoveragePage() {
  const [headingInput, setHeadingInput] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [groupBy, setGroupBy] = useState("doc_type");
  const [sampleSize, setSampleSize] = useState(0);
  const [cohortOnly, setCohortOnly] = useState(true);
  const [regexError, setRegexError] = useState<string | null>(null);

  const mutation = useCoverage();

  const handleRun = useCallback(() => {
    const headingPatterns = headingInput
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (headingPatterns.length === 0) return;

    const keywordPatterns = keywordInput
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);

    // H3+M2 RT2 FIX: Client-side regex validation
    const err = validateRegexPatterns([...headingPatterns, ...keywordPatterns]);
    if (err) { setRegexError(err); return; }
    setRegexError(null);

    mutation.mutate({
      headingPatterns,
      keywordPatterns: keywordPatterns.length > 0 ? keywordPatterns : undefined,
      groupBy,
      sampleSize,
      cohortOnly,
    });
  }, [mutation, headingInput, keywordInput, groupBy, sampleSize, cohortOnly]);

  const data = mutation.data;

  // Chart data: groups sorted by hit rate
  const chartData = data
    ? data.groups
        .filter((g) => g.total >= 2)
        .slice(0, 20)
        .map((g) => ({
          name: g.group.length > 20 ? g.group.slice(0, 20) + "\u2026" : g.group,
          fullName: `${g.group} (${g.total} docs)`,
          value: g.hit_rate,
        }))
    : [];

  return (
    <ViewContainer title="Coverage Analysis">
      {/* Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        {/* Heading patterns */}
        <div>
          <label className="text-xs text-text-muted uppercase tracking-wider block mb-1">
            Heading Patterns (one per line)
          </label>
          <textarea
            value={headingInput}
            onChange={(e) => setHeadingInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !mutation.isPending && headingInput.trim()) handleRun(); }}
            placeholder={"indebtedness\nlimitation on.*debt"}
            rows={3}
            className={cn(SELECT_CLASS, "w-full resize-y font-mono text-xs")}
            aria-label="Heading patterns"
          />
        </div>

        {/* Keyword patterns */}
        <div>
          <label className="text-xs text-text-muted uppercase tracking-wider block mb-1">
            Keyword Patterns (optional)
          </label>
          <textarea
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            placeholder="permitted indebtedness"
            rows={3}
            className={cn(SELECT_CLASS, "w-full resize-y font-mono text-xs")}
            aria-label="Keyword patterns"
          />
        </div>

        {/* Settings */}
        <div className="space-y-3">
          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            Group By
            <select
              className={SELECT_CLASS}
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value)}
              aria-label="Group by dimension"
            >
              {GROUP_BY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            Sample Size
            <select
              className={SELECT_CLASS}
              value={sampleSize}
              onChange={(e) => setSampleSize(Number(e.target.value))}
              aria-label="Sample size"
            >
              <option value={0}>All</option>
              <option value={500}>500</option>
              <option value={1000}>1,000</option>
              <option value={5000}>5,000</option>
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

          <button
            onClick={handleRun}
            disabled={mutation.isPending || !headingInput.trim()}
            className="px-4 py-1.5 text-xs font-medium rounded-sm bg-accent-blue text-white hover:bg-accent-blue/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors w-full"
          >
            {mutation.isPending ? "Analyzing\u2026" : "Run Coverage"}
          </button>
        </div>
      </div>

      {/* KPIs */}
      <KpiCardGrid className="mb-4">
        <KpiCard
          title="Overall Hit Rate"
          value={data ? formatPercent(data.overall_hit_rate) : "\u2014"}
          color={data && data.overall_hit_rate >= 80 ? "green" : data && data.overall_hit_rate >= 50 ? "orange" : "red"}
        />
        <KpiCard
          title="Total Hits"
          value={data ? formatNumber(data.total_hits) : "\u2014"}
          color="green"
        />
        <KpiCard
          title="Total Docs"
          value={data ? formatNumber(data.total_docs) : "\u2014"}
        />
        <KpiCard
          title="Groups"
          value={data ? formatNumber(data.groups.length) : "\u2014"}
        />
      </KpiCardGrid>

      {/* Loading / Error */}
      {mutation.isPending && <LoadingState message="Running coverage analysis..." />}
      {/* H3 RT2 FIX: Show actual error message from API */}
      {regexError && (
        <EmptyState title="Invalid pattern" message={regexError} />
      )}
      {mutation.error && !regexError && (
        <EmptyState title="Analysis failed" message={formatApiError(mutation.error)} />
      )}

      {/* Results */}
      {data && (
        <>
          {/* Chart */}
          {chartData.length > 0 && (
            <div className="mb-4">
              <ChartCard title={`Hit Rate by ${GROUP_BY_OPTIONS.find((o) => o.value === groupBy)?.label ?? groupBy}`}>
                <HBarChart
                  data={chartData}
                  color={CHART_COLORS.green}
                  tooltipFormatter={(v) => `${v.toFixed(1)}%`}
                />
              </ChartCard>
            </div>
          )}

          {/* Table */}
          <ChartCard title="" height="auto">
            {data.groups.length === 0 ? (
              <EmptyState title="No groups" message="No documents found for the given patterns." />
            ) : (
              <div className="overflow-auto max-h-[500px]">
                <table className="w-full text-sm" aria-label="Coverage by group">
                  <thead className="sticky top-0 bg-surface-tertiary z-10">
                    <tr className="text-left text-xs text-text-muted uppercase">
                      <th className="px-3 py-2">Group</th>
                      <th className="px-3 py-2">Hit Rate</th>
                      <th className="px-3 py-2 text-right">Hits</th>
                      <th className="px-3 py-2 text-right">Total</th>
                      <th className="px-3 py-2">Coverage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.groups.map((g, i) => (
                      <CoverageRow key={`${g.group}_${i}`} item={g} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </ChartCard>
        </>
      )}

      {/* Initial empty state */}
      {!data && !mutation.isPending && !mutation.error && (
        <EmptyState
          title="Analyze pattern coverage"
          message="Enter heading patterns and select a grouping dimension to see how well your patterns cover different segments of the corpus."
        />
      )}
    </ViewContainer>
  );
}
