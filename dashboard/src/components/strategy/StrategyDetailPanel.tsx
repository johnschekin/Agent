"use client";

import { useStrategy } from "@/lib/queries";
import { LoadingState } from "@/components/ui/Spinner";
import { Badge } from "@/components/ui/Badge";
import { StrategyMetricsBar } from "./StrategyMetricsBar";
import { cn } from "@/lib/cn";

const STATUS_VARIANT: Record<string, "green" | "blue" | "orange" | "default"> =
  {
    production: "green",
    corpus_validated: "blue",
    bootstrap: "default",
  };

interface StrategyDetailPanelProps {
  conceptId: string | null;
  onClose: () => void;
}

function TagList({ items, color }: { items: string[]; color?: string }) {
  if (items.length === 0)
    return <span className="text-xs text-text-muted italic">None</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((item, i) => (
        <span
          key={i}
          className={cn(
            "text-[11px] px-1.5 py-0.5 rounded font-mono",
            color ?? "bg-surface-3 text-text-secondary"
          )}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wide">
        {title}
      </h4>
      {children}
    </div>
  );
}

export function StrategyDetailPanel({
  conceptId,
  onClose,
}: StrategyDetailPanelProps) {
  const { data, isLoading, error } = useStrategy(conceptId);

  return (
    <div
      className={cn(
        "fixed top-0 right-0 h-full bg-surface-2 border-l border-border",
        "w-[480px] max-w-[calc(100vw-260px)]",
        "transform transition-transform duration-200 ease-in-out z-30",
        "flex flex-col overflow-hidden",
        conceptId ? "translate-x-0" : "translate-x-full"
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface-3 flex-shrink-0">
        <h3 className="text-sm font-medium text-text-primary truncate pr-4">
          {data?.concept_name || conceptId || "Strategy Detail"}
        </h3>
        <button
          className="text-text-muted hover:text-text-primary text-lg leading-none flex-shrink-0"
          onClick={onClose}
          aria-label="Close detail panel"
        >
          ×
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {isLoading && <LoadingState message="Loading strategy..." />}

        {error && (
          <div className="text-sm text-accent-red p-3 bg-accent-red/10 rounded">
            Failed to load strategy details
          </div>
        )}

        {data && (
          <>
            {/* Identity */}
            <div className="flex items-center gap-2 flex-wrap">
              <Badge
                variant={STATUS_VARIANT[data.validation_status] ?? "default"}
              >
                {data.validation_status.replace("_", " ")}
              </Badge>
              <Badge variant="green">{data.family}</Badge>
              <Badge variant="default">v{data.version}</Badge>
            </div>

            <div className="text-[11px] text-text-muted font-mono break-all">
              {data.concept_id}
            </div>

            {/* Corpus Metrics */}
            <Section title="Corpus Metrics">
              <div className="space-y-1.5">
                <StrategyMetricsBar
                  value={data.heading_hit_rate}
                  label="Hit"
                />
                <StrategyMetricsBar
                  value={data.keyword_precision}
                  label="Prec"
                />
                <StrategyMetricsBar
                  value={data.corpus_prevalence}
                  label="Prev"
                />
                <StrategyMetricsBar
                  value={data.cohort_coverage}
                  label="Cov"
                />
              </div>
            </Section>

            {/* Search Vocabulary */}
            <Section title="Heading Patterns">
              <TagList
                items={data.heading_patterns}
                color="bg-accent-blue/10 text-accent-blue"
              />
            </Section>

            <Section title="Keyword Anchors">
              <TagList items={data.keyword_anchors} />
            </Section>

            {(data.keyword_anchors_section_only?.length ?? 0) > 0 && (
              <Section title="Section-Only Keywords">
                <TagList items={data.keyword_anchors_section_only} />
              </Section>
            )}

            {(data.concept_specific_keywords?.length ?? 0) > 0 && (
              <Section title="Concept-Specific Keywords">
                <TagList
                  items={data.concept_specific_keywords}
                  color="bg-accent-green/10 text-accent-green"
                />
              </Section>
            )}

            {/* DNA Phrases */}
            {((data.dna_tier1?.length ?? 0) > 0 || (data.dna_tier2?.length ?? 0) > 0) && (
              <Section title="DNA Phrases">
                {(data.dna_tier1?.length ?? 0) > 0 && (
                  <div className="space-y-1">
                    <span className="text-[10px] text-text-muted">Tier 1:</span>
                    <TagList
                      items={data.dna_tier1 ?? []}
                      color="bg-accent-orange/10 text-accent-orange"
                    />
                  </div>
                )}
                {(data.dna_tier2?.length ?? 0) > 0 && (
                  <div className="space-y-1 mt-2">
                    <span className="text-[10px] text-text-muted">Tier 2:</span>
                    <TagList items={data.dna_tier2 ?? []} />
                  </div>
                )}
              </Section>
            )}

            {/* Domain Knowledge */}
            {(data.defined_term_dependencies?.length ?? 0) > 0 && (
              <Section title="Defined Term Dependencies">
                <TagList items={data.defined_term_dependencies} />
              </Section>
            )}

            {(data.concept_notes?.length ?? 0) > 0 && (
              <Section title="Concept Notes">
                {data.concept_notes.map((note, i) => (
                  <p
                    key={i}
                    className="text-xs text-text-secondary leading-relaxed"
                  >
                    {note}
                  </p>
                ))}
              </Section>
            )}

            {data.fallback_escalation && (
              <Section title="Fallback Escalation">
                <p className="text-xs text-text-secondary italic leading-relaxed">
                  {data.fallback_escalation}
                </p>
              </Section>
            )}

            {(data.xref_follow?.length ?? 0) > 0 && (
              <Section title="Cross-References">
                <ul className="space-y-1">
                  {data.xref_follow.map((xref, i) => (
                    <li
                      key={i}
                      className="text-xs text-text-secondary leading-relaxed"
                    >
                      {xref}
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {/* Structural Location */}
            {((data.primary_articles?.length ?? 0) > 0 ||
              (data.primary_sections?.length ?? 0) > 0) && (
              <Section title="Structural Location">
                <div className="grid grid-cols-2 gap-2 text-xs">
                  {(data.primary_articles?.length ?? 0) > 0 && (
                    <div>
                      <span className="text-text-muted">Articles: </span>
                      <span className="text-text-primary font-mono">
                        {data.primary_articles.join(", ")}
                      </span>
                    </div>
                  )}
                  {(data.primary_sections?.length ?? 0) > 0 && (
                    <div>
                      <span className="text-text-muted">Sections: </span>
                      <span className="text-text-primary font-mono">
                        {data.primary_sections.join(", ")}
                      </span>
                    </div>
                  )}
                </div>
              </Section>
            )}

            {/* QC Indicators */}
            {((data.dropped_headings?.length ?? 0) > 0 ||
              (data.false_positive_keywords?.length ?? 0) > 0) && (
              <Section title="QC Issues">
                {(data.dropped_headings?.length ?? 0) > 0 && (
                  <div className="space-y-1">
                    <span className="text-[10px] text-accent-red">
                      Dropped headings:
                    </span>
                    <TagList
                      items={data.dropped_headings ?? []}
                      color="bg-accent-red/10 text-accent-red"
                    />
                  </div>
                )}
                {(data.false_positive_keywords?.length ?? 0) > 0 && (
                  <div className="space-y-1 mt-2">
                    <span className="text-[10px] text-accent-orange">
                      False positive keywords:
                    </span>
                    <TagList
                      items={data.false_positive_keywords ?? []}
                      color="bg-accent-orange/10 text-accent-orange"
                    />
                  </div>
                )}
              </Section>
            )}

            {/* Update Notes */}
            {(data.update_notes?.length ?? 0) > 0 && (
              <Section title="Update Notes">
                {data.update_notes.map((note, i) => (
                  <p
                    key={i}
                    className="text-xs text-text-secondary leading-relaxed"
                  >
                    {note}
                  </p>
                ))}
              </Section>
            )}

            {data.last_updated && (
              <div className="text-[10px] text-text-muted pt-2 border-t border-border">
                Last updated: {data.last_updated}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
