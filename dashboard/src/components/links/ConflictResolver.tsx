"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { CompoundCovenantOverlay } from "./CompoundCovenantOverlay";
import { SubClauseSplitter, type SplitAssignment } from "./SubClauseSplitter";
import {
  useCreateConflictPolicyMutation,
  useBatchUnlinkMutation,
} from "@/lib/queries";
import type { ConflictGroup, ConflictPolicy } from "@/lib/types";

interface ConflictResolverProps {
  conflict: ConflictGroup;
  policies: ConflictPolicy[];
  onResolve: () => void;
  onClose: () => void;
}

const POLICY_COLORS: Record<string, "green" | "orange" | "red" | "purple" | "default"> = {
  coexist: "green",
  shared_ok: "green",
  subsumes: "orange",
  warn: "orange",
  exclusive: "red",
  compound_covenant: "purple",
};

const FAMILY_COLORS = ["#3B82F6", "#22C55E", "#F59E0B", "#A855F7", "#14B8A6", "#EF4444"];

type ResolutionType = "winner" | "compound" | "split";

function getConflictLinkId(conflict: ConflictGroup, familyId: string): string | null {
  const fromEvidence = conflict.evidence_by_family?.[familyId]?.link_id;
  if (fromEvidence && fromEvidence.trim().length > 0) {
    return fromEvidence;
  }
  const fromLinks = conflict.links?.find((row) => row.family_id === familyId)?.link_id;
  if (fromLinks && fromLinks.trim().length > 0) {
    return fromLinks;
  }
  return null;
}

function getUniqueEvidenceCount(conflict: ConflictGroup, familyId: string): number {
  const fromEvidence = conflict.evidence_by_family?.[familyId]?.unique_count;
  if (typeof fromEvidence === "number") {
    return fromEvidence;
  }
  return 0;
}

