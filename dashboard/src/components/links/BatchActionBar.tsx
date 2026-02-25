"use client";

import { cn } from "@/lib/cn";

interface BatchActionBarProps {
  selectedCount: number;
  onUnlink: () => void;
  onRelink: () => void;
  onBookmark: () => void;
  onClear: () => void;
  className?: string;
}

export function BatchActionBar({
  selectedCount,
  onUnlink,
  onRelink,
  onBookmark,
  onClear,
  className,
}: BatchActionBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div
      className={cn(
        "fixed bottom-6 left-1/2 -translate-x-1/2 z-40",
        "flex items-center gap-3 px-5 py-3",
        "bg-surface-2 border border-border rounded-xl shadow-overlay",
        "animate-batch-bar-in",
        className
      )}
    >
      <span className="text-sm font-medium text-text-primary tabular-nums">
        {selectedCount} selected
      </span>
      <div className="w-px h-5 bg-border" />
      <button onClick={onUnlink} className="btn-ghost text-accent-red text-xs">
        Unlink
      </button>
      <button onClick={onRelink} className="btn-ghost text-accent-green text-xs">
        Relink
      </button>
      <button onClick={onBookmark} className="btn-ghost text-accent-blue text-xs">
        Bookmark
      </button>
      <div className="w-px h-5 bg-border" />
      <button onClick={onClear} className="btn-ghost text-xs">
        Clear
      </button>
    </div>
  );
}
