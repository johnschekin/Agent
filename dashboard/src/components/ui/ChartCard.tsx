import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface ChartCardProps {
  title: string;
  children: ReactNode;
  className?: string;
  height?: string;
}

export function ChartCard({
  title,
  children,
  className,
  height = "300px",
}: ChartCardProps) {
  return (
    <div
      className={cn(
        "bg-surface-secondary border border-border rounded-md",
        className
      )}
    >
      {title ? (
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-sm font-medium text-text-secondary">{title}</h3>
        </div>
      ) : null}
      <div className="p-4" style={{ height }}>
        {children}
      </div>
    </div>
  );
}
