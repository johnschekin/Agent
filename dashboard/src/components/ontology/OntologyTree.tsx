"use client";

import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { cn } from "@/lib/cn";
import { EmptyState } from "@/components/ui/EmptyState";
import type { OntologyTreeNode, OntologyNodeType } from "@/lib/types";

// --- Domain color map ---
const DOMAIN_DOT_COLORS: Record<string, string> = {
  deal_econ: "bg-accent-blue",
  debt_capacity: "bg-accent-green",
  cash_flow: "bg-accent-orange",
  fin_framework: "bg-[#A855F7]",
  credit_protection: "bg-accent-red",
  governance: "bg-accent-teal",
};

// --- Type badges ---
const TYPE_BADGE_STYLES: Record<OntologyNodeType, string> = {
  domain: "bg-accent-blue/15 text-accent-blue",
  family: "bg-accent-green/15 text-accent-green",
  concept: "bg-accent-orange/15 text-accent-orange",
  sub_component: "bg-surface-3 text-text-secondary",
  parameter: "bg-accent-red/15 text-accent-red",
};

// --- Flatten tree for virtualization ---
interface FlatRow {
  node: OntologyTreeNode;
  depth: number;
  isExpanded: boolean;
  hasChildren: boolean;
}

function flattenTree(
  nodes: OntologyTreeNode[],
  expandedSet: Set<string>,
  depth = 0
): FlatRow[] {
  const rows: FlatRow[] = [];
  for (const node of nodes) {
    const hasChildren = (node.children?.length ?? 0) > 0;
    const isExpanded = expandedSet.has(node.id);
    rows.push({ node, depth, isExpanded, hasChildren });
    if (isExpanded && node.children) {
      rows.push(...flattenTree(node.children, expandedSet, depth + 1));
    }
  }
  return rows;
}

// --- Collect all ancestor IDs for search auto-expand ---
function collectExpandableIds(
  nodes: OntologyTreeNode[],
  searchLower: string,
  parentIds: string[] = []
): Set<string> {
  const result = new Set<string>();
  for (const node of nodes) {
    const matches =
      node.name.toLowerCase().includes(searchLower) ||
      node.id.toLowerCase().includes(searchLower);

    if (matches) {
      parentIds.forEach((pid) => result.add(pid));
    }

    if (node.children && node.children.length > 0) {
      const childResults = collectExpandableIds(
        node.children,
        searchLower,
        [...parentIds, node.id]
      );
      childResults.forEach((id) => result.add(id));
    }
  }
  return result;
}

// --- Tree row component ---
function TreeRow({
  row,
  selectedId,
  searchLower,
  onToggle,
  onSelect,
}: {
  row: FlatRow;
  selectedId: string | null;
  searchLower: string;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
}) {
  const { node, depth, isExpanded, hasChildren } = row;
  const isSelected = node.id === selectedId;
  const domainId = node.domain_id || node.id;
  const dotClass = DOMAIN_DOT_COLORS[domainId] ?? "bg-text-muted";

  // Highlight matching text
  const nameContent = useMemo(() => {
    if (!searchLower) return node.name;
    const idx = node.name.toLowerCase().indexOf(searchLower);
    if (idx === -1) return node.name;
    return (
      <>
        {node.name.slice(0, idx)}
        <mark className="bg-accent-blue/30 text-text-primary rounded-sm px-0.5">
          {node.name.slice(idx, idx + searchLower.length)}
        </mark>
        {node.name.slice(idx + searchLower.length)}
      </>
    );
  }, [node.name, searchLower]);

  return (
    <div
      className={cn(
        "flex items-center gap-1 py-1 px-2 cursor-pointer hover:bg-surface-3/60 transition-colors group text-xs",
        isSelected && "bg-accent-blue/10 border-l-2 border-accent-blue",
        !isSelected && "border-l-2 border-transparent"
      )}
      style={{ paddingLeft: `${8 + depth * 16}px` }}
      onClick={() => onSelect(node.id)}
      role="treeitem"
      aria-expanded={hasChildren ? isExpanded : undefined}
      aria-selected={isSelected}
    >
      {/* Expand chevron */}
      <button
        className={cn(
          "w-4 h-4 flex items-center justify-center text-text-muted hover:text-text-primary flex-shrink-0",
          !hasChildren && "invisible"
        )}
        onClick={(e) => {
          e.stopPropagation();
          onToggle(node.id);
        }}
        tabIndex={-1}
        aria-label={isExpanded ? "Collapse" : "Expand"}
      >
        <svg
          className={cn(
            "w-3 h-3 transition-transform duration-150",
            isExpanded && "rotate-90"
          )}
          viewBox="0 0 16 16"
          fill="currentColor"
        >
          <path d="M6 4l4 4-4 4V4z" />
        </svg>
      </button>

      {/* Domain-colored dot */}
      <span className={cn("w-2 h-2 rounded-full flex-shrink-0", dotClass)} />

      {/* Name */}
      <span className={cn(
        "truncate flex-1",
        isSelected ? "text-text-primary font-medium" : "text-text-secondary"
      )}>
        {nameContent}
      </span>

      {/* Type badge (only for non-domain levels) */}
      {node.type !== "domain" && (
        <span className={cn(
          "text-[9px] px-1 py-0.5 rounded font-medium flex-shrink-0 uppercase hidden group-hover:inline-block",
          TYPE_BADGE_STYLES[node.type]
        )}>
          {node.type === "sub_component" ? "sub" : node.type.slice(0, 3)}
        </span>
      )}

      {/* Child count */}
      {hasChildren && (
        <span className="text-[10px] text-text-muted tabular-nums flex-shrink-0">
          {node.child_count}
        </span>
      )}
    </div>
  );
}

// --- Main tree component ---
interface OntologyTreeProps {
  roots: OntologyTreeNode[];
  selectedId: string | null;
  onSelectNode: (nodeId: string) => void;
  searchQuery: string;
}

export function OntologyTree({
  roots,
  selectedId,
  onSelectNode,
  searchQuery,
}: OntologyTreeProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => {
    // Auto-expand domains on initial load
    return new Set(roots.map((r) => r.id));
  });

  const scrollRef = useRef<HTMLDivElement>(null);
  const searchLower = searchQuery.toLowerCase().trim();

  // When search changes, auto-expand matching branches
  useEffect(() => {
    if (!searchLower) return;
    const toExpand = collectExpandableIds(roots, searchLower);
    // Also keep domains expanded
    for (const r of roots) toExpand.add(r.id);
    setExpandedIds(toExpand);
  }, [searchLower, roots]);

  const handleToggle = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const flatRows = useMemo(
    () => flattenTree(roots, expandedIds),
    [roots, expandedIds]
  );

  return (
    <div
      ref={scrollRef}
      className="overflow-y-auto flex-1"
      role="tree"
      aria-label="Ontology tree"
    >
      {flatRows.map((row) => (
        <TreeRow
          key={row.node.id}
          row={row}
          selectedId={selectedId}
          searchLower={searchLower}
          onToggle={handleToggle}
          onSelect={onSelectNode}
        />
      ))}
      {flatRows.length === 0 && (
        <div className="p-4">
          <EmptyState title="No nodes found" message="Try a different search term or clear the filters." />
        </div>
      )}
    </div>
  );
}
