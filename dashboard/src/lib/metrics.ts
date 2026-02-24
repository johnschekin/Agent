/**
 * Shared metric definitions used by scatter, stats, and other analysis views.
 * Prevents duplication of METRICS arrays, labels, and formatters.
 */
import { formatCurrencyMM } from "./formatters";

export const METRICS = [
  { value: "word_count", label: "Word Count" },
  { value: "definition_count", label: "Definition Count" },
  { value: "clause_count", label: "Clause Count" },
  { value: "section_count", label: "Section Count" },
  { value: "facility_size_mm", label: "Facility Size ($M)" },
  { value: "text_length", label: "Text Length" },
] as const;

/** All metric options plus categorical color options (for scatter). */
export const COLOR_OPTIONS = [
  { value: "", label: "None" },
  { value: "doc_type", label: "Doc Type" },
  { value: "market_segment", label: "Market Segment" },
  ...METRICS,
] as const;

/** Group-by options for statistics views. */
export const GROUP_OPTIONS = [
  { value: "", label: "None" },
  { value: "doc_type", label: "Doc Type" },
  { value: "market_segment", label: "Market Segment" },
  { value: "template_family", label: "Template Family" },
  { value: "admin_agent", label: "Admin Agent" },
  { value: "cohort_included", label: "Cohort Included" },
] as const;

/** Categorical color dimensions (non-numeric). */
export const CATEGORICAL_COLORS = new Set(["doc_type", "market_segment"]);

/** Get human-readable label for a metric or color option. */
export function metricLabel(value: string): string {
  // Check COLOR_OPTIONS (includes METRICS + categorical)
  for (const opt of COLOR_OPTIONS) {
    if (opt.value === value) return opt.label;
  }
  // Check GROUP_OPTIONS for group-by labels
  for (const opt of GROUP_OPTIONS) {
    if (opt.value === value) return opt.label;
  }
  return value;
}

/** Get the appropriate formatter for a metric (currency for facility_size_mm). */
export function metricFormatter(
  metric: string
): ((v: number) => string) | undefined {
  if (metric === "facility_size_mm") return (v) => formatCurrencyMM(v);
  return undefined;
}
