"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import type { WhyMatchedFactor } from "@/lib/types";

interface WhyMatchedPopoverProps {
  factors: WhyMatchedFactor[];
  confidence: number;
  confidenceTier: string;
  trigger: React.ReactNode;
}

export function WhyMatchedPopover({
  factors,
  confidence,
  confidenceTier,
  trigger,
}: WhyMatchedPopoverProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const tierColor =
    confidenceTier === "high"
      ? "text-accent-green"
      : confidenceTier === "medium"
      ? "text-accent-orange"
      : "text-accent-red";

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={() => setOpen(!open)}
        className="hover:opacity-80 transition-opacity"
      >
        {trigger}
      </button>
      {open && (
        <div className="absolute z-50 top-full mt-1 right-0 w-72 bg-surface-2 border border-border rounded-lg shadow-overlay animate-fade-in p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
              Why Matched
            </span>
            <span className={cn("text-sm font-bold tabular-nums", tierColor)}>
              {(confidence * 100).toFixed(1)}%
            </span>
          </div>

          {/* Factor bars */}
          <div className="space-y-2">
            {factors.map((f, i) => (
              <div key={i}>
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-xs text-text-secondary">{f.factor}</span>
                  <span className="text-xs text-text-muted tabular-nums">
                    {f.score.toFixed(2)} × {f.weight.toFixed(1)}
                  </span>
                </div>
                <div className="progress-bar-track">
                  <div
                    className="progress-bar-fill"
                    style={{ width: `${Math.min(f.score * 100, 100)}%` }}
                  />
                </div>
                {f.detail && (
                  <p className="text-[10px] text-text-muted mt-0.5">{f.detail}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
