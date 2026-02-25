"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { HierarchyBreadcrumbs } from "./HierarchyBreadcrumbs";
import type { FamilyLink, WhyMatchedFactor } from "@/lib/types";
import { useContextStrip, useWhyMatched } from "@/lib/queries";

interface TriageModeProps {
  links: FamilyLink[];
  initialIdx: number;
  sessionId: string | null;
  contextStrip?: {
    section_text?: string;
    definitions?: { term: string; definition_text: string }[];
  } | null;
  whyMatchedData?: { factors: WhyMatchedFactor[]; confidence: number } | null;
  onApprove: (linkId: string) => void;
  onReject: (linkId: string) => void;
  onDefer: (linkId: string) => void;
  onNote: (linkId: string, note: string) => void;
  onExit: () => void;
}

// ── Text highlight utilities ────────────────────────────────────────────────

interface HighlightSpan {
  start: number;
  end: number;
  type: "heading" | "exclude" | "definition" | "dna";
}

function buildHighlightSpans(
  text: string,
  headingTerms: string[],
  excludeTerms: string[],
  definitionTerms: string[],
  dnaPhrases: string[],
): HighlightSpan[] {
  const spans: HighlightSpan[] = [];

  function addMatches(terms: string[], type: HighlightSpan["type"]) {
    for (const term of terms) {
      if (!term.trim()) continue;
      const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const re = new RegExp(escaped, "gi");
      let m: RegExpExecArray | null;
      while ((m = re.exec(text)) !== null) {
        spans.push({ start: m.index, end: m.index + m[0].length, type });
      }
    }
  }

  // Priority order: dna > definition > exclude > heading
  // Lower-priority spans added first; higher-priority ones will overwrite in rendering
  addMatches(headingTerms, "heading");
  addMatches(excludeTerms, "exclude");
  addMatches(definitionTerms, "definition");
  addMatches(dnaPhrases, "dna");

  return spans;
}

const PRIORITY: Record<HighlightSpan["type"], number> = {
  heading: 1,
  exclude: 2,
  definition: 3,
  dna: 4,
};

function renderHighlightedText(
  text: string,
  spans: HighlightSpan[],
): React.ReactNode[] {
  if (spans.length === 0) return [text];

  // Build a char-level priority map
  const priority = new Uint8Array(text.length);
  const typeAt = new Array<HighlightSpan["type"] | null>(text.length).fill(null);

  for (const span of spans) {
    const p = PRIORITY[span.type];
    for (let i = span.start; i < span.end; i++) {
      if (p > priority[i]) {
        priority[i] = p;
        typeAt[i] = span.type;
      }
    }
  }

  // Collapse into contiguous runs
  const nodes: React.ReactNode[] = [];
  let i = 0;
  while (i < text.length) {
    const t = typeAt[i];
    if (t === null) {
      let j = i + 1;
      while (j < text.length && typeAt[j] === null) j++;
      nodes.push(text.slice(i, j));
      i = j;
    } else {
      let j = i + 1;
      while (j < text.length && typeAt[j] === t) j++;
      const slice = text.slice(i, j);
      if (t === "heading") {
        nodes.push(
          <mark
            key={`h-${i}`}
            className="bg-transparent text-accent-green font-medium not-italic"
          >
            {slice}
          </mark>,
        );
      } else if (t === "exclude") {
        nodes.push(
          <mark
            key={`e-${i}`}
            className="bg-transparent text-accent-red font-medium not-italic"
          >
            {slice}
          </mark>,
        );
      } else if (t === "definition") {
        nodes.push(
          <span
            key={`d-${i}`}
            className="underline decoration-dotted decoration-blue-400 decoration-1 underline-offset-2 cursor-help"
          >
            {slice}
          </span>,
        );
      } else {
        // dna
        nodes.push(
          <span
            key={`p-${i}`}
            className="underline decoration-solid decoration-purple-400 decoration-1 underline-offset-2"
          >
            {slice}
          </span>,
        );
      }
      i = j;
    }
  }
  return nodes;
}

// ── Mini factor bar ─────────────────────────────────────────────────────────

