"use client";

import { useMemo, useState } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { Badge } from "@/components/ui/Badge";
import { useReviewQueue } from "@/lib/queries";
import type { ReviewQueueItem } from "@/lib/types";
import { cn, SELECT_CLASS } from "@/lib/cn";

const PRIORITY_VARIANT: Record<string, "red" | "orange" | "default"> = {
  high: "red",
  medium: "orange",
  low: "default",
};

function pct(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

function ConfidenceBar({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="w-16 text-text-muted">{label}</span>
      <div className="flex-1 h-2 bg-surface-tertiary rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full",
            value >= 0.5
              ? "bg-accent-green"
              : value >= 0.25
                ? "bg-accent-orange"
                : "bg-accent-red"
          )}
          style={{ width: `${Math.min(100, value * 100)}%` }}
        />
      </div>
      <span className="w-8 text-right tabular-nums">{pct(value)}</span>
    </div>
  );
}

function ExpandedDetail({ item }: { item: ReviewQueueItem }) {
  const cc = item.confidence_components;
  const riskEntries = Object.entries(item.risk_components).sort(
    (a, b) => b[1] - a[1]
  );

  return (
    <tr>
      <td colSpan={10} className="px-4 py-3 bg-surface-secondary/50">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          {/* Confidence breakdown */}
          <div>
            <div className="font-semibold text-text-primary mb-2">
              Confidence Breakdown
            </div>
            <div className="space-y-1">
              <ConfidenceBar label="Score" value={cc.score} />
              <ConfidenceBar label="Margin" value={cc.margin} />
              <ConfidenceBar label="Channels" value={cc.channels} />
              <ConfidenceBar label="Heading" value={cc.heading} />
              <ConfidenceBar label="Keyword" value={cc.keyword} />
              <ConfidenceBar label="DNA" value={cc.dna} />
            </div>
          </div>

          {/* Outlier flags */}
          <div>
            <div className="font-semibold text-text-primary mb-2">
              Outlier Flags ({item.outlier_flags.length})
            </div>
            <div className="flex flex-wrap gap-1">
              {item.outlier_flags.map((f) => (
                <span
                  key={f}
                  className="px-1.5 py-0.5 rounded text-[10px] bg-surface-tertiary text-text-secondary"
                >
                  {f}
                </span>
              ))}
              {item.outlier_flags.length === 0 && (
                <span className="text-text-muted">None</span>
              )}
            </div>
          </div>

          {/* Risk components */}
          <div>
            <div className="font-semibold text-text-primary mb-2">
              Risk Components
            </div>
            <div className="space-y-1">
              {riskEntries.map(([key, val]) => (
                <div key={key} className="flex items-center gap-2">
                  <span className="w-28 text-text-muted truncate">{key}</span>
                  <div className="flex-1 h-1.5 bg-surface-tertiary rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-accent-red/70"
                      style={{ width: `${Math.min(100, val * 100)}%` }}
                    />
                  </div>
                  <span className="w-8 text-right tabular-nums text-[10px]">
                    {val.toFixed(2)}
                  </span>
                </div>
              ))}
              {riskEntries.length === 0 && (
                <span className="text-text-muted">None</span>
              )}
            </div>
          </div>
        </div>

        {/* Review reasons */}
        <div className="mt-3 flex items-center gap-2">
          <span className="text-[11px] font-semibold text-text-primary">
            Review Reasons:
          </span>
          {item.review_reasons.map((r) => (
            <Badge key={r} variant="blue">
              {r.replace(/_/g, " ")}
            </Badge>
          ))}
        </div>
      </td>
    </tr>
  );
}

