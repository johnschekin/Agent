"use client";

import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import type { TrafficLightNode, CounterfactualResponse } from "@/lib/types";

interface TrafficLightAstProps {
  evaluationTree: TrafficLightNode | null;
  onMuteNode?: (path: string) => void;
  onUnmuteNode?: (path: string) => void;
  counterfactualResult?: CounterfactualResponse;
}

function TrafficLightNodeView({
  node,
  path,
  depth,
  onMuteNode,
  onUnmuteNode,
  counterfactualResult,
}: {
  node: TrafficLightNode;
  path: string;
  depth: number;
  onMuteNode?: (path: string) => void;
  onUnmuteNode?: (path: string) => void;
  counterfactualResult?: CounterfactualResponse;
}) {
  const isMuted = !!node.muted;
  const isGroup = !!node.children && node.children.length > 0;

  return (
    <div
      className={cn("relative", depth > 0 && "ml-5")}
      data-testid={`traffic-node-${path || "root"}`}
    >
      {/* Vertical connector line for groups */}
      {isGroup && depth > 0 && (
        <div className="absolute left-[-12px] top-0 bottom-0 w-px bg-border" />
      )}

      {/* Node chip with AND/OR label for groups */}
      <div className="flex items-center gap-2 py-0.5">
        {/* AND/OR operator label for group nodes */}
        {isGroup && (
          <span
            className={cn(
              "text-[10px] font-bold uppercase px-1.5 py-0.5 rounded",
              node.node.toLowerCase().includes("and")
                ? "bg-glow-blue text-accent-blue"
                : node.node.toLowerCase().includes("or")
                ? "bg-glow-purple text-accent-purple"
                : "bg-surface-2 text-text-muted",
            )}
            data-testid={`traffic-op-${path || "root"}`}
          >
            {node.node.toLowerCase().includes("and") ? "AND" : node.node.toLowerCase().includes("or") ? "OR" : node.node}
          </span>
        )}

        <button
          type="button"
          onClick={() => {
            if (isMuted && onUnmuteNode) {
              onUnmuteNode(path);
            } else if (!node.result && onMuteNode) {
              onMuteNode(path);
            }
          }}
          className={cn(
            "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium transition-colors",
            isMuted
              ? "bg-glow-purple text-accent-purple line-through cursor-pointer"
              : node.result
              ? "bg-glow-green text-accent-green"
              : "bg-glow-red text-accent-red cursor-pointer hover:opacity-80",
          )}
          disabled={!isMuted && node.result}
          data-testid={`traffic-chip-${path || "root"}`}
        >
          {isGroup ? (node.result ? "PASS" : "FAIL") : node.node}
        </button>

        {isMuted && (
          <Badge variant="purple" className="text-[10px]">
            muted
          </Badge>
        )}

        {isMuted && counterfactualResult && (
          <span
            className="text-[10px] text-text-muted"
            title={`Would capture ${counterfactualResult.new_hits} new docs, ${counterfactualResult.false_positives} FPs`}
          >
            +{counterfactualResult.new_hits} hits, {counterfactualResult.false_positives} FP
          </span>
        )}
      </div>

      {/* Children with bracket */}
      {isGroup && node.children && (
        <div className="mt-0.5 space-y-0.5 border-l-2 border-border pl-2 ml-1">
          {node.children.map((child, idx) => {
            const childPath = path ? `${path}.${idx}` : String(idx);
            return (
              <TrafficLightNodeView
                key={childPath}
                node={child}
                path={childPath}
                depth={depth + 1}
                onMuteNode={onMuteNode}
                onUnmuteNode={onUnmuteNode}
                counterfactualResult={counterfactualResult}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

export function TrafficLightAst({
  evaluationTree,
  onMuteNode,
  onUnmuteNode,
  counterfactualResult,
}: TrafficLightAstProps) {
  if (!evaluationTree) {
    return (
      <div className="text-sm text-text-muted p-4" data-testid="traffic-light-ast">
        No evaluation data
      </div>
    );
  }

  return (
    <div data-testid="traffic-light-ast" className="p-2">
      <TrafficLightNodeView
        node={evaluationTree}
        path=""
        depth={0}
        onMuteNode={onMuteNode}
        onUnmuteNode={onUnmuteNode}
        counterfactualResult={counterfactualResult}
      />
    </div>
  );
}
