"use client";

import { useMemo } from "react";
import {
  ScatterChart as RechartsScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  Cell,
} from "recharts";
import { CHART_THEME, CHART_COLORS, CATEGORICAL_PALETTE } from "@/lib/colors";
import type { ScatterPoint } from "@/lib/types";

// --- Props ---

interface ScatterPlotProps {
  data: ScatterPoint[];
  /** Display label for X axis */
  xName?: string;
  /** Display label for Y axis */
  yName?: string;
  /** Label for the color dimension (shown in tooltip) */
  colorLabel?: string;
  /** Whether color dimension is categorical (vs numeric gradient) */
  colorCategorical?: boolean;
  logScaleX?: boolean;
  logScaleY?: boolean;
  xFormatter?: (value: number) => string;
  yFormatter?: (value: number) => string;
  onPointClick?: (point: ScatterPoint) => void;
}

// --- Helpers ---

const MAX_CATEGORIES = 12;

/** Interpolate between two hex colors. Inputs must be 6-digit hex (#RRGGBB). */
function lerpColor(a: string, b: string, t: number): string {
  const tc = Math.max(0, Math.min(1, t));
  const ah = parseInt(a.replace("#", ""), 16);
  const bh = parseInt(b.replace("#", ""), 16);
  const ar = (ah >> 16) & 0xff, ag = (ah >> 8) & 0xff, ab = ah & 0xff;
  const br = (bh >> 16) & 0xff, bg = (bh >> 8) & 0xff, bb = bh & 0xff;
  const rr = Math.max(0, Math.min(255, Math.round(ar + (br - ar) * tc)));
  const rg = Math.max(0, Math.min(255, Math.round(ag + (bg - ag) * tc)));
  const rb = Math.max(0, Math.min(255, Math.round(ab + (bb - ab) * tc)));
  return `#${((rr << 16) | (rg << 8) | rb).toString(16).padStart(6, "0")}`;
}

function safeFormat(value: number | null | undefined, formatter?: (v: number) => string): string {
  if (value == null || !Number.isFinite(value)) return "N/A";
  return formatter ? formatter(value) : value.toLocaleString();
}

// --- Tooltip (shared, extracted to avoid duplication) ---

