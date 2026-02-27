"use client";

import { useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { ChartCard } from "@/components/ui/ChartCard";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ClauseAnomalyDetail } from "@/components/edge-cases/ClauseAnomalyDetail";
import { DefinitionAnomalyDetail } from "@/components/edge-cases/DefinitionAnomalyDetail";
import { useEdgeCases } from "@/lib/queries";
import { formatNumber, formatCurrencyMM } from "@/lib/formatters";
import { cn } from "@/lib/cn";
import { SEVERITY_COLORS } from "@/lib/colors";
import type { EdgeCaseRecord } from "@/lib/types";

// --- Tier labels ---

const TIER_ORDER = [
  "structural",
  "clauses",
  "definitions",
  "metadata",
  "document",
  "template",
] as const;

const TIER_LABELS: Record<string, string> = {
  structural: "Structural",
  clauses: "Clauses",
  definitions: "Definitions",
  metadata: "Metadata",
  document: "Document Quality",
  template: "Template",
};

const TIER_COLORS: Record<string, "red" | "orange" | undefined> = {
  structural: "red",
  clauses: "red",
  definitions: "orange",
  metadata: "orange",
  document: undefined,
  template: undefined,
};

const GROUP_LABELS: Record<string, string> = {
  parser_integrity: "Parser Integrity",
  baseline_enrichment: "Baseline Enrichment",
  outlier_monitoring: "Outlier Monitoring",
  all: "All Signals",
};
const GROUP_ORDER = [
  "parser_integrity",
  "baseline_enrichment",
  "outlier_monitoring",
  "all",
] as const;
const COLLISION_HOT_RANK: Record<string, number> = {
  clause_dup_id_burst: 0,
  clause_root_label_repeat_explosion: 1,
  clause_depth_reset_after_deep: 2,
};

// --- Category labels (38 categories across 6 tiers) ---

const CATEGORY_LABELS: Record<string, string> = {
  // Structural
  missing_sections: "Missing Sections",
  low_section_count: "Low Section Count",
  excessive_section_count: "Excessive Sections",
  section_fallback_used: "Fallback Parser Used",
  section_numbering_gap: "Section Numbering Gap",
  empty_section_headings: "Empty Section Headings",
  // Clauses
  zero_clauses: "Zero Clauses",
  low_clause_density: "Low Clause Density",
  low_avg_clause_confidence: "Low Clause Confidence",
  orphan_deep_clause: "Orphan Deep Clause",
  inconsistent_sibling_depth: "Inconsistent Sibling Depth",
  deep_nesting_outlier: "Deep Nesting Outlier",
  low_structural_ratio: "Low Structural Ratio",
  rootless_deep_clause: "Rootless Deep Clause",
  clause_root_label_repeat_explosion: "Root Label Repeat Explosion",
  clause_dup_id_burst: "Clause ID Dup Burst",
  clause_depth_reset_after_deep: "Depth Reset After Deep",
  // Definitions
  low_definitions: "Low Definitions",
  zero_definitions: "Zero Definitions",
  high_definition_count: "High Definition Count",
  duplicate_definitions: "Duplicate Definitions",
  single_engine_definitions: "Single Engine Defs",
  definition_truncated_at_cap: "Definition Truncated At Cap",
  definition_signature_leak: "Definition Signature Leak",
  definition_malformed_term: "Definition Malformed Term",
  // Metadata
  extreme_facility: "Extreme Facility Size",
  missing_borrower: "Missing Borrower",
  missing_facility_size: "Missing Facility Size",
  missing_closing_date: "Missing Closing Date",
  unknown_doc_type: "Unknown Doc Type",
  // Document Quality
  extreme_word_count: "Extreme Word Count",
  short_text: "Short Text",
  extreme_text_ratio: "High Text/Word Ratio",
  very_short_document: "Very Short Document",
  // Template
  orphan_template: "No Template Family",
  non_credit_agreement: "Non-Credit Agreement",
  uncertain_market_segment: "Uncertain Segment",
  non_cohort_large_doc: "Large Non-Cohort Doc",
};

// Categories that support clause-level drill-down
const CLAUSE_DRILL_DOWN_CATEGORIES = new Set([
  "inconsistent_sibling_depth",
  "orphan_deep_clause",
  "deep_nesting_outlier",
  "low_avg_clause_confidence",
  "low_structural_ratio",
  "rootless_deep_clause",
  "clause_root_label_repeat_explosion",
  "clause_dup_id_burst",
  "clause_depth_reset_after_deep",
]);

