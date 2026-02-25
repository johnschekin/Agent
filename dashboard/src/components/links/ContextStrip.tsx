"use client";

import { useState } from "react";
import { useContextStrip } from "@/lib/queries";
import { cn } from "@/lib/cn";
import { SkeletonPanel } from "@/components/ui/Spinner";

interface ContextStripProps {
  linkId: string | null;
  className?: string;
}

export function ContextStrip({ linkId, className }: ContextStripProps) {
  const { data, isLoading } = useContextStrip(linkId);
  const [expandedDef, setExpandedDef] = useState<string | null>(null);
  const [expandedXref, setExpandedXref] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  if (!linkId) return null;

  return (
    <>
      {/* Mobile toggle button — visible only below lg breakpoint */}
      <button
        onClick={() => setMobileOpen((p) => !p)}
        className="lg:hidden fixed bottom-16 right-4 z-30 bg-surface-2 border border-border rounded-lg p-2 shadow-card text-xs text-text-secondary hover:text-text-primary"
        title="Toggle Context Panel"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 20 20" fill="currentColor">
          <path d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
        </svg>
      </button>
      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-40 bg-black/50" onClick={() => setMobileOpen(false)} />
      )}
    <div className={cn(
      "bg-surface-1 border-l border-border overflow-y-auto",
      // On mobile: slide-in overlay when open, hidden when closed
      "lg:relative lg:block",
      mobileOpen ? "fixed right-0 top-0 bottom-0 z-50 w-72 animate-palette-slide-in" : "hidden lg:block",
      className,
    )}>
      {isLoading ? (
        <SkeletonPanel lines={6} />
      ) : !data ? (
        <div className="p-4 text-xs text-text-muted">No context available</div>
      ) : (
        <div className="divide-y divide-border">
          {/* Primary covenant */}
          <div className="p-3">
            <h4 className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-2">
              Primary Covenant
            </h4>
            <p className="text-xs font-medium text-text-primary mb-1">
              {data.primary_covenant_heading}
            </p>
            <p className="text-xs text-text-secondary leading-relaxed">
              {data.primary_covenant_preview}
            </p>
          </div>

          {/* Definitions that matter */}
          {data.definitions.length > 0 && (
            <div className="p-3">
              <h4 className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-2">
                Key Definitions ({data.definitions.length})
              </h4>
              <div className="space-y-1">
                {data.definitions.map((def) => (
                  <div key={def.term}>
                    <button
                      onClick={() =>
                        setExpandedDef(expandedDef === def.term ? null : def.term)
                      }
                      className={cn(
                        "w-full text-left text-xs px-2 py-1.5 rounded-md transition-colors",
                        expandedDef === def.term
                          ? "bg-glow-blue text-accent-blue"
                          : "text-text-secondary hover:text-text-primary hover:bg-surface-3"
                      )}
                    >
                      <span className="font-medium">{def.term}</span>
                    </button>
                    {expandedDef === def.term && (
                      <div className="px-2 py-2 text-xs text-text-secondary leading-relaxed animate-fade-in">
                        {def.definition_text}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Cross-references */}
          {data.xrefs.length > 0 && (
            <div className="p-3">
              <h4 className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-2">
                Cross-References ({data.xrefs.length})
              </h4>
              <div className="space-y-1">
                {data.xrefs.map((xref) => (
                  <div key={xref.section_ref}>
                    <button
                      onClick={() =>
                        setExpandedXref(
                          expandedXref === xref.section_ref ? null : xref.section_ref
                        )
                      }
                      className={cn(
                        "w-full text-left text-xs px-2 py-1.5 rounded-md transition-colors",
                        expandedXref === xref.section_ref
                          ? "bg-glow-cyan text-accent-cyan"
                          : "text-text-secondary hover:text-text-primary hover:bg-surface-3"
                      )}
                    >
                      <span className="font-medium">{xref.section_ref}</span>
                      <span className="text-text-muted ml-1">— {xref.heading}</span>
                    </button>
                    {expandedXref === xref.section_ref && (
                      <div className="px-2 py-2 text-xs text-text-secondary leading-relaxed animate-fade-in">
                        {xref.text_preview}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
    </>
  );
}
