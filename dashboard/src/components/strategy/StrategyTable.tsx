"use client";

import { useMemo } from "react";
import { type ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/components/tables/DataTable";
import { Badge } from "@/components/ui/Badge";
import { StrategyMetricsBar } from "./StrategyMetricsBar";
import type { StrategySummary } from "@/lib/types";
import type { SortingState, OnChangeFn } from "@tanstack/react-table";

const STATUS_VARIANT: Record<string, "green" | "blue" | "orange" | "default"> =
  {
    production: "green",
    corpus_validated: "blue",
    bootstrap: "default",
  };

interface StrategyTableProps {
  strategies: StrategySummary[];
  sorting: SortingState;
  onSortingChange: OnChangeFn<SortingState>;
  onRowClick: (row: StrategySummary) => void;
  selectedConceptId: string | null;
}

export function StrategyTable({
  strategies,
  sorting,
  onSortingChange,
  onRowClick,
  selectedConceptId,
}: StrategyTableProps) {
  const columns = useMemo<ColumnDef<StrategySummary, unknown>[]>(
    () => [
      {
        accessorKey: "concept_name",
        header: "Concept",
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="text-sm font-medium text-text-primary truncate">
              {row.original.concept_name}
            </div>
            <div className="text-[10px] text-text-muted font-mono truncate">
              {row.original.concept_id}
            </div>
          </div>
        ),
      },
      {
        accessorKey: "family",
        header: "Family",
        cell: ({ getValue }) => (
          <Badge variant="green">{getValue() as string}</Badge>
        ),
      },
      {
        accessorKey: "validation_status",
        header: "Status",
        cell: ({ getValue }) => {
          const status = getValue() as string;
          return (
            <Badge variant={STATUS_VARIANT[status] ?? "default"}>
              {status.replace("_", " ")}
            </Badge>
          );
        },
      },
      {
        accessorKey: "version",
        header: "Ver",
        cell: ({ getValue }) => (
          <span className="text-xs tabular-nums text-text-secondary">
            v{getValue() as number}
          </span>
        ),
      },
      {
        accessorKey: "heading_hit_rate",
        header: "Hit Rate",
        cell: ({ getValue }) => (
          <div className="w-24">
            <StrategyMetricsBar
              value={getValue() as number}
              showLabel={false}
            />
          </div>
        ),
      },
      {
        accessorKey: "keyword_precision",
        header: "Precision",
        cell: ({ getValue }) => (
          <div className="w-24">
            <StrategyMetricsBar
              value={getValue() as number}
              showLabel={false}
            />
          </div>
        ),
      },
      {
        accessorKey: "dna_phrase_count",
        header: "DNA",
        cell: ({ getValue }) => (
          <span className="text-xs tabular-nums text-text-secondary">
            {getValue() as number}
          </span>
        ),
      },
      {
        id: "qc",
        header: "QC",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.has_qc_issues ? (
            <span
              className="w-2 h-2 rounded-full bg-accent-red inline-block"
              title="Has QC issues"
            />
          ) : null,
      },
    ],
    []
  );

  return (
    <DataTable
      columns={columns}
      data={strategies}
      sorting={sorting}
      onSortingChange={onSortingChange}
      onRowClick={onRowClick}
      selectedRowId={selectedConceptId ?? undefined}
      getRowId={(row) => row.concept_id}
      totalRows={strategies.length}
      emptyMessage="No strategies found"
    />
  );
}
