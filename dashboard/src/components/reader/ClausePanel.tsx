"use client";

import { useMemo } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import type { ReaderClause } from "@/lib/types";

// Confidence badge color
function confidenceVariant(c: number): "green" | "orange" | "red" {
  if (c >= 0.8) return "green";
  if (c >= 0.5) return "orange";
  return "red";
}

// Depth-based left border colors
const DEPTH_COLORS = [
  "border-accent-blue",
  "border-accent-green",
  "border-accent-orange",
  "border-[#8F56BF]",
  "border-accent-red",
  "border-accent-teal",
];

interface ClausePanelProps {
  clauses: ReaderClause[];
  selectedClauseId: string | null;
  onSelectClause: (clauseId: string | null) => void;
}

export function ClausePanel({
  clauses,
  selectedClauseId,
  onSelectClause,
}: ClausePanelProps) {
  const selected = useMemo(
    () => clauses.find((c) => c.clause_id === selectedClauseId) ?? null,
    [clauses, selectedClauseId]
  );

  if (clauses.length === 0) {
    return (
      <div className="p-4 text-xs text-text-muted italic text-center">
        No clauses parsed for this section
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Clause tree */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-3 py-2 border-b border-border bg-surface-tertiary">
          <span className="text-xs font-medium text-text-muted uppercase tracking-wide">
            Clause Tree ({clauses.length})
          </span>
        </div>
        <div className="py-1">
          {clauses.map((clause) => {
            const isSelected = clause.clause_id === selectedClauseId;
            const depthColor = DEPTH_COLORS[clause.depth % DEPTH_COLORS.length];

            return (
              <button
                key={clause.clause_id}
                className={cn(
                  "w-full text-left flex items-center gap-1.5 py-1 px-2 text-xs",
                  "hover:bg-surface-tertiary/60 transition-colors",
                  "border-l-2",
                  isSelected
                    ? "bg-accent-blue/10 border-accent-blue"
                    : `border-transparent hover:${depthColor}`
                )}
                style={{ paddingLeft: `${8 + clause.depth * 14}px` }}
                onClick={() =>
                  onSelectClause(isSelected ? null : clause.clause_id)
                }
              >
                <span
                  className={cn(
                    "font-mono text-text-muted flex-shrink-0 w-8",
                    isSelected && "text-accent-blue font-medium"
                  )}
                >
                  {clause.label}
                </span>
                <span className="truncate flex-1 text-text-secondary">
                  {clause.header_text || "(no header)"}
                </span>
                {clause.is_structural && (
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-blue flex-shrink-0" />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Selected clause detail */}
      {selected && (
        <div className="border-t border-border px-3 py-3 space-y-2 bg-surface-tertiary flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-text-primary font-mono">
              {selected.label}
            </span>
            <Badge variant={confidenceVariant(selected.parse_confidence)}>
              {Math.round(selected.parse_confidence * 100)}%
            </Badge>
            {selected.is_structural && (
              <Badge variant="blue">structural</Badge>
            )}
          </div>
          <p className="text-xs text-text-secondary leading-relaxed">
            {selected.header_text || "(no header text)"}
          </p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
            <div>
              <span className="text-text-muted">Depth:</span>{" "}
              <span className="text-text-primary">{selected.depth}</span>
            </div>
            <div>
              <span className="text-text-muted">Type:</span>{" "}
              <span className="text-text-primary">{selected.level_type}</span>
            </div>
            <div>
              <span className="text-text-muted">Span:</span>{" "}
              <span className="text-text-primary font-mono tabular-nums">
                {selected.span_start}–{selected.span_end}
              </span>
            </div>
            {selected.parent_id && (
              <div>
                <span className="text-text-muted">Parent:</span>{" "}
                <span className="text-text-primary font-mono">
                  {selected.parent_id}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
