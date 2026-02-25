"use client";

import type { CohortFunnel as CohortFunnelData } from "@/lib/types";
import { cn } from "@/lib/cn";

interface CohortFunnelProps {
  data: CohortFunnelData;
}

export function CohortFunnel({ data }: CohortFunnelProps) {
  const maxCount = data.total;

  return (
    <div className="py-2 space-y-3">
      {/* Total */}
      <div className="flex items-center gap-3">
        <div className="w-36 text-right text-xs text-text-secondary">
          All Documents
        </div>
        <div className="flex-1 relative h-7 bg-surface-1 rounded overflow-hidden">
          <div
            className="absolute inset-y-0 left-0 bg-accent-blue/30 rounded"
            style={{ width: "100%" }}
          />
          <span className="absolute inset-y-0 left-3 flex items-center text-xs font-medium text-text-primary tabular-nums">
            {data.total.toLocaleString()}
          </span>
        </div>
      </div>

      {/* By Doc Type */}
      <div className="pl-[156px] text-xs text-text-muted mb-1">
        By Document Type
      </div>
      {data.by_doc_type.map((item) => {
        const pct = maxCount > 0 ? (item.count / maxCount) * 100 : 0;
        const isCA = item.label === "credit_agreement";
        return (
          <div key={item.label} className="flex items-center gap-3">
            <div className="w-36 text-right text-xs text-text-secondary truncate">
              {item.label.replace(/_/g, " ")}
            </div>
            <div className="flex-1 relative h-6 bg-surface-1 rounded overflow-hidden">
              <div
                className={cn(
                  "absolute inset-y-0 left-0 rounded transition-all",
                  isCA ? "bg-accent-green/40" : "bg-surface-3"
                )}
                style={{ width: `${Math.max(pct, 1)}%` }}
              />
              <span className="absolute inset-y-0 left-3 flex items-center text-xs tabular-nums text-text-primary">
                {item.count.toLocaleString()}
              </span>
            </div>
          </div>
        );
      })}

      {/* By Market Segment (CAs only) */}
      {data.by_market_segment.length > 0 && (
        <>
          <div className="pl-[156px] text-xs text-text-muted mt-2 mb-1">
            Credit Agreements by Market Segment
          </div>
          {data.by_market_segment.map((item) => {
            const caTotal = data.by_doc_type.find(
              (d) => d.label === "credit_agreement"
            )?.count ?? data.total;
            const pct = caTotal > 0 ? (item.count / caTotal) * 100 : 0;
            const isLeveraged = item.label === "leveraged";
            return (
              <div key={item.label} className="flex items-center gap-3">
                <div className="w-36 text-right text-xs text-text-secondary">
                  {item.label.replace(/_/g, " ")}
                </div>
                <div className="flex-1 relative h-6 bg-surface-1 rounded overflow-hidden">
                  <div
                    className={cn(
                      "absolute inset-y-0 left-0 rounded transition-all",
                      isLeveraged ? "bg-accent-green/60" : "bg-surface-3"
                    )}
                    style={{ width: `${Math.max(pct, 1)}%` }}
                  />
                  <span className="absolute inset-y-0 left-3 flex items-center text-xs tabular-nums text-text-primary">
                    {item.count.toLocaleString()}
                    {isLeveraged && " (COHORT)"}
                  </span>
                </div>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
