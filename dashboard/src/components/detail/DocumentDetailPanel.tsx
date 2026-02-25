"use client";

import { useDocument } from "@/lib/queries";
import { formatNumber, formatCurrencyMM } from "@/lib/formatters";
import { LoadingState } from "@/components/ui/Spinner";
import { MetadataGrid } from "./MetadataGrid";
import { SectionTree } from "./SectionTree";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";

interface DocumentDetailPanelProps {
  docId: string | null;
  onClose: () => void;
}

export function DocumentDetailPanel({ docId, onClose }: DocumentDetailPanelProps) {
  const { data, isLoading, error } = useDocument(docId);

  return (
    <div
      className={cn(
        "fixed top-0 right-0 h-full bg-surface-2 border-l border-border",
        "w-[480px] max-w-[calc(100vw-260px)]",
        "transform transition-transform duration-200 ease-in-out z-30",
        "flex flex-col overflow-hidden",
        docId ? "translate-x-0" : "translate-x-full"
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface-3 flex-shrink-0">
        <h3 className="text-sm font-medium text-text-primary truncate pr-4">
          {data?.doc.borrower || docId || "Document Detail"}
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
        {isLoading && <LoadingState message="Loading document..." />}

        {error && (
          <div className="text-sm text-accent-red p-3 bg-accent-red/10 rounded">
            Failed to load document details
          </div>
        )}

        {data && (
          <>
            {/* Identity badges */}
            <div className="flex flex-wrap gap-2">
              <Badge variant={data.doc.doc_type === "credit_agreement" ? "green" : "default"}>
                {data.doc.doc_type.replace(/_/g, " ")}
              </Badge>
              <Badge variant={data.doc.market_segment === "leveraged" ? "blue" : "default"}>
                {data.doc.market_segment.replace(/_/g, " ")}
              </Badge>
              {data.doc.cohort_included && (
                <Badge variant="green">Cohort</Badge>
              )}
            </div>

            {/* Metadata */}
            <div>
              <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                Metadata
              </h4>
              <MetadataGrid
                items={[
                  { label: "Doc ID", value: data.doc.doc_id },
                  { label: "Borrower", value: data.doc.borrower },
                  { label: "Admin Agent", value: data.doc.admin_agent },
                  {
                    label: "Facility Size",
                    value:
                      data.doc.facility_size_mm != null
                        ? formatCurrencyMM(data.doc.facility_size_mm)
                        : null,
                  },
                  { label: "Closing Date", value: data.doc.closing_date },
                  { label: "Filing Date", value: data.doc.filing_date },
                  { label: "CIK", value: data.doc.cik },
                  { label: "Form Type", value: data.doc.form_type },
                  { label: "Accession", value: data.doc.accession },
                  { label: "Word Count", value: formatNumber(data.doc.word_count) },
                  { label: "Text Length", value: formatNumber(data.doc.text_length) },
                  { label: "Template Family", value: data.doc.template_family },
                ]}
              />
            </div>

            {/* Stats bar */}
            <div className="flex gap-4 text-xs">
              <div className="flex items-center gap-1.5">
                <span className="text-text-muted">Sections:</span>
                <span className="text-text-primary tabular-nums font-medium">
                  {formatNumber(data.doc.section_count)}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-text-muted">Definitions:</span>
                <span className="text-text-primary tabular-nums font-medium">
                  {formatNumber(data.definition_count)}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-text-muted">Clauses:</span>
                <span className="text-text-primary tabular-nums font-medium">
                  {formatNumber(data.clause_count)}
                </span>
              </div>
            </div>

            {/* Section Tree */}
            <div>
              <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                Structure ({data.sections.length} sections)
              </h4>
              <SectionTree sections={data.sections} articles={data.articles} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
