"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { TrafficLightAst } from "./TrafficLightAst";
import {
  useWhyNotCoverageMutation,
  useCounterfactualMutation,
  useSemanticCandidates,
  useSaveAsRuleMutation,
} from "@/lib/queries";
import type { TrafficLightNode } from "@/lib/types";

interface WhyNotMatchedPanelProps {
  docId: string;
  sectionNumber: string;
  ruleId: string;
  familyId: string;
  onClose: () => void;
}

export function WhyNotMatchedPanel({
  docId,
  sectionNumber,
  ruleId,
  familyId,
  onClose,
}: WhyNotMatchedPanelProps) {
  const whyNotMut = useWhyNotCoverageMutation();
  const counterfactualMut = useCounterfactualMutation();
  const { data: semanticData } = useSemanticCandidates(familyId);
  const saveRuleMut = useSaveAsRuleMutation();
  const [mutedPath, setMutedPath] = useState<string | null>(null);

  // Fetch on mount
  useEffect(() => {
    whyNotMut.mutate({ docId, ruleId, sectionNumber });
    setMutedPath(null);
    counterfactualMut.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId, ruleId, sectionNumber]);

  const whyNotData = whyNotMut.data;
  const isTriviallyFixable =
    whyNotData && whyNotData.missing_factors.length === 1;

  const baseTrafficTree: TrafficLightNode | null = whyNotData
    ? (whyNotData.traffic_tree as TrafficLightNode | null) ?? {
        node: "Rule Evaluation",
        result: false,
        children: whyNotData.missing_factors.map((factor) => ({
          node: factor,
          result: false,
        })),
      }
    : null;

  const trafficTree: TrafficLightNode | null = useMemo(() => {
    if (!baseTrafficTree) return null;
    if (mutedPath === null) return baseTrafficTree;
    const applyMuted = (node: TrafficLightNode, path: string): TrafficLightNode => {
      const next: TrafficLightNode = { ...node, muted: path === mutedPath };
      if (node.children?.length) {
        next.children = node.children.map((child, idx) =>
          applyMuted(child, path ? `${path}.${idx}` : String(idx)),
        );
      }
      return next;
    };
    return applyMuted(baseTrafficTree, "");
  }, [baseTrafficTree, mutedPath]);

  const handleMuteNode = useCallback(
    (path: string) => {
      if (!whyNotData?.rule_ast) return;
      setMutedPath(path);
      counterfactualMut.mutate({
        family_id: familyId,
        heading_filter_ast: whyNotData.rule_ast as Record<string, unknown>,
        muted_node_path: path,
      });
    },
    [counterfactualMut, familyId, whyNotData],
  );

  const handleUnmuteNode = useCallback(() => {
    setMutedPath(null);
    counterfactualMut.reset();
  }, [counterfactualMut]);

  return (
    <div
      className="fixed inset-y-0 right-0 w-96 bg-surface-1 border-l border-border shadow-overlay z-40 flex flex-col"
      data-testid="why-not-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-text-primary">
            Why Not Matched
          </h3>
          {isTriviallyFixable && (
            <Badge variant="green" className="text-[10px]">
              Trivially fixable
            </Badge>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-text-muted hover:text-text-primary transition-colors text-lg leading-none"
          data-testid="why-not-close"
        >
          &times;
        </button>
      </div>

      {/* Doc info */}
      <div className="px-4 py-2 border-b border-border bg-surface-2">
        <p className="text-xs font-mono text-text-secondary">{docId}</p>
        <p className="text-xs text-text-muted">Section {sectionNumber}</p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {whyNotMut.isPending && (
          <p className="text-sm text-text-muted animate-pulse">Analyzing...</p>
        )}

        {whyNotMut.isError && (
          <p className="text-sm text-accent-red">
            Error: {whyNotMut.error?.message ?? "Failed to analyze"}
          </p>
        )}

        {whyNotData && (
          <>
            {/* Nearest score */}
            <div>
              <p className="text-xs text-text-muted mb-1">Nearest Miss Score</p>
              <p className="text-lg font-bold text-text-primary tabular-nums">
                {(whyNotData.nearest_score * 100).toFixed(1)}%
              </p>
            </div>

            {/* Traffic light tree */}
            <div>
              <p className="text-xs text-text-muted mb-1">Evaluation Breakdown</p>
              <TrafficLightAst
                evaluationTree={trafficTree}
                onMuteNode={handleMuteNode}
                onUnmuteNode={handleUnmuteNode}
                counterfactualResult={counterfactualMut.data}
              />
              {counterfactualMut.isPending && (
                <p className="text-[11px] text-text-muted mt-1 animate-pulse">
                  Computing counterfactual impact...
                </p>
              )}
              {counterfactualMut.isError && (
                <p className="text-[11px] text-accent-red mt-1">
                  Counterfactual unavailable right now.
                </p>
              )}
            </div>

            {/* Suggestion */}
            {whyNotData.suggestion && (
              <div>
                <p className="text-xs text-text-muted mb-1">Suggestion</p>
                <p className="text-sm text-text-secondary">
                  {whyNotData.suggestion}
                </p>
              </div>
            )}

            {/* Apply suggested tuning */}
            {isTriviallyFixable && (
              <button
                type="button"
                onClick={() => {
                  const suggested = whyNotData.missing_factors[0] ?? "";
                  saveRuleMut.mutate({
                    family_id: familyId,
                    heading_filter_dsl: `heading:"${suggested}"`,
                    heading_filter_ast: { value: suggested },
                  });
                }}
                disabled={saveRuleMut.isPending}
                className="w-full px-3 py-2 bg-accent-blue text-white text-sm rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                data-testid="apply-suggested-tuning"
              >
                {saveRuleMut.isPending
                  ? "Saving..."
                  : "Apply Suggested Tuning"}
              </button>
            )}
          </>
        )}

        {/* Semantic candidates */}
        {semanticData && semanticData.candidates.length > 0 && (
          <div>
            <p className="text-xs text-text-muted mb-2">
              Semantic Candidates
            </p>
            <div className="space-y-1.5">
              {semanticData.candidates.slice(0, 5).map((candidate) => (
                <div
                  key={`${candidate.doc_id}-${candidate.section_number}`}
                  className="flex items-center gap-2 px-2 py-1.5 bg-surface-2 rounded text-xs"
                  data-testid="semantic-candidate"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-text-primary truncate">
                      {candidate.heading}
                    </p>
                    <p className="text-text-muted font-mono text-[10px]">
                      {candidate.doc_id}
                    </p>
                  </div>
                  <Badge
                    variant={
                      candidate.similarity > 0.8
                        ? "green"
                        : candidate.similarity > 0.5
                        ? "orange"
                        : "red"
                    }
                  >
                    {(candidate.similarity * 100).toFixed(0)}%
                  </Badge>
                  <button
                    type="button"
                    onClick={() => {
                      saveRuleMut.mutate({
                        family_id: familyId,
                        heading_filter_dsl: `heading:"${candidate.heading}"`,
                        heading_filter_ast: { value: candidate.heading },
                      });
                    }}
                    disabled={saveRuleMut.isPending}
                    className="flex-shrink-0 text-[10px] text-accent-blue hover:underline disabled:opacity-50"
                    data-testid={`use-heading-variant-${candidate.doc_id}`}
                  >
                    Use this variant
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
