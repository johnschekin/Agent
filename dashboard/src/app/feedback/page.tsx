"use client";

import { useState, useCallback } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { FeedbackTable } from "@/components/feedback/FeedbackTable";
import { FeedbackCreateForm } from "@/components/feedback/FeedbackCreateForm";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { Badge } from "@/components/ui/Badge";
import {
  useFeedback,
  useCreateFeedback,
  useUpdateFeedback,
  useDeleteFeedback,
} from "@/lib/queries";
import type { FeedbackCreateRequest, FeedbackStatus } from "@/lib/types";
import { cn, SELECT_CLASS } from "@/lib/cn";

const STATUS_VARIANT: Record<string, "blue" | "orange" | "green"> = {
  open: "blue",
  in_progress: "orange",
  resolved: "green",
};

export default function FeedbackPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const { data, isLoading, error } = useFeedback({
    status: statusFilter || undefined,
    type: typeFilter || undefined,
    priority: priorityFilter || undefined,
  });

  const createMutation = useCreateFeedback();
  const updateMutation = useUpdateFeedback();
  const deleteMutation = useDeleteFeedback();

  const handleCreate = useCallback(
    (formData: FeedbackCreateRequest) => {
      createMutation.mutate(formData, {
        onSuccess: () => setShowCreate(false),
      });
    },
    [createMutation]
  );

  const handleStatusChange = useCallback(
    (id: string, newStatus: FeedbackStatus) => {
      updateMutation.mutate({ id, data: { status: newStatus } });
    },
    [updateMutation]
  );

  const handleDelete = useCallback(
    (id: string) => {
      deleteMutation.mutate(id);
    },
    [deleteMutation]
  );

  if (error) {
    return (
      <ViewContainer title="Feedback Backlog">
        <EmptyState
          title="Feedback Unavailable"
          message="Could not load feedback. Make sure the API server is running."
        />
      </ViewContainer>
    );
  }

  return (
    <ViewContainer
      title="Feedback Backlog"
      actions={
        !showCreate ? (
          <button
            onClick={() => setShowCreate(true)}
            className={cn(
              "px-3 py-1.5 text-xs font-medium rounded",
              "bg-accent-blue text-white hover:bg-accent-blue/90",
              "transition-colors"
            )}
          >
            + New Feedback
          </button>
        ) : undefined
      }
    >
      {/* Status counts */}
      {data && (
        <div className="flex items-center gap-2 px-6 py-3 border-b border-border">
          {data.status_counts.map((sc) => (
            <Badge key={sc.status} variant={STATUS_VARIANT[sc.status] ?? "blue"}>
              {sc.status.replace("_", " ")}: {sc.count}
            </Badge>
          ))}
          <span className="text-xs text-text-muted ml-2">
            {data.total} total
          </span>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-border flex-wrap">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={cn(SELECT_CLASS, "w-[140px]")}
        >
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="in_progress">In Progress</option>
          <option value="resolved">Resolved</option>
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className={cn(SELECT_CLASS, "w-[140px]")}
        >
          <option value="">All types</option>
          <option value="bug">Bug</option>
          <option value="improvement">Improvement</option>
          <option value="question">Question</option>
        </select>
        <select
          value={priorityFilter}
          onChange={(e) => setPriorityFilter(e.target.value)}
          className={cn(SELECT_CLASS, "w-[140px]")}
        >
          <option value="">All priorities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="px-6 pt-4">
          <FeedbackCreateForm
            onSubmit={handleCreate}
            onCancel={() => setShowCreate(false)}
            isPending={createMutation.isPending}
          />
        </div>
      )}

      {/* Content */}
      <div className="flex-1 min-h-0">
        {isLoading && !data ? (
          <div className="flex items-center justify-center p-8">
            <LoadingState message="Loading feedback..." />
          </div>
        ) : (
          <FeedbackTable
            items={data?.items ?? []}
            onStatusChange={handleStatusChange}
            onDelete={handleDelete}
          />
        )}
      </div>
    </ViewContainer>
  );
}
