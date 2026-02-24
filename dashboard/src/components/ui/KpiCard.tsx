import { cn } from "@/lib/cn";

interface KpiCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  color?: "blue" | "green" | "red" | "orange";
}

const colorMap = {
  blue: "border-t-accent-blue",
  green: "border-t-accent-green",
  red: "border-t-accent-red",
  orange: "border-t-accent-orange",
};

export function KpiCard({ title, value, subtitle, color }: KpiCardProps) {
  return (
    <div
      className={cn(
        "bg-surface-secondary border border-border rounded-md p-4",
        color && `border-t-2 ${colorMap[color]}`
      )}
    >
      <div className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
        {title}
      </div>
      <div className="text-2xl font-bold text-text-primary tabular-nums">
        {value}
      </div>
      {subtitle && (
        <div className="text-xs text-text-secondary mt-1">{subtitle}</div>
      )}
    </div>
  );
}

export function KpiCardGrid({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-6",
        className
      )}
    >
      {children}
    </div>
  );
}
