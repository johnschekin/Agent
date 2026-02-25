export function Spinner({ size = 24 }: { size?: number }) {
  return (
    <svg
      className="animate-spin text-accent-blue"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

export function LoadingState({ message = "Loading..." }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-text-secondary">
      <Spinner size={32} />
      <p className="mt-3 text-sm">{message}</p>
    </div>
  );
}

// ── Skeleton loaders ──────────────────────────────────────────────────────

import { cn } from "@/lib/cn";

/** A single shimmer bar. Use `className` to set width/height. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "rounded bg-surface-3 animate-shimmer",
        className,
      )}
      style={{
        backgroundImage:
          "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.04) 50%, transparent 100%)",
        backgroundSize: "200% 100%",
      }}
    />
  );
}

/** Skeleton row that mimics a data table row with N cells. */
export function SkeletonTableRow({ cols = 6 }: { cols?: number }) {
  return (
    <tr className="border-b border-border/30">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-3 py-3">
          <Skeleton className={cn("h-3", i === 0 ? "w-8" : i === 3 ? "w-32" : "w-16")} />
        </td>
      ))}
    </tr>
  );
}

/** Multiple skeleton rows for table loading. */
export function SkeletonTableRows({ rows = 8, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonTableRow key={i} cols={cols} />
      ))}
    </>
  );
}

/** Skeleton for a panel/card content area. */
export function SkeletonPanel({ lines = 4, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-3 p-4", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-3", i === 0 ? "w-3/4" : i === lines - 1 ? "w-1/3" : "w-full")}
        />
      ))}
    </div>
  );
}
