"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { HBarChart } from "@/components/charts/HBarChart";
import { useHeadingDiscovery } from "@/lib/queries";
import { formatNumber, validateRegexPatterns, formatApiError } from "@/lib/formatters";
import { cn, SELECT_CLASS } from "@/lib/cn";
import { CHART_COLORS } from "@/lib/colors";
import type { HeadingDiscoveryResult } from "@/lib/types";

// --- Heading row ---

function HeadingRow({
  item,
  onSearch,
}: {
  item: HeadingDiscoveryResult;
  onSearch: (heading: string) => void;
}) {
  return (
    <tr className="border-t border-border hover:bg-surface-3/50 transition-colors">
      <td className="px-3 py-2">
        <button
          className="text-accent-blue hover:underline text-xs text-left"
          onClick={() => onSearch(item.heading)}
          title={`Search corpus for "${item.heading}"`}
        >
          {item.heading || "\u2014"}
        </button>
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.frequency)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.doc_count)}
      </td>
      <td className="px-3 py-2 text-xs text-text-secondary">
        {item.article_nums.slice(0, 5).join(", ")}
        {item.article_nums.length > 5 && "\u2026"}
      </td>
      <td className="px-3 py-2 text-xs text-text-muted font-mono">
        {item.example_doc_ids.slice(0, 2).map((id) => id.slice(0, 10)).join(", ")}
      </td>
    </tr>
  );
}

// --- Main page ---

export default function HeadingsPage() {
  const router = useRouter();
  const [searchPattern, setSearchPattern] = useState("");
  const [articleMin, setArticleMin] = useState("");
  const [articleMax, setArticleMax] = useState("");
  const [minFrequency, setMinFrequency] = useState(2);
  const [cohortOnly, setCohortOnly] = useState(true);
  const [regexError, setRegexError] = useState<string | null>(null);

  const mutation = useHeadingDiscovery();

  const handleRun = useCallback(() => {
    // H3+M2 RT2 FIX: Client-side regex validation
    if (searchPattern) {
      const err = validateRegexPatterns([searchPattern]);
      if (err) { setRegexError(err); return; }
    }
    setRegexError(null);

    mutation.mutate({
      searchPattern: searchPattern || undefined,
      articleMin: articleMin ? parseInt(articleMin) : undefined,
      articleMax: articleMax ? parseInt(articleMax) : undefined,
      minFrequency,
      limit: 200,
      cohortOnly,
    });
  }, [mutation, searchPattern, articleMin, articleMax, minFrequency, cohortOnly]);

  const handleSearch = useCallback(
    (heading: string) => {
      router.push(`/search?q=${encodeURIComponent(heading)}`);
    },
    [router]
  );

  const data = mutation.data;

  // Top 20 headings for chart
  const chartData = data
    ? data.headings.slice(0, 20).map((h) => ({
        name: h.heading.length > 25 ? h.heading.slice(0, 25) + "\u2026" : h.heading,
        fullName: `${h.heading} (${h.doc_count} docs)`,
        value: h.frequency,
      }))
    : [];

  return (
    <ViewContainer title="Heading Discovery">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex-1 min-w-[250px]">
          <input
            type="text"
            placeholder="Heading pattern (regex)..."
            value={searchPattern}
            onChange={(e) => setSearchPattern(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !mutation.isPending) handleRun(); }}
            className={cn(SELECT_CLASS, "w-full")}
            aria-label="Heading search pattern"
          />
        </div>

        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          Article
          <input
            type="number"
            placeholder="Min"
            value={articleMin}
            onChange={(e) => setArticleMin(e.target.value)}
            className={cn(SELECT_CLASS, "w-16 text-center")}
            aria-label="Minimum article number"
            min={1}
          />
          <span className="text-text-muted">{"\u2013"}</span>
          <input
            type="number"
            placeholder="Max"
            value={articleMax}
            onChange={(e) => setArticleMax(e.target.value)}
            className={cn(SELECT_CLASS, "w-16 text-center")}
            aria-label="Maximum article number"
            min={1}
          />
        </label>

        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          Min Freq
          <select
            className={SELECT_CLASS}
            value={minFrequency}
            onChange={(e) => setMinFrequency(Number(e.target.value))}
            aria-label="Minimum frequency"
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={5}>5</option>
            <option value={10}>10</option>
            <option value={25}>25</option>
            <option value={50}>50</option>
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
          disabled={mutation.isPending}
          className="px-4 py-1.5 text-xs font-medium rounded-sm bg-accent-blue text-white hover:bg-accent-blue/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {mutation.isPending ? "Discovering\u2026" : "Discover"}
        </button>
      </div>

      {/* KPIs */}
      <KpiCardGrid className="mb-4">
        <KpiCard
          title="Unique Headings"
          value={data ? formatNumber(data.total_headings) : "\u2014"}
          color="blue"
        />
        <KpiCard
          title="Sections Scanned"
          value={data ? formatNumber(data.total_sections_scanned) : "\u2014"}
        />
      </KpiCardGrid>

      {/* Loading / Error */}
      {mutation.isPending && <LoadingState message="Scanning headings..." />}
      {/* H3 RT2 FIX: Show actual error message from API */}
      {regexError && (
        <EmptyState title="Invalid pattern" message={regexError} />
      )}
      {mutation.error && !regexError && (
        <EmptyState title="Discovery failed" message={formatApiError(mutation.error)} />
      )}

      {/* Results */}
      {data && (
        <>
          {/* Chart */}
          {chartData.length > 0 && (
            <div className="mb-4">
              <ChartCard title="Top 20 Headings by Frequency">
                <HBarChart
                  data={chartData}
                  color={CHART_COLORS.blue}
                  tooltipFormatter={(v) => `${v} occurrences`}
                />
              </ChartCard>
            </div>
          )}

          {/* Table */}
          <ChartCard title="" height="auto">
            {data.headings.length === 0 ? (
              <EmptyState
                title="No headings found"
                message="Try adjusting the search pattern or lowering the minimum frequency."
              />
            ) : (
              <div className="overflow-auto max-h-[500px]">
                <table className="w-full text-sm" aria-label="Discovered headings">
                  <thead className="sticky top-0 bg-surface-3 z-10">
                    <tr className="text-left text-xs text-text-muted uppercase">
                      <th className="px-3 py-2">Heading</th>
                      <th className="px-3 py-2 text-right">Frequency</th>
                      <th className="px-3 py-2 text-right">Documents</th>
                      <th className="px-3 py-2">Articles</th>
                      <th className="px-3 py-2">Example Docs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.headings.map((h, i) => (
                      <HeadingRow
                        key={`${h.heading}_${i}`}
                        item={h}
                        onSearch={handleSearch}
                      />
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
          title="Discover heading variants"
          message="Enter an optional regex pattern and click Discover to find all unique section headings across the corpus."
        />
      )}
    </ViewContainer>
  );
}
