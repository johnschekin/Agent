"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { TrafficLightAst } from "./TrafficLightAst";
import { useEvaluateTextMutation } from "@/lib/queries";
import type { FilterExpressionNode, TrafficLightNode } from "@/lib/types";

interface ScratchpadPaneProps {
  ast: FilterExpressionNode | null;
  heading: string;
  familyId?: string;
  className?: string;
}

export function ScratchpadPane({
  ast,
  heading,
  className,
}: ScratchpadPaneProps) {
  const [scratchText, setScratchText] = useState("");
  const evaluateMut = useEvaluateTextMutation();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doEvaluate = useCallback(() => {
    if (!ast || !scratchText.trim()) return;
    evaluateMut.mutate({
      rule_ast: ast as unknown as Record<string, unknown>,
      raw_text: scratchText,
      heading,
    });
  }, [ast, scratchText, heading, evaluateMut]);

  // Debounce evaluation on text change
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!scratchText.trim() || !ast) return;
    debounceRef.current = setTimeout(doEvaluate, 200);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scratchText, ast, heading]);

  const result = evaluateMut.data;
  const isMatch = result?.matched ?? false;

  // Build traffic light tree from matched_nodes
  const trafficTree: TrafficLightNode | null = result
    ? (result.traffic_tree as TrafficLightNode | null) ?? {
        node: "Evaluation",
        result: result.matched,
        children: result.matched_nodes.map((n, i) => ({
          node: String((n as Record<string, unknown>).node ?? `node_${i}`),
          result: !!(n as Record<string, unknown>).result,
        })),
      }
    : null;

  return (
    <div
      className={cn("flex flex-col border border-border rounded-lg overflow-hidden", className)}
      data-testid="scratchpad-pane"
    >
      {/* Header */}
      <div className="px-3 py-2 border-b border-border bg-surface-2 flex items-center justify-between">
        <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Scratchpad
        </span>
        {result && (
          <Badge
            variant={isMatch ? "green" : "red"}
            data-testid="scratchpad-result"
          >
            {isMatch ? "MATCH" : "NO MATCH"}
          </Badge>
        )}
      </div>

      {/* Textarea */}
      <div className="flex-1 flex flex-col md:flex-row">
        <div className="flex-1 min-h-[120px]">
          <textarea
            value={scratchText}
            onChange={(e) => setScratchText(e.target.value)}
            placeholder="Paste section text here to test the current filter..."
            className="w-full h-full bg-surface-1 p-3 text-sm text-text-primary font-mono resize-none focus:outline-none placeholder:text-text-muted"
            data-testid="scratchpad-textarea"
          />
        </div>

        {/* Result panel */}
        <div className="flex-1 border-t md:border-t-0 md:border-l border-border overflow-y-auto">
          {evaluateMut.isPending && (
            <div className="p-3 text-sm text-text-muted animate-pulse">
              Evaluating...
            </div>
          )}

          {result && (
            <div className="p-2">
              {/* Result banner */}
              <div
                className={cn(
                  "px-3 py-2 rounded-lg mb-2 text-sm font-medium",
                  isMatch
                    ? "bg-glow-green text-accent-green"
                    : "bg-glow-red text-accent-red",
                )}
                data-testid="scratchpad-banner"
              >
                {isMatch ? "MATCH" : "NO MATCH"} — Traffic light:{" "}
                {result.traffic_light}
              </div>

              {/* Traffic light tree */}
              <TrafficLightAst evaluationTree={trafficTree} />
            </div>
          )}

          {!result && !evaluateMut.isPending && (
            <div className="p-3 text-sm text-text-muted">
              Type or paste text to evaluate against the current filter.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
