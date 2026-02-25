"use client";

import { useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useSearchText } from "@/lib/queries";
import { useDebounce } from "@/hooks/useDebounce";
import { formatNumber } from "@/lib/formatters";
import { cn, SELECT_CLASS } from "@/lib/cn";
import type { SearchTextMatch } from "@/lib/types";

// --- KwicLine component ---

function KwicLine({
  match,
  onDocClick,
}: {
  match: SearchTextMatch;
  onDocClick: (docId: string) => void;
}) {
  return (
    <div className="flex items-start gap-3 py-2 px-3 border-b border-border hover:bg-surface-3/50 transition-colors">
      {/* Doc info column */}
      <div className="flex-shrink-0 w-[200px]">
        <button
          className="text-accent-blue hover:underline text-xs font-mono truncate block w-full text-left"
          onClick={() => onDocClick(match.doc_id)}
          title={`Open ${match.doc_id} in Explorer`}
        >
          {match.doc_id.slice(0, 16)}
        </button>
        <div className="text-[10px] text-text-muted truncate" title={match.borrower}>
          {match.borrower || "\u2014"}
        </div>
      </div>

      {/* Section badge */}
      <div className="flex-shrink-0 w-[80px]">
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-3 text-text-secondary border border-border">
          {match.section_number}
        </span>
        <div className="text-[10px] text-text-muted truncate mt-0.5" title={match.heading}>
          {match.heading}
        </div>
      </div>

      {/* KWIC context */}
      <div className="flex-1 min-w-0 font-mono text-xs leading-relaxed">
        <span className="text-text-secondary">
          {match.context_before}
        </span>
        <mark className="bg-accent-blue/30 text-text-primary px-0.5 rounded-sm font-semibold">
          {match.matched_text}
        </mark>
        <span className="text-text-secondary">
          {match.context_after}
        </span>
      </div>
    </div>
  );
}

// --- Grouped view (L2: memoized grouping) ---

function GroupedResults({
  matches,
  onDocClick,
}: {
  matches: SearchTextMatch[];
  onDocClick: (docId: string) => void;
}) {
  const groups = useMemo(() => {
    const map = new Map<string, SearchTextMatch[]>();
    for (const m of matches) {
      if (!map.has(m.doc_id)) map.set(m.doc_id, []);
      map.get(m.doc_id)!.push(m);
    }
    return Array.from(map.entries());
  }, [matches]);

  return (
    // M3: Add max-height and overflow to grouped results (matches flat view)
    <div className="max-h-[70vh] overflow-auto space-y-4">
      {groups.map(([docId, docMatches]) => (
        <div key={docId} className="border border-border rounded-sm overflow-hidden">
          <div className="flex items-center gap-3 px-3 py-2 bg-surface-3">
            {/* L3: Add title attribute for full doc_id on grouped header */}
            <button
              className="text-accent-blue hover:underline text-xs font-mono"
              onClick={() => onDocClick(docId)}
              title={`Open ${docId} in Explorer`}
            >
              {docId.slice(0, 16)}
            </button>
            <span className="text-[10px] text-text-muted">
              {docMatches[0]?.borrower}
            </span>
            <span className="ml-auto text-[10px] text-text-muted">
              {docMatches.length} match{docMatches.length !== 1 ? "es" : ""}
            </span>
          </div>
          {docMatches.map((m, i) => (
            <KwicLine key={`${m.section_number}_${m.char_offset}_${i}`} match={m} onDocClick={onDocClick} />
          ))}
        </div>
      ))}
    </div>
  );
}

// --- Main page ---

