"use client";

import { useState } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useReviewStrategyTimeline, useStrategies } from "@/lib/queries";
import { cn, SELECT_CLASS } from "@/lib/cn";

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

export default function ReviewStrategyTimelinePage() {
  const [draftConceptId, setDraftConceptId] = useState("debt_capacity.indebtedness");
  const [conceptId, setConceptId] = useState("debt_capacity.indebtedness");
  const query = useReviewStrategyTimeline(conceptId || null);
  const strategies = useStrategies({ sortBy: "concept_id", sortDir: "asc" });

  return (
    <ViewContainer
      title="Review: Strategy Timeline"
      subtitle="Version evolution, deltas, and judge precision history for a concept."
      actions={
        <div className="flex items-center gap-2">
          <input
            value={draftConceptId}
            onChange={(e) => setDraftConceptId(e.target.value)}
            className={cn(SELECT_CLASS, "w-[320px]")}
            placeholder="concept_id"
            list="review-strategy-concept-ids"
          />
          <button
            onClick={() => setConceptId(draftConceptId.trim())}
            className="px-3 py-1.5 text-xs font-medium rounded-sm bg-accent-blue text-white hover:bg-accent-blue/80 transition-colors"
          >
            Load
          </button>
          <datalist id="review-strategy-concept-ids">
            {(strategies.data?.strategies ?? []).map((s) => (
              <option key={s.concept_id} value={s.concept_id} />
            ))}
          </datalist>
        </div>
      }
    >
      {query.isLoading && <LoadingState message="Loading strategy timeline..." />}

      {query.error && (
        <EmptyState
          title="No Timeline Found"
          message="No strategy versions were found for this concept id yet."
        />
      )}

      {query.data && query.data.versions.length === 0 && (
        <EmptyState title="No Versions" message="No versions are available for this concept." />
      )}

      {query.data && query.data.versions.length > 0 && (
        <div className="overflow-auto border border-border rounded-md">
          <table className="w-full text-xs">
            <thead className="bg-surface-tertiary text-text-muted uppercase">
              <tr>
                <th className="px-3 py-2 text-left">Version</th>
                <th className="px-3 py-2 text-left">Note</th>
                <th className="px-3 py-2 text-right">Headings</th>
                <th className="px-3 py-2 text-right">Keywords</th>
                <th className="px-3 py-2 text-right">DNA</th>
                <th className="px-3 py-2 text-right">Hit</th>
                <th className="px-3 py-2 text-right">Precision</th>
                <th className="px-3 py-2 text-right">Coverage</th>
                <th className="px-3 py-2 text-right">Judge</th>
                <th className="px-3 py-2 text-right">N</th>
              </tr>
            </thead>
            <tbody>
              {query.data.versions.map((v) => (
                <tr key={v.version} className="border-t border-border hover:bg-surface-tertiary/40">
                  <td className="px-3 py-2 font-mono">v{v.version.toString().padStart(3, "0")}</td>
                  <td className="px-3 py-2 max-w-[280px] truncate">{v.note || "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {v.heading_pattern_count}
                    {typeof v.delta.heading_pattern_count === "number" && (
                      <span className="text-text-muted"> ({v.delta.heading_pattern_count >= 0 ? "+" : ""}{v.delta.heading_pattern_count})</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {v.keyword_anchor_count}
                    {typeof v.delta.keyword_anchor_count === "number" && (
                      <span className="text-text-muted"> ({v.delta.keyword_anchor_count >= 0 ? "+" : ""}{v.delta.keyword_anchor_count})</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {v.dna_phrase_count}
                    {typeof v.delta.dna_phrase_count === "number" && (
                      <span className="text-text-muted"> ({v.delta.dna_phrase_count >= 0 ? "+" : ""}{v.delta.dna_phrase_count})</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{pct(v.heading_hit_rate)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{pct(v.keyword_precision)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{pct(v.cohort_coverage)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {v.judge.exists ? pct(v.judge.precision_estimate) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {v.judge.exists ? v.judge.n_sampled : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </ViewContainer>
  );
}
