"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { HBarChart } from "@/components/charts/HBarChart";
import {
  useDefinitionFrequency,
  useDefinitionVariants,
} from "@/lib/queries";
import { useDebounce } from "@/hooks/useDebounce";
import { formatNumber } from "@/lib/formatters";
import { cn, SELECT_CLASS } from "@/lib/cn";
import type { DefinitionFrequency } from "@/lib/types";

// --- Term row (M2: border-l-2 on both states to prevent horizontal shift) ---

function TermRow({
  term,
  isSelected,
  onSelect,
}: {
  term: DefinitionFrequency;
  isSelected: boolean;
  onSelect: (termName: string) => void;
}) {
  return (
    <tr
      className={cn(
        "border-t border-border cursor-pointer transition-colors border-l-2",
        isSelected
          ? "bg-accent-blue/10 border-l-accent-blue"
          : "border-l-transparent hover:bg-surface-tertiary/50"
      )}
      onClick={() => onSelect(term.term)}
    >
      <td className="px-3 py-2 text-text-primary font-medium">
        {term.term}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {formatNumber(term.doc_count)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {formatNumber(term.total_occurrences)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
        {(term.avg_confidence * 100).toFixed(0)}%
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {term.engines.map((e) => (
            <span
              key={e}
              className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-surface-tertiary text-text-muted border border-border"
            >
              {e}
            </span>
          ))}
        </div>
      </td>
    </tr>
  );
}

// --- Variant panel (M6: expandable definition text) ---

function VariantPanel({
  term,
  cohortOnly,
  onDocClick,
}: {
  term: string;
  cohortOnly: boolean;
  onDocClick: (docId: string) => void;
}) {
  const variants = useDefinitionVariants(term, cohortOnly);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  const toggleExpand = useCallback((index: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }, []);

  if (variants.isLoading) return <LoadingState message="Loading variants..." />;
  if (variants.error) return <EmptyState title="Failed to load" message="" />;
  if (!variants.data || variants.data.variants.length === 0) {
    return <EmptyState title="No variants" message="" />;
  }

  return (
    <div className="space-y-3">
      <div className="text-xs text-text-muted px-1">
        {variants.data.total_variants} variant{variants.data.total_variants !== 1 ? "s" : ""} across documents
      </div>
      <div className="max-h-[400px] overflow-auto space-y-2">
        {variants.data.variants.map((v, i) => {
          const isExpanded = expandedIds.has(i);
          return (
            <div
              key={`${v.doc_id}_${i}`}
              className="border border-border rounded-sm p-3 bg-surface-primary"
            >
              <div className="flex items-center gap-2 mb-2">
                <button
                  className="text-accent-blue hover:underline text-xs font-mono"
                  onClick={() => onDocClick(v.doc_id)}
                  title={`Open ${v.doc_id} in Explorer`}
                >
                  {v.doc_id.slice(0, 16)}
                </button>
                <span className="text-[10px] text-text-muted truncate">
                  {v.borrower}
                </span>
                <span className="ml-auto text-[10px] text-text-muted">
                  {v.engine} \u00B7 {(v.confidence * 100).toFixed(0)}%
                </span>
              </div>
              {/* M6: Expandable definition text — click to toggle between clamped and full */}
              <button
                className={cn(
                  "text-xs text-text-secondary leading-relaxed text-left w-full",
                  !isExpanded && "line-clamp-4"
                )}
                onClick={() => toggleExpand(i)}
                title={isExpanded ? "Click to collapse" : "Click to expand full definition"}
              >
                {v.definition_text}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- Main page ---

export default function DefinitionsPage() {
  const router = useRouter();
  const [rawFilter, setRawFilter] = useState("");
  const [cohortOnly, setCohortOnly] = useState(true);
  const [selectedTerm, setSelectedTerm] = useState<string | null>(null);

  const debouncedFilter = useDebounce(rawFilter, 300);

  const freq = useDefinitionFrequency({
    termPattern: debouncedFilter || undefined,
    cohortOnly,
    limit: 200,
  });

  const handleDocClick = useCallback(
    (docId: string) => {
      router.push(`/explorer?selected=${encodeURIComponent(docId)}`);
    },
    [router]
  );

  const handleTermSelect = useCallback((termName: string) => {
    setSelectedTerm((prev) => (prev === termName ? null : termName));
  }, []);

  // L1: Use shared SELECT_CLASS instead of local duplicate
  const data = freq.data;

  return (
    <ViewContainer title="Definition Explorer">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex-1 min-w-[250px]">
          <input
            type="text"
            placeholder="Filter terms..."
            value={rawFilter}
            onChange={(e) => setRawFilter(e.target.value)}
            className={cn(SELECT_CLASS, "w-full")}
            aria-label="Filter defined terms"
          />
        </div>

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

      {/* Stale indicator */}
      {freq.isPlaceholderData && (
        <div className="text-xs text-text-muted mb-2 animate-pulse">
          Updating\u2026
        </div>
      )}

      {/* M1: Always render KPI grid — show dash placeholders during loading
          to prevent layout shift when data arrives. */}
      <KpiCardGrid className="mb-4">
        <KpiCard
          title="Unique Terms"
          value={data ? formatNumber(data.total_terms) : "\u2014"}
          color="blue"
        />
        <KpiCard
          title="Most Common"
          value={data?.terms[0]?.term ?? "\u2014"}
        />
        <KpiCard
          title="Top Term Doc Count"
          value={data?.terms[0] ? formatNumber(data.terms[0].doc_count) : "\u2014"}
          color="green"
        />
      </KpiCardGrid>

      {freq.isLoading && !data && (
        <LoadingState message="Loading definitions..." />
      )}

      {freq.error && !data && (
        <EmptyState
          title="Failed to load"
          message="Definition frequency query failed. Check the API server."
        />
      )}

      {data && (
        <div className={cn(freq.isPlaceholderData && "opacity-60 transition-opacity")}>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
            {/* Top terms chart — M5: pass full term name via title for HBarChart tooltip */}
            <ChartCard title="Top 20 Defined Terms">
              {data.terms.length > 0 ? (
                <HBarChart
                  data={data.terms.slice(0, 20).map((t) => ({
                    name: t.term.length > 25 ? t.term.slice(0, 25) + "\u2026" : t.term,
                    fullName: t.term,
                    value: t.doc_count,
                  }))}
                />
              ) : (
                <EmptyState title="No terms" message="" />
              )}
            </ChartCard>

            {/* Frequency table — L4: aria-label for screen readers */}
            <div className="lg:col-span-2">
              <ChartCard title="Term Frequency" height="auto">
                {data.terms.length === 0 ? (
                  <EmptyState
                    title="No terms found"
                    message={debouncedFilter ? `No terms matching \u201c${debouncedFilter}\u201d.` : "No definitions in corpus."}
                  />
                ) : (
                  <div className="overflow-auto max-h-[500px]">
                    <table className="w-full text-sm" aria-label="Definition term frequency">
                      <thead className="sticky top-0 bg-surface-tertiary z-10">
                        <tr className="text-left text-xs text-text-muted uppercase">
                          <th className="px-3 py-2">Term</th>
                          <th className="px-3 py-2 text-right">Documents</th>
                          <th className="px-3 py-2 text-right">Occurrences</th>
                          <th className="px-3 py-2 text-right">Confidence</th>
                          <th className="px-3 py-2">Engines</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.terms.map((t) => (
                          <TermRow
                            key={t.term}
                            term={t}
                            isSelected={selectedTerm === t.term}
                            onSelect={handleTermSelect}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </ChartCard>
            </div>
          </div>

          {/* Variant panel */}
          {selectedTerm && (
            <ChartCard
              title={`\u201c${selectedTerm}\u201d \u2014 Definition Variants`}
              height="auto"
            >
              <VariantPanel
                term={selectedTerm}
                cohortOnly={cohortOnly}
                onDocClick={handleDocClick}
              />
            </ChartCard>
          )}
        </div>
      )}
    </ViewContainer>
  );
}
