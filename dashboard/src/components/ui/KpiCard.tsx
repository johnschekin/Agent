import { cn } from "@/lib/cn";

// ── Sparkline: 7-bar mini chart ────────────────────────────────────────────

interface SparklineProps {
  data: number[];
  color?: string;
}

function Sparkline({ data, color = "#3B82F6" }: SparklineProps) {
  const max = Math.max(...data, 1);
  const barCount = data.length || 7;
  return (
    <div className="flex items-end gap-[2px] h-5">
      {data.slice(0, 7).map((v, i) => (
        <div
          key={i}
          className="rounded-sm flex-1 min-w-[3px]"
          style={{
            height: `${Math.max((v / max) * 100, 8)}%`,
            backgroundColor: i === barCount - 1 ? color : `${color}60`,
          }}
        />
      ))}
    </div>
  );
}

// ── Trend indicator ────────────────────────────────────────────────────────

interface TrendProps {
  value: number; // percentage change, e.g. 12.5 for +12.5%
}

function TrendIndicator({ value }: TrendProps) {
  if (value === 0) return null;
  const isUp = value > 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs font-medium",
        isUp ? "text-accent-green" : "text-accent-red"
      )}
    >
      <span className="text-[10px]">{isUp ? "▲" : "▼"}</span>
      {Math.abs(value).toFixed(1)}%
    </span>
  );
}

// ── KpiCard ────────────────────────────────────────────────────────────────

interface KpiCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  color?: "blue" | "green" | "red" | "orange" | "purple" | "teal";
  sparkline?: number[];
  trend?: number;
  comparisonSubtitle?: string;
}

const colorMap: Record<string, string> = {
  blue: "#3B82F6",
  green: "#22C55E",
  red: "#EF4444",
  orange: "#F59E0B",
  purple: "#A855F7",
  teal: "#14B8A6",
};

const borderColorMap: Record<string, string> = {
  blue: "border-t-accent-blue",
  green: "border-t-accent-green",
  red: "border-t-accent-red",
  orange: "border-t-accent-orange",
  purple: "border-t-accent-purple",
  teal: "border-t-accent-teal",
};

export function KpiCard({
  title,
  value,
  subtitle,
  color,
  sparkline,
  trend,
  comparisonSubtitle,
}: KpiCardProps) {
  return (
    <div
      className={cn(
        "bg-surface-1 rounded-lg p-4 shadow-card",
        color && `border-t-2 ${borderColorMap[color]}`
      )}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          {title}
        </div>
        {trend !== undefined && <TrendIndicator value={trend} />}
      </div>
      <div className="text-2xl font-bold text-text-primary tabular-nums">
        {value}
      </div>
      {subtitle && (
        <div className="text-xs text-text-secondary mt-1">{subtitle}</div>
      )}
      {comparisonSubtitle && (
        <div className="text-xs text-text-muted mt-0.5">{comparisonSubtitle}</div>
      )}
      {sparkline && sparkline.length > 0 && (
        <div className="mt-2">
          <Sparkline data={sparkline} color={color ? colorMap[color] : undefined} />
        </div>
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
