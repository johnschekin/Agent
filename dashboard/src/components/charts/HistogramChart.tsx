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
import type { HistogramBin } from "@/lib/types";

interface HistogramChartProps {
  data: HistogramBin[];
  color?: string;
  xLabel?: string;
  tooltipFormatter?: (value: number) => string;
}

export function HistogramChart({
  data,
  color = CHART_COLORS.blue,
  xLabel,
  tooltipFormatter,
}: HistogramChartProps) {
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
        margin={{ top: 4, right: 8, left: 0, bottom: xLabel ? 20 : 4 }}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          stroke={CHART_THEME.gridColor}
          strokeOpacity={CHART_THEME.gridOpacity}
          vertical={false}
        />
        <XAxis
          dataKey="bin_center"
          tick={{ fill: CHART_THEME.axisColor, fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: CHART_THEME.gridColor }}
          tickFormatter={(v) =>
            typeof v === "number"
              ? v >= 1000
                ? `${(v / 1000).toFixed(0)}K`
                : v.toFixed(0)
              : v
          }
          label={
            xLabel
              ? {
                  value: xLabel,
                  position: "insideBottom",
                  offset: -12,
                  fill: CHART_THEME.axisColor,
                  fontSize: 11,
                }
              : undefined
          }
        />
        <YAxis
          tick={{ fill: CHART_THEME.axisColor, fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={40}
        />
        <Tooltip
          content={<ChartTooltip labelFormatter={tooltipFormatter} />}
          cursor={{ fill: "rgba(255,255,255,0.05)" }}
        />
        <Bar
          dataKey="count"
          fill={color}
          radius={[2, 2, 0, 0]}
          maxBarSize={40}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
