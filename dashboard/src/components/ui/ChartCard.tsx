import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface ChartCardProps {
  title: string;
  children: ReactNode;
  className?: string;
  height?: string;
  actions?: ReactNode;
}

export function ChartCard({
  title,
  children,
  className,
  height = "300px",
  actions,
}: ChartCardProps) {
  return (
    <div
      className={cn(
        "bg-surface-1 rounded-lg shadow-card",
        className
      )}
    >
      {title ? (
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h3 className="text-sm font-medium text-text-secondary">{title}</h3>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      ) : null}
      <div className="p-4" style={{ height }}>
        {children}
      </div>
    </div>
  );
}
