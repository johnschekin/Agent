"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";

export function DslCheatSheet({ className }: { className?: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className={cn("text-xs", className)}>
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="text-text-muted hover:text-accent-blue transition-colors"
        data-testid="dsl-cheatsheet-toggle"
      >
        {open ? "Hide" : "Syntax reference"}
      </button>

      <div
        className={cn(
          "overflow-hidden transition-all duration-200",
          open ? "max-h-96 mt-2" : "max-h-0",
        )}
      >
        <div className="rounded-lg border border-border bg-surface-1 p-3 grid grid-cols-2 gap-x-6 gap-y-2 font-mono text-text-secondary">
          {/* Fields */}
          <div>
            <span className="text-accent-cyan font-semibold">Fields</span>{" "}
            <span className="text-text-muted">(text)</span>
            <div className="mt-0.5 space-y-0.5">
              <div>
                <code>heading:</code> <code>article:</code> <code>clause:</code>{" "}
                <code>section:</code> <code>defined_term:</code>
              </div>
            </div>
            <span className="text-accent-cyan font-semibold">Meta</span>
            <div className="mt-0.5 space-y-0.5">
              <div>
                <code>template:</code> <code>vintage:</code> <code>market:</code>{" "}
                <code>doc_type:</code> <code>admin_agent:</code> <code>facility_size_mm</code>
              </div>
            </div>
          </div>

          {/* Operators + Values */}
          <div>
            <span className="text-accent-orange font-semibold">Operators</span>
            <div className="mt-0.5 space-y-0.5">
              <div>
                <code>&</code> / <code>AND</code> &nbsp;
                <code>|</code> / <code>OR</code> &nbsp;
                <code>!</code> / <code>NOT</code> &nbsp;
                <code>( )</code> grouping
              </div>
            </div>
            <span className="text-accent-green font-semibold mt-1 inline-block">Values</span>
            <div className="mt-0.5 space-y-0.5">
              <div>
                bare word &nbsp; <code>&quot;quoted phrase&quot;</code> &nbsp;
                <code>/regex/</code>
              </div>
            </div>
          </div>

          {/* Examples — full width */}
          <div className="col-span-2 border-t border-border pt-2 mt-1">
            <span className="text-text-muted font-semibold">Examples</span>
            <div className="mt-0.5 space-y-0.5 text-text-primary">
              <div>
                <code>heading: indebtedness &amp; !&quot;restricted payments&quot;</code>
              </div>
              <div>
                <code>heading: liens article: &quot;negative covenants&quot;</code>
              </div>
              <div>
                <code>heading: (debt OR indebtedness) AND NOT liens</code>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
