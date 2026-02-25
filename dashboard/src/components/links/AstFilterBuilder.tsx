"use client";

import { useCallback } from "react";
import { cn } from "@/lib/cn";
import type { FilterExpressionNode } from "@/lib/types";
import { isFilterGroup } from "@/lib/types";
import { FilterGroupNode } from "./FilterGroupNode";

interface AstFilterBuilderProps {
  ast: FilterExpressionNode | null;
  onAstChange: (ast: FilterExpressionNode | null) => void;
  disabled?: boolean;
  className?: string;
}

/**
 * Deep-clone a node and set a value at a dot-separated path.
 * Path segments like "children.0.children.1" address nested positions.
 */
function setAtPath(
  root: FilterExpressionNode,
  path: string,
  value: FilterExpressionNode,
): FilterExpressionNode {
  if (!path) return value;
  const clone = structuredClone(root);
  const segments = path.split(".");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let cursor: any = clone;
  for (let i = 0; i < segments.length - 1; i++) {
    const seg = segments[i];
    cursor = cursor[isNaN(Number(seg)) ? seg : Number(seg)];
  }
  const lastSeg = segments[segments.length - 1];
  cursor[isNaN(Number(lastSeg)) ? lastSeg : Number(lastSeg)] = value;
  return clone;
}

/**
 * Deep-clone root and remove the node at `path`.
 */
function removeAtPath(
  root: FilterExpressionNode,
  path: string,
): FilterExpressionNode | null {
  if (!path) return null;
  const clone = structuredClone(root);
  const segments = path.split(".");
  // Navigate to parent
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let cursor: any = clone;
  for (let i = 0; i < segments.length - 2; i++) {
    const seg = segments[i];
    cursor = cursor[isNaN(Number(seg)) ? seg : Number(seg)];
  }
  // The second-to-last segment should be "children" and last is the index
  const parentKey = segments[segments.length - 2];
  const idx = Number(segments[segments.length - 1]);
  if (parentKey === "children" && Array.isArray(cursor.children)) {
    cursor.children.splice(idx, 1);
  }
  return clone;
}

export function AstFilterBuilder({
  ast,
  onAstChange,
  disabled,
  className,
}: AstFilterBuilderProps) {
  const handleUpdate = useCallback(
    (path: string, node: FilterExpressionNode) => {
      if (!ast) return;
      const updated = setAtPath(ast, path, node);
      onAstChange(updated);
    },
    [ast, onAstChange],
  );

  const handleRemove = useCallback(
    (path: string) => {
      if (!ast) return;
      const updated = removeAtPath(ast, path);
      onAstChange(updated);
    },
    [ast, onAstChange],
  );

  if (!ast) {
    return (
      <div
        className={cn(
          "border-2 border-dashed border-border rounded-lg p-6 flex flex-col items-center justify-center gap-2",
          className,
        )}
        data-testid="ast-builder"
      >
        <p className="text-sm text-text-muted">No filter defined</p>
        <button
          type="button"
          onClick={() => {
            onAstChange({ op: "and", children: [] });
          }}
          disabled={disabled}
          className="text-sm text-accent-blue hover:underline disabled:opacity-50"
          data-testid="ast-builder-init"
        >
          Click + to add your first filter
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn("space-y-2", disabled && "opacity-50 pointer-events-none", className)}
      data-testid="ast-builder"
    >
      <FilterGroupNode
        node={ast}
        path=""
        onUpdate={handleUpdate}
        onRemove={handleRemove}
        depth={0}
      />
    </div>
  );
}
