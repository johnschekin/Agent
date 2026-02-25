"use client";

import { useState, useRef, useCallback } from "react";
import { cn } from "@/lib/cn";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FilterOp = "or" | "and" | "not" | "and_not";

export interface FilterChip {
  value: string;
  op: FilterOp;
}

const OP_CYCLE: FilterOp[] = ["or", "and", "not", "and_not"];

const OP_LABELS: Record<FilterOp, string> = {
  or: "OR",
  and: "AND",
  not: "NOT",
  and_not: "AND NOT",
};

const OP_COLORS: Record<FilterOp, string> = {
  or: "bg-accent-blue/20 text-accent-blue border-accent-blue/30",
  and: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  not: "bg-red-500/20 text-red-400 border-red-500/30",
  and_not: "bg-orange-500/20 text-orange-400 border-orange-500/30",
};

const CHIP_STYLE =
  "bg-accent-blue/10 border border-accent-blue/30 text-accent-blue rounded px-1.5 py-0.5 inline-flex items-center gap-1 text-xs";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface MultiValueInputProps {
  chips: FilterChip[];
  onChange: (chips: FilterChip[]) => void;
  placeholder?: string;
  ariaLabel?: string;
}

export function MultiValueInput({
  chips,
  onChange,
  placeholder = "Type + Enter",
  ariaLabel,
}: MultiValueInputProps) {
  const [draft, setDraft] = useState("");
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const commitChip = useCallback(
    (value: string) => {
      const trimmed = value.trim();
      if (!trimmed) return;
      onChange([...chips, { value: trimmed, op: "or" }]);
      setDraft("");
    },
    [chips, onChange],
  );

  const removeChip = useCallback(
    (index: number) => {
      onChange(chips.filter((_, i) => i !== index));
    },
    [chips, onChange],
  );

  const cycleOp = useCallback(
    (index: number) => {
      const updated = chips.map((chip, i) => {
        if (i !== index) return chip;
        const nextIdx = (OP_CYCLE.indexOf(chip.op) + 1) % OP_CYCLE.length;
        return { ...chip, op: OP_CYCLE[nextIdx] };
      });
      onChange(updated);
    },
    [chips, onChange],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        commitChip(draft);
      } else if (e.key === "Backspace" && draft === "" && chips.length > 0) {
        e.preventDefault();
        removeChip(chips.length - 1);
      }
    },
    [draft, chips, commitChip, removeChip],
  );

  const handleBlur = useCallback(() => {
    setFocused(false);
    // Auto-commit draft text on blur
    if (draft.trim()) {
      commitChip(draft);
    }
  }, [draft, commitChip]);

  return (
    <div
      className={cn(
        "bg-surface-3 border rounded-sm px-2 py-1 text-sm",
        "flex flex-wrap items-center gap-1.5 min-h-[34px] cursor-text transition-colors",
        focused
          ? "border-accent-blue ring-1 ring-accent-blue"
          : "border-border",
      )}
      onClick={() => inputRef.current?.focus()}
    >
      {chips.map((chip, i) => (
        <span
          key={`${i}-${chip.value}`}
          className="inline-flex items-center gap-0.5 shrink-0"
        >
          {/* Operator badge — hidden for first chip */}
          {i > 0 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                cycleOp(i);
              }}
              className={cn(
                "px-1 py-0.5 rounded text-[10px] font-bold cursor-pointer select-none border",
                OP_COLORS[chip.op],
              )}
              title={`Click to cycle: OR → AND → NOT → AND NOT`}
            >
              {OP_LABELS[chip.op]}
            </button>
          )}
          <span className={CHIP_STYLE}>
            <span>{chip.value}</span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                removeChip(i);
              }}
              className="text-accent-blue/60 hover:text-red-400 transition-colors leading-none font-bold"
              aria-label={`Remove ${chip.value}`}
            >
              ×
            </button>
          </span>
        </span>
      ))}
      <input
        ref={inputRef}
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        onFocus={() => setFocused(true)}
        onBlur={handleBlur}
        placeholder={chips.length === 0 ? placeholder : "add filter…"}
        className="flex-1 min-w-[80px] bg-transparent border-none outline-none text-sm text-text-primary placeholder:text-text-muted/60 p-0"
        aria-label={ariaLabel}
      />
      {/* Hint badge when focused and no chips yet */}
      {focused && chips.length === 0 && draft.length > 0 && (
        <span className="text-[10px] text-text-muted/60 shrink-0 select-none">
          ↵ Enter
        </span>
      )}
    </div>
  );
}
