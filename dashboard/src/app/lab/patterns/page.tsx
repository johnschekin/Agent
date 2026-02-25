"use client";

import { useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { HBarChart } from "@/components/charts/HBarChart";
import { usePatternTest } from "@/lib/queries";
import { formatNumber, formatPercent, validateRegexPatterns, formatApiError } from "@/lib/formatters";
import { cn, SELECT_CLASS } from "@/lib/cn";
import { CHART_COLORS } from "@/lib/colors";
import type { PatternMatch, PatternMiss } from "@/lib/types";

// --- Match row ---

function MatchRow({
  item,
  onDocClick,
}: {
  item: PatternMatch;
  onDocClick: (docId: string) => void;
}) {
  return (
    <tr
      className="border-t border-border hover:bg-surface-3/50 cursor-pointer transition-colors"
      onClick={() => onDocClick(item.doc_id)}
    >
      <td className="px-3 py-2">
        <button
          className="text-accent-blue hover:underline text-xs font-mono"
          onClick={(e) => {
            e.stopPropagation();
            onDocClick(item.doc_id);
          }}
        >
          {item.doc_id.slice(0, 16)}
        </button>
      </td>
      <td className="px-3 py-2 text-text-secondary text-xs truncate max-w-[160px]">
        {item.borrower || "\u2014"}
      </td>
      <td className="px-3 py-2 text-xs font-mono">{item.section_number}</td>
      <td className="px-3 py-2 text-xs truncate max-w-[200px]" title={item.heading}>
        {item.heading}
      </td>
      <td className="px-3 py-2">
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent-green/20 text-accent-green">
          {item.match_method}
        </span>
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {item.score.toFixed(2)}
      </td>
    </tr>
  );
}

// --- Miss row ---

function MissRow({
  item,
  onDocClick,
}: {
  item: PatternMiss;
  onDocClick: (docId: string) => void;
}) {
  return (
    <tr
      className="border-t border-border hover:bg-surface-3/50 cursor-pointer transition-colors"
      onClick={() => onDocClick(item.doc_id)}
    >
      <td className="px-3 py-2">
        <button
          className="text-accent-blue hover:underline text-xs font-mono"
          onClick={(e) => {
            e.stopPropagation();
            onDocClick(item.doc_id);
          }}
        >
          {item.doc_id.slice(0, 16)}
        </button>
      </td>
      <td className="px-3 py-2 text-text-secondary text-xs truncate max-w-[160px]">
        {item.borrower || "\u2014"}
      </td>
      <td className="px-3 py-2 text-xs font-mono">{item.best_section || "\u2014"}</td>
      <td className="px-3 py-2 text-xs truncate max-w-[200px]" title={item.best_heading}>
        {item.best_heading || "\u2014"}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs text-text-muted">
        {item.best_score.toFixed(2)}
      </td>
    </tr>
  );
}

// --- Main page ---

export default function PatternsPage() {
  const router = useRouter();
  const [headingInput, setHeadingInput] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [sectionFilter, setSectionFilter] = useState("");
  const [sampleSize, setSampleSize] = useState(500);
  const [cohortOnly, setCohortOnly] = useState(true);
  const [activeTab, setActiveTab] = useState<"matches" | "misses">("matches");
  const [regexError, setRegexError] = useState<string | null>(null);

  const mutation = usePatternTest();

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
      sectionFilter: sectionFilter || undefined,
      sampleSize,
      cohortOnly,
    });
  }, [mutation, headingInput, keywordInput, sectionFilter, sampleSize, cohortOnly]);

  const handleDocClick = useCallback(
    (docId: string) => {
      router.push(`/explorer?selected=${encodeURIComponent(docId)}`);
    },
    [router]
  );

  const data = mutation.data;

  // L3 RT2 FIX: Memoize article chart data
  const articleChartData = useMemo(() => {
    if (!data) return [];
    return data.by_article
      .filter((a) => a.n >= 2)
      .slice(0, 15)
      .map((a) => ({
        name: `Art. ${a.article_num ?? "?"}`,
        fullName: `Article ${a.article_num ?? "?"} (${a.n} docs)`,
        value: a.hit_rate,
      }));
  }, [data]);

  return (
    <ViewContainer title="Pattern Testing Lab">
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
            placeholder={"indebtedness\nlimitation on.*debt\npermitted.*indebtedness"}
            rows={4}
            className={cn(SELECT_CLASS, "w-full resize-y font-mono text-xs")}
            aria-label="Heading patterns"
          />
        </div>

        {/* Keyword patterns */}
        <div>
          <label className="text-xs text-text-muted uppercase tracking-wider block mb-1">
            Keyword Patterns (optional, one per line)
          </label>
          <textarea
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            placeholder={"permitted indebtedness\ndebt basket\ngeneral basket"}
            rows={4}
            className={cn(SELECT_CLASS, "w-full resize-y font-mono text-xs")}
            aria-label="Keyword patterns"
          />
        </div>

        {/* Settings */}
        <div className="space-y-3">
          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            Section Filter
            <input
              type="text"
              placeholder="e.g. 7.01"
              value={sectionFilter}
              onChange={(e) => setSectionFilter(e.target.value)}
              className={cn(SELECT_CLASS, "w-24")}
              aria-label="Section filter"
            />
          </label>

          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            Sample Size
            <select
              className={SELECT_CLASS}
              value={sampleSize}
              onChange={(e) => setSampleSize(Number(e.target.value))}
              aria-label="Sample size"
            >
              <option value={100}>100</option>
              <option value={500}>500</option>
              <option value={1000}>1,000</option>
              <option value={5000}>5,000</option>
              <option value={0}>All</option>
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
            {mutation.isPending ? "Testing\u2026" : "Run Test"}
          </button>
        </div>
      </div>

      {/* KPIs */}
      <KpiCardGrid className="mb-4">
        <KpiCard
          title="Hit Rate"
          value={data ? formatPercent(data.hit_rate) : "\u2014"}
          color={data && data.hit_rate >= 80 ? "green" : data && data.hit_rate >= 50 ? "orange" : "red"}
        />
        <KpiCard
          title="Hits"
          value={data ? formatNumber(data.hits) : "\u2014"}
          color="green"
        />
        <KpiCard
          title="Misses"
          value={data ? formatNumber(data.misses) : "\u2014"}
          color="red"
        />
        <KpiCard
          title="Total Docs"
          value={data ? formatNumber(data.total_docs) : "\u2014"}
        />
      </KpiCardGrid>

      {/* Loading / Error */}
      {mutation.isPending && <LoadingState message="Testing patterns..." />}
      {/* H3 RT2 FIX: Show actual error message from API */}
      {regexError && (
        <EmptyState title="Invalid pattern" message={regexError} />
      )}
      {mutation.error && !regexError && (
        <EmptyState title="Test failed" message={formatApiError(mutation.error)} />
      )}

      {/* Results */}
      {data && (
        <>
          {/* Article breakdown chart */}
          {articleChartData.length > 0 && (
            <div className="mb-4">
              <ChartCard title="Hit Rate by Article Number">
                <HBarChart
                  data={articleChartData}
                  color={CHART_COLORS.green}
                  tooltipFormatter={(v) => `${v.toFixed(1)}%`}
                />
              </ChartCard>
            </div>
          )}

          {/* Matches / Misses tabs */}
          <ChartCard title="" height="auto">
            <div className="flex gap-1.5 mb-3">
              <button
                onClick={() => setActiveTab("matches")}
                className={cn(
                  "px-2.5 py-1 rounded-sm text-xs font-medium transition-colors",
                  activeTab === "matches"
                    ? "bg-accent-green/20 text-accent-green"
                    : "bg-surface-3 text-text-muted hover:text-text-secondary border border-border"
                )}
              >
                Matches
                <span className="ml-1 text-[10px] opacity-70">{data.hits}</span>
              </button>
              <button
                onClick={() => setActiveTab("misses")}
                className={cn(
                  "px-2.5 py-1 rounded-sm text-xs font-medium transition-colors",
                  activeTab === "misses"
                    ? "bg-accent-red/20 text-accent-red"
                    : "bg-surface-3 text-text-muted hover:text-text-secondary border border-border"
                )}
              >
                Misses
                <span className="ml-1 text-[10px] opacity-70">{data.misses}</span>
              </button>
            </div>

            {activeTab === "matches" ? (
              data.matches.length === 0 ? (
                <EmptyState title="No matches" message="No documents matched the heading patterns." />
              ) : (
                <div className="overflow-auto max-h-[500px]">
                  <table className="w-full text-sm" aria-label="Pattern matches">
                    <thead className="sticky top-0 bg-surface-3 z-10">
                      <tr className="text-left text-xs text-text-muted uppercase">
                        <th className="px-3 py-2">Doc ID</th>
                        <th className="px-3 py-2">Borrower</th>
                        <th className="px-3 py-2">Section</th>
                        <th className="px-3 py-2">Heading</th>
                        <th className="px-3 py-2">Method</th>
                        <th className="px-3 py-2 text-right">Score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.matches.map((m, i) => (
                        <MatchRow
                          key={`${m.doc_id}_${m.section_number}_${i}`}
                          item={m}
                          onDocClick={handleDocClick}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            ) : data.miss_details.length === 0 ? (
              <EmptyState title="No misses" message="All documents matched." />
            ) : (
              <div className="overflow-auto max-h-[500px]">
                <table className="w-full text-sm" aria-label="Pattern misses">
                  <thead className="sticky top-0 bg-surface-3 z-10">
                    <tr className="text-left text-xs text-text-muted uppercase">
                      <th className="px-3 py-2">Doc ID</th>
                      <th className="px-3 py-2">Borrower</th>
                      <th className="px-3 py-2">Best Section</th>
                      <th className="px-3 py-2">Best Heading</th>
                      <th className="px-3 py-2 text-right">Best Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.miss_details.map((m, i) => (
                      <MissRow
                        key={`${m.doc_id}_${i}`}
                        item={m}
                        onDocClick={handleDocClick}
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
          title="Test heading patterns"
          message="Enter regex patterns for section headings (one per line) and click Run Test to measure hit rate across the corpus."
        />
      )}
    </ViewContainer>
  );
}