const DEFINITION_DRILL_DOWN_CATEGORIES = new Set([
  "definition_truncated_at_cap",
  "definition_signature_leak",
  "definition_malformed_term",
]);

// --- Edge case row ---

function EdgeCaseRow({
  item,
  onDocClick,
}: {
  item: EdgeCaseRecord;
  onDocClick: (docId: string, category: string) => void;
}) {
  return (
    <tr
      className="border-t border-border hover:bg-surface-3/50 cursor-pointer transition-colors"
      onClick={() => onDocClick(item.doc_id, item.category)}
    >
      <td className="px-3 py-2">
        <button
          className="text-accent-blue hover:underline text-xs font-mono"
          onClick={(e) => {
            e.stopPropagation();
            onDocClick(item.doc_id, item.category);
          }}
          title={
            CLAUSE_DRILL_DOWN_CATEGORIES.has(item.category) || DEFINITION_DRILL_DOWN_CATEGORIES.has(item.category)
              ? `Inspect edge-case rows in ${item.doc_id}`
              : `Open ${item.doc_id} in Explorer`
          }
        >
          {item.doc_id.slice(0, 16)}
        </button>
      </td>
      <td className="px-3 py-2 text-text-secondary text-xs truncate max-w-[160px]">
        {item.borrower || "\u2014"}
      </td>
      <td className="px-3 py-2">
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-3 text-text-secondary border border-border">
          {CATEGORY_LABELS[item.category] ?? item.category}
        </span>
      </td>
      <td className="px-3 py-2">
        <span
          className={cn(
            "inline-block px-1.5 py-0.5 rounded text-[10px] font-medium",
            SEVERITY_COLORS[item.severity] ?? SEVERITY_COLORS.low
          )}
        >
          {item.severity}
        </span>
      </td>
      <td className="px-3 py-2 text-xs text-text-secondary max-w-[300px] truncate" title={item.detail}>
        {item.detail}
      </td>
      <td className="px-3 py-2 text-xs text-text-secondary">
        {item.doc_type}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.word_count)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.section_count)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.clause_count)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {formatNumber(item.definition_count)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-xs">
        {item.facility_size_mm != null ? formatCurrencyMM(item.facility_size_mm) : "\u2014"}
      </td>
    </tr>
  );
}

// --- Main page ---

