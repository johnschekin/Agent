"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import {
  useExpandTermMutation,
  useRuleAutocompleteMutation,
} from "@/lib/queries";
import { tokenizeDsl, DSL_TOKEN_CLASSES } from "@/lib/rule-dsl-highlight";
import type { DslError, DslValidationResponse } from "@/lib/types";

/** All field names the DSL supports — used for field discovery autocomplete. */
const ALL_FIELD_NAMES = [
  "heading",
  "article",
  "clause",
  "section",
  "defined_term",
  "template",
  "vintage",
  "market",
  "doc_type",
  "admin_agent",
  "facility_size_mm",
] as const;

type AutocompleteField = (typeof ALL_FIELD_NAMES)[number];

/** Regex matching any known field name followed by a colon and optional prefix. */
const FIELD_TRIGGER_RE = new RegExp(
  `^(${ALL_FIELD_NAMES.join("|")}):([^\\s]*)$`,
  "i",
);

interface TextQueryBarProps {
  dsl: string;
  onDslChange: (dsl: string) => void;
  onValidationResult?: (result: DslValidationResponse) => void;
  familyId?: string;
  matchCount?: number;
  matchCountLoading?: boolean;
  errors: DslError[];
  queryCost?: number;
  disabled?: boolean;
  className?: string;
}

