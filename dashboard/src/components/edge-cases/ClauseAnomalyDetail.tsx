"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useEdgeCaseClauseDetail } from "@/lib/queries";
import type { EdgeCaseClauseDetail } from "@/lib/types";

// Depth-based left border colors (reused from ClausePanel)
const DEPTH_COLORS = [
  "border-accent-blue",
  "border-accent-green",
  "border-accent-orange",
  "border-[#A855F7]",
  "border-accent-red",
  "border-accent-teal",
];

function confidenceVariant(c: number): "green" | "orange" | "red" {
  if (c >= 0.8) return "green";
  if (c >= 0.5) return "orange";
  return "red";
}

const CATEGORY_EXPLANATIONS: Record<string, string> = {
  inconsistent_sibling_depth:
    "Sibling clauses under the same parent have different tree nesting levels, indicating structural inconsistency.",
  orphan_deep_clause:
    "Deeply nested clauses (tree level >= 3) whose parent reference does not match any existing clause.",
  deep_nesting_outlier:
    "Clauses nested beyond level 4 (5+ levels deep), which is atypical for credit agreements.",
  low_avg_clause_confidence:
    "Clauses with low parse confidence (< 0.4), indicating the parser was uncertain about the clause boundary.",
  low_structural_ratio:
    "Non-structural clauses (the parser flagged these as non-structural content within clause regions).",
  rootless_deep_clause:
    "Multi-segment clause paths (tree level > 1) with no parent link, indicating the parser failed to connect the hierarchy.",
  clause_root_label_repeat_explosion:
    "A root-level enumerator label repeats excessively within the same section, indicating hierarchy collapse.",
  clause_dup_id_burst:
    "A large share of structural clause IDs required duplicate suffixes (_dupN), indicating parser collisions.",
  clause_depth_reset_after_deep:
    "Clause ordering includes resets from deep nesting directly back to root-level labels in suspicious positions.",
};

const CATEGORY_LABELS: Record<string, string> = {
  inconsistent_sibling_depth: "Inconsistent Sibling Depth",
  orphan_deep_clause: "Orphan Deep Clause",
  deep_nesting_outlier: "Deep Nesting Outlier",
  low_avg_clause_confidence: "Low Clause Confidence",
  low_structural_ratio: "Low Structural Ratio",
  rootless_deep_clause: "Rootless Deep Clause",
  clause_root_label_repeat_explosion: "Root Label Repeat Explosion",
  clause_dup_id_burst: "Clause ID Dup Burst",
  clause_depth_reset_after_deep: "Depth Reset After Deep",
};

interface SectionGroup {
  sectionNumber: string;
  sectionHeading: string;
  clauses: EdgeCaseClauseDetail[];
}

interface ClauseAnomalyDetailProps {
  docId: string;
  category: string;
  onClose: () => void;
}

