"use client";

import { useCallback, useRef } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import type { FilterExpressionNode, FilterGroupNode as FilterGroupNodeType } from "@/lib/types";
import { isFilterGroup } from "@/lib/types";

interface FilterGroupNodeProps {
  node: FilterExpressionNode;
  path: string;
  onUpdate: (path: string, node: FilterExpressionNode) => void;
  onRemove: (path: string) => void;
  depth: number;
}

const MAX_DEPTH = 5;

export function FilterGroupNode({
  node,
  path,
  onUpdate,
  onRemove,
  depth,
}: FilterGroupNodeProps) {
  if (isFilterGroup(node)) {
    return (
      <div
        className={cn(
          "border border-border rounded-lg p-2",
          depth > 0 && "ml-4",
          depth === 0 && "border-border/50"
        )}
        data-testid={`filter-group-${path || "root"}`}
      >
        {/* Group header: AND/OR toggle */}
        <div className="flex items-center gap-2 mb-2">
          <button
            type="button"
            onClick={() => {
              const newOp = node.op === "and" ? "or" : "and";
              onUpdate(path, { ...node, op: newOp });
            }}
            className={cn(
              "px-2 py-0.5 rounded text-xs font-bold uppercase transition-colors",
              node.op === "and"
                ? "bg-glow-blue text-accent-blue"
                : "bg-glow-purple text-accent-purple"
            )}
            data-testid={`toggle-op-${path || "root"}`}
          >
            {node.op}
          </button>

          {depth < MAX_DEPTH && (
            <>
              <button
                type="button"
                onClick={() => {
                  const newChildren = [
                    ...node.children,
                    { value: "" } as FilterExpressionNode,
                  ];
                  onUpdate(path, { ...node, children: newChildren });
                }}
                className="text-xs text-text-muted hover:text-text-primary transition-colors"
                data-testid={`add-match-${path || "root"}`}
              >
                + Match
              </button>
              <button
                type="button"
                onClick={() => {
                  const newChildren = [
                    ...node.children,
                    { op: "and", children: [] } as FilterExpressionNode,
                  ];
                  onUpdate(path, { ...node, children: newChildren });
                }}
                className="text-xs text-text-muted hover:text-text-primary transition-colors"
                data-testid={`add-group-${path || "root"}`}
              >
                + Group
              </button>
            </>
          )}

          {depth > 0 && (
            <button
              type="button"
              onClick={() => onRemove(path)}
              className="ml-auto text-xs text-text-muted hover:text-accent-red transition-colors"
              aria-label="Remove group"
            >
              &times;
            </button>
          )}
        </div>

        {/* Render children */}
        <div className="space-y-1.5">
          {node.children.map((child, idx) => {
            const childPath = path ? `${path}.children.${idx}` : `children.${idx}`;
            return (
              <FilterGroupNode
                key={childPath}
                node={child}
                path={childPath}
                onUpdate={onUpdate}
                onRemove={onRemove}
                depth={depth + 1}
              />
            );
          })}
        </div>
      </div>
    );
  }

  // Leaf node (FilterMatchNode) with keyboard navigation:
  // Tab: move between chips, Enter: focus input for editing, Delete/Backspace: remove chip
  const handleChipKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Delete" || e.key === "Backspace") {
      // Don't remove if user is editing inside the input
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      e.preventDefault();
      onRemove(path);
    } else if (e.key === "Enter") {
      e.preventDefault();
      // Focus the input inside the chip for inline editing
      const input = (e.currentTarget as HTMLElement).querySelector("input");
      input?.focus();
    }
  };

  return (
    <div
      className={cn("inline-flex items-center gap-1.5", depth > 0 && "ml-4")}
      data-testid={`filter-match-${path}`}
      tabIndex={0}
      onKeyDown={handleChipKeyDown}
    >
      <Badge variant={node.negate ? "red" : "blue"}>
        {node.negate && (
          <span className="mr-1 font-bold" data-testid={`negate-badge-${path}`}>!</span>
        )}
        <input
          type="text"
          value={node.value}
          onChange={(e) => {
            onUpdate(path, { ...node, value: e.target.value });
          }}
          onKeyDown={(e) => {
            // Delete on empty input removes the chip
            if ((e.key === "Delete" || e.key === "Backspace") && node.value === "") {
              e.preventDefault();
              onRemove(path);
            }
          }}
          className="bg-transparent border-none outline-none text-xs w-24 min-w-0"
          placeholder="value..."
          tabIndex={0}
          data-testid={`match-input-${path}`}
        />
      </Badge>
      <button
        type="button"
        onClick={() => {
          onUpdate(path, { ...node, negate: !node.negate });
        }}
        className={cn(
          "text-[10px] font-bold px-1 rounded transition-colors",
          node.negate
            ? "text-accent-red hover:text-text-primary"
            : "text-text-muted hover:text-accent-red"
        )}
        title="Toggle negate"
        tabIndex={0}
        data-testid={`toggle-negate-${path}`}
      >
        !
      </button>
      <button
        type="button"
        onClick={() => onRemove(path)}
        className="text-xs text-text-muted hover:text-accent-red transition-colors"
        aria-label="Remove match"
        tabIndex={0}
        data-testid={`remove-match-${path}`}
      >
        &times;
      </button>
    </div>
  );
}
