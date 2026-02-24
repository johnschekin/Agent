"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { cn } from "@/lib/cn";
import type { ReaderDefinition } from "@/lib/types";

interface DefinitionTooltipProps {
  definition: ReaderDefinition;
  children: React.ReactNode;
}

export function DefinitionTooltip({ definition, children }: DefinitionTooltipProps) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        ref.current &&
        !ref.current.contains(e.target as Node) &&
        tooltipRef.current &&
        !tooltipRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
        setExpanded(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const toggle = useCallback(() => {
    setOpen((prev) => {
      if (prev) setExpanded(false);
      return !prev;
    });
  }, []);

  const truncated =
    definition.definition_text.length > 200 && !expanded
      ? definition.definition_text.slice(0, 200) + "…"
      : definition.definition_text;

  return (
    <span ref={ref} className="relative inline">
      <span
        className="underline decoration-dotted decoration-accent-blue/50 cursor-pointer hover:decoration-accent-blue hover:bg-accent-blue/5 transition-colors"
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
        role="button"
        tabIndex={0}
        aria-label={`Definition: ${definition.term}`}
      >
        {children}
      </span>

      {open && (
        <div
          ref={tooltipRef}
          className={cn(
            "absolute z-50 left-0 top-full mt-1",
            "w-[320px] max-w-[calc(100vw-2rem)]",
            "bg-surface-secondary border border-border rounded shadow-lg",
            "p-3 space-y-2"
          )}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-accent-blue">
              {definition.term}
            </span>
            <span className="text-[10px] text-text-muted tabular-nums">
              {Math.round(definition.confidence * 100)}%
            </span>
          </div>
          <p className="text-xs text-text-secondary leading-relaxed">
            {truncated}
          </p>
          {definition.definition_text.length > 200 && (
            <button
              className="text-[10px] text-accent-blue hover:underline"
              onClick={() => setExpanded((prev) => !prev)}
            >
              {expanded ? "Show less" : "Show full definition"}
            </button>
          )}
        </div>
      )}
    </span>
  );
}
