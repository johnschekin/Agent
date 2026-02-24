"use client";

import { useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { HBarChart } from "@/components/charts/HBarChart";
import { useClauseSearch } from "@/lib/queries";
import { formatNumber, validateRegexPatterns, formatApiError } from "@/lib/formatters";
import { cn, SELECT_CLASS } from "@/lib/cn";
import { CHART_COLORS } from "@/lib/colors";
import type { ClauseMatch } from "@/lib/types";

// --- Clause row ---

function ClauseRow({
  item,
  onDocClick,
}: {
  item: ClauseMatch;
  onDocClick: (docId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr
        className="border-t border-border hover:bg-surface-tertiary/50 cursor-pointer transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <td className="px-3 py-2">
          <button
            className="text-accent-blue hover:underline text-xs font-mono"
            onClick={(e) => {
              e.stopPropagation();
              onDocClick(item.doc_id);
            }}
          >
            {item.doc_id.slice(0, 12)}
          </button>
        </td>
        <td className="px-3 py-2 text-xs font-mono">{item.section_number}</td>
        <td className="px-3 py-2 text-xs truncate max-w-[140px]" title={item.section_heading}>
          {item.section_heading}
        </td>
        <td className="px-3 py-2 text-xs font-mono text-text-secondary">
          {item.clause_path}
        </td>
        <td className="px-3 py-2">
          <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-tertiary text-text-secondary border border-border">
            {item.clause_label}
          </span>
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-xs">
          {item.depth}
        </td>
        <td className="px-3 py-2 text-xs truncate max-w-[180px]" title={item.header_text}>
          {item.header_text || "\u2014"}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-xs">
          {formatNumber(item.word_count)}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-surface-tertiary/30">
          <td colSpan={8} className="px-6 py-3">
            <pre className="text-xs font-mono text-text-secondary whitespace-pre-wrap max-h-40 overflow-auto leading-relaxed">
              {item.clause_text || "(no text)"}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

// --- Main page ---

export default function ClausesPage() {
  const router = useRouter();
  const [sectionNumber, setSectionNumber] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [headingPattern, setHeadingPattern] = useState("");
  const [minDepth, setMinDepth] = useState(1);
  const [maxDepth, setMaxDepth] = useState(6);
  const [cohortOnly, setCohortOnly] = useState(true);
  const [regexError, setRegexError] = useState<string | null>(null);

  const mutation = useClauseSearch();

  const handleRun = useCallback(() => {
    const keywords = keywordInput
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);

    // H3+M2 RT2 FIX: Client-side regex validation for heading pattern
    if (headingPattern) {
      const err = validateRegexPatterns([headingPattern]);
      if (err) { setRegexError(err); return; }
    }
    setRegexError(null);

    mutation.mutate({
      sectionNumber: sectionNumber || undefined,
      keywords: keywords.length > 0 ? keywords : undefined,
      headingPattern: headingPattern || undefined,
      minDepth,
      maxDepth,
      limit: 200,
      cohortOnly,
    });
  }, [mutation, sectionNumber, keywordInput, headingPattern, minDepth, maxDepth, cohortOnly]);

  const handleDocClick = useCallback(
    (docId: string) => {
      router.push(`/explorer?selected=${encodeURIComponent(docId)}`);
    },
    [router]
  );

  const data = mutation.data;

  // Depth distribution for chart
  const depthChartData = useMemo(() => {
    if (!data) return [];
    const depthCounts: Record<number, number> = {};
    for (const m of data.matches) {
      depthCounts[m.depth] = (depthCounts[m.depth] || 0) + 1;
    }
    return Object.entries(depthCounts)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([depth, count]) => ({
        name: `Depth ${depth}`,
        value: count,
      }));
  }, [data]);

  return (
    <ViewContainer title="Clause Deep Dive">
      {/* Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-4">
        {/* Keywords */}
        <div>
          <label className="text-xs text-text-muted uppercase tracking-wider block mb-1">
            Keywords (one per line)
          </label>
          <textarea
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !mutation.isPending) handleRun(); }}
            placeholder={"permitted\nbasket\naggregate"}
            rows={3}
            className={cn(SELECT_CLASS, "w-full resize-y font-mono text-xs")}
            aria-label="Keywords"
          />
        </div>

        {/* Heading pattern */}
        <div>
          <label className="text-xs text-text-muted uppercase tracking-wider block mb-1">
            Parent Heading Pattern (regex)
          </label>
          <input
            type="text"
            value={headingPattern}
            onChange={(e) => setHeadingPattern(e.target.value)}
            placeholder="e.g. indebtedness"
            className={cn(SELECT_CLASS, "w-full font-mono mb-2")}
            aria-label="Heading pattern"
          />
          <label className="text-xs text-text-muted uppercase tracking-wider block mb-1">
            Section Number
          </label>
          <input
            type="text"
            value={sectionNumber}
            onChange={(e) => setSectionNumber(e.target.value)}
            placeholder="e.g. 7.01"
            className={cn(SELECT_CLASS, "w-full font-mono")}
            aria-label="Section number"
          />
        </div>

        {/* Depth range */}
        <div className="space-y-3">
          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            Min Depth
            <select
              className={SELECT_CLASS}
              value={minDepth}
              onChange={(e) => {
                const v = Number(e.target.value);
                setMinDepth(v);
                // M3 RT2 FIX: Auto-adjust max if min exceeds it
                if (v > maxDepth) setMaxDepth(v);
              }}
              aria-label="Minimum depth"
            >
              {[0, 1, 2, 3, 4].map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            Max Depth
            <select
              className={SELECT_CLASS}
              value={maxDepth}
              onChange={(e) => {
                const v = Number(e.target.value);
                setMaxDepth(v);
                // M3 RT2 FIX: Auto-adjust min if max drops below it
                if (v < minDepth) setMinDepth(v);
              }}
              aria-label="Maximum depth"
            >
              {[2, 3, 4, 5, 6, 8, 10].map((d) => (
                <option key={d} value={d}>{d}</option>
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

        {/* Run */}
        <div className="flex items-end">
          <button
            onClick={handleRun}
            disabled={mutation.isPending}
            className="px-4 py-1.5 text-xs font-medium rounded-sm bg-accent-blue text-white hover:bg-accent-blue/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors w-full"
          >
            {mutation.isPending ? "Searching\u2026" : "Search Clauses"}
          </button>
        </div>
      </div>

      {/* KPIs */}
      <KpiCardGrid className="mb-4">
        <KpiCard
          title="Total Matches"
          value={data ? formatNumber(data.total) : "\u2014"}
          color="blue"
        />
        <KpiCard
          title="Shown"
          value={data ? formatNumber(data.matches.length) : "\u2014"}
        />
      </KpiCardGrid>

      {/* Loading / Error */}
      {mutation.isPending && <LoadingState message="Searching clauses..." />}
      {/* H3 RT2 FIX: Show actual error message from API */}
      {regexError && (
        <EmptyState title="Invalid pattern" message={regexError} />
      )}
      {mutation.error && !regexError && (
        <EmptyState title="Search failed" message={formatApiError(mutation.error)} />
      )}

      {/* Results */}
      {data && (
        <>
          {/* Depth chart */}
          {depthChartData.length > 0 && (
            <div className="mb-4">
              <ChartCard title="Matches by Depth">
                <HBarChart
                  data={depthChartData}
                  color={CHART_COLORS.purple}
                  tooltipFormatter={(v) => `${v} clauses`}
                />
              </ChartCard>
            </div>
          )}

          {/* Table */}
          <ChartCard title="" height="auto">
            {data.matches.length === 0 ? (
              <EmptyState
                title="No clauses found"
                message="Try broader keywords or a wider depth range."
              />
            ) : (
              <div className="overflow-auto max-h-[500px]">
                <table className="w-full text-sm" aria-label="Clause matches">
                  <thead className="sticky top-0 bg-surface-tertiary z-10">
                    <tr className="text-left text-xs text-text-muted uppercase">
                      <th className="px-3 py-2">Doc ID</th>
                      <th className="px-3 py-2">Section</th>
                      <th className="px-3 py-2">Heading</th>
                      <th className="px-3 py-2">Path</th>
                      <th className="px-3 py-2">Label</th>
                      <th className="px-3 py-2 text-right">Depth</th>
                      <th className="px-3 py-2">Header Text</th>
                      <th className="px-3 py-2 text-right">Words</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.matches.map((m, i) => (
                      <ClauseRow
                        key={`${m.doc_id}_${m.section_number}_${m.clause_path}`}
                        item={m}
                        onDocClick={handleDocClick}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {data.total > data.matches.length && (
              <div className="text-xs text-text-muted mt-2 px-3">
                Showing {formatNumber(data.matches.length)} of {formatNumber(data.total)} total matches.
              </div>
            )}
          </ChartCard>
        </>
      )}

      {/* Initial empty state */}
      {!data && !mutation.isPending && !mutation.error && (
        <EmptyState
          title="Search clause trees"
          message="Enter keywords, heading patterns, or section numbers to find matching clauses across the corpus. Click any row to expand and see clause text."
        />
      )}
    </ViewContainer>
  );
}
