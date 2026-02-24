"use client";

import { useMemo, useRef, useEffect, useCallback } from "react";
import { cn } from "@/lib/cn";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { DefinitionTooltip } from "./DefinitionTooltip";
import type { ReaderSectionDetail, ReaderClause, ReaderDefinition } from "@/lib/types";

// Depth-based left border colors (matches ClausePanel)
const DEPTH_BORDER_COLORS = [
  "border-l-accent-blue",
  "border-l-accent-green",
  "border-l-accent-orange",
  "border-l-[#8F56BF]",
  "border-l-accent-red",
  "border-l-accent-teal",
];

/**
 * Build segments from text + clause spans.
 * Each segment is either plain text or text within a clause boundary.
 */
interface TextSegment {
  text: string;
  clause: ReaderClause | null;
  charStart: number;
}

function buildSegments(
  text: string,
  clauses: ReaderClause[]
): TextSegment[] {
  if (clauses.length === 0) {
    return [{ text, clause: null, charStart: 0 }];
  }

  // Only use top-level clauses (depth 1) for visual segmentation to avoid overlap
  const topClauses = clauses
    .filter((c) => c.depth === 1)
    .sort((a, b) => a.span_start - b.span_start);

  const segments: TextSegment[] = [];
  let cursor = 0;

  for (const clause of topClauses) {
    const start = Math.max(0, Math.min(clause.span_start, text.length));
    const end = Math.max(start, Math.min(clause.span_end, text.length));

    // Gap before this clause
    if (cursor < start) {
      segments.push({
        text: text.slice(cursor, start),
        clause: null,
        charStart: cursor,
      });
    }

    // The clause span
    if (start < end) {
      segments.push({
        text: text.slice(start, end),
        clause,
        charStart: start,
      });
    }

    cursor = end;
  }

  // Trailing text after last clause
  if (cursor < text.length) {
    segments.push({
      text: text.slice(cursor),
      clause: null,
      charStart: cursor,
    });
  }

  return segments;
}

/**
 * Render text with defined term highlighting.
 * Finds occurrences of defined terms in the text and wraps them in DefinitionTooltip.
 */
function renderTextWithDefinitions(
  text: string,
  definitions: ReaderDefinition[]
): React.ReactNode {
  if (definitions.length === 0) return text;

  // Sort definitions by length descending (longest match first to avoid partial matches)
  const sorted = [...definitions].sort(
    (a, b) => b.term.length - a.term.length
  );

  // Build a case-insensitive regex for all terms
  const escaped = sorted.map((d) =>
    d.term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  );
  const pattern = new RegExp(`\\b(${escaped.join("|")})\\b`, "gi");

  // Build a lookup map (lowercase term → definition)
  const defMap = new Map<string, ReaderDefinition>();
  for (const d of sorted) {
    const key = d.term.toLowerCase();
    if (!defMap.has(key)) defMap.set(key, d);
  }

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let keyCounter = 0;

  // Limit to first 50 matches to avoid rendering overhead
  let matchCount = 0;
  while ((match = pattern.exec(text)) !== null && matchCount < 50) {
    matchCount++;
    const matchedText = match[0];
    const idx = match.index;

    // Text before match
    if (idx > lastIndex) {
      parts.push(text.slice(lastIndex, idx));
    }

    // The defined term
    const def = defMap.get(matchedText.toLowerCase());
    if (def) {
      parts.push(
        <DefinitionTooltip key={`def-${keyCounter++}`} definition={def}>
          {matchedText}
        </DefinitionTooltip>
      );
    } else {
      parts.push(matchedText);
    }

    lastIndex = idx + matchedText.length;
  }

  // Remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? <>{parts}</> : text;
}

interface SectionViewerProps {
  section: ReaderSectionDetail | null;
  isLoading: boolean;
  error: unknown;
  definitions: ReaderDefinition[];
  selectedClauseId: string | null;
  onSelectClause: (clauseId: string | null) => void;
  onPrevSection: (() => void) | null;
  onNextSection: (() => void) | null;
}