export default function ReviewQueuePage() {
  const [priority, setPriority] = useState("");
  const [conceptId, setConceptId] = useState("");
  const [templateFamily, setTemplateFamily] = useState("");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const params = useMemo(
    () => ({
      priority: priority || undefined,
      conceptId: conceptId.trim() || undefined,
      templateFamily: templateFamily.trim() || undefined,
      limit,
      offset,
    }),
    [priority, conceptId, templateFamily, limit, offset]
  );
  const query = useReviewQueue(params);

  return (
    <ViewContainer
      title="Review Queue"
      subtitle="Prioritized evidence items needing human review."
      actions={
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={priority}
            onChange={(e) => {
              setPriority(e.target.value);
              setOffset(0);
            }}
            className={cn(SELECT_CLASS, "w-[130px]")}
          >
            <option value="">All priorities</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <input
            value={conceptId}
            onChange={(e) => {
              setConceptId(e.target.value);
              setOffset(0);
            }}
            placeholder="concept_id"
            className={cn(SELECT_CLASS, "w-[200px]")}
          />
          <input
            value={templateFamily}
            onChange={(e) => {
              setTemplateFamily(e.target.value);
              setOffset(0);
            }}
            placeholder="template_family"
            className={cn(SELECT_CLASS, "w-[180px]")}
          />
          <select
            value={limit}
            onChange={(e) => {
              setLimit(Number(e.target.value));
              setOffset(0);
            }}
            className={cn(SELECT_CLASS, "w-[100px]")}
          >
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
            <option value={500}>500</option>
          </select>
          <button
            onClick={() => {
              setPriority("");
              setConceptId("");
              setTemplateFamily("");
              setLimit(100);
              setOffset(0);
              setExpandedIdx(null);
            }}
            className="px-3 py-1.5 text-xs font-medium rounded-sm bg-surface-tertiary text-text-secondary hover:bg-surface-tertiary/70 transition-colors"
          >
            Reset
          </button>
        </div>
      }
    >
      {query.isLoading && !query.data && (
        <LoadingState message="Scanning evidence for review items..." />
      )}
      {query.error && (
        <EmptyState
          title="Review Queue Unavailable"
          message="Could not load review queue. Make sure the API server is running."
        />
      )}

      {query.data && (
        <>
          <KpiCardGrid className="mb-4">
            <KpiCard
              title="Total Queue"
              value={query.data.kpis.total_queue}
              color="blue"
            />
            <KpiCard
              title="High Priority"
              value={query.data.kpis.high_priority}
              color="red"
            />
            <KpiCard
              title="Medium Priority"
              value={query.data.kpis.medium_priority}
              color="orange"
            />
            <KpiCard
              title="Low Priority"
              value={query.data.kpis.low_priority}
            />
            <KpiCard
              title="Concepts"
              value={query.data.kpis.concepts_affected}
              color="blue"
            />
            <KpiCard
              title="Families"
              value={query.data.kpis.families_affected}
              color="blue"
            />
          </KpiCardGrid>

          {query.data.items.length === 0 ? (
            <EmptyState
              title="No Review Items"
              message="No evidence rows matched the current filters."
            />
          ) : (
            <div className="space-y-2">
              {/* Pagination bar */}
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs text-text-muted">
                  Showing {query.data.items.length} of{" "}
                  {query.data.total_matched} items (offset {offset})
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setOffset(Math.max(0, offset - limit))}
                    disabled={!query.data.has_prev}
                    className="px-2.5 py-1 text-xs rounded-sm border border-border disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface-tertiary"
                  >
                    Prev
                  </button>
                  <button
                    onClick={() => setOffset(offset + limit)}
                    disabled={!query.data.has_next}
                    className="px-2.5 py-1 text-xs rounded-sm border border-border disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface-tertiary"
                  >
                    Next
                  </button>
                </div>
              </div>

              {/* Table */}
              <div className="overflow-auto border border-border rounded-md max-h-[70vh]">
                <table className="w-full text-xs">
                  <thead className="bg-surface-tertiary text-text-muted uppercase sticky top-0 z-10">
                    <tr>
                      <th className="px-3 py-2 text-left">Priority</th>
                      <th className="px-3 py-2 text-left">Concept</th>
                      <th className="px-3 py-2 text-left">Doc</th>
                      <th className="px-3 py-2 text-left">Template</th>
                      <th className="px-3 py-2 text-left">Section</th>
                      <th className="px-3 py-2 text-right">Score</th>
                      <th className="px-3 py-2 text-right">Confidence</th>
                      <th className="px-3 py-2 text-left">Outlier</th>
                      <th className="px-3 py-2 text-left">Flags</th>
                      <th className="px-3 py-2 text-left">Reasons</th>
                    </tr>
                  </thead>
                  <tbody>
                    {query.data.items.map((item, i) => (
                      <>
                        <tr
                          key={`${item.doc_id}_${item.section_number}_${i}`}
                          className={cn(
                            "border-t border-border cursor-pointer transition-colors",
                            expandedIdx === i
                              ? "bg-surface-secondary"
                              : "hover:bg-surface-tertiary/40"
                          )}
                          onClick={() =>
                            setExpandedIdx(expandedIdx === i ? null : i)
                          }
                        >
                          <td className="px-3 py-2">
                            <Badge
                              variant={
                                PRIORITY_VARIANT[item.priority] ?? "default"
                              }
                            >
                              {item.priority}
                            </Badge>
                          </td>
                          <td className="px-3 py-2 font-mono max-w-[200px] truncate">
                            {item.concept_id}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {item.doc_id.slice(0, 8)}
                          </td>
                          <td className="px-3 py-2">
                            {item.template_family || "unknown"}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            {item.section_number}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {item.score != null ? item.score.toFixed(3) : "—"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {pct(item.confidence_final)}
                          </td>
                          <td className="px-3 py-2">
                            <Badge
                              variant={
                                item.outlier_level === "high"
                                  ? "red"
                                  : item.outlier_level === "medium"
                                    ? "orange"
                                    : "default"
                              }
                            >
                              {item.outlier_level}
                            </Badge>
                          </td>
                          <td className="px-3 py-2 text-text-muted">
                            {item.outlier_flags.length}
                          </td>
                          <td className="px-3 py-2">
                            <span className="text-text-muted">
                              {item.review_reasons.length}
                            </span>
                          </td>
                        </tr>
                        {expandedIdx === i && (
                          <ExpandedDetail
                            key={`detail_${i}`}
                            item={item}
                          />
                        )}
                      </>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </ViewContainer>
  );
}