export function ConflictResolver({
  conflict,
  policies,
  onResolve,
  onClose,
}: ConflictResolverProps) {
  const [resolutionType, setResolutionType] = useState<ResolutionType>("winner");
  const [winnerFamilyId, setWinnerFamilyId] = useState(conflict.families[0] ?? "");
  const [metaRuleFormOpen, setMetaRuleFormOpen] = useState(false);
  const [metaRuleFamilyA, setMetaRuleFamilyA] = useState(conflict.families[0] ?? "");
  const [metaRuleFamilyB, setMetaRuleFamilyB] = useState(conflict.families[1] ?? "");
  const [metaRulePolicy, setMetaRulePolicy] = useState("coexist");
  const [metaRuleReason, setMetaRuleReason] = useState("");
  const [compoundValidationError, setCompoundValidationError] = useState<string | null>(null);
  const [resolutionError, setResolutionError] = useState<string | null>(null);

  const panelRef = useRef<HTMLDivElement>(null);

  const createPolicyMut = useCreateConflictPolicyMutation();
  const batchUnlinkMut = useBatchUnlinkMutation();

  // Keyboard shortcuts: 1/2/3 select resolution, Enter apply, Escape close
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT") return;

      switch (e.key) {
        case "1":
          e.preventDefault();
          setResolutionType("winner");
          break;
        case "2":
          e.preventDefault();
          setResolutionType("compound");
          break;
        case "3":
          e.preventDefault();
          setResolutionType("split");
          break;
        case "Enter":
          e.preventDefault();
          handleApply();
          break;
        case "Escape":
          e.preventDefault();
          onClose();
          break;
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolutionType, winnerFamilyId, onClose]);

  const handleApply = useCallback(() => {
    setResolutionError(null);
    if (resolutionType === "winner") {
      const losers = conflict.families.filter((f) => f !== winnerFamilyId);
      const missingLinkIdFamilies = losers.filter((familyId) => !getConflictLinkId(conflict, familyId));
      if (missingLinkIdFamilies.length > 0) {
        setResolutionError(
          `Cannot resolve winner: missing link_id for ${missingLinkIdFamilies.join(", ")}`,
        );
        return;
      }
      if (losers.length > 0) {
        const loserLinkIds = losers
          .map((familyId) => getConflictLinkId(conflict, familyId))
          .filter((linkId): linkId is string => !!linkId);
        batchUnlinkMut.mutate(
          {
            linkIds: loserLinkIds,
            reason: `Conflict resolved: winner=${winnerFamilyId}`,
          },
          { onSuccess: () => onResolve() },
        );
        return;
      }
      onResolve();
      return;
    } else if (resolutionType === "compound") {
      if (conflict.families.length < 2) {
        setCompoundValidationError("Compound covenant requires at least 2 families");
        return;
      }
      const missingIndependentEvidence = conflict.families.filter(
        (familyId) => getUniqueEvidenceCount(conflict, familyId) < 1,
      );
      if (missingIndependentEvidence.length > 0) {
        setCompoundValidationError(
          `Independent evidence required for: ${missingIndependentEvidence.join(", ")}`,
        );
        return;
      }
      setCompoundValidationError(null);
      const pairs: [string, string][] = [];
      for (let i = 0; i < conflict.families.length; i++) {
        for (let j = i + 1; j < conflict.families.length; j++) {
          pairs.push([conflict.families[i], conflict.families[j]]);
        }
      }
      const [a, b] = pairs[0];
      createPolicyMut.mutate(
        { family_a: a, family_b: b, policy: "compound_covenant", reason: "Compound covenant resolution" },
        { onSuccess: () => onResolve() },
      );
      return;
    }
    if (resolutionType === "split") {
      setResolutionError("Use the splitter below and click \"Apply Split\" to finalize split resolution.");
    }
    return;
  }, [resolutionType, winnerFamilyId, conflict, batchUnlinkMut, createPolicyMut, onResolve]);

  const handleCreateMetaRule = useCallback(() => {
    createPolicyMut.mutate(
      {
        family_a: metaRuleFamilyA,
        family_b: metaRuleFamilyB,
        policy: metaRulePolicy,
        reason: metaRuleReason || undefined,
      },
      {
        onSuccess: () => {
          setMetaRuleFormOpen(false);
          onResolve();
        },
      },
    );
  }, [createPolicyMut, metaRuleFamilyA, metaRuleFamilyB, metaRulePolicy, metaRuleReason, onResolve]);

  // Get policy for a pair of families
  const getPolicyForFamily = (familyId: string): ConflictPolicy | undefined => {
    return policies.find(
      (p) =>
        (p.family_a === familyId || p.family_b === familyId) &&
        conflict.families.includes(p.family_a) &&
        conflict.families.includes(p.family_b),
    );
  };

  const isApplying = batchUnlinkMut.isPending || createPolicyMut.isPending;

  return (
    <div
      ref={panelRef}
      className="fixed inset-y-0 right-0 w-[28rem] bg-surface-1 border-l border-border shadow-overlay z-40 flex flex-col"
      data-testid="conflict-resolver"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">
            Resolve Conflict
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            {conflict.heading}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="default">{conflict.doc_id}</Badge>
          <Badge variant="blue">{conflict.family_count} families</Badge>
          <button
            type="button"
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors text-lg leading-none ml-2"
            data-testid="conflict-resolver-close"
          >
            &times;
          </button>
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {/* Family list with policy badges */}
        <div>
          <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
            Conflicting Families
          </p>
          <div className="space-y-1.5">
            {conflict.families.map((fam, idx) => {
              const policy = getPolicyForFamily(fam);
              const policyName = policy?.policy ?? "unknown";
              const uniqueEvidenceCount = getUniqueEvidenceCount(conflict, fam);
              const linkId = getConflictLinkId(conflict, fam);
              return (
                <div
                  key={fam}
                  className="flex items-center justify-between px-3 py-2 bg-surface-2 rounded-lg"
                  data-testid={`conflict-family-${fam}`}
                >
                  <div className="flex items-center gap-2">
                    <div
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{ backgroundColor: FAMILY_COLORS[idx % FAMILY_COLORS.length] }}
                    />
                    <div className="flex flex-col">
                      <span className="text-sm text-text-primary">{fam}</span>
                      <span className="text-[10px] text-text-muted">
                        {uniqueEvidenceCount} unique evidence
                        {!linkId ? " • missing link id" : ""}
                      </span>
                    </div>
                  </div>
                  <Badge variant={POLICY_COLORS[policyName] ?? "default"}>
                    {policyName}
                  </Badge>
                </div>
              );
            })}
          </div>
        </div>

        {/* Resolution options */}
        <div>
          <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
            Resolution <span className="normal-case font-normal">(1/2/3 to select, Enter to apply, Esc to close)</span>
          </p>
          <div className="space-y-2">
            {/* Option 1: Choose winner */}
            <label
              className={cn(
                "flex items-start gap-3 px-3 py-2.5 rounded-lg border transition-colors cursor-pointer",
                resolutionType === "winner"
                  ? "border-accent-blue bg-glow-blue"
                  : "border-border hover:bg-surface-2",
              )}
              data-testid="resolution-winner"
            >
              <input
                type="radio"
                name="resolution"
                value="winner"
                checked={resolutionType === "winner"}
                onChange={() => setResolutionType("winner")}
                className="mt-0.5 accent-accent-blue"
              />
              <div className="flex-1">
                <p className="text-sm font-medium text-text-primary">
                  <span className="text-text-muted mr-1">1.</span> Choose Winner
                </p>
                <p className="text-xs text-text-muted mt-0.5">
                  Keep one family, unlink the others
                </p>
                {resolutionType === "winner" && (
                  <select
                    value={winnerFamilyId}
                    onChange={(e) => setWinnerFamilyId(e.target.value)}
                    className="mt-2 w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-text-primary"
                    data-testid="winner-family-select"
                  >
                    {conflict.families.map((fam) => (
                      <option key={fam} value={fam}>
                        {fam}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </label>

            {/* Option 2: Compound covenant */}
            <label
              className={cn(
                "flex items-start gap-3 px-3 py-2.5 rounded-lg border transition-colors cursor-pointer",
                resolutionType === "compound"
                  ? "border-accent-purple bg-glow-purple"
                  : "border-border hover:bg-surface-2",
              )}
              data-testid="resolution-compound"
            >
              <input
                type="radio"
                name="resolution"
                value="compound"
                checked={resolutionType === "compound"}
                onChange={() => {
                  setResolutionType("compound");
                  setCompoundValidationError(null);
                  setResolutionError(null);
                }}
                className="mt-0.5 accent-accent-purple"
              />
              <div className="flex-1">
                <p className="text-sm font-medium text-text-primary">
                  <span className="text-text-muted mr-1">2.</span> Mark Compound Covenant
                </p>
                <p className="text-xs text-text-muted mt-0.5">
                  Section legitimately covers multiple families (requires independent evidence per family)
                </p>
                {compoundValidationError && resolutionType === "compound" && (
                  <p className="text-xs text-accent-red mt-1" data-testid="compound-validation-error">
                    {compoundValidationError}
                  </p>
                )}
              </div>
            </label>

            {/* Option 3: Split section */}
            <label
              className={cn(
                "flex items-start gap-3 px-3 py-2.5 rounded-lg border transition-colors cursor-pointer",
                resolutionType === "split"
                  ? "border-accent-orange bg-glow-amber"
                  : "border-border hover:bg-surface-2",
              )}
              data-testid="resolution-split"
            >
              <input
                type="radio"
                name="resolution"
                value="split"
                checked={resolutionType === "split"}
                onChange={() => {
                  setResolutionType("split");
                  setResolutionError(null);
                  setCompoundValidationError(null);
                }}
                className="mt-0.5 accent-accent-orange"
              />
              <div className="flex-1">
                <p className="text-sm font-medium text-text-primary">
                  <span className="text-text-muted mr-1">3.</span> Split Section
                </p>
                <p className="text-xs text-text-muted mt-0.5">
                  Assign sub-clause ranges to different families
                </p>
              </div>
            </label>
          </div>
        </div>

        {/* Sub-clause splitter */}
        {resolutionType === "split" && (
          <SubClauseSplitter
            sectionText={`Section ${conflict.section_number}: ${conflict.heading}`}
            families={conflict.families.map((fam, idx) => ({
              family_id: fam,
              family_name: fam,
              color: FAMILY_COLORS[idx % FAMILY_COLORS.length],
            }))}
            onSplit={(assignments: SplitAssignment[]) => {
              setResolutionError(null);
              const assignedFamilies = new Set(assignments.map((a) => a.family_id));
              const unassigned = conflict.families.filter((f) => !assignedFamilies.has(f));
              const missingLinkIdFamilies = unassigned.filter((familyId) => !getConflictLinkId(conflict, familyId));
              if (missingLinkIdFamilies.length > 0) {
                setResolutionError(
                  `Cannot apply split: missing link_id for ${missingLinkIdFamilies.join(", ")}`,
                );
                return;
              }
              const unassignedLinkIds = unassigned
                .map((familyId) => getConflictLinkId(conflict, familyId))
                .filter((linkId): linkId is string => !!linkId);
              if (unassigned.length > 0) {
                batchUnlinkMut.mutate(
                  {
                    linkIds: unassignedLinkIds,
                    reason: `Split resolution: sub-clause assignment (${assignments.length} ranges)`,
                  },
                  { onSuccess: () => onResolve() },
                );
              } else {
                onResolve();
              }
            }}
            onCancel={() => setResolutionType("winner")}
          />
        )}

        {/* Compound covenant overlay */}
        {resolutionType === "compound" && (
          <CompoundCovenantOverlay
            sectionText={`Section ${conflict.section_number}: ${conflict.heading}`}
            families={conflict.families.map((fam, idx) => ({
              family_id: fam,
              family_name: fam,
              color: FAMILY_COLORS[idx % FAMILY_COLORS.length],
            }))}
          />
        )}

        {/* Apply button */}
        <button
          type="button"
          onClick={handleApply}
          disabled={isApplying}
          className="w-full px-3 py-2.5 bg-accent-blue text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
          data-testid="conflict-apply"
        >
          {isApplying ? "Applying..." : "Apply Resolution"}
        </button>

        {/* Error display */}
        {batchUnlinkMut.isError && (
          <p className="text-xs text-accent-red">
            Failed to apply resolution: {batchUnlinkMut.error?.message ?? "Unknown error"}
          </p>
        )}
        {resolutionError && (
          <p className="text-xs text-accent-red" data-testid="resolution-error">
            {resolutionError}
          </p>
        )}

        {/* Meta-rule creation */}
        <div className="border-t border-border pt-3">
          <button
            type="button"
            onClick={() => setMetaRuleFormOpen(!metaRuleFormOpen)}
            className="text-sm text-accent-blue hover:underline"
            data-testid="create-meta-rule-toggle"
          >
            {metaRuleFormOpen ? "Cancel meta-rule" : "Create meta-rule"}
          </button>

          {metaRuleFormOpen && (
            <div className="mt-3 space-y-2">
              <div className="flex gap-2">
                <select
                  value={metaRuleFamilyA}
                  onChange={(e) => setMetaRuleFamilyA(e.target.value)}
                  className="flex-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-text-primary"
                >
                  {conflict.families.map((fam) => (
                    <option key={fam} value={fam}>{fam}</option>
                  ))}
                </select>
                <select
                  value={metaRuleFamilyB}
                  onChange={(e) => setMetaRuleFamilyB(e.target.value)}
                  className="flex-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-text-primary"
                >
                  {conflict.families.map((fam) => (
                    <option key={fam} value={fam}>{fam}</option>
                  ))}
                </select>
              </div>
              <select
                value={metaRulePolicy}
                onChange={(e) => setMetaRulePolicy(e.target.value)}
                className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-text-primary"
                data-testid="meta-rule-policy-select"
              >
                <option value="coexist">Coexist</option>
                <option value="exclusive">Exclusive</option>
                <option value="subsumes">Subsumes</option>
                <option value="compound_covenant">Compound Covenant</option>
              </select>
              <textarea
                value={metaRuleReason}
                onChange={(e) => setMetaRuleReason(e.target.value)}
                placeholder="Reason (optional)"
                className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-text-primary resize-none h-16"
              />
              <button
                type="button"
                onClick={handleCreateMetaRule}
                disabled={createPolicyMut.isPending}
                className="w-full px-3 py-2 bg-accent-purple text-white text-sm rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                data-testid="save-meta-rule"
              >
                {createPolicyMut.isPending ? "Saving..." : "Save Meta-Rule"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
