"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";

export interface CommandPaletteTarget {
  type: "tab" | "family" | "rule" | "action";
  id: string;
  label: string;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onNavigate: (target: CommandPaletteTarget) => void;
  families?: { family_id: string; family_name: string }[];
  rules?: { rule_id: string; family_name: string; heading_filter_dsl: string }[];
}

const TAB_ITEMS: (CommandPaletteTarget & { shortcut?: string })[] = [
  { type: "tab", id: "review", label: "Review", shortcut: "1" },
  { type: "tab", id: "query", label: "Query", shortcut: "2" },
  { type: "tab", id: "rules", label: "Rules", shortcut: "3" },
  { type: "tab", id: "dashboard", label: "Dashboard", shortcut: "4" },
];

const ACTION_ITEMS: CommandPaletteTarget[] = [
  { type: "action", id: "preview-links", label: "Preview Links" },
  { type: "action", id: "apply-high-tier", label: "Apply High-Tier" },
  { type: "action", id: "unlink-selected", label: "Unlink Selected" },
  { type: "action", id: "compare-rules", label: "Compare Rules" },
  { type: "action", id: "run-all-rules", label: "Run All Rules" },
  { type: "action", id: "export-view", label: "Export View" },
];

const TYPE_BADGE_VARIANT: Record<string, "blue" | "green" | "purple" | "amber"> = {
  tab: "blue",
  family: "green",
  rule: "purple",
  action: "amber",
};

// Per-item shortcut map: keyed by `${type}-${id}`
const ITEM_SHORTCUTS: Record<string, string> = Object.fromEntries(
  TAB_ITEMS.filter((t) => t.shortcut).map((t) => [`tab-${t.id}`, t.shortcut as string]),
);

function fuzzyMatch(query: string, text: string): boolean {
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  let qi = 0;
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) qi++;
  }
  return qi === q.length;
}

export function CommandPalette({
  open,
  onClose,
  onNavigate,
  families = [],
  rules = [],
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Build items list
  const allItems = useMemo<CommandPaletteTarget[]>(() => {
    const tabItems: CommandPaletteTarget[] = TAB_ITEMS.map(({ type, id, label }) => ({
      type,
      id,
      label,
    }));
    const familyItems: CommandPaletteTarget[] = families.map((f) => ({
      type: "family" as const,
      id: f.family_id,
      label: f.family_name,
    }));
    const ruleItems: CommandPaletteTarget[] = rules.map((r) => ({
      type: "rule" as const,
      id: r.rule_id,
      label: `${r.family_name}: ${r.heading_filter_dsl}`,
    }));
    return [...tabItems, ...familyItems, ...ruleItems, ...ACTION_ITEMS];
  }, [families, rules]);

  // Filter items by fuzzy query
  const filtered = useMemo(() => {
    if (!query.trim()) return allItems;
    return allItems.filter(
      (item) => fuzzyMatch(query, item.label) || fuzzyMatch(query, item.type),
    );
  }, [allItems, query]);

  // Reset on open/query change
  useEffect(() => {
    setSelectedIdx(0);
  }, [query, open]);

  // Focus input on open
  useEffect(() => {
    if (open) {
      setQuery("");
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Escape should close regardless of where focus currently is.
  useEffect(() => {
    if (!open) return;
    const onWindowKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onWindowKeyDown);
    return () => window.removeEventListener("keydown", onWindowKeyDown);
  }, [open, onClose]);

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setSelectedIdx((prev) => Math.min(prev + 1, filtered.length - 1));
          break;
        case "ArrowUp":
          e.preventDefault();
          setSelectedIdx((prev) => Math.max(prev - 1, 0));
          break;
        case "Enter":
          e.preventDefault();
          if (filtered[selectedIdx]) {
            onNavigate(filtered[selectedIdx]);
            onClose();
          }
          break;
        case "Escape":
          e.preventDefault();
          onClose();
          break;
      }
    },
    [filtered, selectedIdx, onNavigate, onClose],
  );

  // Scroll selected item into view
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const selected = list.querySelector(`[data-idx="${selectedIdx}"]`);
    if (selected) {
      selected.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIdx]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]"
      onClick={onClose}
      data-testid="command-palette"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Modal */}
      <div
        className="relative w-full max-w-[520px] bg-surface-1 rounded-xl shadow-overlay border border-border overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center px-4 py-3 border-b border-border gap-3">
          {/* Magnifying glass icon */}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="flex-shrink-0 text-text-muted"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search tabs, scopes, rules, actions..."
            className="flex-1 bg-transparent text-base text-text-primary placeholder:text-text-muted focus:outline-none"
            data-testid="command-palette-input"
          />
        </div>

        {/* Results list */}
        <div
          ref={listRef}
          className="max-h-80 overflow-y-auto py-1"
          data-testid="command-palette-results"
        >
          {filtered.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-text-muted">No results found</div>
          ) : (
            filtered.map((item, idx) => {
              const shortcut = ITEM_SHORTCUTS[`${item.type}-${item.id}`];
              return (
                <button
                  key={`${item.type}-${item.id}`}
                  type="button"
                  data-idx={idx}
                  onClick={() => {
                    onNavigate(item);
                    onClose();
                  }}
                  className={cn(
                    "w-full flex items-center gap-3 px-4 py-2 text-left transition-colors",
                    idx === selectedIdx
                      ? "bg-glow-blue text-text-primary"
                      : "text-text-secondary hover:bg-surface-2",
                  )}
                  data-testid={`palette-item-${item.type}-${item.id}`}
                >
                  <Badge
                    variant={TYPE_BADGE_VARIANT[item.type] ?? "default"}
                    className="text-[10px] flex-shrink-0"
                  >
                    {item.type === "family" ? "scope" : item.type}
                  </Badge>
                  <span className="text-sm truncate flex-1">{item.label}</span>
                  {shortcut && (
                    <kbd className="flex-shrink-0 ml-auto inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface-3 text-text-muted border border-border leading-none">
                      {shortcut}
                    </kbd>
                  )}
                </button>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div
          className="flex items-center gap-4 px-4 py-2 border-t border-border bg-surface-2 text-[11px] text-text-muted"
          data-testid="command-palette-footer"
        >
          <span className="flex items-center gap-1">
            <kbd className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface-3 border border-border leading-none">
              ↑
            </kbd>
            <kbd className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface-3 border border-border leading-none">
              ↓
            </kbd>
            Navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface-3 border border-border leading-none">
              Enter
            </kbd>
            Select
          </span>
          <span className="flex items-center gap-1">
            <kbd className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface-3 border border-border leading-none">
              Esc
            </kbd>
            Close
          </span>
        </div>
      </div>
    </div>
  );
}
