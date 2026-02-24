"use client";

import { useMemo, useCallback } from "react";
import { type ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/components/tables/DataTable";
import { Badge } from "@/components/ui/Badge";
import type { FeedbackItem, FeedbackStatus } from "@/lib/types";

const TYPE_VARIANT: Record<string, "red" | "blue" | "default"> = {
  bug: "red",
  improvement: "blue",
  question: "default",
};

const PRIORITY_VARIANT: Record<string, "red" | "orange" | "default"> = {
  high: "red",
  medium: "orange",
  low: "default",
};

const STATUS_VARIANT: Record<string, "blue" | "orange" | "green"> = {
  open: "blue",
  in_progress: "orange",
  resolved: "green",
};

const NEXT_STATUS: Record<FeedbackStatus, FeedbackStatus> = {
  open: "in_progress",
  in_progress: "resolved",
  resolved: "open",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

interface FeedbackTableProps {
  items: FeedbackItem[];
  onStatusChange: (id: string, newStatus: FeedbackStatus) => void;
  onDelete: (id: string) => void;
}

export function FeedbackTable({
  items,
  onStatusChange,
  onDelete,
}: FeedbackTableProps) {
  const handleStatusClick = useCallback(
    (e: React.MouseEvent, item: FeedbackItem) => {
      e.stopPropagation();
      onStatusChange(item.id, NEXT_STATUS[item.status]);
    },
    [onStatusChange]
  );

  const handleDeleteClick = useCallback(
    (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      onDelete(id);
    },
    [onDelete]
  );

  const columns = useMemo<ColumnDef<FeedbackItem, unknown>[]>(
    () => [
      {
        accessorKey: "title",
        header: "Title",
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="text-sm text-text-primary truncate max-w-[300px]">
              {row.original.title}
            </div>
            {row.original.related_concept_id && (
              <div className="text-[10px] text-text-muted font-mono truncate">
                {row.original.related_concept_id}
              </div>
            )}
          </div>
        ),
      },
      {
        accessorKey: "type",
        header: "Type",
        cell: ({ getValue }) => {
          const t = getValue() as string;
          return <Badge variant={TYPE_VARIANT[t] ?? "default"}>{t}</Badge>;
        },
      },
      {
        accessorKey: "priority",
        header: "Priority",
        cell: ({ getValue }) => {
          const p = getValue() as string;
          return (
            <Badge variant={PRIORITY_VARIANT[p] ?? "default"}>{p}</Badge>
          );
        },
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => {
          const s = row.original.status;
          return (
            <button
              onClick={(e) => handleStatusClick(e, row.original)}
              className="cursor-pointer"
              title={`Click to change to ${NEXT_STATUS[s].replace("_", " ")}`}
            >
              <Badge variant={STATUS_VARIANT[s] ?? "blue"}>
                {s.replace("_", " ")}
              </Badge>
            </button>
          );
        },
      },
      {
        accessorKey: "created_at",
        header: "Created",
        cell: ({ getValue }) => (
          <span className="text-xs text-text-muted tabular-nums">
            {timeAgo(getValue() as string)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) => (
          <button
            onClick={(e) => handleDeleteClick(e, row.original.id)}
            className="text-text-muted hover:text-accent-red text-xs transition-colors"
            title="Delete"
          >
            ×
          </button>
        ),
      },
    ],
    [handleStatusClick, handleDeleteClick]
  );

  return (
    <DataTable
      columns={columns}
      data={items}
      totalRows={items.length}
      getRowId={(row) => row.id}
      emptyMessage="No feedback items"
    />
  );
}