export function TextQueryBar({
  dsl,
  onDslChange,
  onValidationResult,
  familyId,
  matchCount,
  matchCountLoading,
  errors,
  queryCost,
  disabled,
  className,
}: TextQueryBarProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);
  const [autocompleteOpen, setAutocompleteOpen] = useState(false);
  const [autocompleteItems, setAutocompleteItems] = useState<string[]>([]);
  const [autocompleteIdx, setAutocompleteIdx] = useState(0);
  const autocompleteReqRef = useRef(0);

  const expandMut = useExpandTermMutation();
  const autocompleteMut = useRuleAutocompleteMutation();

  // Debounced validation trigger
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Expose focus method via the input ref for parent keyboard shortcut (/)
  useEffect(() => {
    const el = inputRef.current;
    if (el) {
      el.setAttribute("data-testid", "text-query-bar-input");
    }
  }, []);

  // Sync highlight overlay scroll with input scroll
  const syncScroll = useCallback(() => {
    if (inputRef.current && highlightRef.current) {
      highlightRef.current.scrollLeft = inputRef.current.scrollLeft;
    }
  }, []);

  /** Show field name suggestions (for empty input or Ctrl+Space at field position). */
  const showFieldSuggestions = useCallback(() => {
    const suggestions = ALL_FIELD_NAMES.map((f) => `${f}:`);
    setAutocompleteItems([...suggestions]);
    setAutocompleteIdx(0);
    setAutocompleteOpen(true);
  }, []);

  const handleChange = useCallback(
    (value: string) => {
      onDslChange(value);

      // Autocomplete triggers
      const lastWord = value.split(/\s/).pop() ?? "";

      // Empty input → show field names
      if (!value.trim()) {
        showFieldSuggestions();
        return;
      }

      // Field triggers: any known field followed by colon
      const fieldMatch = lastWord.match(FIELD_TRIGGER_RE);
      if (fieldMatch) {
        const field = fieldMatch[1].toLowerCase() as AutocompleteField;
        const prefix = fieldMatch[2] ?? "";
        const reqId = ++autocompleteReqRef.current;
        autocompleteMut.mutate(
          { field, prefix, limit: 8 },
          {
            onSuccess: (data) => {
              if (reqId !== autocompleteReqRef.current) return;
              const matches = data.suggestions.map((v) => `${field}:${v}`);
              setAutocompleteItems(matches);
              setAutocompleteIdx(0);
              setAutocompleteOpen(matches.length > 0);
            },
            onError: () => {
              if (reqId !== autocompleteReqRef.current) return;
              setAutocompleteItems([]);
              setAutocompleteOpen(false);
            },
          },
        );
        return;
      }

      setAutocompleteOpen(false);

      // Debounce validation
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        // Parent handles validation via useEffect on dsl change
      }, 300);
    },
    [onDslChange, autocompleteMut, showFieldSuggestions],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (autocompleteOpen) {
        if (e.key === "ArrowDown" || e.key === "j") {
          e.preventDefault();
          setAutocompleteIdx((prev) =>
            Math.min(prev + 1, autocompleteItems.length - 1),
          );
          return;
        }
        if (e.key === "ArrowUp" || e.key === "k") {
          e.preventDefault();
          setAutocompleteIdx((prev) => Math.max(prev - 1, 0));
          return;
        }
        if (e.key === "Enter") {
          e.preventDefault();
          const selected = autocompleteItems[autocompleteIdx];
          if (selected) {
            // Replace last word with selected
            const parts = dsl.split(/\s/);
            parts[parts.length - 1] = selected;
            onDslChange(parts.join(" ") + " ");
          }
          setAutocompleteOpen(false);
          return;
        }
        if (e.key === "Escape") {
          setAutocompleteOpen(false);
          return;
        }
      }

      // Ctrl+Space: context-aware autocomplete
      if (e.ctrlKey && e.key === " ") {
        e.preventDefault();
        const cursorPos = inputRef.current?.selectionStart ?? 0;
        const before = dsl.slice(0, cursorPos);
        const lastWord = before.split(/\s/).pop() ?? "";

        // If after a field:, show field values
        const fieldMatch = lastWord.match(FIELD_TRIGGER_RE);
        if (fieldMatch) {
          const field = fieldMatch[1].toLowerCase() as AutocompleteField;
          const prefix = fieldMatch[2] ?? "";
          autocompleteMut.mutate(
            { field, prefix, limit: 8 },
            {
              onSuccess: (data) => {
                const matches = data.suggestions.map((v) => `${field}:${v}`);
                setAutocompleteItems(matches);
                setAutocompleteIdx(0);
                setAutocompleteOpen(matches.length > 0);
              },
            },
          );
        } else {
          // Otherwise show field names
          showFieldSuggestions();
        }
        return;
      }

      // Cmd+E: expand term under cursor
      if ((e.metaKey || e.ctrlKey) && e.key === "e") {
        e.preventDefault();
        const cursorPos = inputRef.current?.selectionStart ?? 0;
        const before = dsl.slice(0, cursorPos);
        const wordMatch = before.match(/(\S+)$/);
        if (wordMatch) {
          expandMut.mutate(wordMatch[1]);
        }
      }
    },
    [autocompleteOpen, autocompleteItems, autocompleteIdx, dsl, onDslChange, expandMut, autocompleteMut, showFieldSuggestions],
  );

  const handleFocus = useCallback(() => {
    // When input is empty and focused, show field suggestions
    if (!dsl.trim()) {
      showFieldSuggestions();
    }
  }, [dsl, showFieldSuggestions]);

  // Clean up debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // Close autocomplete when clicking/tapping outside the DSL input area.
  useEffect(() => {
    if (!autocompleteOpen) return;

    const handleOutside = (event: MouseEvent | TouchEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (rootRef.current && !rootRef.current.contains(target)) {
        setAutocompleteOpen(false);
      }
    };

    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("touchstart", handleOutside);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("touchstart", handleOutside);
    };
  }, [autocompleteOpen]);

  // Public method for parent to focus the input (called by / keyboard shortcut)
  const focusInput = useCallback(() => {
    inputRef.current?.focus();
  }, []);

  // Attach focusInput to the DOM element so parent can call it
  useEffect(() => {
    const el = rootRef.current;
    if (el) {
      (el as HTMLElement & { focusInput?: () => void }).focusInput = focusInput;
    }
  }, [focusInput]);

  // Render syntax-highlighted tokens
  const highlightTokens = tokenizeDsl(dsl);

  return (
    <div ref={rootRef} className={cn("relative", className)} data-testid="text-query-bar">
      {/* Input container with highlight overlay */}
      <div className="relative flex items-center">
        {/* Syntax highlight overlay — invisible to pointer events */}
        <div
          ref={highlightRef}
          aria-hidden="true"
          className="absolute inset-0 overflow-hidden pointer-events-none rounded-lg px-4 py-2.5 font-mono text-sm whitespace-pre pr-24"
        >
          {highlightTokens.map((tok, i) => (
            <span key={i} className={DSL_TOKEN_CLASSES[tok.type]}>
              {tok.text}
            </span>
          ))}
        </div>

        {/* Actual input — text is transparent so the overlay shows through, but caret remains visible */}
        <input
          ref={inputRef}
          type="text"
          value={dsl}
          onChange={(e) => handleChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={handleFocus}
          onScroll={syncScroll}
          disabled={disabled}
          placeholder={
            familyId
              ? `heading:... article:... template:...`
              : "Select an ontology node first"
          }
          className={cn(
            "w-full bg-surface-2 border border-border rounded-lg px-4 py-2.5 font-mono text-sm placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent-blue disabled:opacity-50 pr-24",
            dsl ? "text-transparent caret-text-primary" : "text-text-primary",
          )}
        />

        {/* Match count badge (right-aligned) */}
        <div className="absolute right-3 flex items-center gap-2">
          {queryCost !== undefined && queryCost > 20 && (
            <Badge variant={queryCost > 50 ? "red" : "amber"} className="text-[10px]">
              Cost: {queryCost}
            </Badge>
          )}
          {matchCountLoading ? (
            <span className="text-xs text-text-muted animate-pulse">...</span>
          ) : matchCount !== undefined ? (
            <Badge variant="blue" data-testid="match-count-badge">
              {matchCount.toLocaleString()}
            </Badge>
          ) : null}
        </div>
      </div>

      {/* Autocomplete dropdown */}
      {autocompleteOpen && autocompleteItems.length > 0 && (
        <div
          className="absolute z-50 mt-1 w-full bg-surface-2 border border-border rounded-lg shadow-overlay max-h-48 overflow-y-auto"
          data-testid="autocomplete-dropdown"
        >
          {autocompleteItems.map((item, idx) => (
            <button
              key={item}
              type="button"
              onClick={() => {
                const parts = dsl.split(/\s/);
                parts[parts.length - 1] = item;
                onDslChange(parts.join(" ") + " ");
                setAutocompleteOpen(false);
                inputRef.current?.focus();
              }}
              className={cn(
                "w-full text-left px-3 py-1.5 text-sm font-mono transition-colors",
                idx === autocompleteIdx
                  ? "bg-glow-blue text-accent-blue"
                  : "text-text-secondary hover:bg-surface-3",
              )}
            >
              {item}
            </button>
          ))}
        </div>
      )}

      {/* Expand term results */}
      {expandMut.data && expandMut.data.expansions.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {expandMut.data.expansions.map((exp) => (
            <button
              key={exp}
              type="button"
              onClick={() => {
                onDslChange(dsl + " " + exp);
                expandMut.reset();
              }}
              className="text-xs text-accent-blue hover:underline"
            >
              +{exp}
            </button>
          ))}
        </div>
      )}

      {/* Error display */}
      {errors.length > 0 && (
        <div className="mt-1 space-y-0.5" data-testid="dsl-errors">
          {errors.map((err, idx) => (
            <p key={idx} className="text-xs text-accent-red">
              {err.message}
              {err.position > 0 && (
                <span className="text-text-muted ml-1">(pos {err.position})</span>
              )}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
