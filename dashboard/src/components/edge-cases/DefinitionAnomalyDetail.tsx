"use client";

import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingState } from "@/components/ui/Spinner";
import { useEdgeCaseDefinitionDetail } from "@/lib/queries";
import type { EdgeCaseDefinitionDetail } from "@/lib/types";

const CATEGORY_LABELS: Record<string, string> = {
  definition_truncated_at_cap: "Definition Truncated At Cap",
  definition_signature_leak: "Definition Signature Leak",
  definition_malformed_term: "Definition Malformed Term",
};

const CATEGORY_EXPLANATIONS: Record<string, string> = {
  definition_truncated_at_cap:
    "Definition text hit the extraction cap and is likely incomplete.",
  definition_signature_leak:
    "Term text appears to come from a signature block rather than a real definition.",
  definition_malformed_term:
    "Term payload is malformed (e.g., newline-heavy or sentence-like) and likely noisy extraction.",
};

interface SectionGroup {
  sectionKey: string;
  sectionNumber: string;
  sectionHeading: string;
  definitions: EdgeCaseDefinitionDetail[];
}

interface DefinitionAnomalyDetailProps {
  docId: string;
  category: string;
  onClose: () => void;
}

export function DefinitionAnomalyDetail({
  docId,
  category,
  onClose,
}: DefinitionAnomalyDetailProps) {
  const { data, isLoading, error } = useEdgeCaseDefinitionDetail(docId, category);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());

  const sectionGroups = useMemo<SectionGroup[]>(() => {
    if (!data) return [];
    const map = new Map<string, SectionGroup>();
    for (const row of data.definitions) {
      const sectionNumber = row.section_number || "(unmapped)";
      const sectionHeading = row.section_heading || "(no heading)";
      const sectionKey = `${sectionNumber}::${sectionHeading}`;
      if (!map.has(sectionKey)) {
        map.set(sectionKey, {
          sectionKey,
          sectionNumber,
          sectionHeading,
          definitions: [],
        });
      }
      map.get(sectionKey)?.definitions.push(row);
    }
    return Array.from(map.values()).sort((a, b) =>
      a.sectionNumber.localeCompare(b.sectionNumber, undefined, { numeric: true }),
    );
  }, [data]);

  useMemo(() => {
    if (sectionGroups.length > 0 && expandedSections.size === 0) {
      setExpandedSections(new Set(sectionGroups.map((g) => g.sectionKey)));
    }
  }, [sectionGroups, expandedSections.size]);

  const toggleSection = (sectionKey: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionKey)) next.delete(sectionKey);
      else next.add(sectionKey);
      return next;
    });
  };

  return (
    <div className="mt-4 border border-border rounded-lg bg-surface-2 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 bg-surface-3 border-b border-border">
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-xs font-mono text-accent-blue truncate">{docId.slice(0, 24)}</span>
          <Badge variant="blue">{CATEGORY_LABELS[category] ?? category}</Badge>
          {data && (
            <span className="text-xs text-text-muted">
              {data.total_flagged} definition{data.total_flagged !== 1 ? "s" : ""} flagged
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-text-muted hover:text-text-primary text-sm px-2 py-1 rounded hover:bg-surface-3 transition-colors"
          title="Close drill-down"
        >
          Close
        </button>
      </div>

      {CATEGORY_EXPLANATIONS[category] && (
        <div className="px-4 py-2 text-xs text-text-muted bg-surface-2/50 border-b border-border">
          {CATEGORY_EXPLANATIONS[category]}
        </div>
      )}

      <div className="max-h-[500px] overflow-y-auto">
        {isLoading && <LoadingState message="Loading definition details..." />}
        {error && (
          <EmptyState
            title="Failed to load"
            message="Could not fetch definition detail. Check the API server."
          />
        )}
        {data && data.definitions.length === 0 && (
          <EmptyState
            title="No flagged definitions"
            message="No definitions match this anomaly category for this document."
          />
        )}

        {sectionGroups.map((group) => (
          <div key={group.sectionKey} className="border-b border-border last:border-b-0">
            <button
              onClick={() => toggleSection(group.sectionKey)}
              className="w-full flex items-center gap-2 px-4 py-2 text-left hover:bg-surface-3/50 transition-colors"
            >
              <span className="text-[10px] text-text-muted">
                {expandedSections.has(group.sectionKey) ? "\u25BC" : "\u25B6"}
              </span>
              <span className="text-xs font-medium text-text-primary">{group.sectionNumber}</span>
              <span className="text-xs text-text-secondary truncate flex-1">{group.sectionHeading}</span>
              <span className="text-[10px] text-text-muted tabular-nums">{group.definitions.length}</span>
            </button>

            {expandedSections.has(group.sectionKey) && (
              <div className="pb-1">
                {group.definitions.map((row) => (
                  <div
                    key={`${group.sectionKey}:${row.term}:${row.char_start ?? 0}`}
                    className="grid grid-cols-[minmax(180px,1fr)_100px_90px_minmax(220px,2fr)] gap-2 items-start px-4 py-2 border-t border-border/30 hover:bg-surface-3/40 transition-colors"
                  >
                    <div>
                      <div className="text-xs text-text-primary font-medium break-words">{row.term || "(empty term)"}</div>
                      <div className="text-[10px] text-text-muted tabular-nums">
                        {row.char_start ?? "?"} - {row.char_end ?? "?"}
                      </div>
                    </div>
                    <div className="text-xs text-text-secondary">{row.pattern_engine || "unknown"}</div>
                    <div className="text-xs text-text-secondary tabular-nums">{row.definition_length}</div>
                    <div className="text-xs text-text-secondary break-words">{row.tail_snippet || "(no text)"}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
