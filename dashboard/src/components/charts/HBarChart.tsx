"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { CHART_THEME, CHART_COLORS } from "@/lib/colors";
import { ChartTooltip } from "./ChartTooltip";

interface HBarDatum {
  name: string;
  value: number;
  /** Full untruncated name for tooltip display (M5). Falls back to name. */
  fullName?: string;
}

interface HBarChartProps {
  data: HBarDatum[];
  color?: string;
  tooltipFormatter?: (value: number) => string;
}

export function HBarChart({
  data,
  color = CHART_COLORS.blue,
  tooltipFormatter,
}: HBarChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted text-sm">
        No data
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 8, left: 0, bottom: 4 }}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          stroke={CHART_THEME.gridColor}
          strokeOpacity={CHART_THEME.gridOpacity}
          horizontal={false}
        />
        <XAxis
          type="number"
          tick={{ fill: CHART_THEME.axisColor, fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: CHART_THEME.gridColor }}
        />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fill: CHART_THEME.axisColor, fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={120}
        />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload || payload.length === 0) return null;
            // M5: Look up fullName from the data point for untruncated tooltip label
            const datum = payload[0]?.payload as HBarDatum | undefined;
            const displayLabel = datum?.fullName ?? label;
            return (
              <ChartTooltip
                active={active}
                payload={payload as Array<{ name?: string; value?: number; color?: string }>}
                label={displayLabel}
                formatter={tooltipFormatter}
              />
            );
          }}
          cursor={{ fill: "rgba(255,255,255,0.05)" }}
        />
        <Bar dataKey="value" fill={color} radius={[0, 2, 2, 0]} maxBarSize={24} />
      </BarChart>
    </ResponsiveContainer>
  );
}
