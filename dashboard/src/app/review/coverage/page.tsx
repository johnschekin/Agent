"use client";

import { useMemo, useState } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useReviewCoverageHeatmap } from "@/lib/queries";
import { cn, SELECT_CLASS } from "@/lib/cn";

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function cellClass(rate: number): string {
  if (rate >= 0.8) return "bg-accent-green/20 text-accent-green";
  if (rate >= 0.6) return "bg-accent-orange/20 text-accent-orange";
  return "bg-accent-red/20 text-accent-red";
}

export default function ReviewCoverageHeatmapPage() {
  const [conceptId, setConceptId] = useState("");
  const [topConcepts, setTopConcepts] = useState(25);

  const query = useReviewCoverageHeatmap({
    conceptId: conceptId.trim() || undefined,
    topConcepts,
  });

  const matrix = useMemo(() => {
    if (!query.data) return new Map<string, Map<string, { hits: number; total: number; hit_rate: number }>>();
    const outer = new Map<string, Map<string, { hits: number; total: number; hit_rate: number }>>();
    for (const cell of query.data.cells) {
      const byTemplate = outer.get(cell.concept_id) ?? new Map();
      byTemplate.set(cell.template_family, {
        hits: cell.hits,
        total: cell.total,
        hit_rate: cell.hit_rate,
      });
      outer.set(cell.concept_id, byTemplate);
    }
    return outer;
  }, [query.data]);

  return (
    <ViewContainer
      title="Review: Coverage Heatmap"
      subtitle="Template-family x concept hit-rate matrix from persisted evidence."
      actions={
        <div className="flex items-center gap-2">
          <input
            value={conceptId}
            onChange={(e) => setConceptId(e.target.value)}
            placeholder="concept_id (optional)"
            className={cn(SELECT_CLASS, "w-[280px]")}
          />
          <select
            value={topConcepts}
            onChange={(e) => setTopConcepts(Number(e.target.value))}
            className={cn(SELECT_CLASS, "w-[140px]")}
          >
            <option value={10}>Top 10</option>
            <option value={25}>Top 25</option>
            <option value={50}>Top 50</option>
            <option value={100}>Top 100</option>
          </select>
        </div>
      }
    >
      {query.isLoading && <LoadingState message="Building coverage matrix..." />}
      {query.error && (
        <EmptyState
          title="Coverage Matrix Unavailable"
          message="Could not load review coverage matrix."
        />
      )}

      {query.data && query.data.concepts.length === 0 && (
        <EmptyState title="No Coverage Cells" message="No evidence rows are available yet." />
      )}

      {query.data && query.data.concepts.length > 0 && (
        <div className="overflow-auto border border-border rounded-md max-h-[72vh]">
          <table className="text-xs min-w-[900px]">
            <thead className="bg-surface-3 text-text-muted uppercase sticky top-0 z-10">
              <tr>
                <th className="px-3 py-2 text-left min-w-[280px]">Concept</th>
                {query.data.templates.map((t) => (
                  <th key={t} className="px-2 py-2 text-center min-w-[110px]">
                    {t}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {query.data.concepts.map((cid) => {
                const byTemplate = matrix.get(cid) ?? new Map();
                return (
                  <tr key={cid} className="border-t border-border">
                    <td className="px-3 py-2 font-mono align-top">{cid}</td>
                    {query.data.templates.map((t) => {
                      const cell = byTemplate.get(t);
                      if (!cell || cell.total === 0) {
                        return (
                          <td key={`${cid}_${t}`} className="px-2 py-2 text-center text-text-muted">
                            —
                          </td>
                        );
                      }
                      return (
                        <td key={`${cid}_${t}`} className="px-2 py-2 text-center">
                          <span className={cn("inline-block px-1.5 py-0.5 rounded text-[11px] tabular-nums", cellClass(cell.hit_rate))}>
                            {pct(cell.hit_rate)}
                          </span>
                          <div className="text-[10px] text-text-muted mt-1">
                            {cell.hits}/{cell.total}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </ViewContainer>
  );
}
