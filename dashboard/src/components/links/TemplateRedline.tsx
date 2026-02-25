"use client";

import { useMemo } from "react";
import { cn } from "@/lib/cn";

interface TemplateRedlineProps {
  /** Current section text */
  currentText: string;
  /** Baseline template text (null if no baseline available) */
  baselineText: string | null;
  /** Whether redline mode is active */
  active: boolean;
}

interface DiffSegment {
  type: "same" | "added" | "removed";
  text: string;
}

/**
 * Compute word-level diff between baseline and current text.
 * Simple LCS-based diff for visual display.
 */
function computeWordDiff(baseline: string, current: string): DiffSegment[] {
  const baseWords = baseline.split(/\s+/).filter(Boolean);
  const currWords = current.split(/\s+/).filter(Boolean);

  // Build LCS table
  const m = baseWords.length;
  const n = currWords.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (baseWords[i - 1].toLowerCase() === currWords[j - 1].toLowerCase()) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  // Backtrack to build diff
  const segments: DiffSegment[] = [];
  let i = m;
  let j = n;
  const revSegments: DiffSegment[] = [];

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && baseWords[i - 1].toLowerCase() === currWords[j - 1].toLowerCase()) {
      revSegments.push({ type: "same", text: currWords[j - 1] });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      revSegments.push({ type: "added", text: currWords[j - 1] });
      j--;
    } else {
      revSegments.push({ type: "removed", text: baseWords[i - 1] });
      i--;
    }
  }

  // Reverse and merge consecutive segments of the same type
  for (let k = revSegments.length - 1; k >= 0; k--) {
    const seg = revSegments[k];
    if (segments.length > 0 && segments[segments.length - 1].type === seg.type) {
      segments[segments.length - 1].text += " " + seg.text;
    } else {
      segments.push({ ...seg });
    }
  }

  return segments;
}

export function TemplateRedline({ currentText, baselineText, active }: TemplateRedlineProps) {
  const diff = useMemo(() => {
    if (!active || !baselineText) return null;
    return computeWordDiff(baselineText, currentText);
  }, [active, baselineText, currentText]);

  if (!active) return null;

  if (!baselineText) {
    return (
      <div className="px-4 py-3 bg-surface-2 border border-border rounded-lg text-xs text-text-muted italic">
        No baseline available for this template/family combination.
      </div>
    );
  }

  if (!diff) return null;

  return (
    <div className="px-4 py-3 bg-surface-2 border border-border rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Template Redline
        </span>
        <span className="flex items-center gap-1 text-[10px]">
          <span className="w-2 h-2 rounded-sm bg-accent-green/30" /> Added
          <span className="w-2 h-2 rounded-sm bg-accent-red/30 ml-2" /> Removed
        </span>
      </div>
      <div className="text-sm leading-relaxed">
        {diff.map((seg, i) => (
          <span
            key={i}
            className={cn(
              seg.type === "added" && "bg-accent-green/15 text-accent-green",
              seg.type === "removed" && "bg-accent-red/15 text-accent-red line-through",
              seg.type === "same" && "text-text-primary"
            )}
          >
            {seg.text}{" "}
          </span>
        ))}
      </div>
    </div>
  );
}
