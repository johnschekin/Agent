"use client";

import { useMemo, useState } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useReviewEvidence } from "@/lib/queries";
import { cn, SELECT_CLASS } from "@/lib/cn";

function score(v: number | null): string {
  if (v == null) return "—";
  return Number(v).toFixed(3);
}

export default function ReviewEvidencePage() {
  const [conceptId, setConceptId] = useState("");
  const [templateFamily, setTemplateFamily] = useState("");
  const [recordType, setRecordType] = useState("");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);
  const params = useMemo(
    () => ({
      conceptId: conceptId.trim() || undefined,
      templateFamily: templateFamily.trim() || undefined,
      recordType: recordType.trim() || undefined,
      limit,
      offset,
    }),
    [conceptId, templateFamily, recordType, limit, offset]
  );
  const query = useReviewEvidence(params);

  return (
    <ViewContainer
      title="Review: Evidence Browser"
      subtitle="Filter and inspect persisted HIT/NOT_FOUND evidence rows."
      actions={
        <div className="flex items-center gap-2">
          <input
            value={conceptId}
            onChange={(e) => {
              setConceptId(e.target.value);
              setOffset(0);
            }}
            placeholder="concept_id"
            className={cn(SELECT_CLASS, "w-[220px]")}
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
            value={recordType}
            onChange={(e) => {
              setRecordType(e.target.value);
              setOffset(0);
            }}
            className={cn(SELECT_CLASS, "w-[140px]")}
          >
            <option value="">All records</option>
            <option value="HIT">HIT</option>
            <option value="NOT_FOUND">NOT_FOUND</option>
          </select>
          <select
            value={limit}
            onChange={(e) => {
              setLimit(Number(e.target.value));
              setOffset(0);
            }}
            className={cn(SELECT_CLASS, "w-[110px]")}
          >
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={250}>250</option>
            <option value={500}>500</option>
          </select>
          <button
            onClick={() => {
              setConceptId("");
              setTemplateFamily("");
              setRecordType("");
              setLimit(100);
              setOffset(0);
            }}
            className="px-3 py-1.5 text-xs font-medium rounded-sm bg-surface-3 text-text-secondary hover:bg-surface-3/70 transition-colors"
          >
            Reset
          </button>
        </div>
      }
    >
      {query.isLoading && <LoadingState message="Loading evidence rows..." />}
      {query.error && (
        <EmptyState
          title="Evidence Unavailable"
          message="Could not load evidence rows from workspace artifacts."
        />
      )}

      {query.data && query.data.rows.length === 0 && (
        <EmptyState title="No Evidence Rows" message="No rows matched the current filters." />
      )}

      {query.data && query.data.rows.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs text-text-muted">
              Returned {query.data.rows_returned} rows
              {" / "}
              matched {query.data.rows_matched}
              {" / "}
              scanned {query.data.rows_scanned}
              {" / "}
              offset {offset}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={!query.data.has_prev}
                className="px-2.5 py-1 text-xs rounded-sm border border-border disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface-3"
              >
                Prev
              </button>
              <button
                onClick={() => setOffset(offset + limit)}
                disabled={!query.data.has_next}
                className="px-2.5 py-1 text-xs rounded-sm border border-border disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface-3"
              >
                Next
              </button>
            </div>
          </div>
          <div className="overflow-auto border border-border rounded-md max-h-[70vh]">
            <table className="w-full text-xs">
              <thead className="bg-surface-3 text-text-muted uppercase sticky top-0 z-10">
                <tr>
                  <th className="px-3 py-2 text-left">Type</th>
                  <th className="px-3 py-2 text-left">Concept</th>
                  <th className="px-3 py-2 text-left">Doc</th>
                  <th className="px-3 py-2 text-left">Template</th>
                  <th className="px-3 py-2 text-left">Section</th>
                  <th className="px-3 py-2 text-left">Heading</th>
                  <th className="px-3 py-2 text-right">Score</th>
                  <th className="px-3 py-2 text-left">Outlier</th>
                  <th className="px-3 py-2 text-left">Tool</th>
                </tr>
              </thead>
              <tbody>
                {query.data.rows.map((r, i) => (
                  <tr key={`${r.doc_id}_${r.section_number}_${i}`} className="border-t border-border hover:bg-surface-3/40">
                    <td className="px-3 py-2">{r.record_type}</td>
                    <td className="px-3 py-2 font-mono">{r.concept_id}</td>
                    <td className="px-3 py-2 font-mono">{r.doc_id}</td>
                    <td className="px-3 py-2">{r.template_family || "unknown"}</td>
                    <td className="px-3 py-2 font-mono">
                      {r.section_number}
                      {r.clause_path ? ` (${r.clause_path})` : ""}
                    </td>
                    <td className="px-3 py-2 max-w-[320px] truncate">{r.heading || "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{score(r.score)}</td>
                    <td className="px-3 py-2">{r.outlier_level || "none"}</td>
                    <td className="px-3 py-2">{r.source_tool || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </ViewContainer>
  );
}
