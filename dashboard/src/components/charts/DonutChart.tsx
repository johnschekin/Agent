"use client";

import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { CATEGORICAL_PALETTE, CHART_THEME } from "@/lib/colors";
import type { CategoryItem } from "@/lib/types";

interface DonutChartProps {
  data: CategoryItem[];
  innerRadius?: number;
  outerRadius?: number;
}

export function DonutChart({
  data,
  innerRadius = 55,
  outerRadius = 80,
}: DonutChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted text-sm">
        No data
      </div>
    );
  }

  const chartData = data.map((d) => ({
    name: d.label,
    value: d.count,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={chartData}
          cx="50%"
          cy="50%"
          innerRadius={innerRadius}
          outerRadius={outerRadius}
          paddingAngle={2}
          dataKey="value"
          stroke="none"
        >
          {chartData.map((_, i) => (
            <Cell
              key={i}
              fill={CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length]}
            />
          ))}
        </Pie>
        <Tooltip
          content={({ active, payload }) => {
            if (!active || !payload || payload.length === 0) return null;
            const entry = payload[0];
            return (
              <div
                className="rounded-sm px-3 py-2 text-xs shadow-lg"
                style={{
                  backgroundColor: CHART_THEME.tooltipBg,
                  border: `1px solid ${CHART_THEME.tooltipBorder}`,
                  color: CHART_THEME.tooltipText,
                }}
              >
                <div className="font-medium">{entry.name}</div>
                <div className="tabular-nums">
                  {(entry.value as number)?.toLocaleString()}
                </div>
              </div>
            );
          }}
        />
        <Legend
          verticalAlign="bottom"
          height={36}
          formatter={(value: string) => (
            <span className="text-xs text-text-secondary">{value}</span>
          )}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
