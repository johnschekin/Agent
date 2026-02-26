"use client";

import { useEffect, useMemo, useRef } from "react";
import { cn } from "@/lib/cn";
import { useWhyMatched, useTemplateBaselineText } from "@/lib/queries";
import { HierarchyBreadcrumbs } from "./HierarchyBreadcrumbs";
import { CrossFamilyInspector } from "./CrossFamilyInspector";
import { CrossRefPeek, CROSSREF_PATTERN } from "./CrossRefPeek";
import { TemplateRedline } from "./TemplateRedline";
import { ContextStrip } from "./ContextStrip";
import { ComparablesPanel } from "./ComparablesPanel";
import type { FamilyLink, ComparableSection } from "@/lib/types";

interface ReviewPaneProps {
  link: FamilyLink | null;
  /** Raw section text */
  sectionText: string | null;
  /** All families linked to this section (for cross-family inspector) */
  sectionFamilies: { family_id: string; family_name: string; is_current?: boolean }[];
  /** Defined terms found in this section */
  definitions: { term: string; definition_text: string; char_start: number; char_end: number }[];
  /** Pre-fetched comparable sections (avoids duplicate fetch) */
  comparables?: ComparableSection[];
  /** Whether context folding is active */
  folded: boolean;
  /** Whether template redline is active */
  redlineActive: boolean;
  /** Template family for baseline lookup */
  templateFamily: string | null;
  /** Query tab uses clause-hit highlighting instead of heading/dna/terms */
  highlightMode?: "review" | "query";
  /** Clause-query terms to highlight in query mode */
  queryHighlightTerms?: string[];
  /** Optional clause span (section-relative) to scroll to in query mode */
  queryFocusRange?: { start: number; end: number } | null;
  /** Optional clause text fallback for locating the hit */
  queryFocusText?: string | null;
  className?: string;
}

/**
 * Split-pane reader showing section text with inline highlights:
 * - Heading match: green glow
 * - DNA phrases: purple underline
 * - Defined terms: blue dotted underline (with hover tooltip)
 */
