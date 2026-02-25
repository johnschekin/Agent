"use client";

import { useCallback, useMemo, useRef, useState, useEffect } from "react";
import dynamic from "next/dynamic";
import { useOntologyGraph } from "@/lib/queries";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { cn, SELECT_CLASS } from "@/lib/cn";
import type { OntologyNodeType } from "@/lib/types";

// Dynamic import — react-force-graph-2d uses Canvas/WebGL which is client-only
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => <LoadingState message="Loading graph renderer..." />,
});

// --- Domain color map (hex for canvas rendering) ---
const DOMAIN_COLORS: Record<string, string> = {
  deal_econ: "#3B82F6",
  debt_capacity: "#22C55E",
  cash_flow: "#F59E0B",
  fin_framework: "#A855F7",
  credit_protection: "#EF4444",
  governance: "#00A396",
};

// Edge type colors (top 8 types get distinct colors, rest get gray)
const EDGE_TYPE_COLORS: Record<string, string> = {
  CONSTRAINS: "#EF4444",
  FEEDS_INTO: "#22C55E",
  MIRRORS: "#3B82F6",
  SHARED_CAP: "#F59E0B",
  DEPENDS_ON: "#A855F7",
  EXCLUDES_FROM: "#C23E83",
  STACKS_WITH: "#00A396",
  TRIGGERS: "#00B3D4",
};

const DEFAULT_EDGE_COLOR = "#404854";

// Node size by level (domains largest)
const LEVEL_SIZE: Record<number, number> = {
  0: 14,
  1: 10,
  2: 7,
  3: 5,
  4: 4,
};

interface OntologyGraphProps {
  centerId: string;
  depth: number;
  onDepthChange: (depth: number) => void;
  onNodeClick: (nodeId: string) => void;
}

export function OntologyGraph({
  centerId,
  depth,
  onDepthChange,
  onNodeClick,
}: OntologyGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // M2 RT5 FIX: Track container size via ResizeObserver so graph resizes with panel
  const [containerSize, setContainerSize] = useState({ width: 600, height: 400 });
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setContainerSize({
          width: Math.round(entry.contentRect.width),
          height: Math.round(entry.contentRect.height),
        });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { data, isLoading, error } = useOntologyGraph({
    center: centerId,
    depth,
    maxNodes: 80,
  });

  // Transform data for react-force-graph-2d
  const graphData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    return {
      nodes: data.nodes.map((n) => ({
        id: n.id,
        name: n.name,
        type: n.type as OntologyNodeType,
        level: n.level,
        domain_id: n.domain_id,
        isCenter: n.id === centerId,
      })),
      links: data.edges.map((e) => ({
        source: e.source,
        target: e.target,
        edge_type: e.edge_type,
        description: e.description,
      })),
    };
  }, [data, centerId]);

  const handleNodeClick = useCallback(
    (node: { id?: string | number }) => {
      if (node.id) onNodeClick(String(node.id));
    },
    [onNodeClick]
  );

  const nodeCanvasObject = useCallback(
    (node: Record<string, unknown>, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const domainId = (node.domain_id as string) || "";
      const level = (node.level as number) ?? 2;
      const isCenter = node.isCenter as boolean;
      const label = (node.name as string) || "";
      const x = node.x as number;
      const y = node.y as number;

      if (x == null || y == null) return;

      const size = LEVEL_SIZE[level] ?? 4;
      const color = DOMAIN_COLORS[domainId] ?? "#738091";

      // Center node glow
      if (isCenter) {
        ctx.beginPath();
        ctx.arc(x, y, size + 4, 0, 2 * Math.PI);
        ctx.fillStyle = `${color}33`;
        ctx.fill();
      }

      // Node circle
      ctx.beginPath();
      ctx.arc(x, y, size, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();

      if (isCenter) {
        ctx.strokeStyle = "#FFFFFF";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Label (show when zoomed in enough)
      if (globalScale > 0.7 || isCenter || level <= 1) {
        const fontSize = Math.max(10 / globalScale, 3);
        ctx.font = `${isCenter ? "bold " : ""}${fontSize}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = "#EDEFF2";
        ctx.fillText(label, x, y + size + 2);
      }
    },
    []
  );

  const linkColor = useCallback(
    (link: Record<string, unknown>) => {
      const edgeType = link.edge_type as string;
      return EDGE_TYPE_COLORS[edgeType] ?? DEFAULT_EDGE_COLOR;
    },
    []
  );

  return (
    <div className="flex flex-col h-full">
      {/* Depth control */}
      <div className="flex items-center gap-3 px-3 py-2 border-b border-border bg-surface-3 flex-shrink-0">
        <span className="text-xs text-text-muted">Depth:</span>
        {[1, 2, 3].map((d) => (
          <button
            key={d}
            onClick={() => onDepthChange(d)}
            aria-label={`Set graph depth to ${d}`}
            className={cn(
              "px-2 py-0.5 rounded-sm text-xs font-medium transition-colors",
              depth === d
                ? "bg-accent-blue/20 text-accent-blue"
                : "bg-surface-3 text-text-muted hover:text-text-secondary border border-border"
            )}
          >
            {d}
          </button>
        ))}
        <span className="text-xs text-text-muted ml-auto tabular-nums">
          {graphData.nodes.length} nodes, {graphData.links.length} edges
        </span>
      </div>

      {/* Edge type legend */}
      {graphData.links.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 px-3 py-1.5 border-b border-border text-[10px]">
          {Object.entries(EDGE_TYPE_COLORS)
            .filter(([type]) => graphData.links.some((l) => l.edge_type === type))
            .map(([type, color]) => (
              <span key={type} className="flex items-center gap-1">
                <span className="w-2.5 h-0.5 rounded" style={{ backgroundColor: color }} />
                <span className="text-text-muted">{type}</span>
              </span>
            ))}
        </div>
      )}

      {/* Graph */}
      <div ref={containerRef} className="flex-1 min-h-0 relative">
        {isLoading && <LoadingState message="Loading graph..." />}
        {error && <EmptyState title="Graph error" message="Failed to load graph data." />}
        {!isLoading && !error && graphData.nodes.length === 0 && (
          <EmptyState title="No graph data" message="Select a node in the tree to visualize its neighborhood." />
        )}
        {graphData.nodes.length > 0 && (
          <ForceGraph2D
            graphData={graphData}
            width={containerSize.width}
            height={containerSize.height}
            nodeCanvasObject={nodeCanvasObject}
            nodePointerAreaPaint={(node: Record<string, unknown>, color: string, ctx: CanvasRenderingContext2D) => {
              const x = node.x as number;
              const y = node.y as number;
              const level = (node.level as number) ?? 2;
              if (x == null || y == null) return;
              const size = LEVEL_SIZE[level] ?? 4;
              ctx.beginPath();
              ctx.arc(x, y, size + 2, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
            }}
            onNodeClick={handleNodeClick}
            linkColor={linkColor}
            linkWidth={1}
            linkDirectionalArrowLength={4}
            linkDirectionalArrowRelPos={0.85}
            backgroundColor="transparent"
            cooldownTicks={60}
            enableZoomInteraction={true}
            enablePanInteraction={true}
          />
        )}
      </div>
    </div>
  );
}