export default function SearchPage() {
  const router = useRouter();
  const [rawQuery, setRawQuery] = useState("");
  const [contextChars, setContextChars] = useState(200);
  const [maxResults, setMaxResults] = useState(100);
  const [cohortOnly, setCohortOnly] = useState(true);
  const [groupByDoc, setGroupByDoc] = useState(false);

  const debouncedQuery = useDebounce(rawQuery, 300);

  const search = useSearchText(
    debouncedQuery.length >= 2
      ? { q: debouncedQuery, contextChars, maxResults, cohortOnly }
      : null
  );

  const handleDocClick = useCallback(
    (docId: string) => {
      router.push(`/explorer?selected=${encodeURIComponent(docId)}`);
    },
    [router]
  );

  // L1: Use shared SELECT_CLASS instead of local duplicate

  return (
    <ViewContainer title="Corpus Search">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex-1 min-w-[300px]">
          <input
            type="text"
            placeholder="Search across all documents (min 2 chars)..."
            value={rawQuery}
            onChange={(e) => setRawQuery(e.target.value)}
            className={cn(SELECT_CLASS, "w-full")}
            aria-label="Search pattern"
          />
        </div>

        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          Context
          <select
            aria-label="Context characters"
            className={SELECT_CLASS}
            value={contextChars}
            onChange={(e) => setContextChars(Number(e.target.value))}
          >
            <option value={100}>100 chars</option>
            <option value={200}>200 chars</option>
            <option value={500}>500 chars</option>
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          Max
          <select
            aria-label="Maximum results"
            className={SELECT_CLASS}
            value={maxResults}
            onChange={(e) => setMaxResults(Number(e.target.value))}
          >
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
            <option value={500}>500</option>
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

        <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={groupByDoc}
            onChange={(e) => setGroupByDoc(e.target.checked)}
            className="accent-accent-blue"
          />
          Group by Document
        </label>
      </div>

      {/* Stale indicator */}
      {search.isPlaceholderData && (
        <div className="text-xs text-text-muted mb-2 animate-pulse">
          Updating\u2026
        </div>
      )}

      {/* Results header — M4: use formatNumber for locale-aware grouping */}
      {search.data && debouncedQuery.length >= 2 && (
        <div className="flex items-center gap-3 mb-3">
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-accent-blue/20 text-accent-blue">
            {formatNumber(search.data.total_matches)} match{search.data.total_matches !== 1 ? "es" : ""}
          </span>
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-surface-3 text-text-secondary border border-border">
            {formatNumber(search.data.unique_documents)} document{search.data.unique_documents !== 1 ? "s" : ""}
          </span>
          {/* M7: Use server-provided truncated flag instead of client-side heuristic */}
          {search.data.truncated && (
            <span className="text-xs text-text-muted">
              (limited to {formatNumber(maxResults)} results)
            </span>
          )}
        </div>
      )}

      {/* Content */}
      <div className={cn(search.isPlaceholderData && "opacity-60 transition-opacity")}>
        <ChartCard title="" height="auto">
          {!debouncedQuery || debouncedQuery.length < 2 ? (
            <EmptyState
              title="Enter a search term"
              message="Type at least 2 characters to search across all section text in the corpus."
            />
          ) : search.isLoading && !search.data ? (
            <LoadingState message="Searching corpus..." />
          ) : search.error && !search.data ? (
            // H3: Only show error when there's no stale data to fall back to.
            // If there IS stale data, the opacity-60 wrapper + "Updating..." indicator
            // already communicates the situation. The error will clear on next success.
            <EmptyState
              title="Search failed"
              message="Check the API server is running and try again."
            />
          ) : search.data && search.data.matches.length === 0 ? (
            <EmptyState
              title="No matches"
              message={`No results found for \u201c${debouncedQuery}\u201d.`}
            />
          ) : search.data ? (
            groupByDoc ? (
              <GroupedResults
                matches={search.data.matches}
                onDocClick={handleDocClick}
              />
            ) : (
              <div className="max-h-[70vh] overflow-auto">
                {search.data.matches.map((m, i) => (
                  <KwicLine
                    key={`${m.doc_id}_${m.section_number}_${m.char_offset}_${i}`}
                    match={m}
                    onDocClick={handleDocClick}
                  />
                ))}
              </div>
            )
          ) : null}
        </ChartCard>
      </div>
    </ViewContainer>
  );
}
