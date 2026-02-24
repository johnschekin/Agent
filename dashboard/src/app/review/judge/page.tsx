"use client";

import { useState } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useReviewJudgeHistory, useStrategies } from "@/lib/queries";
import { cn, SELECT_CLASS } from "@/lib/cn";

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

export default function ReviewJudgeHistoryPage() {
  const [draftConceptId, setDraftConceptId] = useState("debt_capacity.indebtedness");
  const [conceptId, setConceptId] = useState("debt_capacity.indebtedness");
  const query = useReviewJudgeHistory(conceptId || null);
  const strategies = useStrategies({ sortBy: "concept_id", sortDir: "asc" });

  return (
    <ViewContainer
      title="Review: LLM Judge History"
      subtitle="Judge precision trajectory by strategy version."
      actions={
        <div className="flex items-center gap-2">
          <input
            value={draftConceptId}
            onChange={(e) => setDraftConceptId(e.target.value)}
            className={cn(SELECT_CLASS, "w-[320px]")}
            placeholder="concept_id"
            list="review-judge-concept-ids"
          />
          <button
            onClick={() => setConceptId(draftConceptId.trim())}
            className="px-3 py-1.5 text-xs font-medium rounded-sm bg-accent-blue text-white hover:bg-accent-blue/80 transition-colors"
          >
            Load
          </button>
          <datalist id="review-judge-concept-ids">
            {(strategies.data?.strategies ?? []).map((s) => (
              <option key={s.concept_id} value={s.concept_id} />
            ))}
          </datalist>
        </div>
      }
    >
      {query.isLoading && <LoadingState message="Loading judge history..." />}
      {query.error && (
        <EmptyState
          title="No Judge History"
          message="No persisted judge reports were found for this concept yet."
        />
      )}
      {query.data && query.data.history.length === 0 && (
        <EmptyState title="No Versions" message="No judge rows available for this concept." />
      )}

      {query.data && query.data.history.length > 0 && (
        <div className="overflow-auto border border-border rounded-md">
          <table className="w-full text-xs">
            <thead className="bg-surface-tertiary text-text-muted uppercase">
              <tr>
                <th className="px-3 py-2 text-left">Version</th>
                <th className="px-3 py-2 text-right">Strict Precision</th>
                <th className="px-3 py-2 text-right">Weighted Precision</th>
                <th className="px-3 py-2 text-right">Sampled</th>
                <th className="px-3 py-2 text-right">Correct</th>
                <th className="px-3 py-2 text-right">Partial</th>
                <th className="px-3 py-2 text-right">Wrong</th>
                <th className="px-3 py-2 text-left">Generated</th>
              </tr>
            </thead>
            <tbody>
              {query.data.history.map((row) => (
                <tr key={row.version} className="border-t border-border hover:bg-surface-tertiary/40">
                  <td className="px-3 py-2 font-mono">v{row.version.toString().padStart(3, "0")}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{pct(row.precision_estimate)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{pct(row.weighted_precision_estimate)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.n_sampled}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.correct}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.partial}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.wrong}</td>
                  <td className="px-3 py-2">{row.generated_at || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </ViewContainer>
  );
}
