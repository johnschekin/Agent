"use client";

import { useState, useCallback } from "react";
import { cn, SELECT_CLASS } from "@/lib/cn";
import type { FeedbackCreateRequest, FeedbackType, FeedbackPriority } from "@/lib/types";

interface FeedbackCreateFormProps {
  onSubmit: (data: FeedbackCreateRequest) => void;
  onCancel: () => void;
  isPending: boolean;
}

export function FeedbackCreateForm({
  onSubmit,
  onCancel,
  isPending,
}: FeedbackCreateFormProps) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState<FeedbackType>("bug");
  const [priority, setPriority] = useState<FeedbackPriority>("medium");
  const [conceptId, setConceptId] = useState("");
  const [description, setDescription] = useState("");

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (title.trim().length < 3) return;
      onSubmit({
        title: title.trim(),
        type,
        priority,
        related_concept_id: conceptId.trim() || null,
        description: description.trim(),
      });
    },
    [title, type, priority, conceptId, description, onSubmit]
  );

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-surface-secondary border border-border rounded-md p-4 space-y-3"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-text-primary">
          New Feedback Item
        </h3>
        <button
          type="button"
          onClick={onCancel}
          className="text-text-muted hover:text-text-primary text-lg leading-none"
        >
          ×
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="md:col-span-2">
          <label className="block text-xs text-text-muted mb-1">
            Title <span className="text-accent-red">*</span>
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Brief description of the issue..."
            className={cn(SELECT_CLASS, "w-full")}
            required
            minLength={3}
            maxLength={200}
          />
        </div>

        <div>
          <label className="block text-xs text-text-muted mb-1">Type</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value as FeedbackType)}
            className={cn(SELECT_CLASS, "w-full")}
          >
            <option value="bug">Bug</option>
            <option value="improvement">Improvement</option>
            <option value="question">Question</option>
          </select>
        </div>

        <div>
          <label className="block text-xs text-text-muted mb-1">
            Priority
          </label>
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value as FeedbackPriority)}
            className={cn(SELECT_CLASS, "w-full")}
          >
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>

        <div className="md:col-span-2">
          <label className="block text-xs text-text-muted mb-1">
            Related Concept ID (optional)
          </label>
          <input
            type="text"
            value={conceptId}
            onChange={(e) => setConceptId(e.target.value)}
            placeholder="e.g. debt_capacity.indebtedness.general_basket"
            className={cn(SELECT_CLASS, "w-full font-mono text-[11px]")}
          />
        </div>

        <div className="md:col-span-2">
          <label className="block text-xs text-text-muted mb-1">
            Description (optional)
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Additional details..."
            className={cn(SELECT_CLASS, "w-full h-20 resize-y")}
            maxLength={2000}
          />
        </div>
      </div>

      <div className="flex items-center gap-2 pt-1">
        <button
          type="submit"
          disabled={isPending || title.trim().length < 3}
          className={cn(
            "px-3 py-1.5 text-xs font-medium rounded",
            "bg-accent-blue text-white hover:bg-accent-blue/90",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "transition-colors"
          )}
        >
          {isPending ? "Creating..." : "Create"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
