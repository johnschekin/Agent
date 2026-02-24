"use client";

import { cn } from "@/lib/cn";
import type { OntologyEdge } from "@/lib/types";

// Group edges by edge_type, sorted by count descending
function groupEdges(edges: OntologyEdge[]): [string, OntologyEdge[]][] {
  const groups: Record<string, OntologyEdge[]> = {};
  for (const edge of edges) {
    (groups[edge.edge_type] ??= []).push(edge);
  }
  return Object.entries(groups).sort((a, b) => b[1].length - a[1].length);
}

interface EdgeListProps {
  edges: OntologyEdge[];
  direction: "outgoing" | "incoming";
  onNodeClick: (nodeId: string) => void;
}

export function EdgeList({ edges, direction, onNodeClick }: EdgeListProps) {
  if (edges.length === 0) {
    return (
      <p className="text-xs text-text-muted italic">No {direction} edges</p>
    );
  }

  const grouped = groupEdges(edges);

  return (
    <div className="space-y-2">
      {grouped.map(([edgeType, items]) => (
        <div key={edgeType}>
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
              {edgeType.replace(/_/g, " ")}
            </span>
            <span className="text-[10px] text-text-muted tabular-nums">
              ({items.length})
            </span>
          </div>
          <ul className="space-y-0.5">
            {items.map((edge, i) => {
              const targetId =
                direction === "outgoing" ? edge.target_id : edge.source_id;
              const targetName =
                direction === "outgoing"
                  ? edge.target_name ?? edge.target_id
                  : edge.source_name ?? edge.source_id;

              return (
                <li key={`${edge.source_id}_${edge.target_id}_${i}`} className="flex items-start gap-1.5 text-xs">
                  <span className="text-text-muted mt-0.5 flex-shrink-0">
                    {direction === "outgoing" ? "\u2192" : "\u2190"}
                  </span>
                  <button
                    className="text-accent-blue hover:underline text-left truncate"
                    onClick={() => onNodeClick(targetId)}
                    title={edge.description}
                  >
                    {targetName}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}
