"use client";

import { useMemo } from "react";
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
              <span className="highlight-green-glow">{link.heading}</span>
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
}

function SectionTextRenderer({ text, docId, heading, definitions, dnaPhrases }: SectionTextRendererProps) {
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