export function ReviewPane({
  link,
  sectionText,
  sectionFamilies,
  definitions,
  comparables,
  folded,
  redlineActive,
  templateFamily,
  highlightMode = "review",
  queryHighlightTerms = [],
  queryFocusRange = null,
  queryFocusText = null,
  className,
}: ReviewPaneProps) {
  const { data: whyData } = useWhyMatched(link?.link_id ?? null);
  const { data: baselineData } = useTemplateBaselineText(
    redlineActive ? link?.family_id ?? null : null,
    redlineActive ? templateFamily : null
  );

  // Extract DNA phrases from whyData factors
  const dnaPhrases = useMemo(() => {
    if (!whyData) return [];
    return whyData.factors
      .filter((f) => f.factor === "dna_phrase" || f.factor === "section_dna")
      .flatMap((f) => f.evidence ?? [])
      .filter((phrase): phrase is string => typeof phrase === "string" && phrase.length > 2);
  }, [whyData]);

  // Highlight heading in text
  const highlightedText = useMemo(() => {
    if (!sectionText || !link) return sectionText;
    return sectionText;
  }, [sectionText, link]);

  if (!link) {
    return (
      <div className={cn("flex items-center justify-center h-full bg-surface-1 rounded-lg text-sm text-text-muted", className)}>
        Select a link to view section text
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col h-full bg-surface-1 rounded-lg overflow-hidden", className)}>
      {/* Breadcrumbs */}
      <HierarchyBreadcrumbs
        article={link.section_number.split(".")[0] ? `Article ${link.section_number.split(".")[0]}` : null}
        section={`Section ${link.section_number}`}
      />

      {/* Cross-family badges */}
      {sectionFamilies.length > 0 && (
        <div className="px-4 py-2 border-b border-border">
          <CrossFamilyInspector families={sectionFamilies} />
        </div>
      )}

      {/* Section text */}
      <div className="flex-1 overflow-auto">
        <div className="flex h-full">
          {/* Main text area */}
          <div className="flex-1 p-4 overflow-auto">
            {/* Heading */}
            <h3 className="text-base font-semibold text-text-primary mb-3">
              {highlightMode === "query" ? (
                link.heading
              ) : (
                <span className="highlight-green-glow">{link.heading}</span>
              )}
            </h3>

            {/* Template redline overlay */}
            {redlineActive && (
              <div className="mb-4">
                <TemplateRedline
                  currentText={sectionText || ""}
                  baselineText={baselineData?.text ?? null}
                  active={redlineActive}
                />
              </div>
            )}

            {/* Section text body */}
            {highlightedText ? (
              <div
                className={cn(
                  "text-sm text-text-secondary leading-relaxed whitespace-pre-wrap",
                  folded && "max-h-64 overflow-hidden relative"
                )}
              >
                <SectionTextRenderer
                  text={highlightedText}
                  docId={link.doc_id}
                  heading={link.heading}
                  definitions={definitions}
                  dnaPhrases={dnaPhrases}
                  queryMode={highlightMode === "query"}
                  queryHighlightTerms={queryHighlightTerms}
                  queryFocusRange={queryFocusRange}
                  queryFocusText={queryFocusText}
                />
                {folded && (
                  <div className="absolute bottom-0 inset-x-0 h-16 bg-gradient-to-t from-surface-1 to-transparent" />
                )}
              </div>
            ) : (
              <p className="text-sm text-text-muted italic">
                Section text not available
              </p>
            )}

            {/* Why matched factors */}
            {whyData && whyData.factors.length > 0 && (
              <div className="mt-4 p-3 bg-surface-2 rounded-lg border border-border">
                <h4 className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-2">
                  Confidence Factors
                </h4>
                <div className="grid grid-cols-2 gap-2">
                  {whyData.factors.map((f, i) => (
                    <div key={i} className="flex items-center justify-between">
                      <span className="text-xs text-text-secondary">{f.factor}</span>
                      <span className="text-xs font-mono text-text-primary tabular-nums">
                        {f.score.toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Comparables panel — rendered below text in main area */}
            {comparables && comparables.length > 0 && (
              <div className="mt-4 border-t border-border pt-3">
                <h4 className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-2">
                  Comparables ({comparables.length})
                </h4>
                <ComparablesPanel linkId={link.link_id} />
              </div>
            )}
          </div>

          {/* Context strip sidebar — handles own responsive visibility */}
          <ContextStrip linkId={link.link_id} className="w-60 flex-shrink-0" />
        </div>
      </div>
    </div>
  );
}

// ── Section text renderer with inline highlights ───────────────────────────

interface SectionTextRendererProps {
  text: string;
  docId: string;
  heading: string;
  definitions: { term: string; definition_text: string; char_start: number; char_end: number }[];
  /** DNA phrases to highlight purple */
  dnaPhrases: string[];
  /** Query mode: disable heading/dna/term highlights and focus the clause hit */
  queryMode?: boolean;
  queryHighlightTerms?: string[];
  queryFocusRange?: { start: number; end: number } | null;
  queryFocusText?: string | null;
}

function SectionTextRenderer({
  text,
  docId,
  heading,
  definitions,
  dnaPhrases,
  queryMode = false,
  queryHighlightTerms = [],
  queryFocusRange = null,
  queryFocusText = null,
}: SectionTextRendererProps) {
  const focusRef = useRef<HTMLSpanElement | null>(null);
  const hasFocusSpecifier =
    !!queryFocusRange ||
    queryHighlightTerms.some((term) => String(term || "").trim().length >= 2) ||
    (typeof queryFocusText === "string" && queryFocusText.trim().length >= 2);

  useEffect(() => {
    if (!hasFocusSpecifier || !focusRef.current) return;
    focusRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [
    hasFocusSpecifier,
    text,
    queryFocusRange?.start,
    queryFocusRange?.end,
    queryFocusText,
    queryHighlightTerms.join("|"),
  ]);

  if (queryMode || hasFocusSpecifier) {
    return (
      <>{renderQueryFocusedText(
        text,
        queryHighlightTerms,
        queryFocusRange,
        queryFocusText,
        focusRef,
      )}</>
    );
  }

  // Build a set of defined terms for highlighting
  const termSet = useMemo(() => {
    const terms = new Map<string, string>();
    for (const def of definitions) {
      terms.set(def.term.toLowerCase(), def.definition_text);
    }
    return terms;
  }, [definitions]);

  // Simple paragraph split with term highlighting
  const paragraphs = text.split(/\n\n+/);

  return (
    <>
      {paragraphs.map((para, pi) => (
        <p key={pi} className="mb-3">
          {renderParagraphWithCrossRefs(para, docId, heading, termSet, dnaPhrases)}
        </p>
      ))}
    </>
  );
}

function renderParagraphWithCrossRefs(
  text: string,
  docId: string,
  heading: string,
  termMap: Map<string, string>,
  dnaPhrases: string[],
): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  CROSSREF_PATTERN.lastIndex = 0;

  let match: RegExpExecArray | null;
  while ((match = CROSSREF_PATTERN.exec(text)) !== null) {
    const fullMatch = match[0];
    const sectionRef = match[1];
    if (match.index > lastIndex) {
      nodes.push(
        ...highlightTermsInText(
          text.slice(lastIndex, match.index),
          heading,
          termMap,
          dnaPhrases,
        ),
      );
    }
    const lookupRef = docId ? `${docId}:${sectionRef}` : sectionRef;
    nodes.push(
      <CrossRefPeek key={`xref-${key++}`} sectionRef={lookupRef}>
        <span data-xref={sectionRef}>{fullMatch}</span>
      </CrossRefPeek>,
    );
    lastIndex = match.index + fullMatch.length;
  }

  if (lastIndex < text.length) {
    nodes.push(...highlightTermsInText(text.slice(lastIndex), heading, termMap, dnaPhrases));
  }
  return nodes;
}

function normalizeRange(
  range: { start: number; end: number } | null | undefined,
  textLength: number,
): { start: number; end: number } | null {
  if (!range) return null;
  const start = Number(range.start);
  const end = Number(range.end);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  const boundedStart = Math.max(0, Math.min(textLength, Math.floor(start)));
  const boundedEnd = Math.max(boundedStart, Math.min(textLength, Math.floor(end)));
  if (boundedEnd <= boundedStart) return null;
  return { start: boundedStart, end: boundedEnd };
}

function findFirstTermRange(
  text: string,
  terms: string[],
  windowStart = 0,
  windowEnd = text.length,
): { start: number; end: number } | null {
  const boundedStart = Math.max(0, Math.min(text.length, windowStart));
  const boundedEnd = Math.max(boundedStart, Math.min(text.length, windowEnd));
  const haystackWindow = text.slice(boundedStart, boundedEnd).toLowerCase();
  if (!haystackWindow) return null;

  for (const raw of terms) {
    const term = String(raw || "").trim();
    if (!term || term.length < 2) continue;
    const idx = haystackWindow.indexOf(term.toLowerCase());
    if (idx >= 0) {
      const start = boundedStart + idx;
      return { start, end: start + term.length };
    }
  }
  return null;
}

function renderQueryFocusedText(
  text: string,
  queryHighlightTerms: string[],
  queryFocusRange: { start: number; end: number } | null,
  queryFocusText: string | null,
  focusRef: { current: HTMLSpanElement | null },
): React.ReactNode[] {
  if (!text) return [text];

  const focusRange = normalizeRange(queryFocusRange, text.length);
  const sortedTerms = [...queryHighlightTerms]
    .map((term) => String(term || "").trim())
    .filter((term) => term.length >= 2)
    .sort((a, b) => b.length - a.length);

  let highlightRange: { start: number; end: number } | null = null;
  if (focusRange) {
    highlightRange = findFirstTermRange(
      text,
      sortedTerms,
      focusRange.start,
      focusRange.end,
    );
  }
  if (!highlightRange) {
    highlightRange = findFirstTermRange(text, sortedTerms);
  }
  if (!highlightRange && queryFocusText) {
    const needle = String(queryFocusText).trim().toLowerCase();
    if (needle.length >= 2) {
      const idx = text.toLowerCase().indexOf(needle);
      if (idx >= 0) {
        highlightRange = { start: idx, end: idx + needle.length };
      }
    }
  }

  const anchorPos = focusRange?.start ?? highlightRange?.start ?? null;
  if (anchorPos === null && !highlightRange) {
    return [text];
  }

  const boundaries = new Set<number>([0, text.length]);
  if (anchorPos !== null) boundaries.add(anchorPos);
  if (highlightRange) {
    boundaries.add(highlightRange.start);
    boundaries.add(highlightRange.end);
  }
  const sortedBounds = Array.from(boundaries).sort((a, b) => a - b);

  const nodes: React.ReactNode[] = [];
  let key = 0;
  for (let i = 0; i < sortedBounds.length - 1; i++) {
    const start = sortedBounds[i];
    const end = sortedBounds[i + 1];
    if (anchorPos !== null && start === anchorPos) {
      nodes.push(
        <span
          key={`anchor-${key++}`}
          ref={focusRef}
          data-testid="query-hit-anchor"
          className="inline-block w-0 h-0 align-baseline"
        />,
      );
    }
    if (end <= start) continue;
    const chunk = text.slice(start, end);
    if (
      highlightRange &&
      start >= highlightRange.start &&
      end <= highlightRange.end
    ) {
      nodes.push(
        <span
          key={`hit-${key++}`}
          className="rounded bg-amber-300/25 px-0.5 text-amber-100"
        >
          {chunk}
        </span>,
      );
    } else {
      nodes.push(
        <span key={`text-${key++}`}>{chunk}</span>,
      );
    }
  }

  if (anchorPos === text.length) {
    nodes.push(
      <span
        key={`anchor-end-${nodes.length}`}
        ref={focusRef}
        data-testid="query-hit-anchor"
        className="inline-block w-0 h-0 align-baseline"
      />,
    );
  }
  return nodes;
}

/**
 * Highlight heading matches (green), DNA phrases (purple underline),
 * and defined terms (blue dotted underline) in text.
 */
function highlightTermsInText(
  text: string,
  heading: string,
  termMap: Map<string, string>,
  dnaPhrases: string[]
): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];

  // Build regex for heading, DNA phrases, and terms
  const patterns: { regex: RegExp; type: "heading" | "dna" | "term"; term?: string }[] = [];

  // Heading pattern
  if (heading) {
    try {
      patterns.push({
        regex: new RegExp(`(${escapeRegex(heading)})`, "gi"),
        type: "heading",
      });
    } catch {
      // Invalid regex, skip
    }
  }

  // DNA phrase patterns
  for (const phrase of dnaPhrases) {
    try {
      patterns.push({
        regex: new RegExp(`\\b(${escapeRegex(phrase)})\\b`, "gi"),
        type: "dna",
      });
    } catch {
      // Invalid regex, skip
    }
  }

  // Term patterns
  termMap.forEach((_defText, term) => {
    try {
      patterns.push({
        regex: new RegExp(`\\b(${escapeRegex(term)})\\b`, "gi"),
        type: "term",
        term,
      });
    } catch {
      // Invalid regex, skip
    }
  });

  if (patterns.length === 0) {
    return [text];
  }

  // Combine all patterns
  const combined = patterns
    .map((p, i) => `(?<g${i}>${p.regex.source})`)
    .join("|");

  let combinedRegex: RegExp;
  try {
    combinedRegex = new RegExp(combined, "gi");
  } catch {
    return [text];
  }

  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let nodeKey = 0;

  while ((match = combinedRegex.exec(text)) !== null) {
    // Text before match
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    // Find which group matched
    let matchType: "heading" | "dna" | "term" = "heading";
    let termKey: string | undefined;
    for (let i = 0; i < patterns.length; i++) {
      if (match.groups?.[`g${i}`]) {
        matchType = patterns[i].type;
        termKey = patterns[i].term;
        break;
      }
    }

    if (matchType === "heading") {
      nodes.push(
        <span key={nodeKey++} className="highlight-green-glow font-medium">
          {match[0]}
        </span>
      );
    } else if (matchType === "dna") {
      nodes.push(
        <span key={nodeKey++} className="highlight-purple underline decoration-purple-400">
          {match[0]}
        </span>
      );
    } else {
      const defText = termKey ? termMap.get(termKey) : undefined;
      nodes.push(
        <span
          key={nodeKey++}
          className="highlight-blue-term"
          title={defText ? `${termKey}: ${defText.slice(0, 150)}...` : undefined}
        >
          {match[0]}
        </span>
      );
    }

    lastIndex = match.index + match[0].length;
  }

  // Remaining text
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