export function SectionViewer({
  section,
  isLoading,
  error,
  definitions,
  selectedClauseId,
  onSelectClause,
  onPrevSection,
  onNextSection,
}: SectionViewerProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const selectedSpanRef = useRef<HTMLDivElement>(null);

  // Scroll to selected clause
  useEffect(() => {
    if (selectedClauseId && selectedSpanRef.current) {
      selectedSpanRef.current.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
    }
  }, [selectedClauseId]);

  // Reset scroll on section change
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [section?.section_number]);

  const segments = useMemo(
    () =>
      section ? buildSegments(section.text, section.clauses) : [],
    [section]
  );

  const handleClauseClick = useCallback(
    (clauseId: string) => {
      onSelectClause(
        clauseId === selectedClauseId ? null : clauseId
      );
    },
    [selectedClauseId, onSelectClause]
  );

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <LoadingState message="Loading section text…" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <EmptyState
          title="Failed to load section"
          message="Check the API server connection."
        />
      </div>
    );
  }

  if (!section) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <EmptyState
          title="Select a section"
          message="Choose a section from the table of contents to read its content."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Section header */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border bg-surface-tertiary flex-shrink-0">
        <button
          className={cn(
            "text-xs px-1.5 py-0.5 rounded text-text-muted hover:text-text-primary hover:bg-surface-tertiary transition-colors",
            !onPrevSection && "invisible"
          )}
          onClick={onPrevSection ?? undefined}
          disabled={!onPrevSection}
          aria-label="Previous section"
        >
          ←
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-accent-blue">
              § {section.section_number}
            </span>
            <span className="text-sm font-medium text-text-primary truncate">
              {section.heading || "(no heading)"}
            </span>
          </div>
          <div className="flex gap-3 text-[10px] text-text-muted mt-0.5">
            <span>Article {section.article_num}</span>
            <span>{section.word_count.toLocaleString()} words</span>
            <span>{section.clauses.length} clauses</span>
          </div>
        </div>

        <button
          className={cn(
            "text-xs px-1.5 py-0.5 rounded text-text-muted hover:text-text-primary hover:bg-surface-tertiary transition-colors",
            !onNextSection && "invisible"
          )}
          onClick={onNextSection ?? undefined}
          disabled={!onNextSection}
          aria-label="Next section"
        >
          →
        </button>
      </div>

      {/* Section text */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-6 py-4"
      >
        {section.text ? (
          <div className="max-w-3xl space-y-0">
            {segments.map((seg, i) => {
              if (seg.clause) {
                const isSelected =
                  seg.clause.clause_id === selectedClauseId;
                const depthColor =
                  DEPTH_BORDER_COLORS[
                    seg.clause.depth % DEPTH_BORDER_COLORS.length
                  ];

                return (
                  <div
                    key={`seg-${i}`}
                    ref={isSelected ? selectedSpanRef : undefined}
                    className={cn(
                      "border-l-2 pl-3 py-1 cursor-pointer transition-colors",
                      isSelected
                        ? "bg-accent-blue/8 border-l-accent-blue"
                        : `${depthColor} hover:bg-surface-tertiary/40`
                    )}
                    onClick={() => handleClauseClick(seg.clause!.clause_id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        handleClauseClick(seg.clause!.clause_id);
                      }
                    }}
                    role="button"
                    tabIndex={0}
                    aria-label={`Clause ${seg.clause.label}`}
                  >
                    <p className="text-sm text-text-primary leading-relaxed whitespace-pre-wrap break-words">
                      {renderTextWithDefinitions(seg.text, definitions)}
                    </p>
                  </div>
                );
              }

              return (
                <p
                  key={`seg-${i}`}
                  className="text-sm text-text-primary leading-relaxed whitespace-pre-wrap break-words py-1"
                >
                  {renderTextWithDefinitions(seg.text, definitions)}
                </p>
              );
            })}
          </div>
        ) : (
          <div className="py-8">
            <EmptyState
              title="No text available"
              message="Section text was not extracted for this section."
            />
          </div>
        )}
      </div>
    </div>
  );
}
