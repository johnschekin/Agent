"use client";

import { useRef, useState } from "react";

interface DefinedTermPeekProps {
  term: string;
  definitionText: string;
  children: React.ReactNode;
}

export function DefinedTermPeek({ term, definitionText, children }: DefinedTermPeekProps) {
  const [show, setShow] = useState(false);
  const timeoutId = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = () => {
    if (timeoutId.current !== null) {
      clearTimeout(timeoutId.current);
      timeoutId.current = null;
    }
  };

  const handleMouseEnter = () => {
    clearTimer();
    timeoutId.current = setTimeout(() => setShow(true), 300);
  };

  const handleMouseLeave = () => {
    clearTimer();
    timeoutId.current = setTimeout(() => setShow(false), 150);
  };

  return (
    <span
      className="highlight-blue-term relative"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}
      {show && (
        <span
          className="absolute z-50 bottom-full left-0 mb-1 w-80 p-3 bg-surface-2 border border-border rounded-lg shadow-overlay animate-fade-in text-left"
          onMouseEnter={() => {
            clearTimer();
          }}
          onMouseLeave={handleMouseLeave}
        >
          <span className="block text-xs font-semibold text-accent-blue mb-1">
            {term}
          </span>
          <span className="block text-xs text-text-secondary leading-relaxed">
            {definitionText}
          </span>
        </span>
      )}
    </span>
  );
}
