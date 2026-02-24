"use client";

import { cn } from "@/lib/cn";

interface StrategyMetricsBarProps {
  value: number; // 0-1
  label?: string;
  showLabel?: boolean;
}

export function StrategyMetricsBar({
  value,
  label,
  showLabel = true,
}: StrategyMetricsBarProps) {
  const pct = Math.round(value * 100);
  const color =
    value >= 0.8
      ? "bg-accent-green"
      : value >= 0.5
        ? "bg-accent-orange"
        : value > 0
          ? "bg-accent-red"
          : "bg-border";

  if (value === 0) {
    return (
      <span className="text-[11px] text-text-muted italic">
        {label ? `${label}: ` : ""}Not tested
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      {label && showLabel && (
        <span className="text-[11px] text-text-muted w-12 flex-shrink-0">
          {label}
        </span>
      )}
      <div className="flex-1 h-1.5 bg-border rounded-full overflow-hidden min-w-[40px]">
        <div
          className={cn("h-full rounded-full transition-all", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span
        className={cn(
          "text-[11px] tabular-nums font-medium w-8 text-right",
          value >= 0.8
            ? "text-accent-green"
            : value >= 0.5
              ? "text-accent-orange"
              : "text-accent-red"
        )}
      >
        {pct}%
      </span>
    </div>
  );
}
