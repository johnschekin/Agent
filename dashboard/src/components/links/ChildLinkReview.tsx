"use client";

import { useCallback, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { HierarchyBreadcrumbs } from "./HierarchyBreadcrumbs";
import { WhyMatchedPopover } from "./WhyMatchedPopover";
import { useNodeLinks, useUnlinkNodeLinkMutation } from "@/lib/queries";
import type { NodeLink, WhyMatchedFactor } from "@/lib/types";

interface ChildLinkReviewProps {
  parentLinkId: string;
  familyId: string;
  className?: string;
}

// Group items sharing the same immediate parent path (everything before the
// last segment in the clause_path, e.g. "1.a.i" → parent "1.a").
function parentPath(clausePath: string): string {
  const parts = clausePath.split(".");
  return parts.length > 1 ? parts.slice(0, -1).join(".") : clausePath;
}

// Extract a text-hash key for clustering identical clause text.
// NodeLink does not currently carry clause_text_hash, so we fall back to
// clause_path as the grouping key when no hash is present.
function textHashKey(nl: NodeLink): string {
  // If the API ever adds clause_text_hash we surface it here.
  return (nl as NodeLink & { clause_text_hash?: string }).clause_text_hash ?? nl.clause_path;
}

type BadgeVariant = "green" | "red" | "default" | "blue" | "orange" | "amber" | "purple" | "cyan" | "teal";

function tierVariant(tier: string): BadgeVariant {
  return tier === "high" ? "green" : tier === "medium" ? "orange" : "red";
}

function statusVariant(status: string): BadgeVariant {
  if (status === "active") return "green";
  if (status === "pending_review") return "orange";
  if (status === "unlinked") return "red";
  return "default";
}

export function ChildLinkReview({ parentLinkId, familyId, className }: ChildLinkReviewProps) {
  const { data: nodeLinksData, isLoading } = useNodeLinks(parentLinkId);
  const unlinkNodeMut = useUnlinkNodeLinkMutation();
  const nodeLinks: NodeLink[] = nodeLinksData?.node_links ?? [];

  // ── Selection state ──────────────────────────────────────────────────────
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // ── Per-row verdicts (optimistic local state) ────────────────────────────
  const [verdicts, setVerdicts] = useState<Map<string, "accepted" | "rejected">>(new Map());

  // ── Sibling basket navigation ────────────────────────────────────────────
  // Track which "sibling basket" (same clause parent path) the user is viewing.
  const [basketCursor, setBasketCursor] = useState<Map<string, number>>(new Map());

  // ── Clustering by clause_text_hash ───────────────────────────────────────
  // Map: hash → list of NodeLinks with that hash
  const clusterMap = useMemo<Map<string, NodeLink[]>>(() => {
    const m = new Map<string, NodeLink[]>();
    for (const nl of nodeLinks) {
      const key = textHashKey(nl);
      const bucket = m.get(key) ?? [];
      bucket.push(nl);
      m.set(key, bucket);
    }
    return m;
  }, [nodeLinks]);

  // Deduplicated list: one representative per cluster (first occurrence).
  const representativeLinks = useMemo<NodeLink[]>(() => {
    const seen = new Set<string>();
    const out: NodeLink[] = [];
    for (const nl of nodeLinks) {
      const key = textHashKey(nl);
      if (!seen.has(key)) {
        seen.add(key);
        out.push(nl);
      }
    }
    return out;
  }, [nodeLinks]);

  // ── Sibling baskets ───────────────────────────────────────────────────────
  // Map: parentClausePath → NodeLink[]
  const siblingBaskets = useMemo<Map<string, NodeLink[]>>(() => {
    const m = new Map<string, NodeLink[]>();
    for (const nl of representativeLinks) {
      const key = parentPath(nl.clause_path);
      const bucket = m.get(key) ?? [];
      bucket.push(nl);
      m.set(key, bucket);
    }
    return m;
  }, [representativeLinks]);

  // ── Helpers ───────────────────────────────────────────────────────────────
  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelected((prev) =>
      prev.size === representativeLinks.length
        ? new Set()
        : new Set(representativeLinks.map((nl) => nl.node_link_id)),
    );
  }, [representativeLinks]);

  const setVerdict = useCallback(
    (id: string, verdict: "accepted" | "rejected") => {
      setVerdicts((prev) => {
        const next = new Map(prev);
        if (next.get(id) === verdict) next.delete(id);
        else next.set(id, verdict);
        return next;
      });
      if (verdict === "rejected") {
        unlinkNodeMut.mutate({ nodeLinkId: id, reason: "child_review_rejected" });
      }
    },
    [unlinkNodeMut],
  );

  const batchAccept = useCallback(() => {
    setVerdicts((prev) => {
      const next = new Map(prev);
      for (const id of Array.from(selected)) next.set(id, "accepted");
      return next;
    });
  }, [selected]);

  const batchReject = useCallback(() => {
    setVerdicts((prev) => {
      const next = new Map(prev);
      for (const id of Array.from(selected)) next.set(id, "rejected");
      return next;
    });
    for (const id of Array.from(selected)) {
      unlinkNodeMut.mutate({ nodeLinkId: id, reason: "child_review_batch_rejected" });
    }
  }, [selected, unlinkNodeMut]);

  const basketNav = useCallback(
    (basketKey: string, delta: number) => {
      setBasketCursor((prev) => {
        const basket = siblingBaskets.get(basketKey) ?? [];
        const cur = prev.get(basketKey) ?? 0;
        const next = new Map(prev);
        next.set(basketKey, Math.max(0, Math.min(basket.length - 1, cur + delta)));
        return next;
      });
    },
    [siblingBaskets],
  );

  // Build the final display list respecting basket cursor offsets.
  // When a basket has multiple siblings, show the item at the current cursor.
  const displayLinks = useMemo<NodeLink[]>(() => {
    const visited = new Set<string>();
    const out: NodeLink[] = [];
    for (const nl of representativeLinks) {
      const bKey = parentPath(nl.clause_path);
      if (visited.has(bKey)) continue;
      visited.add(bKey);
      const basket = siblingBaskets.get(bKey) ?? [nl];
      const cursor = basketCursor.get(bKey) ?? 0;
      out.push(basket[cursor] ?? nl);
    }
    return out;
  }, [representativeLinks, siblingBaskets, basketCursor]);

  // ── Rendering ──────────────────────────────────────────────────────────────
  const allSelected =
    representativeLinks.length > 0 && selected.size === representativeLinks.length;
  const someSelected = selected.size > 0;

  return (
    <div className={cn("space-y-3", className)} data-testid="child-link-review">
      {/* Header */}
      <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
        Existing Child Links ({nodeLinks.length})
      </h4>

      {/* Batch actions bar — shown when at least one row is selected */}
      {someSelected && (
        <div className="flex items-center gap-2 px-3 py-2 bg-surface-2 border border-border rounded-lg">
          <span className="text-xs text-text-muted tabular-nums mr-1">
            {selected.size} selected
          </span>
          <button
            type="button"
            onClick={batchAccept}
            className="px-2.5 py-1 bg-glow-green text-accent-green text-xs font-medium rounded hover:opacity-90 transition-opacity"
            data-testid="child-batch-accept"
          >
            Accept Selected
          </button>
          <button
            type="button"
            onClick={batchReject}
            className="px-2.5 py-1 bg-glow-red text-accent-red text-xs font-medium rounded hover:opacity-90 transition-opacity"
            data-testid="child-batch-reject"
          >
            Reject Selected
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                  Node
                </th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                  Clause Path
                </th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                  Confidence
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colSpan={3} className="px-3 py-4 text-sm text-text-muted text-center">
                  Loading child links...
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : nodeLinks.length === 0 ? (
        <p className="text-sm text-text-muted py-6 text-center">
          No child links for this parent
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                {/* Checkbox column */}
                <th className="px-3 py-2 border-b border-border w-8">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleSelectAll}
                    className="accent-accent-blue cursor-pointer"
                    aria-label="Select all"
                  />
                </th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                  Node
                </th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                  Clause Path
                </th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                  Confidence
                </th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                  Status
                </th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                  Why
                </th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {displayLinks.map((nl) => {
                const bKey = parentPath(nl.clause_path);
                const basket = siblingBaskets.get(bKey) ?? [nl];
                const hasSiblings = basket.length > 1;
                const cursor = basketCursor.get(bKey) ?? 0;
                const clusterCount = clusterMap.get(textHashKey(nl))?.length ?? 1;
                const hasCluster = clusterCount > 1;
                const verdict = verdicts.get(nl.node_link_id);
                const isSelected = selected.has(nl.node_link_id);

                // factors may not exist on NodeLink from the API; cast safely
                const factors: WhyMatchedFactor[] =
                  (nl as NodeLink & { factors?: WhyMatchedFactor[] }).factors ?? [];

                return (
                  <tr
                    key={nl.node_link_id}
                    className={cn(
                      "border-b border-border/30 hover:bg-surface-2/50 transition-colors",
                      isSelected && "bg-surface-2",
                      verdict === "accepted" && "bg-glow-green/20",
                      verdict === "rejected" && "bg-glow-red/20",
                    )}
                    data-testid={`child-link-${nl.node_link_id}`}
                  >
                    {/* Checkbox */}
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(nl.node_link_id)}
                        className="accent-accent-blue cursor-pointer"
                        aria-label={`Select ${nl.node_name}`}
                      />
                    </td>

                    {/* Node name */}
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm text-text-primary">{nl.node_name}</span>
                        {hasCluster && (
                          <Badge variant="default">
                            {clusterCount} identical
                          </Badge>
                        )}
                      </div>
                    </td>

                    {/* Clause path via HierarchyBreadcrumbs + sibling nav */}
                    <td className="px-3 py-2">
                      <div className="flex flex-col gap-1">
                        <HierarchyBreadcrumbs clause={nl.clause_path} />
                        {hasSiblings && (
                          <div className="flex items-center gap-1 mt-0.5">
                            <button
                              type="button"
                              onClick={() => basketNav(bKey, -1)}
                              disabled={cursor === 0}
                              className="px-1 py-0.5 text-[10px] text-text-muted hover:text-text-primary disabled:opacity-30 rounded transition-colors"
                              aria-label="Previous sibling"
                            >
                              ‹ prev
                            </button>
                            <span className="text-[10px] text-text-muted tabular-nums">
                              {cursor + 1} / {basket.length}
                            </span>
                            <button
                              type="button"
                              onClick={() => basketNav(bKey, 1)}
                              disabled={cursor === basket.length - 1}
                              className="px-1 py-0.5 text-[10px] text-text-muted hover:text-text-primary disabled:opacity-30 rounded transition-colors"
                              aria-label="Next sibling"
                            >
                              next ›
                            </button>
                          </div>
                        )}
                      </div>
                    </td>

                    {/* Confidence badge */}
                    <td className="px-3 py-2">
                      <Badge variant={tierVariant(nl.confidence_tier)}>
                        {(nl.confidence * 100).toFixed(0)}%
                      </Badge>
                    </td>

                    {/* Status badge */}
                    <td className="px-3 py-2">
                      <Badge variant={statusVariant(nl.status)}>
                        {nl.status.replace(/_/g, " ")}
                      </Badge>
                    </td>

                    {/* WhyMatchedPopover */}
                    <td className="px-3 py-2">
                      <WhyMatchedPopover
                        factors={factors}
                        confidence={nl.confidence}
                        confidenceTier={nl.confidence_tier}
                        trigger={
                          <span className="text-xs text-accent-blue underline-offset-2 underline cursor-pointer">
                            Why?
                          </span>
                        }
                      />
                    </td>

                    {/* Accept / Reject actions */}
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setVerdict(nl.node_link_id, "accepted")}
                          className={cn(
                            "px-2 py-0.5 rounded text-xs font-medium transition-colors",
                            verdict === "accepted"
                              ? "bg-glow-green text-accent-green"
                              : "text-text-muted hover:text-accent-green hover:bg-glow-green",
                          )}
                          data-testid={`child-link-accept-${nl.node_link_id}`}
                          aria-label={`Accept ${nl.node_name}`}
                        >
                          Accept
                        </button>
                        <button
                          type="button"
                          onClick={() => setVerdict(nl.node_link_id, "rejected")}
                          className={cn(
                            "px-2 py-0.5 rounded text-xs font-medium transition-colors",
                            verdict === "rejected"
                              ? "bg-glow-red text-accent-red"
                              : "text-text-muted hover:text-accent-red hover:bg-glow-red",
                          )}
                          data-testid={`child-link-reject-${nl.node_link_id}`}
                          aria-label={`Reject ${nl.node_name}`}
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
      )}
    </div>
  );
}