export function ClauseAnomalyDetail({
  docId,
  category,
  onClose,
}: ClauseAnomalyDetailProps) {
  const { data, isLoading, error } = useEdgeCaseClauseDetail(docId, category);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set()
  );

  // Group clauses by section
  const sectionGroups = useMemo<SectionGroup[]>(() => {
    if (!data) return [];
    const groupMap = new Map<string, SectionGroup>();
    for (const clause of data.clauses) {
      const key = clause.section_number;
      if (!groupMap.has(key)) {
        groupMap.set(key, {
          sectionNumber: clause.section_number,
          sectionHeading: clause.section_heading,
          clauses: [],
        });
      }
      groupMap.get(key)!.clauses.push(clause);
    }
    return Array.from(groupMap.values()).sort((a, b) =>
      a.sectionNumber.localeCompare(b.sectionNumber, undefined, {
        numeric: true,
      })
    );
  }, [data]);

  // Expand all sections by default on first load
  useMemo(() => {
    if (sectionGroups.length > 0 && expandedSections.size === 0) {
      setExpandedSections(new Set(sectionGroups.map((g) => g.sectionNumber)));
    }
  }, [sectionGroups, expandedSections.size]);

  const toggleSection = (sn: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sn)) next.delete(sn);
      else next.add(sn);
      return next;
    });
  };

  return (
    <div className="mt-4 border border-border rounded-lg bg-surface-2 overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-3 bg-surface-3 border-b border-border">
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-xs font-mono text-accent-blue truncate">
            {docId.slice(0, 24)}
          </span>
          <Badge variant="blue">
            {CATEGORY_LABELS[category] ?? category}
          </Badge>
          {data && (
            <span className="text-xs text-text-muted">
              {data.total_flagged} clause{data.total_flagged !== 1 ? "s" : ""}{" "}
              flagged
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

      {/* Explanation */}
      {CATEGORY_EXPLANATIONS[category] && (
        <div className="px-4 py-2 text-xs text-text-muted bg-surface-2/50 border-b border-border">
          {CATEGORY_EXPLANATIONS[category]}
        </div>
      )}

      {/* Content */}
      <div className="max-h-[500px] overflow-y-auto">
        {isLoading && <LoadingState message="Loading clause details..." />}

        {error && (
          <EmptyState
            title="Failed to load"
            message="Could not fetch clause detail. Check the API server."
          />
        )}

        {data && data.clauses.length === 0 && (
          <EmptyState
            title="No flagged clauses"
            message="No clauses match this anomaly category for this document."
          />
        )}

        {sectionGroups.map((group) => (
          <div key={group.sectionNumber} className="border-b border-border last:border-b-0">
            {/* Section header */}
            <button
              onClick={() => toggleSection(group.sectionNumber)}
              className="w-full flex items-center gap-2 px-4 py-2 text-left hover:bg-surface-3/50 transition-colors"
            >
              <span className="text-[10px] text-text-muted">
                {expandedSections.has(group.sectionNumber) ? "\u25BC" : "\u25B6"}
              </span>
              <span className="text-xs font-medium text-text-primary">
                {group.sectionNumber}
              </span>
              <span className="text-xs text-text-secondary truncate flex-1">
                {group.sectionHeading || "(no heading)"}
              </span>
              <span className="text-[10px] text-text-muted tabular-nums">
                {group.clauses.length}
              </span>
            </button>

            {/* Clause rows */}
            {expandedSections.has(group.sectionNumber) && (
              <div className="pb-1">
                {group.clauses.map((clause) => {
                  const depthColor =
                    DEPTH_COLORS[
                      (clause.tree_level - 1) % DEPTH_COLORS.length
                    ];
                  return (
                    <div
                      key={`${clause.section_number}_${clause.clause_id}`}
                      className={cn(
                        "flex items-center gap-2 py-1.5 px-3 text-xs",
                        "border-l-2 hover:bg-surface-3/40 transition-colors",
                        depthColor
                      )}
                      style={{
                        paddingLeft: `${12 + clause.tree_level * 16}px`,
                      }}
                    >
                      {/* Label */}
                      <span className="font-mono text-text-muted w-12 flex-shrink-0">
                        {clause.label}
                      </span>

                      {/* Header text */}
                      <span className="text-text-secondary truncate flex-1 min-w-0">
                        {clause.header_text || "(no header)"}
                      </span>

                      {/* Tree level badge */}
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent-blue/10 text-accent-blue flex-shrink-0">
                        L{clause.tree_level}
                      </span>

                      {/* Enumerator type badge */}
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-surface-3 text-text-muted flex-shrink-0">
                        {clause.level_type}
                      </span>

                      {/* Parent */}
                      {clause.parent_id ? (
                        <span className="text-[10px] text-text-muted font-mono flex-shrink-0">
                          &uarr;{clause.parent_id}
                        </span>
                      ) : (
                        <span className="text-[10px] text-accent-red/70 flex-shrink-0">
                          no parent
                        </span>
                      )}

                      {/* Confidence */}
                      <Badge variant={confidenceVariant(clause.parse_confidence)}>
                        {Math.round(clause.parse_confidence * 100)}%
                      </Badge>

                      {/* Structural indicator */}
                      {clause.is_structural && (
                        <span className="w-1.5 h-1.5 rounded-full bg-accent-blue flex-shrink-0" />
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
