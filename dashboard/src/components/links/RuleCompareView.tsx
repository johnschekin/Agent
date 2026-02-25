"use client";

import { useEffect } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { useRuleCompareMutation } from "@/lib/queries";
import type { RuleCompareDetailItem } from "@/lib/types";

interface RuleCompareViewProps {
  ruleIdA: string;
  ruleIdB: string;
  onClose: () => void;
  onPromote?: (fromId: string, toId: string) => void;
}

function SampleList({
  items,
  testId,
  emptyLabel,
  accentClass,
}: {
  items: RuleCompareDetailItem[] | undefined;
  testId: string;
  emptyLabel: string;
  accentClass: string;
}) {
  if (!items || items.length === 0) {
    return (
      <ul data-testid={testId} className="space-y-1">
        <li className="text-xs text-text-muted italic">{emptyLabel}</li>
      </ul>
    );
  }

  return (
    <ul data-testid={testId} className="space-y-2">
      {items.map((item, idx) => (
        <li
          key={`${item.doc_id}-${item.section_number}-${idx}`}
          className="rounded-md bg-surface-2 px-3 py-2 text-xs space-y-0.5"
        >
          <div className="flex items-center gap-2">
            <span className={cn("font-mono font-semibold", accentClass)}>
              {item.section_number || "\u2014"}
            </span>
            <span className="text-text-muted truncate">{item.doc_id}</span>
          </div>
          {item.heading && (
            <div className="text-text-secondary truncate">{item.heading}</div>
          )}
          {item.reason && (
            <div className="text-text-muted italic">{item.reason}</div>
          )}
        </li>
      ))}
    </ul>
  );
}

export function RuleCompareView({
  ruleIdA,
  ruleIdB,
  onClose,
  onPromote,
}: RuleCompareViewProps) {
  const compareMut = useRuleCompareMutation();

  useEffect(() => {
    compareMut.mutate({ ruleIdA, ruleIdB });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ruleIdA, ruleIdB]);

  // Escape to close
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const result = compareMut.data;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={onClose}
      data-testid="rule-compare-view"
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-2xl bg-surface-1 rounded-xl shadow-overlay border border-border overflow-hidden max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <h3 className="text-sm font-semibold text-text-primary">Rule Comparison</h3>
          <div className="flex items-center gap-2">
            {onPromote && result && (
              <button
                type="button"
                onClick={() => onPromote(ruleIdB, ruleIdA)}
                className="text-xs px-3 py-1.5 rounded-md bg-accent-purple/10 text-accent-purple hover:bg-accent-purple/20 font-medium transition-colors"
                data-testid="compare-promote-btn"
              >
                Promote B &rarr; A
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="text-text-muted hover:text-text-primary text-lg leading-none"
              data-testid="compare-close"
            >
              &times;
            </button>
          </div>
        </div>

        {/* Scrollable content */}
        <div className="p-5 overflow-y-auto flex-1">
          {compareMut.isPending ? (
            <p className="text-sm text-text-muted text-center py-8">Comparing rules...</p>
          ) : compareMut.isError ? (
            <p className="text-sm text-accent-red text-center py-8">
              Failed to compare: {compareMut.error?.message ?? "Unknown error"}
            </p>
          ) : result ? (
            <div className="space-y-5">
              {/* Rule IDs */}
              <div className="flex items-center justify-between">
                <Badge variant="blue" data-testid="compare-rule-a">{result.rule_id_a}</Badge>
                <span className="text-text-muted text-sm">vs</span>
                <Badge variant="purple" data-testid="compare-rule-b">{result.rule_id_b}</Badge>
              </div>

              {/* Venn diagram (SVG) */}
              <div className="flex justify-center" data-testid="compare-venn">
                <svg viewBox="0 0 300 180" className="w-72 h-44">
                  {/* Circle A */}
                  <circle cx="110" cy="90" r="70" fill="rgba(59,130,246,0.15)" stroke="#3B82F6" strokeWidth="2" />
                  {/* Circle B */}
                  <circle cx="190" cy="90" r="70" fill="rgba(168,85,247,0.15)" stroke="#A855F7" strokeWidth="2" />
                  {/* Labels */}
                  <text x="75" y="90" textAnchor="middle" className="fill-accent-blue text-xl font-bold">
                    {result.only_a_matches}
                  </text>
                  <text x="75" y="108" textAnchor="middle" className="fill-text-muted text-[10px]">
                    A only
                  </text>
                  <text x="150" y="90" textAnchor="middle" className="fill-text-primary text-xl font-bold">
                    {result.shared_matches}
                  </text>
                  <text x="150" y="108" textAnchor="middle" className="fill-text-muted text-[10px]">
                    shared
                  </text>
                  <text x="225" y="90" textAnchor="middle" className="fill-accent-purple text-xl font-bold">
                    {result.only_b_matches}
                  </text>
                  <text x="225" y="108" textAnchor="middle" className="fill-text-muted text-[10px]">
                    B only
                  </text>
                </svg>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-surface-2 rounded-lg p-3 text-center">
                  <p className="text-lg font-bold text-accent-blue tabular-nums">{result.only_a_matches}</p>
                  <p className="text-xs text-text-muted">Only in A</p>
                </div>
                <div className="bg-surface-2 rounded-lg p-3 text-center">
                  <p className="text-lg font-bold text-text-primary tabular-nums">{result.shared_matches}</p>
                  <p className="text-xs text-text-muted">Shared</p>
                </div>
                <div className="bg-surface-2 rounded-lg p-3 text-center">
                  <p className="text-lg font-bold text-accent-purple tabular-nums">{result.only_b_matches}</p>
                  <p className="text-xs text-text-muted">Only in B</p>
                </div>
              </div>

              {/* Overlap ratio */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted">Overlap ratio:</span>
                <div className="flex-1 h-2 bg-surface-3 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-accent-green rounded-full"
                    style={{ width: `${(result.overlap_ratio * 100).toFixed(0)}%` }}
                  />
                </div>
                <Badge variant={result.overlap_ratio > 0.7 ? "green" : result.overlap_ratio > 0.3 ? "orange" : "red"}>
                  {(result.overlap_ratio * 100).toFixed(0)}%
                </Badge>
              </div>

              {/* Per-item breakdown: Only in A / Only in B */}
              <div className="grid grid-cols-2 gap-4 pt-1">
                {/* Only in A */}
                <div>
                  <h4 className="text-xs font-semibold text-accent-blue mb-2">
                    Only in A
                    {result.only_a_sample && result.only_a_sample.length > 0 && (
                      <span className="ml-1 font-normal text-text-muted">
                        ({result.only_a_sample.length} sample{result.only_a_sample.length !== 1 ? "s" : ""})
                      </span>
                    )}
                  </h4>
                  <SampleList
                    items={result.only_a_sample}
                    testId="compare-only-a-list"
                    emptyLabel="No samples available"
                    accentClass="text-accent-blue"
                  />
                </div>

                {/* Only in B */}
                <div>
                  <h4 className="text-xs font-semibold text-accent-purple mb-2">
                    Only in B
                    {result.only_b_sample && result.only_b_sample.length > 0 && (
                      <span className="ml-1 font-normal text-text-muted">
                        ({result.only_b_sample.length} sample{result.only_b_sample.length !== 1 ? "s" : ""})
                      </span>
                    )}
                  </h4>
                  <SampleList
                    items={result.only_b_sample}
                    testId="compare-only-b-list"
                    emptyLabel="No samples available"
                    accentClass="text-accent-purple"
                  />
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
