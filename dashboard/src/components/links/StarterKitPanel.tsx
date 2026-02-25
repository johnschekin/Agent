"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { useStarterKit } from "@/lib/queries";

interface StarterKitPanelProps {
  familyId: string;
  onCreateRule?: (dsl: string) => void;
  onClose: () => void;
}

export function StarterKitPanel({ familyId, onCreateRule, onClose }: StarterKitPanelProps) {
  const [expanded, setExpanded] = useState(true);
  const { data: kit, isLoading } = useStarterKit(familyId);

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="text-xs text-accent-blue hover:underline"
        data-testid="starter-kit-expand"
      >
        Show Starter Kit
      </button>
    );
  }

  const generateDsl = (): string => {
    if (!kit) return "";
    const parts: string[] = [];

    // Headings → filter_dsl format: heading: "x" | "y"
    const headings = kit.suggested_headings;
    if (headings.length > 0) {
      const terms = headings.map((h) => (h.includes(" ") ? `"${h}"` : h));
      parts.push(`heading: ${terms.join(" | ")}`);
    }

    // Keywords → clause field (closest DSL mapping for keyword anchors)
    const keywords = kit.suggested_keywords;
    if (keywords.length > 0) {
      const terms = keywords.map((k) => (k.includes(" ") ? `"${k}"` : k));
      parts.push(`clause: ${terms.join(" | ")}`);
    }

    // Defined terms
    const definedTerms = kit.suggested_defined_terms ?? [];
    if (definedTerms.length > 0) {
      const terms = definedTerms.map((t) => (t.includes(" ") ? `"${t}"` : t));
      parts.push(`defined_term: ${terms.join(" | ")}`);
    }

    if (parts.length === 0) return "";
    return parts.join("\n");
  };

  return (
    <div className="border border-border rounded-lg bg-surface-2" data-testid="starter-kit-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <div className="flex items-center gap-2">
          <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
            Starter Kit
          </h4>
          <Badge variant="blue">{familyId}</Badge>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-text-muted hover:text-text-primary text-sm"
          data-testid="starter-kit-close"
        >
          &times;
        </button>
      </div>

      {/* Content */}
      <div className="px-4 py-3">
        {isLoading ? (
          <p className="text-sm text-text-muted py-4 text-center">Loading starter kit...</p>
        ) : !kit ? (
          <p className="text-sm text-text-muted py-4 text-center">No starter kit available for this family</p>
        ) : (
          <div className="space-y-3">
            {/* Heading variants */}
            {kit.suggested_headings.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">
                  Heading Variants ({kit.suggested_headings.length})
                </p>
                <div className="flex flex-wrap gap-1">
                  {kit.suggested_headings.map((h) => (
                    <Badge key={h} variant="blue">{h}</Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Keywords */}
            {kit.suggested_keywords.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">
                  Keywords ({kit.suggested_keywords.length})
                </p>
                <div className="flex flex-wrap gap-1">
                  {kit.suggested_keywords.map((k) => (
                    <Badge key={k} variant="green">{k}</Badge>
                  ))}
                </div>
              </div>
            )}

            {/* DNA phrases */}
            {kit.suggested_dna_phrases.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">
                  DNA Phrases ({kit.suggested_dna_phrases.length})
                </p>
                <div className="flex flex-wrap gap-1">
                  {kit.suggested_dna_phrases.map((d) => (
                    <Badge key={d} variant="purple">{d}</Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Defined Terms */}
            {kit.suggested_defined_terms && kit.suggested_defined_terms.length > 0 && (
              <div data-testid="starter-kit-defined-terms">
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">
                  Defined Terms ({kit.suggested_defined_terms.length})
                </p>
                <div className="flex flex-wrap gap-1">
                  {kit.suggested_defined_terms.map((t) => (
                    <Badge key={t} variant="cyan">{t}</Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Location Priors */}
            {kit.location_priors && kit.location_priors.length > 0 && (
              <div data-testid="starter-kit-location-priors">
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">
                  Location Priors ({kit.location_priors.length})
                </p>
                <div className="space-y-1">
                  {kit.location_priors.map((prior, idx) => (
                    <div
                      key={`${prior.article_concept ?? ""}-${prior.section_range ?? ""}-${idx}`}
                      className="flex items-center gap-2 text-xs"
                    >
                      {prior.article_concept && (
                        <span className="text-text-secondary">
                          Article: <span className="text-text-primary font-medium">{prior.article_concept}</span>
                        </span>
                      )}
                      {prior.section_range && (
                        <span className="text-text-secondary">
                          Range: <span className="text-text-primary font-medium">{prior.section_range}</span>
                        </span>
                      )}
                      {prior.probability != null && (
                        <Badge variant="default" className="text-[10px]">
                          {(prior.probability * 100).toFixed(0)}%
                        </Badge>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Exclusions */}
            {kit.exclusions && kit.exclusions.length > 0 && (
              <div data-testid="starter-kit-exclusions">
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">
                  Exclusions ({kit.exclusions.length})
                </p>
                <div className="flex flex-wrap gap-1">
                  {kit.exclusions.map((e) => (
                    <Badge key={e} variant="red">{e}</Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Notes */}
            {kit.notes && (
              <p className="text-xs text-text-secondary italic">{kit.notes}</p>
            )}

            {/* Generate rule button */}
            {onCreateRule && (kit.suggested_headings.length > 0 || kit.suggested_keywords.length > 0 || kit.suggested_dna_phrases.length > 0) && (
              <button
                type="button"
                onClick={() => onCreateRule(generateDsl())}
                className="w-full px-3 py-2 bg-accent-blue text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
                data-testid="generate-rule-draft"
              >
                Generate Rule Draft
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
