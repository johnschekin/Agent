"use client";

import { cn } from "@/lib/cn";

interface SessionProgressBarProps {
  totalReviewed: number;
  totalLinks: number;
  unlinked: number;
  bookmarked: number;
  className?: string;
}

export function SessionProgressBar({
  totalReviewed,
  totalLinks,
  unlinked,
  bookmarked,
  className,
}: SessionProgressBarProps) {
  const pct = totalLinks > 0 ? (totalReviewed / totalLinks) * 100 : 0;

  return (
    <div className={cn("flex items-center gap-3 text-xs", className)}>
      {/* Progress bar */}
      <div className="progress-bar-track w-24">
        <div
          className="progress-bar-fill"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>

      {/* Text summary */}
      <span className="text-text-secondary tabular-nums">
        Reviewed{" "}
        <span className="text-text-primary font-medium">{totalReviewed}</span>
        /{totalLinks}
      </span>

      {/* Unlinked / bookmarked counts */}
      {unlinked > 0 && (
        <span className="text-accent-red tabular-nums">
          {unlinked} unlinked
        </span>
      )}
      {bookmarked > 0 && (
        <span className="text-accent-blue tabular-nums">
          {bookmarked} bookmarked
        </span>
      )}
    </div>
  );
}
