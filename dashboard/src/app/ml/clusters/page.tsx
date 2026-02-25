"use client";

import { useState } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { Badge } from "@/components/ui/Badge";
import { useHeadingClusters, useConceptsWithEvidence } from "@/lib/queries";
import { cn, SELECT_CLASS } from "@/lib/cn";

export default function ClustersPage() {
  const [conceptId, setConceptId] = useState<string | null>(null);
  const [expandedHeading, setExpandedHeading] = useState<string | null>(null);

  const conceptsQuery = useConceptsWithEvidence();
  const clustersQuery = useHeadingClusters(conceptId);

  return (
    <ViewContainer
      title="Clause Clusters"
      subtitle="Heading patterns grouped by similarity per concept."
      actions={
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Concept</span>
          <select
            value={conceptId ?? ""}
            onChange={(e) => {
              setConceptId(e.target.value || null);
              setExpandedHeading(null);
            }}
            className={cn(SELECT_CLASS, "w-[320px]")}
          >
            <option value="">-- Select a concept --</option>
            {conceptsQuery.data?.concepts.map((c) => (
              <option key={c.concept_id} value={c.concept_id}>
                {c.concept_id} ({c.hit_count} hits)
              </option>
            ))}
          </select>
        </div>
      }
    >
      {/* Loading concepts */}
      {conceptsQuery.isLoading && (
        <LoadingState message="Loading concepts..." />
      )}
      {conceptsQuery.error && (
        <EmptyState
          title="Concepts Unavailable"
          message="Could not load concept list from evidence."
        />
      )}

      {/* No concept selected */}
      {!conceptId && conceptsQuery.data && (
        <EmptyState
          title="Select a Concept"
          message="Choose a concept from the dropdown above to view heading clusters."
        />
      )}

      {/* Loading clusters */}
      {conceptId && clustersQuery.isLoading && (
        <LoadingState message="Clustering headings..." />
      )}
      {conceptId && clustersQuery.error && (
        <EmptyState
          title="Clusters Unavailable"
          message="Could not load heading clusters for this concept."
        />
      )}

      {/* Clusters loaded */}
      {clustersQuery.data && (
        <>
          <KpiCardGrid className="mb-4">
            <KpiCard
              title="Total Clusters"
              value={clustersQuery.data.kpis.total_clusters}
              color="blue"
            />
            <KpiCard
              title="Known Headings"
              value={clustersQuery.data.kpis.known_headings}
              subtitle="In strategy"
              color="green"
            />
            <KpiCard
              title="Unknown Headings"
              value={clustersQuery.data.kpis.unknown_headings}
              subtitle="Not in strategy"
              color="orange"
            />
            <KpiCard
              title="Orphan Headings"
              value={clustersQuery.data.kpis.orphan_headings}
              subtitle="Single doc only"
              color="red"
            />
            <KpiCard
              title="Total HITs"
              value={clustersQuery.data.kpis.total_hits}
            />
            <KpiCard
              title="Unique Docs"
              value={clustersQuery.data.kpis.unique_docs}
            />
          </KpiCardGrid>

          {/* Strategy patterns reference */}
          {clustersQuery.data.strategy_heading_patterns.length > 0 && (
            <div className="mb-4 rounded-md border border-border bg-surface-2 p-3">
              <div className="text-xs font-semibold text-text-primary mb-1.5">
                Strategy Heading Patterns ({clustersQuery.data.strategy_heading_patterns.length})
              </div>
              <div className="flex flex-wrap gap-1.5">
                {clustersQuery.data.strategy_heading_patterns.map((p) => (
                  <span
                    key={p}
                    className="px-2 py-0.5 rounded text-[11px] bg-accent-green/15 text-accent-green font-mono"
                  >
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Cluster table */}
          {clustersQuery.data.clusters.length === 0 ? (
            <EmptyState
              title="No Clusters"
              message="No HIT evidence rows found for this concept."
            />
          ) : (
            <div className="overflow-auto border border-border rounded-md max-h-[65vh]">
              <table className="w-full text-xs">
                <thead className="bg-surface-3 text-text-muted uppercase sticky top-0 z-10">
                  <tr>
                    <th className="px-3 py-2 text-left">Heading</th>
                    <th className="px-3 py-2 text-right">Docs</th>
                    <th className="px-3 py-2 text-left">Templates</th>
                    <th className="px-3 py-2 text-right">Avg Score</th>
                    <th className="px-3 py-2 text-right">Range</th>
                    <th className="px-3 py-2 text-left">Match Types</th>
                  </tr>
                </thead>
                <tbody>
                  {clustersQuery.data.clusters.map((c) => (
                    <>
                      <tr
                        key={c.heading_normalized}
                        className={cn(
                          "border-t border-border cursor-pointer transition-colors",
                          expandedHeading === c.heading_normalized
                            ? "bg-surface-2"
                            : "hover:bg-surface-3/40"
                        )}
                        onClick={() =>
                          setExpandedHeading(
                            expandedHeading === c.heading_normalized
                              ? null
                              : c.heading_normalized
                          )
                        }
                      >
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-1.5">
                            <span className="max-w-[300px] truncate">
                              {c.heading_display}
                            </span>
                            {c.in_strategy ? (
                              <Badge variant="green">Known</Badge>
                            ) : (
                              <Badge variant="orange">Unknown</Badge>
                            )}
                            {c.is_orphan && (
                              <Badge variant="red">Orphan</Badge>
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {c.doc_count}
                        </td>
                        <td className="px-3 py-2 text-text-muted">
                          {c.template_families.join(", ") || "—"}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {c.avg_score.toFixed(3)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-text-muted">
                          {c.min_score.toFixed(2)}–{c.max_score.toFixed(2)}
                        </td>
                        <td className="px-3 py-2 text-text-muted">
                          {c.match_types.join(", ") || "—"}
                        </td>
                      </tr>
                      {expandedHeading === c.heading_normalized && (
                        <tr key={`${c.heading_normalized}_docs`}>
                          <td
                            colSpan={6}
                            className="px-4 py-3 bg-surface-2/50"
                          >
                            <div className="text-[11px] font-semibold text-text-primary mb-1.5">
                              Documents ({c.doc_count}
                              {c.doc_ids.length < c.doc_count
                                ? `, showing ${c.doc_ids.length}`
                                : ""}
                              )
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {c.doc_ids.map((d) => (
                                <span
                                  key={d}
                                  className="px-1.5 py-0.5 rounded text-[10px] bg-surface-3 text-text-secondary font-mono"
                                >
                                  {d}
                                </span>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </ViewContainer>
  );
}
