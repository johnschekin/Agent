"use client";

import { useMemo } from "react";
import { createColumnHelper, type SortingState } from "@tanstack/react-table";
import type { DocSummary } from "@/lib/types";
import { formatNumber, formatCurrencyMM } from "@/lib/formatters";
import { DataTable } from "./DataTable";
import { Badge } from "@/components/ui/Badge";

const col = createColumnHelper<DocSummary>();

interface DocumentTableProps {
  data: DocSummary[];
  totalRows: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  sorting: SortingState;
  onSortingChange: (sorting: SortingState) => void;
  onRowClick: (doc: DocSummary) => void;
  selectedDocId?: string;
  loading?: boolean;
}

export function DocumentTable({
  data,
  totalRows,
  page,
  pageSize,
  onPageChange,
  sorting,
  onSortingChange,
  onRowClick,
  selectedDocId,
  loading,
}: DocumentTableProps) {
  const columns = useMemo(
    () => [
      col.accessor("borrower", {
        header: "Borrower",
        cell: (info) => (
          <span className="truncate max-w-[200px] block" title={info.getValue()}>
            {info.getValue() || "—"}
          </span>
        ),
        enableSorting: true,
      }),
      col.accessor("admin_agent", {
        header: "Admin Agent",
        cell: (info) => (
          <span className="truncate max-w-[140px] block text-text-secondary" title={info.getValue()}>
            {info.getValue() || "—"}
          </span>
        ),
        enableSorting: true,
      }),
      col.accessor("facility_size_mm", {
        header: "Facility ($M)",
        cell: (info) => (
          <span className="tabular-nums text-right block">
            {info.getValue() != null ? formatCurrencyMM(info.getValue()!) : "—"}
          </span>
        ),
        enableSorting: true,
      }),
      col.accessor("doc_type", {
        header: "Doc Type",
        cell: (info) => (
          <Badge variant={info.getValue() === "credit_agreement" ? "green" : "default"}>
            {info.getValue().replace(/_/g, " ")}
          </Badge>
        ),
        enableSorting: true,
      }),
      col.accessor("market_segment", {
        header: "Segment",
        cell: (info) => (
          <Badge variant={info.getValue() === "leveraged" ? "blue" : "default"}>
            {info.getValue().replace(/_/g, " ")}
          </Badge>
        ),
        enableSorting: true,
      }),
      col.accessor("section_count", {
        header: "Sections",
        cell: (info) => (
          <span className="tabular-nums text-right block">{formatNumber(info.getValue())}</span>
        ),
        enableSorting: true,
      }),
      col.accessor("definition_count", {
        header: "Defs",
        cell: (info) => (
          <span className="tabular-nums text-right block">{formatNumber(info.getValue())}</span>
        ),
        enableSorting: true,
      }),
      col.accessor("word_count", {
        header: "Words",
        cell: (info) => (
          <span className="tabular-nums text-right block">{formatNumber(info.getValue())}</span>
        ),
        enableSorting: true,
      }),
      col.accessor("cohort_included", {
        header: "Cohort",
        cell: (info) => (
          <span className={info.getValue() ? "text-accent-green" : "text-text-muted"}>
            {info.getValue() ? "Yes" : "No"}
          </span>
        ),
        enableSorting: true,
      }),
    ],
    []
  );

  return (
    <DataTable
      columns={columns}
      data={data}
      totalRows={totalRows}
      page={page}
      pageSize={pageSize}
      onPageChange={onPageChange}
      sorting={sorting}
      onSortingChange={(updater) => {
        const newSorting = typeof updater === "function" ? updater(sorting) : updater;
        onSortingChange(newSorting);
      }}
      onRowClick={onRowClick}
      selectedRowId={selectedDocId}
      getRowId={(row) => row.doc_id}
      loading={loading}
      emptyMessage="No documents match your filters"
    />
  );
}
