"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useDnaDiscovery } from "@/lib/queries";
import { formatNumber, validateRegexPatterns, formatApiError } from "@/lib/formatters";
import { cn, SELECT_CLASS } from "@/lib/cn";
import type { DnaCandidate } from "@/lib/types";

// --- Score bar (inline visual) ---

function ScoreBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 bg-surface-tertiary rounded-full overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-[10px] tabular-nums text-text-muted">{value.toFixed(3)}</span>
    </div>
  );
}

// --- Candidate row ---

function CandidateRow({
  item,
  maxCombined,
  onSearch,
}: {
  item: DnaCandidate;
  maxCombined: number;
  onSearch: (phrase: string) => void;
}) {
  return (
    <tr className="border-t border-border hover:bg-surface-tertiary/50 transition-colors">
      <td className="px-3 py-2">
        <button
          className="text-accent-blue hover:underline text-xs font-mono text-left"
          onClick={() => onSearch(item.phrase)}
          title={`Search corpus for "${item.phrase}"`}
        >
          {item.phrase}
        </button>
      </td>
      <td className="px-3 py-2">
        <ScoreBar value={item.combined_score} max={maxCombined} color="#137CBD" />
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {item.tfidf_score.toFixed(3)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {item.log_odds_ratio.toFixed(2)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {(item.section_rate * 100).toFixed(1)}%
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs text-text-muted">
        {(item.background_rate * 100).toFixed(2)}%
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.doc_count)}
      </td>
    </tr>
  );
}

// --- Main page ---

