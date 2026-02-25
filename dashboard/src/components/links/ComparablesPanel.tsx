"use client";

import { useComparables } from "@/lib/queries";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";

interface ComparablesPanelProps {
  linkId: string | null;
  onPinAsTP?: (docId: string, sectionNumber: string) => void;
  onUseAsBaseline?: (docId: string, sectionNumber: string) => void;
  className?: string;
}

export function ComparablesPanel({
  linkId,
  onPinAsTP,
  onUseAsBaseline,
  className,
}: ComparablesPanelProps) {
  const { data, isLoading } = useComparables(linkId);

  if (!linkId) return null;

  return (
    <div className={cn("bg-surface-1 border-l border-border overflow-y-auto", className)}>
      <div className="p-3 border-b border-border">
        <h4 className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">
          Comparables
        </h4>
      </div>

      {isLoading ? (
        <div className="p-4 text-xs text-text-muted">Loading comparables...</div>
      ) : !data || data.comparables.length === 0 ? (
        <div className="p-4 text-xs text-text-muted">No comparable sections found</div>
      ) : (
        <div className="divide-y divide-border/50">
          {data.comparables.slice(0, 5).map((comp) => (
            <div key={`${comp.doc_id}:${comp.section_number}`} className="p-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-text-primary truncate">
                  {comp.borrower}
                </span>
                <Badge variant={comp.similarity_score >= 0.8 ? "green" : "default"}>
                  {(comp.similarity_score * 100).toFixed(0)}%
                </Badge>
              </div>
              <div className="text-[10px] text-text-muted mb-1.5">
                {comp.doc_id} &middot; {comp.section_number} &middot; {comp.template_family}
              </div>
              <p className="text-xs text-text-secondary leading-relaxed mb-2">
                {comp.text_preview.slice(0, 200)}
                {comp.text_preview.length > 200 && "..."}
              </p>
              <div className="flex items-center gap-2">
                {onPinAsTP && (
                  <button
                    onClick={() => onPinAsTP(comp.doc_id, comp.section_number)}
                    className="btn-ghost text-[10px] text-accent-green"
                  >
                    Pin as TP
                  </button>
                )}
                {onUseAsBaseline && (
                  <button
                    onClick={() => onUseAsBaseline(comp.doc_id, comp.section_number)}
                    className="btn-ghost text-[10px] text-accent-blue"
                  >
                    Use as baseline
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
