"use client";

import { useCallback, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { WhyMatchedPopover } from "@/components/links/WhyMatchedPopover";
import {
  useCreateChildLinkPreviewMutation,
  useApplyChildLinksMutation,
} from "@/lib/queries";
import type { ChildLinkCandidate, ConfidenceTier, WhyMatchedFactor } from "@/lib/types";

interface ChildLinkQueueProps {
  parentLinkId: string;
  familyId: string;
  onApply?: () => void;
  className?: string;
}

export function ChildLinkQueue({ parentLinkId, familyId, onApply, className }: ChildLinkQueueProps) {
  const [tierFilter, setTierFilter] = useState<ConfidenceTier | "all">("all");
  const [verdicts, setVerdicts] = useState<Map<string, "accepted" | "rejected">>(new Map());

  const createPreviewMut = useCreateChildLinkPreviewMutation();
  const applyMut = useApplyChildLinksMutation();

  const preview = createPreviewMut.data;
  const candidates = preview?.candidates ?? [];

  const filteredCandidates =
    tierFilter === "all"
      ? candidates
      : candidates.filter((c) => c.confidence_tier === tierFilter);

  const handleGenerate = useCallback(() => {
    createPreviewMut.mutate({ linkId: parentLinkId, familyId });
  }, [parentLinkId, familyId, createPreviewMut]);

  const toggleVerdict = useCallback((clausePath: string, verdict: "accepted" | "rejected") => {
    setVerdicts((prev) => {
      const next = new Map(prev);
      if (next.get(clausePath) === verdict) {
        next.delete(clausePath);
      } else {
        next.set(clausePath, verdict);
      }
      return next;
    });
  }, []);

  const handleApply = useCallback(() => {
    if (!preview) return;
    const verdictPayload: { clause_id: string; doc_id: string; verdict: "accepted" | "rejected" }[] = [];
    for (const [key, verdict] of Array.from(verdicts.entries())) {
      const match = candidates.find((candidate) => `${candidate.clause_path}:${candidate.node_id}` === key);
      if (!match) continue;
      const row = match as ChildLinkCandidate & { clause_id?: string; doc_id?: string };
      verdictPayload.push({
        clause_id: row.clause_id ?? match.clause_path,
        doc_id: row.doc_id ?? "",
        verdict,
      });
    }
    applyMut.mutate(
      { linkId: parentLinkId, previewId: preview.preview_id, verdicts: verdictPayload },
      { onSuccess: () => onApply?.() },
    );
  }, [parentLinkId, preview, applyMut, onApply, verdicts, candidates]);

  const tierColor = (tier: string) =>
    tier === "high" ? "green" : tier === "medium" ? "orange" : "red";

  /** Build factors array for the popover; fall back to a synthetic single factor if empty. */
  function getFactors(c: ChildLinkCandidate): WhyMatchedFactor[] {
    if (c.factors && c.factors.length > 0) return c.factors;
    return [
      {
        factor: "overall",
        score: c.confidence,
        weight: 1.0,
        detail: `Overall confidence: ${(c.confidence * 100).toFixed(0)}%`,
      },
    ];
  }

  return (
    <div className={cn("space-y-3", className)} data-testid="child-link-queue">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Candidate Child Links
        </h4>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={createPreviewMut.isPending}
          className="px-3 py-1.5 bg-accent-blue text-white text-xs rounded-lg hover:opacity-90 disabled:opacity-50"
          data-testid="generate-candidates-btn"
        >
          {createPreviewMut.isPending ? "Generating..." : "Generate Candidates"}
        </button>
      </div>

      {/* Tier filter tabs */}
      {candidates.length > 0 && (
        <div className="flex items-center gap-1">
          {(["all", "high", "medium", "low"] as const).map((tier) => (
            <button
              key={tier}
              type="button"
              onClick={() => setTierFilter(tier)}
              className={cn(
                "filter-chip",
                tierFilter === tier && "active",
              )}
              data-testid={`child-tier-${tier}`}
            >
              {tier === "all" ? "All" : tier.charAt(0).toUpperCase() + tier.slice(1)}
              {tier !== "all" && (
                <span className="ml-1 text-text-muted">
                  ({candidates.filter((c) => c.confidence_tier === tier).length})
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Candidates table */}
      {createPreviewMut.isPending ? (
        <p className="text-sm text-text-muted py-6 text-center">Generating candidates...</p>
      ) : candidates.length === 0 ? (
        <p className="text-sm text-text-muted py-6 text-center">
          Click &ldquo;Generate Candidates&rdquo; to find child link opportunities
        </p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Clause
                  </th>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Node
                  </th>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Confidence
                  </th>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Verdict
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredCandidates.map((c) => {
                  const key = `${c.clause_path}:${c.node_id}`;
                  const verdict = verdicts.get(key);
                  return (
                    <tr
                      key={key}
                      className="border-b border-border/30 hover:bg-surface-2/50"
                      data-testid={`child-candidate-${c.clause_path}`}
                    >
                      <td className="px-3 py-2">
                        <div>
                          <span className="text-sm text-text-primary">{c.clause_label}</span>
                          <span className="text-xs text-text-muted ml-1.5">{c.clause_path}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-sm text-text-primary">
                        {c.node_name}
                      </td>
                      <td className="px-3 py-2" data-testid={`child-factors-${c.clause_path}`}>
                        <WhyMatchedPopover
                          factors={getFactors(c)}
                          confidence={c.confidence}
                          confidenceTier={c.confidence_tier}
                          trigger={
                            <Badge variant={tierColor(c.confidence_tier)}>
                              {(c.confidence * 100).toFixed(0)}%
                            </Badge>
                          }
                        />
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => toggleVerdict(key, "accepted")}
                            className={cn(
                              "px-1.5 py-0.5 rounded text-xs transition-colors",
                              verdict === "accepted"
                                ? "bg-glow-green text-accent-green"
                                : "text-text-muted hover:text-accent-green",
                            )}
                            data-testid={`child-accept-${c.clause_path}`}
                          >
                            Accept
                          </button>
                          <button
                            type="button"
                            onClick={() => toggleVerdict(key, "rejected")}
                            className={cn(
                              "px-1.5 py-0.5 rounded text-xs transition-colors",
                              verdict === "rejected"
                                ? "bg-glow-red text-accent-red"
                                : "text-text-muted hover:text-accent-red",
                            )}
                            data-testid={`child-reject-${c.clause_path}`}
                          >
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Apply button */}
          <button
            type="button"
            onClick={handleApply}
            disabled={applyMut.isPending}
            className="w-full px-3 py-2 bg-accent-green text-white text-sm font-medium rounded-lg hover:opacity-90 disabled:opacity-50"
            data-testid="apply-child-links-btn"
          >
            {applyMut.isPending ? "Applying..." : `Apply ${verdicts.size > 0 ? `(${verdicts.size} reviewed)` : ""}`}
          </button>
        </>
      )}
    </div>
  );
}