export default function EdgeCasesPage() {
  const router = useRouter();
  const [category, setCategory] = useState("all");
  const [group, setGroup] = useState("parser_integrity");
  const [includeMonitorOnly, setIncludeMonitorOnly] = useState(false);
  const [cohortOnly, setCohortOnly] = useState(true);
  const [page, setPage] = useState(0);
  const detectorStatus = includeMonitorOnly ? "all" : "active";

  // Drill-down state for clause anomaly categories
  const [selectedDoc, setSelectedDoc] = useState<{
    docId: string;
    category: string;
  } | null>(null);

  const edgeCases = useEdgeCases({
    category,
    group,
    detectorStatus,
    page,
    pageSize: 50,
    cohortOnly,
  });

  const handleDocClick = useCallback(
    (docId: string, itemCategory: string) => {
      if (
        CLAUSE_DRILL_DOWN_CATEGORIES.has(itemCategory) ||
        DEFINITION_DRILL_DOWN_CATEGORIES.has(itemCategory)
      ) {
        setSelectedDoc({ docId, category: itemCategory });
      } else {
        router.push(`/explorer?selected=${encodeURIComponent(docId)}`);
      }
    },
    [router]
  );

  const handleCategoryChange = useCallback((key: string) => {
    setCategory(key);
    setPage(0);
    setSelectedDoc(null);
  }, []);

  const handleGroupChange = useCallback((nextGroup: string) => {
    setGroup(nextGroup);
    setCategory("all");
    setPage(0);
    setSelectedDoc(null);
  }, []);

  const data = edgeCases.data;
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;

  // Global total from category sums (not data.total which is filtered)
  const globalTotal = useMemo(() => {
    if (!data) return 0;
    return data.categories.reduce((sum, c) => sum + c.count, 0);
  }, [data]);

  // Compute tier counts from API response
  const tierCounts = useMemo(() => {
    if (!data) return new Map<string, number>();
    const m = new Map<string, number>();
    for (const c of data.categories) {
      const tier = c.tier ?? "unknown";
      m.set(tier, (m.get(tier) ?? 0) + c.count);
    }
    return m;
  }, [data]);

  // Build tier-grouped category pills from API response
  const tierGroupedPills = useMemo(() => {
    if (!data) return new Map<string, { key: string; label: string; count: number }[]>();
    const countMap = new Map<string, { count: number; tier: string }>();
    for (const c of data.categories) {
      countMap.set(c.category, { count: c.count, tier: c.tier });
    }
    const grouped = new Map<string, { key: string; label: string; count: number }[]>();
    for (const tier of TIER_ORDER) {
      const pills: { key: string; label: string; count: number }[] = [];
      for (const [catKey, catLabel] of Object.entries(CATEGORY_LABELS)) {
        const info = countMap.get(catKey);
        if (info && info.tier === tier && info.count > 0) {
          pills.push({ key: catKey, label: catLabel, count: info.count });
        }
      }
      if (group === "parser_integrity" && tier === "clauses") {
        pills.sort((a, b) => {
          const aHot = Object.prototype.hasOwnProperty.call(COLLISION_HOT_RANK, a.key);
          const bHot = Object.prototype.hasOwnProperty.call(COLLISION_HOT_RANK, b.key);
          if (aHot && bHot) return COLLISION_HOT_RANK[a.key] - COLLISION_HOT_RANK[b.key];
          if (aHot) return -1;
          if (bHot) return 1;
          return b.count - a.count || a.label.localeCompare(b.label);
        });
      }
      if (pills.length > 0) {
        grouped.set(tier, pills);
      }
    }
    return grouped;
  }, [data]);

  return (
    <ViewContainer title="Edge Case Inspector">
      {/* Controls */}
      <div className="mb-4">
        <div className="flex flex-wrap items-center gap-2 mb-2">
          {GROUP_ORDER.map((groupKey) => (
            <button
              key={groupKey}
              onClick={() => handleGroupChange(groupKey)}
              className={cn(
                "px-2.5 py-1 rounded-sm text-xs font-medium transition-colors",
                group === groupKey
                  ? "bg-accent-blue/20 text-accent-blue"
                  : "bg-surface-3 text-text-muted hover:text-text-secondary border border-border"
              )}
            >
              {GROUP_LABELS[groupKey]}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={includeMonitorOnly}
              onChange={(e) => {
                setIncludeMonitorOnly(e.target.checked);
                setCategory("all");
                setPage(0);
              }}
              className="accent-accent-blue"
            />
            Include monitor-only detectors
          </label>
        <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={cohortOnly}
            onChange={(e) => {
              setCohortOnly(e.target.checked);
              setPage(0);
            }}
            className="accent-accent-blue"
          />
          Cohort Only
        </label>
        </div>
      </div>

      {/* KPI cards — tier-level summaries */}
      <KpiCardGrid className="mb-4">
        <KpiCard
          title="Total Edge Cases"
          value={data ? formatNumber(globalTotal) : "\u2014"}
          color="orange"
        />
        {TIER_ORDER.map((tier) => (
          <KpiCard
            key={tier}
            title={TIER_LABELS[tier]}
            value={data ? formatNumber(tierCounts.get(tier) ?? 0) : "\u2014"}
            color={TIER_COLORS[tier]}
          />
        ))}
      </KpiCardGrid>

      {edgeCases.isLoading && !data && (
        <LoadingState message="Detecting edge cases..." />
      )}

      {edgeCases.error && !data && (
        <EmptyState
          title="Failed to load"
          message="Edge case detection query failed. Check the API server."
        />
      )}

      {data && (
        <ChartCard title="" height="auto">
          {/* "All" pill */}
          <div className="mb-2">
            <button
              onClick={() => handleCategoryChange("all")}
              className={cn(
                "px-2.5 py-1 rounded-sm text-xs font-medium transition-colors",
                category === "all"
                  ? "bg-accent-blue/20 text-accent-blue"
                  : "bg-surface-3 text-text-muted hover:text-text-secondary border border-border"
              )}
            >
              All
              <span className="ml-1 text-[10px] opacity-70">
                {globalTotal}
              </span>
            </button>
          </div>

          {/* Category filter pills grouped by tier */}
          <div className="mb-3">
            {TIER_ORDER.map((tierKey) => {
              const tierPills = tierGroupedPills.get(tierKey);
              if (!tierPills || tierPills.length === 0) return null;
              return (
                <div key={tierKey} className="flex flex-wrap items-center gap-1.5 mb-1.5">
                  <span className="text-[10px] uppercase text-text-muted font-semibold w-20 shrink-0">
                    {TIER_LABELS[tierKey]}
                  </span>
                  {tierPills.map((pill) => (
                    <button
                      key={pill.key}
                      onClick={() => handleCategoryChange(pill.key)}
                      className={cn(
                        "px-2 py-0.5 rounded-sm text-[11px] font-medium transition-colors",
                        category === pill.key
                          ? "bg-accent-blue/20 text-accent-blue"
                          : "bg-surface-3 text-text-muted hover:text-text-secondary border border-border"
                      )}
                    >
                      {pill.label}
                      <span className="ml-1 text-[10px] opacity-70">
                        {pill.count}
                      </span>
                    </button>
                  ))}
                </div>
              );
            })}
          </div>

          {/* Stale indicator */}
          {edgeCases.isPlaceholderData && (
            <div className="text-xs text-text-muted mb-2 animate-pulse">
              Updating&hellip;
            </div>
          )}

          {/* Table */}
          {data.cases.length === 0 ? (
            <EmptyState
              title="No edge cases"
              message={
                category === "all"
                  ? "No edge cases detected in the corpus."
                  : `No documents with "${CATEGORY_LABELS[category] ?? category}" issues.`
              }
            />
          ) : (
            <div
              className={cn(
                edgeCases.isPlaceholderData && "opacity-60 transition-opacity"
              )}
            >
              <div className="overflow-auto max-h-[500px]">
                <table
                  className="w-full text-sm"
                  aria-label="Edge case documents"
                >
                  <thead className="sticky top-0 bg-surface-3 z-10">
                    <tr className="text-left text-xs text-text-muted uppercase">
                      <th className="px-3 py-2">Doc ID</th>
                      <th className="px-3 py-2">Borrower</th>
                      <th className="px-3 py-2">Category</th>
                      <th className="px-3 py-2">Severity</th>
                      <th className="px-3 py-2">Detail</th>
                      <th className="px-3 py-2">Doc Type</th>
                      <th className="px-3 py-2 text-right">Words</th>
                      <th className="px-3 py-2 text-right">Sections</th>
                      <th className="px-3 py-2 text-right">Clauses</th>
                      <th className="px-3 py-2 text-right">Definitions</th>
                      <th className="px-3 py-2 text-right">Facility</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.cases.map((c, i) => (
                      <EdgeCaseRow
                        key={`${c.doc_id}_${c.category}_${i}`}
                        item={c}
                        onDocClick={handleDocClick}
                      />
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
                  <span className="text-xs text-text-muted">
                    {formatNumber(data.total)} edge cases total
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage((p) => Math.max(0, p - 1))}
                      disabled={page === 0}
                      className="px-2 py-1 text-xs rounded-sm bg-surface-3 text-text-secondary hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed border border-border"
                    >
                      Previous
                    </button>
                    <span className="text-xs text-text-muted tabular-nums">
                      Page {page + 1} of {totalPages}
                    </span>
                    <button
                      onClick={() =>
                        setPage((p) => Math.min(totalPages - 1, p + 1))
                      }
                      disabled={page >= totalPages - 1}
                      className="px-2 py-1 text-xs rounded-sm bg-surface-3 text-text-secondary hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed border border-border"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </ChartCard>
      )}

      {/* Clause / definition anomaly drill-down panel */}
      {selectedDoc && (
        CLAUSE_DRILL_DOWN_CATEGORIES.has(selectedDoc.category) ? (
          <ClauseAnomalyDetail
            docId={selectedDoc.docId}
            category={selectedDoc.category}
            onClose={() => setSelectedDoc(null)}
          />
        ) : (
          <DefinitionAnomalyDetail
            docId={selectedDoc.docId}
            category={selectedDoc.category}
            onClose={() => setSelectedDoc(null)}
          />
        )
      )}
    </ViewContainer>
  );
}
