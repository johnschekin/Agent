"use client";

import { CHART_THEME } from "@/lib/colors";

interface ChartTooltipProps {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number; color?: string }>;
  label?: string | number;
  /** Formats the label (e.g. the bin_center / x-axis value) */
  labelFormatter?: (value: number) => string;
  /** Formats each entry value (e.g. the count) */
  formatter?: (value: number) => string;
}

export function ChartTooltip({
  active,
  payload,
  label,
  labelFormatter,
  formatter,
}: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const formattedLabel =
    labelFormatter && typeof label === "number"
      ? labelFormatter(label)
      : label;

  return (
    <div
      className="rounded-sm px-3 py-2 text-xs shadow-lg"
      style={{
        backgroundColor: CHART_THEME.tooltipBg,
        border: `1px solid ${CHART_THEME.tooltipBorder}`,
        color: CHART_THEME.tooltipText,
      }}
    >
      {formattedLabel !== undefined && (
        <div className="text-text-secondary mb-1">{formattedLabel}</div>
      )}
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center gap-2">
          <div
            className="w-2.5 h-2.5 rounded-sm"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-text-secondary">{entry.name}:</span>
          <span className="font-medium tabular-nums">
            {formatter && typeof entry.value === "number"
              ? formatter(entry.value)
              : entry.value?.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}
