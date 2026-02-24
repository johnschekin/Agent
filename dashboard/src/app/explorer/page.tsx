"use client";

import { useState, useCallback } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { DocumentTable } from "@/components/tables/DocumentTable";
import { DocumentDetailPanel } from "@/components/detail/DocumentDetailPanel";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useDocuments } from "@/lib/queries";
import type { DocSummary } from "@/lib/types";
import type { SortingState } from "@tanstack/react-table";

export default function ExplorerPage() {
  // Filter state
  const [search, setSearch] = useState("");
  const [docType, setDocType] = useState<string>("");
  const [marketSegment, setMarketSegment] = useState<string>("");
  const [cohortOnly, setCohortOnly] = useState(true);
  const [page, setPage] = useState(0);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "borrower", desc: false },
  ]);

  // Detail panel
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);

  // Build query params
  const sortBy = sorting.length > 0 ? sorting[0].id : "borrower";
  const sortDir = sorting.length > 0 && sorting[0].desc ? "desc" : "asc";

  const { data, isLoading, error } = useDocuments({
    page,
    pageSize: 50,
    sortBy,
    sortDir,
    search: search || undefined,
    docType: docType || undefined,
    marketSegment: marketSegment || undefined,
    cohortOnly,
  });

  const handleRowClick = useCallback((doc: DocSummary) => {
    setSelectedDocId((prev) => (prev === doc.doc_id ? null : doc.doc_id));
  }, []);

  const handleSortingChange = useCallback((newSorting: SortingState) => {
    setSorting(newSorting);
    setPage(0);
  }, []);

  if (error) {
    return (
      <ViewContainer title="Document Explorer">
        <EmptyState
          title="Explorer Unavailable"
          message="Could not load documents. Make sure the API server is running."
        />
      </ViewContainer>
    );
  }

  return (
    <ViewContainer title="Document Explorer">
      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <input
          type="text"
          placeholder="Search borrower, agent, doc_id..."
          aria-label="Search documents"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
          className="px-3 py-1.5 text-sm bg-surface-tertiary border border-border rounded text-text-primary placeholder:text-text-muted w-64 focus:outline-none focus:border-accent-blue"
        />
        <select
          value={docType}
          aria-label="Filter by document type"
          onChange={(e) => {
            setDocType(e.target.value);
            setPage(0);
          }}
          className="px-3 py-1.5 text-sm bg-surface-tertiary border border-border rounded text-text-primary focus:outline-none focus:border-accent-blue"
        >
          <option value="">All Doc Types</option>
          <option value="credit_agreement">Credit Agreement</option>
          <option value="amendment">Amendment</option>
          <option value="waiver">Waiver</option>
          <option value="intercreditor">Intercreditor</option>
          <option value="guaranty">Guaranty</option>
          <option value="supplement">Supplement</option>
          <option value="note_purchase">Note Purchase</option>
          <option value="other">Other</option>
        </select>
        <select
          value={marketSegment}
          aria-label="Filter by market segment"
          onChange={(e) => {
            setMarketSegment(e.target.value);
            setPage(0);
          }}
          className="px-3 py-1.5 text-sm bg-surface-tertiary border border-border rounded text-text-primary focus:outline-none focus:border-accent-blue"
        >
          <option value="">All Segments</option>
          <option value="leveraged">Leveraged</option>
          <option value="investment_grade">Investment Grade</option>
          <option value="uncertain">Uncertain</option>
        </select>
        <label className="flex items-center gap-2 text-sm text-text-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={cohortOnly}
            onChange={(e) => {
              setCohortOnly(e.target.checked);
              setPage(0);
            }}
            className="rounded bg-surface-tertiary border-border"
          />
          Cohort Only
        </label>
        {data && (
          <span className="text-xs text-text-muted ml-auto tabular-nums">
            {data.total.toLocaleString()} documents
          </span>
        )}
      </div>

      {/* Table + Detail Panel */}
      <div className="flex-1 min-h-0 flex">
        <div
          className="flex-1 min-w-0 bg-surface-secondary rounded border border-border overflow-hidden"
          style={{ marginRight: selectedDocId ? 480 : 0, transition: "margin-right 200ms" }}
        >
          {isLoading ? (
            <LoadingState message="Loading documents..." />
          ) : data ? (
            <DocumentTable
              data={data.documents}
              totalRows={data.total}
              page={data.page}
              pageSize={data.page_size}
              onPageChange={setPage}
              sorting={sorting}
              onSortingChange={handleSortingChange}
              onRowClick={handleRowClick}
              selectedDocId={selectedDocId ?? undefined}
            />
          ) : null}
        </div>

        <DocumentDetailPanel
          docId={selectedDocId}
          onClose={() => setSelectedDocId(null)}
        />
      </div>
    </ViewContainer>
  );
}