function ScatterTooltipContent({
  active,
  payload,
  xName,
  yName,
  colorLabel,
  xFormatter,
  yFormatter,
}: {
  active?: boolean;
  payload?: Array<{ payload?: ScatterPoint }>;
  xName?: string;
  yName?: string;
  colorLabel?: string;
  xFormatter?: (v: number) => string;
  yFormatter?: (v: number) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;

  return (
    <div
      className="rounded-sm px-3 py-2 text-xs shadow-lg"
      style={{
        backgroundColor: CHART_THEME.tooltipBg,
        border: `1px solid ${CHART_THEME.tooltipBorder}`,
        color: CHART_THEME.tooltipText,
      }}
    >
      <div className="font-medium mb-1">{p.borrower || p.doc_id}</div>
      <div className="text-text-secondary text-[10px] mb-1">{p.doc_id}</div>
      <div className="tabular-nums">
        {xName ?? "X"}: {safeFormat(p.x, xFormatter)}
      </div>
      <div className="tabular-nums">
        {yName ?? "Y"}: {safeFormat(p.y, yFormatter)}
      </div>
      {colorLabel && p.color != null && (
        <div className="text-text-secondary">
          {colorLabel}: {String(p.color)}
        </div>
      )}
    </div>
  );
}

// --- Main component ---

export function ScatterPlot({
  data,
  xName,
  yName,
  colorLabel,
  colorCategorical = false,
  logScaleX = false,
  logScaleY = false,
  xFormatter,
  yFormatter,
  onPointClick,
}: ScatterPlotProps) {
  // H4: Filter NaN/Infinity values
  const cleanData = useMemo(
    () => data.filter((d) => Number.isFinite(d.x) && Number.isFinite(d.y)),
    [data]
  );

  // H3: For log scale, also filter out values <= 0
  const chartData = useMemo(() => {
    let filtered = cleanData;
    if (logScaleX) filtered = filtered.filter((d) => d.x > 0);
    if (logScaleY) filtered = filtered.filter((d) => d.y > 0);
    return filtered;
  }, [cleanData, logScaleX, logScaleY]);

  // L3: Memoize categorical grouping
  const categoryGroups = useMemo(() => {
    if (!colorLabel || !colorCategorical) return null;
    const groups = new Map<string, ScatterPoint[]>();
    for (const point of chartData) {
      const key = String(point.color ?? "unknown");
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(point);
    }
    // L1: Cap categories to MAX_CATEGORIES, roll excess into "Other"
    const entries = Array.from(groups.entries()).sort((a, b) => b[1].length - a[1].length);
    if (entries.length > MAX_CATEGORIES) {
      const kept = entries.slice(0, MAX_CATEGORIES - 1);
      const otherPoints = entries.slice(MAX_CATEGORIES - 1).flatMap(([, pts]) => pts);
      kept.push(["Other", otherPoints]);
      return kept;
    }
    return entries;
  }, [chartData, colorLabel, colorCategorical]);

  // L3: Memoize numeric color range (H1: use reduce instead of spread)
  const { colorMin, colorMax } = useMemo(() => {
    if (!colorLabel || colorCategorical) return { colorMin: 0, colorMax: 1 };
    let min = Infinity;
    let max = -Infinity;
    for (const d of chartData) {
      if (typeof d.color === "number" && Number.isFinite(d.color)) {
        if (d.color < min) min = d.color;
        if (d.color > max) max = d.color;
      }
    }
    if (!Number.isFinite(min)) return { colorMin: 0, colorMax: 1 };
    return { colorMin: min, colorMax: max };
  }, [chartData, colorLabel, colorCategorical]);

  // L3: Memoize per-point colors for non-categorical mode
  const coloredData = useMemo(() => {
    if (categoryGroups) return null; // categorical mode uses grouped Scatters
    return chartData.map((point) => {
      let fill = CHART_COLORS.blue;
      if (colorLabel && !colorCategorical && typeof point.color === "number") {
        const range = colorMax - colorMin;
        const t = range > 0 ? (point.color - colorMin) / range : 0.5;
        fill = lerpColor(CHART_COLORS.blue, CHART_COLORS.red, t); // L4: use design system
      }
      return { ...point, _fill: fill };
    });
  }, [chartData, categoryGroups, colorLabel, colorCategorical, colorMin, colorMax]);

  if (!chartData || chartData.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full text-text-muted text-sm"
        role="status"
      >
        No data
      </div>
    );
  }

  // H2: Safe onClick handler that extracts payload correctly
  const handleClick = onPointClick
    ? (entry: Record<string, unknown>) => {
        // Recharts wraps original data under .payload
        const payload = (entry?.payload ?? entry) as ScatterPoint;
        if (payload?.doc_id) onPointClick(payload);
      }
    : undefined;

  // M2: Single chart structure, branching only for Scatter children
  return (
    <div role="img" aria-label={`Scatter plot: ${xName ?? "X"} vs ${yName ?? "Y"}`}>
      <ResponsiveContainer width="100%" height="100%">
        <RechartsScatterChart
          margin={{ top: 8, right: 16, left: 8, bottom: xName ? 28 : 8 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke={CHART_THEME.gridColor}
            strokeOpacity={CHART_THEME.gridOpacity}
          />
          <XAxis
            dataKey="x"
            type="number"
            scale={logScaleX ? "log" : "auto"}
            domain={logScaleX ? ["dataMin", "dataMax"] : undefined}
            tick={{ fill: CHART_THEME.axisColor, fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: CHART_THEME.gridColor }}
            tickFormatter={xFormatter}
            name={xName ?? "X"}
            label={
              xName
                ? {
                    value: xName,
                    position: "insideBottom",
                    offset: -16,
                    fill: CHART_THEME.axisColor,
                    fontSize: 11,
                  }
                : undefined
            }
          />
          <YAxis
            dataKey="y"
            type="number"
            scale={logScaleY ? "log" : "auto"}
            domain={logScaleY ? ["dataMin", "dataMax"] : undefined}
            tick={{ fill: CHART_THEME.axisColor, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={50}
            tickFormatter={yFormatter}
            name={yName ?? "Y"}
          />
          <Tooltip
            content={(props) => (
              <ScatterTooltipContent
                active={props.active}
                payload={props.payload as Array<{ payload?: ScatterPoint }>}
                xName={xName}
                yName={yName}
                colorLabel={colorLabel}
                xFormatter={xFormatter}
                yFormatter={yFormatter}
              />
            )}
          />

          {/* Categorical: one Scatter per group with auto-legend */}
          {categoryGroups ? (
            <>
              <Legend
                verticalAlign="top"
                height={28}
                formatter={(value: string) => (
                  <span className="text-xs text-text-secondary">{value}</span>
                )}
              />
              {categoryGroups.map(([groupName, points], i) => (
                <Scatter
                  key={groupName}
                  name={groupName.replace(/_/g, " ")}
                  data={points}
                  fill={CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length]}
                  opacity={0.7}
                  onClick={handleClick}
                  cursor={onPointClick ? "pointer" : undefined}
                />
              ))}
            </>
          ) : (
            /* Non-categorical: single Scatter with per-point Cell colors */
            <Scatter
              data={coloredData ?? chartData}
              opacity={0.7}
              onClick={handleClick}
              cursor={onPointClick ? "pointer" : undefined}
            >
              {(coloredData ?? chartData).map((point) => (
                <Cell
                  key={point.doc_id}
                  fill={"_fill" in point ? String(point._fill) : CHART_COLORS.blue}
                />
              ))}
            </Scatter>
          )}
        </RechartsScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
