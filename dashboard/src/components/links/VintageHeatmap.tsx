"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";

interface HeatmapCell {
  vintage_year: number;
  template_family: string;
  coverage_pct: number;
  link_count: number;
}

interface TooltipCell {
  template: string;
  year: number;
  pct: number;
  count: number;
  x: number;
  y: number;
}

interface VintageHeatmapProps {
  data: HeatmapCell[];
  onCellClick?: (template: string, vintage: number) => void;
  className?: string;
}

function coverageColor(pct: number): string {
  if (pct >= 0.8) return "bg-accent-green/30";
  if (pct >= 0.5) return "bg-accent-orange/30";
  if (pct >= 0.2) return "bg-accent-orange/20";
  if (pct > 0) return "bg-accent-red/20";
  return "bg-surface-3";
}

function coverageTextColor(pct: number): string {
  if (pct >= 0.8) return "text-accent-green";
  if (pct >= 0.5) return "text-accent-orange";
  if (pct > 0) return "text-accent-red";
  return "text-text-muted";
}

export function VintageHeatmap({ data, onCellClick, className }: VintageHeatmapProps) {
  const [tooltipCell, setTooltipCell] = useState<TooltipCell | null>(null);

  const { years, templates, cellMap } = useMemo(() => {
    const yearSet = new Set<number>();
    const templateSet = new Set<string>();
    const map = new Map<string, HeatmapCell>();

    for (const cell of data) {
      yearSet.add(cell.vintage_year);
      templateSet.add(cell.template_family);
      map.set(`${cell.template_family}:${cell.vintage_year}`, cell);
    }

    return {
      years: Array.from(yearSet).sort(),
      templates: Array.from(templateSet).sort(),
      cellMap: map,
    };
  }, [data]);

  if (data.length === 0) {
    return (
      <div className={cn("overflow-x-auto", className)} data-testid="vintage-heatmap">
        <table className="border-collapse w-full">
          <thead>
            <tr>
              <th className="px-2 py-1.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider">
                Template
              </th>
              <th className="px-2 py-1.5 text-center text-[10px] font-semibold text-text-muted uppercase tracking-wider">
                —
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td colSpan={2} className="text-sm text-text-muted text-center py-8">
                No vintage data available
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className={cn("overflow-x-auto", className)} data-testid="vintage-heatmap">
      <table className="border-collapse">
        <thead>
          <tr>
            <th className="px-2 py-1.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider sticky left-0 bg-surface-1 z-10">
              Template
            </th>
            {years.map((year) => (
              <th
                key={year}
                className="px-2 py-1.5 text-center text-[10px] font-semibold text-text-muted uppercase tracking-wider min-w-14"
              >
                {year}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {templates.map((template) => (
            <tr key={template}>
              <td className="px-2 py-1 text-xs text-text-primary truncate max-w-32 sticky left-0 bg-surface-1 z-10 border-r border-border">
                {template}
              </td>
              {years.map((year) => {
                const cell = cellMap.get(`${template}:${year}`);
                const pct = cell?.coverage_pct ?? 0;
                return (
                  <td
                    key={year}
                    className={cn(
                      "px-2 py-1 text-center transition-colors",
                      onCellClick && "cursor-pointer hover:ring-1 hover:ring-accent-blue",
                    )}
                    onClick={() => onCellClick?.(template, year)}
                    onMouseEnter={(e) => {
                      const rect = (e.target as HTMLElement).getBoundingClientRect();
                      setTooltipCell({
                        template,
                        year,
                        pct,
                        count: cell?.link_count ?? 0,
                        x: rect.left + rect.width / 2,
                        y: rect.top,
                      });
                    }}
                    onMouseLeave={() => setTooltipCell(null)}
                    data-testid={`heatmap-cell-${template}-${year}`}
                  >
                    <div
                      className={cn(
                        "rounded px-1 py-0.5 text-[10px] font-medium tabular-nums",
                        coverageColor(pct),
                        coverageTextColor(pct),
                      )}
                    >
                      {pct > 0 ? `${(pct * 100).toFixed(0)}%` : "\u2014"}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Custom tooltip */}
      {tooltipCell && (
        <div
          className="fixed z-50 bg-surface-1 border border-border rounded-lg shadow-overlay px-3 py-2 pointer-events-none"
          style={{
            left: tooltipCell.x,
            top: tooltipCell.y - 8,
            transform: "translate(-50%, -100%)",
          }}
          data-testid="heatmap-tooltip"
        >
          <p className="text-xs font-semibold text-text-primary">{tooltipCell.template}</p>
          <p className="text-[10px] text-text-muted mt-0.5">Vintage {tooltipCell.year}</p>
          <div className="flex items-center gap-3 mt-1">
            <span className={cn("text-sm font-bold tabular-nums", coverageTextColor(tooltipCell.pct))}>
              {(tooltipCell.pct * 100).toFixed(1)}%
            </span>
            <span className="text-[10px] text-text-muted">
              {tooltipCell.count} {tooltipCell.count === 1 ? "link" : "links"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
