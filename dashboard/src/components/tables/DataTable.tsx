"use client";

import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type OnChangeFn,
} from "@tanstack/react-table";
import { cn } from "@/lib/cn";

interface DataTableProps<T> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<T, any>[];
  data: T[];
  totalRows?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  onRowClick?: (row: T) => void;
  selectedRowId?: string;
  getRowId?: (row: T) => string;
  loading?: boolean;
  emptyMessage?: string;
}

export function DataTable<T>({
  columns,
  data,
  totalRows,
  page = 0,
  pageSize = 50,
  onPageChange,
  sorting,
  onSortingChange,
  onRowClick,
  selectedRowId,
  getRowId,
  loading,
  emptyMessage = "No data",
}: DataTableProps<T>) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    state: { sorting: sorting ?? [] },
    onSortingChange,
    getRowId: getRowId as (row: T, index: number) => string,
    rowCount: totalRows,
  });

  const totalPages = totalRows ? Math.ceil(totalRows / pageSize) : 1;

  return (
    <div className="flex flex-col h-full">
      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10 bg-surface-tertiary">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  const canSort = header.column.getCanSort();
                  return (
                    <th
                      key={header.id}
                      className={cn(
                        "px-3 py-2 text-left text-xs font-medium text-text-secondary uppercase tracking-wide border-b border-border",
                        canSort && "cursor-pointer select-none hover:text-text-primary"
                      )}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      <div className="flex items-center gap-1">
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {canSort && (
                          <span className="text-[10px]">
                            {sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : "△"}
                          </span>
                        )}
                      </div>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length} className="px-3 py-12 text-center text-text-muted text-sm">
                  Loading...
                </td>
              </tr>
            ) : data.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-3 py-12 text-center text-text-muted text-sm">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => {
                const isSelected = selectedRowId !== undefined && row.id === selectedRowId;
                return (
                  <tr
                    key={row.id}
                    className={cn(
                      "border-b border-border/50 border-l-2 transition-colors",
                      onRowClick && "cursor-pointer",
                      isSelected
                        ? "bg-accent-blue/10 border-l-accent-blue"
                        : "border-l-transparent hover:bg-surface-tertiary/50"
                    )}
                    onClick={() => onRowClick?.(row.original)}
                    onKeyDown={(e) => {
                      if (onRowClick && (e.key === "Enter" || e.key === " ")) {
                        e.preventDefault();
                        onRowClick(row.original);
                      }
                    }}
                    tabIndex={onRowClick ? 0 : undefined}
                    role={onRowClick ? "button" : undefined}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-3 py-2 text-sm text-text-primary">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {onPageChange && totalRows !== undefined && totalRows > pageSize && (
        <div className="flex items-center justify-between px-3 py-2 border-t border-border bg-surface-secondary">
          <span className="text-xs text-text-muted">
            {totalRows.toLocaleString()} total rows
          </span>
          <div className="flex items-center gap-2">
            <button
              className="px-2 py-1 text-xs rounded bg-surface-tertiary text-text-secondary hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed"
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 0}
              aria-label="Previous page"
            >
              Prev
            </button>
            <span className="text-xs text-text-secondary tabular-nums">
              {page + 1} / {totalPages}
            </span>
            <button
              className="px-2 py-1 text-xs rounded bg-surface-tertiary text-text-secondary hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed"
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages - 1}
              aria-label="Next page"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