function FactorBar({ factor, score }: { factor: string; score: number }) {
  const pct = Math.round(score * 100);
  const barColor =
    score >= 0.7
      ? "bg-accent-green"
      : score >= 0.4
        ? "bg-accent-orange"
        : "bg-accent-red";

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-muted truncate leading-tight">
          {factor}
        </span>
        <span className="text-[10px] text-text-secondary tabular-nums ml-1">
          {pct}%
        </span>
      </div>
      <div className="h-1 w-full bg-surface-3 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────

export function TriageMode({
  links,
  initialIdx,
  sessionId,
  contextStrip,
  whyMatchedData,
  onApprove,
  onReject,
  onDefer,
  onNote,
  onExit,
}: TriageModeProps) {
  const [currentIdx, setCurrentIdx] = useState(0);
  const [reviewed, setReviewed] = useState(new Set<string>());
  const [noteInputOpen, setNoteInputOpen] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [hashClusterMode, setHashClusterMode] = useState(false);
  const [filterQuery, setFilterQuery] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);
  const initialAppliedRef = useRef(false);

  const prioritizedLinks = useMemo(() => {
    const rankStatus = (status: string) => (status === "pending_review" ? 0 : status === "deferred" ? 1 : 2);
    const rankTier = (tier: string) => (tier === "low" ? 0 : tier === "medium" ? 1 : 2);
    return [...links].sort((a, b) => {
      const statusDelta = rankStatus(a.status) - rankStatus(b.status);
      if (statusDelta !== 0) return statusDelta;
      const tierDelta = rankTier(a.confidence_tier) - rankTier(b.confidence_tier);
      if (tierDelta !== 0) return tierDelta;
      return a.confidence - b.confidence;
    });
  }, [links]);

  // Cluster by section_text_hash for identical sections
  const clusteredLinks = useMemo(() => {
    if (!hashClusterMode) return prioritizedLinks;
    const seen = new Map<string, FamilyLink>();
    const counts = new Map<string, number>();
    for (const l of prioritizedLinks) {
      // Use section_text_hash when available, fall back to link_id (no dedup)
      const key = l.section_text_hash ?? l.link_id;
      if (!seen.has(key)) {
        seen.set(key, l);
        counts.set(key, 1);
      } else {
        counts.set(key, (counts.get(key) ?? 1) + 1);
      }
    }
    return Array.from(seen.values()).map((l) => ({
      ...l,
      _clusterCount: counts.get(l.section_text_hash ?? l.link_id) ?? 1,
    }));
  }, [prioritizedLinks, hashClusterMode]);

  // Apply dynamic filter
  const displayLinks = useMemo(() => {
    if (!filterQuery.trim()) return clusteredLinks;
    const q = filterQuery.toLowerCase();
    return clusteredLinks.filter(
      (l) =>
        l.heading.toLowerCase().includes(q) ||
        l.family_name.toLowerCase().includes(q) ||
        l.doc_id.toLowerCase().includes(q),
      );
  }, [clusteredLinks, filterQuery]);

  const clusterMembers = useMemo(() => {
    const map = new Map<string, FamilyLink[]>();
    for (const item of prioritizedLinks) {
      const key = item.section_text_hash ?? item.link_id;
      const bucket = map.get(key) ?? [];
      bucket.push(item);
      map.set(key, bucket);
    }
    return map;
  }, [prioritizedLinks]);

  useEffect(() => {
    if (initialAppliedRef.current) return;
    const initialLinkId = links[initialIdx]?.link_id;
    if (!initialLinkId || displayLinks.length === 0) {
      initialAppliedRef.current = true;
      return;
    }
    const idx = displayLinks.findIndex((entry) => entry.link_id === initialLinkId);
    setCurrentIdx(idx >= 0 ? idx : 0);
    initialAppliedRef.current = true;
  }, [links, initialIdx, displayLinks]);

  // Keep index in bounds
  useEffect(() => {
    if (currentIdx >= displayLinks.length && displayLinks.length > 0) {
      setCurrentIdx(displayLinks.length - 1);
    }
  }, [displayLinks.length, currentIdx]);

  const currentLink = displayLinks[currentIdx] ?? null;

  const { data: liveContextStrip } = useContextStrip(currentLink?.link_id ?? null);
  const { data: liveWhyMatchedData } = useWhyMatched(currentLink?.link_id ?? null);

  const effectiveContextStrip = contextStrip ?? liveContextStrip ?? null;
  const effectiveWhyMatchedData = whyMatchedData ?? liveWhyMatchedData ?? null;

  const actionLinkIds = useCallback(
    (target: FamilyLink | null): string[] => {
      if (!target) return [];
      if (!hashClusterMode) return [target.link_id];
      const key = target.section_text_hash ?? target.link_id;
      const group = clusterMembers.get(key) ?? [target];
      return group.map((item) => item.link_id);
    },
    [hashClusterMode, clusterMembers],
  );

  const advance = useCallback(() => {
    setCurrentIdx((prev) => Math.min(prev + 1, displayLinks.length - 1));
    setNoteInputOpen(false);
    setNoteText("");
  }, [displayLinks.length]);

  const handleApprove = useCallback(() => {
    if (!currentLink) return;
    const ids = actionLinkIds(currentLink);
    setReviewed((prev) => {
      const next = new Set(prev);
      for (const id of ids) next.add(id);
      return next;
    });
    for (const id of ids) onApprove(id);
    advance();
  }, [currentLink, onApprove, advance, actionLinkIds]);

  const handleReject = useCallback(() => {
    if (!currentLink) return;
    const ids = actionLinkIds(currentLink);
    setReviewed((prev) => {
      const next = new Set(prev);
      for (const id of ids) next.add(id);
      return next;
    });
    for (const id of ids) onReject(id);
    advance();
  }, [currentLink, onReject, advance, actionLinkIds]);

  const handleDefer = useCallback(() => {
    if (!currentLink) return;
    const ids = actionLinkIds(currentLink);
    setReviewed((prev) => {
      const next = new Set(prev);
      for (const id of ids) next.add(id);
      return next;
    });
    for (const id of ids) onDefer(id);
    advance();
  }, [currentLink, onDefer, advance, actionLinkIds]);

  const handleNoteSubmit = useCallback(() => {
    if (!currentLink || !noteText.trim()) return;
    const ids = actionLinkIds(currentLink);
    for (const id of ids) onNote(id, noteText.trim());
    setNoteInputOpen(false);
    setNoteText("");
  }, [currentLink, noteText, onNote, actionLinkIds]);

  // Keyboard handler
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;

      // Allow Escape even in inputs
      if (e.key === "Escape") {
        e.preventDefault();
        if (filterOpen) {
          setFilterOpen(false);
          setFilterQuery("");
        } else if (noteInputOpen) {
          setNoteInputOpen(false);
          setNoteText("");
        } else {
          onExit();
        }
        return;
      }

      // Skip shortcuts when in input
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;

      switch (e.key) {
        case " ":
          e.preventDefault();
          handleApprove();
          break;
        case "Backspace":
          e.preventDefault();
          handleReject();
          break;
        case "d":
          e.preventDefault();
          handleDefer();
          break;
        case "n":
          e.preventDefault();
          setNoteInputOpen(true);
          break;
        case "g":
          e.preventDefault();
          setHashClusterMode((prev) => !prev);
          break;
        case "/":
          e.preventDefault();
          setFilterOpen(true);
          break;
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleApprove, handleReject, handleDefer, noteInputOpen, filterOpen, onExit]);

  const reviewedCount = reviewed.size;
  const totalCount = displayLinks.length;
  const progressPct = totalCount > 0 ? (reviewedCount / totalCount) * 100 : 0;

  const tierColor =
    currentLink?.confidence_tier === "high"
      ? "green"
      : currentLink?.confidence_tier === "medium"
        ? "orange"
        : "red";

  // Extract terms for text highlighting from whyMatchedData factors
  const headingTerms = useMemo(() => {
    if (!effectiveWhyMatchedData) return [];
    const f = effectiveWhyMatchedData.factors.find((x) => x.factor === "heading");
    return f?.evidence ?? [];
  }, [effectiveWhyMatchedData]);

  const excludeTerms = useMemo(() => {
    if (!effectiveWhyMatchedData) return [];
    const f = effectiveWhyMatchedData.factors.find((x) => x.factor === "exclude");
    return f?.evidence ?? [];
  }, [effectiveWhyMatchedData]);

  const definitionTerms = useMemo(() => {
    return (effectiveContextStrip?.definitions ?? []).map((d) => d.term);
  }, [effectiveContextStrip?.definitions]);

  const dnaPhrases = useMemo(() => {
    if (!effectiveWhyMatchedData) return [];
    const f = effectiveWhyMatchedData.factors.find(
      (x) => x.factor === "dna" || x.factor === "dna_density",
    );
    return f?.evidence ?? [];
  }, [effectiveWhyMatchedData]);

  const highlightedText = useMemo(() => {
    const text = effectiveContextStrip?.section_text;
    if (!text) return null;
    const spans = buildHighlightSpans(
      text,
      headingTerms,
      excludeTerms,
      definitionTerms,
      dnaPhrases,
    );
    return renderHighlightedText(text, spans);
  }, [
    effectiveContextStrip?.section_text,
    headingTerms,
    excludeTerms,
    definitionTerms,
    dnaPhrases,
  ]);

  // Limit factors to 6 for the mini-bar grid
  const displayFactors = useMemo(() => {
    const factors = effectiveWhyMatchedData?.factors ?? [];
    if (factors.length > 0) return factors.slice(0, 6);
    if (!currentLink) return [];
    return [
      {
        factor: "confidence",
        score: currentLink.confidence,
        weight: 1,
        detail: `Model confidence ${(currentLink.confidence * 100).toFixed(0)}%`,
        evidence: currentLink.heading ? [currentLink.heading] : [],
      },
    ];
  }, [effectiveWhyMatchedData, currentLink]);

  return (
    <div
      className="animate-triage-fade-in fixed inset-0 z-50 bg-canvas flex flex-col"
      data-testid="triage-mode"
    >
      {/* Top bar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-border bg-surface-1">
        <div className="flex items-center gap-3">
          {currentLink && (
            <Badge variant="blue">{currentLink.family_name}</Badge>
          )}
          <span
            className="text-sm text-text-secondary tabular-nums"
            data-testid="triage-counter"
          >
            {currentIdx + 1} / {totalCount}
          </span>
          {currentLink && (
            <Badge variant={tierColor as "green" | "orange" | "red"}>
              {(currentLink.confidence * 100).toFixed(0)}%
            </Badge>
          )}
          {hashClusterMode && <Badge variant="purple">Clustered</Badge>}
        </div>
        <div className="flex items-center gap-2">
          {filterOpen && (
            <div className="flex items-center gap-1.5">
              <input
                type="text"
                value={filterQuery}
                onChange={(e) => setFilterQuery(e.target.value)}
                placeholder="Filter queue..."
                className="bg-surface-2 border border-border rounded px-2 py-1 text-sm text-text-primary w-48 focus:outline-none focus:ring-1 focus:ring-accent-blue"
                autoFocus
                data-testid="triage-filter-input"
              />
              {filterQuery && (
                <button
                  type="button"
                  onClick={() => setFilterQuery("")}
                  className="text-xs text-text-muted hover:text-text-primary"
                >
                  Clear
                </button>
              )}
            </div>
          )}
          <span className="text-xs text-text-muted tabular-nums">
            {displayLinks.length}/{clusteredLinks.length}
          </span>
          {!!filterQuery && !filterOpen && (
            <Badge variant="blue" className="text-[10px]">
              Filtered
            </Badge>
          )}
          <button
            type="button"
            onClick={onExit}
            className="px-3 py-1.5 text-sm text-text-muted hover:text-text-primary transition-colors"
            data-testid="triage-exit"
          >
            Esc to exit
          </button>
        </div>
      </div>

      {/* Main card */}
      <div className="flex-1 flex items-center justify-center overflow-auto p-6">
        {currentLink ? (
          <div
            className="w-full max-w-[700px] bg-surface-1 rounded-xl shadow-overlay border border-border overflow-hidden"
            data-testid="triage-card"
          >
            {/* Breadcrumbs */}
            <div className="px-5 pt-4">
              <HierarchyBreadcrumbs
                article={currentLink.section_number.split(".")[0]}
                section={currentLink.section_number}
              />
            </div>

            {/* Heading */}
            <div className="px-5 pt-2 pb-3 border-b border-border">
              <h3 className="text-base font-semibold text-text-primary">
                {currentLink.heading}
              </h3>
              <div className="flex items-center gap-2 mt-1.5">
                <span className="text-xs text-text-muted font-mono">
                  {currentLink.doc_id}
                </span>
                <span className="text-xs text-text-muted">
                  {currentLink.borrower}
                </span>
                {(currentLink as FamilyLink & { _clusterCount?: number })
                  ._clusterCount != null &&
                  (currentLink as FamilyLink & { _clusterCount?: number })
                    ._clusterCount! > 1 && (
                    <Badge variant="purple" data-testid="cluster-count">
                      {
                        (currentLink as FamilyLink & { _clusterCount?: number })
                          ._clusterCount
                      }{" "}
                      identical
                    </Badge>
                  )}
              </div>
            </div>

            {/* Section text with highlights */}
            <div className="px-5 py-4 max-h-64 overflow-y-auto">
              {highlightedText ? (
                <p className="text-sm text-text-primary leading-relaxed whitespace-pre-wrap">
                  {highlightedText}
                </p>
              ) : effectiveContextStrip?.section_text ? (
                <p className="text-sm text-text-primary leading-relaxed whitespace-pre-wrap">
                  {effectiveContextStrip.section_text}
                </p>
              ) : (
                <p className="text-sm text-text-muted italic">
                  Section text not available
                </p>
              )}
            </div>

            {/* 6-factor mini bars in 3-column grid */}
            {displayFactors.length > 0 && (
              <div className="px-5 py-3 border-t border-border bg-surface-2/50">
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
                  Match Factors
                </p>
                <div className="grid grid-cols-3 gap-x-4 gap-y-2">
                  {displayFactors.map((f) => (
                    <FactorBar key={f.factor} factor={f.factor} score={f.score} />
                  ))}
                </div>
              </div>
            )}

            {/* Note input */}
            {noteInputOpen && (
              <div className="px-5 py-3 border-t border-border">
                <input
                  type="text"
                  value={noteText}
                  onChange={(e) => setNoteText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleNoteSubmit();
                    } else if (e.key === "Escape") {
                      e.preventDefault();
                      setNoteInputOpen(false);
                      setNoteText("");
                    }
                  }}
                  placeholder="Type note, Enter to save"
                  className="w-full bg-surface-2 border border-border rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-blue"
                  autoFocus
                  data-testid="triage-note-input"
                />
              </div>
            )}

            {/* Action bar */}
            <div className="flex items-center justify-center gap-3 px-5 py-4 border-t border-border">
              <button
                type="button"
                onClick={handleReject}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-glow-red text-accent-red text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
                data-testid="triage-reject"
              >
                Reject
                <kbd className="inline-flex items-center justify-center rounded border border-accent-red/30 bg-surface-3 px-1.5 py-0.5 text-[10px] font-mono text-accent-red/80 leading-none">
                  ⌫
                </kbd>
              </button>
              <button
                type="button"
                onClick={handleDefer}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-surface-3 text-text-secondary text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
                data-testid="triage-defer"
              >
                Defer
                <kbd className="inline-flex items-center justify-center rounded border border-border bg-surface-4 px-1.5 py-0.5 text-[10px] font-mono text-text-muted leading-none">
                  d
                </kbd>
              </button>
              <button
                type="button"
                onClick={handleApprove}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-glow-green text-accent-green text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
                data-testid="triage-approve"
              >
                Approve
                <kbd className="inline-flex items-center justify-center rounded border border-accent-green/30 bg-surface-3 px-1.5 py-0.5 text-[10px] font-mono text-accent-green/80 leading-none">
                  ␣
                </kbd>
              </button>
            </div>
          </div>
        ) : (
          <div className="text-center">
            <p className="text-lg font-semibold text-text-primary mb-1">
              All items reviewed
            </p>
            <p className="text-sm text-text-muted">
              Press Escape to exit triage mode
            </p>
          </div>
        )}
      </div>

      {/* Progress bar — bottom, h-[3px] */}
      <div className="w-full" data-testid="triage-progress-bar-container">
        <div className="flex items-center gap-2 px-6 py-1 bg-surface-1 border-t border-border">
          <span
            className="text-xs text-text-muted"
            data-testid="triage-progress-label"
          >
            Reviewed {reviewedCount}/{totalCount}
            {sessionId ? " (session)" : ""}
          </span>
        </div>
        <div className="w-full h-[3px] bg-surface-3 overflow-hidden">
          <div
            className="h-full bg-accent-blue transition-all"
            style={{ width: `${totalCount > 0 ? Math.max(progressPct, 1) : 0}%` }}
            data-testid="triage-progress-bar"
          />
        </div>
      </div>
    </div>
  );
}