export default function DnaPage() {
  const router = useRouter();
  const [headingPattern, setHeadingPattern] = useState("");
  const [topK, setTopK] = useState(30);
  const [minSectionRate, setMinSectionRate] = useState(0.2);
  const [maxBgRate, setMaxBgRate] = useState(0.05);
  const [ngramMin, setNgramMin] = useState(1);
  const [ngramMax, setNgramMax] = useState(3);
  const [cohortOnly, setCohortOnly] = useState(true);
  const [regexError, setRegexError] = useState<string | null>(null);

  const mutation = useDnaDiscovery();

  const handleRun = useCallback(() => {
    if (!headingPattern.trim()) return;

    // H3+M2 RT2 FIX: Client-side regex validation
    const err = validateRegexPatterns([headingPattern.trim()]);
    if (err) { setRegexError(err); return; }
    setRegexError(null);

    mutation.mutate({
      positiveHeadingPattern: headingPattern.trim(),
      topK,
      minSectionRate,
      maxBackgroundRate: maxBgRate,
      ngramMin,
      ngramMax,
      cohortOnly,
    });
  }, [mutation, headingPattern, topK, minSectionRate, maxBgRate, ngramMin, ngramMax, cohortOnly]);

  const handleSearch = useCallback(
    (phrase: string) => {
      router.push(`/search?q=${encodeURIComponent(phrase)}`);
    },
    [router]
  );

  const data = mutation.data;
  const maxCombined = data
    ? Math.max(...data.candidates.map((c) => c.combined_score), 0.001)
    : 1;

  return (
    <ViewContainer title="DNA Discovery Studio">
      {/* Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-4">
        {/* Positive heading pattern */}
        <div className="lg:col-span-2">
          <label className="text-xs text-text-muted uppercase tracking-wider block mb-1">
            Positive Heading Pattern (regex)
          </label>
          <input
            type="text"
            value={headingPattern}
            onChange={(e) => setHeadingPattern(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !mutation.isPending && headingPattern.trim()) handleRun(); }}
            placeholder="e.g. indebtedness"
            className={cn(SELECT_CLASS, "w-full font-mono")}
            aria-label="Positive heading pattern"
          />
          <p className="text-[10px] text-text-muted mt-1">
            Sections matching this heading are &quot;positive&quot;. All other sections serve as background.
          </p>
        </div>

        {/* Parameters column 1 */}
        <div className="space-y-2">
          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            Top K
            <select
              className={SELECT_CLASS}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
              aria-label="Top K results"
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={30}>30</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </label>

          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            Min Section Rate
            <select
              className={SELECT_CLASS}
              value={minSectionRate}
              onChange={(e) => setMinSectionRate(Number(e.target.value))}
              aria-label="Minimum section rate"
            >
              <option value={0.05}>5%</option>
              <option value={0.1}>10%</option>
              <option value={0.2}>20%</option>
              <option value={0.3}>30%</option>
              <option value={0.5}>50%</option>
            </select>
          </label>

          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            Max Background Rate
            <select
              className={SELECT_CLASS}
              value={maxBgRate}
              onChange={(e) => setMaxBgRate(Number(e.target.value))}
              aria-label="Maximum background rate"
            >
              <option value={0.01}>1%</option>
              <option value={0.02}>2%</option>
              <option value={0.05}>5%</option>
              <option value={0.1}>10%</option>
              <option value={0.15}>15%</option>
            </select>
          </label>
        </div>

        {/* Parameters column 2 */}
        <div className="space-y-2">
          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            N-gram Range
            <select
              className={SELECT_CLASS}
              value={`${ngramMin}-${ngramMax}`}
              onChange={(e) => {
                const [mn, mx] = e.target.value.split("-").map(Number);
                setNgramMin(mn);
                setNgramMax(mx);
              }}
              aria-label="N-gram range"
            >
              <option value="1-2">1-2</option>
              <option value="1-3">1-3</option>
              <option value="1-4">1-4</option>
              <option value="2-3">2-3</option>
              <option value="2-4">2-4</option>
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
            disabled={mutation.isPending || !headingPattern.trim()}
            className="px-4 py-1.5 text-xs font-medium rounded-sm bg-accent-blue text-white hover:bg-accent-blue/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors w-full"
          >
            {mutation.isPending ? "Discovering\u2026" : "Run Discovery"}
          </button>
        </div>
      </div>

      {/* KPIs */}
      <KpiCardGrid className="mb-4">
        <KpiCard
          title="Positive Sections"
          value={data ? formatNumber(data.positive_count) : "\u2014"}
          color="green"
        />
        <KpiCard
          title="Background Sections"
          value={data ? formatNumber(data.background_count) : "\u2014"}
        />
        <KpiCard
          title="Candidates Found"
          value={data ? formatNumber(data.total_candidates) : "\u2014"}
          color="blue"
        />
      </KpiCardGrid>

      {/* Loading / Error */}
      {mutation.isPending && <LoadingState message="Discovering discriminating phrases..." />}
      {/* H3 RT2 FIX: Show actual error message from API */}
      {regexError && (
        <EmptyState title="Invalid pattern" message={regexError} />
      )}
      {mutation.error && !regexError && (
        <EmptyState title="Discovery failed" message={formatApiError(mutation.error)} />
      )}

      {/* Results */}
      {data && (
        <ChartCard title="" height="auto">
          {data.candidates.length === 0 ? (
            <EmptyState
              title="No discriminating phrases"
              message="Try lowering the min section rate or raising the max background rate."
            />
          ) : (
            <div className="overflow-auto max-h-[600px]">
              <table className="w-full text-sm" aria-label="DNA candidates">
                <thead className="sticky top-0 bg-surface-tertiary z-10">
                  <tr className="text-left text-xs text-text-muted uppercase">
                    <th className="px-3 py-2">Phrase</th>
                    <th className="px-3 py-2">Combined Score</th>
                    <th className="px-3 py-2 text-right">TF-IDF</th>
                    <th className="px-3 py-2 text-right">Log Odds</th>
                    <th className="px-3 py-2 text-right">Section %</th>
                    <th className="px-3 py-2 text-right">BG %</th>
                    <th className="px-3 py-2 text-right">Docs</th>
                  </tr>
                </thead>
                <tbody>
                  {data.candidates.map((c, i) => (
                    <CandidateRow
                      key={`${c.phrase}_${i}`}
                      item={c}
                      maxCombined={maxCombined}
                      onSearch={handleSearch}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ChartCard>
      )}

      {/* Initial empty state */}
      {!data && !mutation.isPending && !mutation.error && (
        <EmptyState
          title="Discover discriminating phrases"
          message="Enter a heading pattern to identify &quot;positive&quot; sections, then run discovery to find n-gram phrases that distinguish those sections from the background corpus."
        />
      )}
    </ViewContainer>
  );
}
