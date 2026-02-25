"use client";

import { useRef, useState } from "react";
import { useCrossrefPeek } from "@/lib/queries";

interface CrossRefPeekProps {
  /** Section reference string, e.g. "DOC-001:7.02(b)" */
  sectionRef: string;
  children: React.ReactNode;
}

/**
 * Cmd+hover on cross-reference text shows section preview tooltip.
 * Detects references like "Section 7.02(b)" in text and wraps them.
 */
export function CrossRefPeek({ sectionRef, children }: CrossRefPeekProps) {
  const [show, setShow] = useState(false);
  const [cmdHeld, setCmdHeld] = useState(false);
  const timeoutId = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { data } = useCrossrefPeek(show ? sectionRef : null);

  const clearTimer = () => {
    if (timeoutId.current !== null) {
      clearTimeout(timeoutId.current);
      timeoutId.current = null;
    }
  };

  const handleMouseEnter = (e: React.MouseEvent) => {
    if (e.metaKey || e.ctrlKey) {
      setCmdHeld(true);
      clearTimer();
      timeoutId.current = setTimeout(() => setShow(true), 200);
    }
  };

  const handleMouseLeave = () => {
    setCmdHeld(false);
    clearTimer();
    timeoutId.current = setTimeout(() => setShow(false), 200);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    const isCmd = e.metaKey || e.ctrlKey;
    if (isCmd && !cmdHeld) {
      setCmdHeld(true);
      clearTimer();
      timeoutId.current = setTimeout(() => setShow(true), 200);
    } else if (!isCmd && cmdHeld) {
      setCmdHeld(false);
      setShow(false);
    }
  };

  return (
    <span
      className="relative cursor-help underline decoration-dotted decoration-text-muted underline-offset-2"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onMouseMove={handleMouseMove}
    >
      {children}
      {show && (
        <span
          role="tooltip"
          className="crossref-tooltip absolute z-50 bottom-full left-0 mb-1 w-96 max-h-48 overflow-auto p-3 bg-surface-2 border border-border rounded-lg shadow-overlay animate-fade-in text-left"
          onMouseEnter={() => {
            clearTimer();
          }}
          onMouseLeave={handleMouseLeave}
        >
          {data ? (
            <>
              <span className="block text-xs font-semibold text-accent-cyan mb-1">
                {data.heading}
              </span>
              <span className="block text-xs text-text-secondary leading-relaxed whitespace-pre-wrap">
                {data.text.slice(0, 500)}
                {data.text.length > 500 && "..."}
              </span>
            </>
          ) : (
            <span className="text-xs text-text-muted">Loading...</span>
          )}
        </span>
      )}
    </span>
  );
}

/**
 * Regex to detect cross-reference patterns in section text.
 * Matches: "Section 7.02", "Section 7.02(b)", "Sec. 7.02(b)(ii)"
 */
export const CROSSREF_PATTERN = /Section\s+(\d+\.\d+(?:\([a-zA-Z0-9]+\))*)/gi;
