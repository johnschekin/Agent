"use client";

import { useMemo } from "react";
import { cn } from "@/lib/cn";

interface KeyboardHelpBarProps {
  activeTab?: string;
  className?: string;
}

const REVIEW_SHORTCUTS = [
  { key: "j/k", action: "Navigate" },
  { key: "Space", action: "Reader" },
  { key: "c", action: "Child Links" },
  { key: "u", action: "Unlink" },
  { key: "r", action: "Relink" },
  { key: "b", action: "Bookmark" },
  { key: "n", action: "Note" },
  { key: "g", action: "Hash Cluster" },
  { key: "/", action: "Queue Filter" },
  { key: "p", action: "Pin TP" },
  { key: "m", action: "Reassign" },
  { key: "d", action: "Redline" },
  { key: "f", action: "Fold" },
  { key: "t", action: "Tier" },
  { key: "[/]", action: "Jump" },
  { key: "\u2318Z", action: "Undo" },
  { key: "\u2318F", action: "Triage" },
];

const RULES_SHORTCUTS = [
  { key: "p", action: "Publish" },
  { key: "c", action: "Compare" },
  { key: "a", action: "Archive" },
];

const CHILDREN_SHORTCUTS = [
  { key: "g", action: "Generate" },
  { key: "Space", action: "Approve" },
  { key: "Cmd+K", action: "Palette" },
];

const DASHBOARD_SHORTCUTS = [
  { key: "\u2318K", action: "Palette" },
];

const GLOBAL_SHORTCUTS = [
  { key: "\u2318K", action: "Palette" },
];

export function KeyboardHelpBar({ activeTab, className }: KeyboardHelpBarProps) {
  const shortcuts = useMemo(() => {
    let tabShortcuts: { key: string; action: string }[] = [];
    switch (activeTab) {
      case "review":
        tabShortcuts = REVIEW_SHORTCUTS;
        break;
      case "rules":
        tabShortcuts = RULES_SHORTCUTS;
        break;
      case "children":
        tabShortcuts = CHILDREN_SHORTCUTS;
        break;
      case "query":
        tabShortcuts = [{ key: "/", action: "Focus DSL" }, { key: "Esc", action: "Close" }];
        break;
      case "dashboard":
        tabShortcuts = DASHBOARD_SHORTCUTS;
        return tabShortcuts; // dashboard tab already has the global shortcut, no need to append
      default:
        tabShortcuts = [];
    }
    return [...tabShortcuts, ...GLOBAL_SHORTCUTS];
  }, [activeTab]);

  if (shortcuts.length === 0) return null;

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-1.5 bg-surface-2 border-t border-border text-[10px] text-text-muted overflow-x-auto",
        className
      )}
    >
      {shortcuts.map((s) => (
        <span key={s.key} className="flex items-center gap-1 whitespace-nowrap">
          <kbd className="px-1 py-0.5 bg-surface-3 rounded text-text-secondary font-mono">
            {s.key}
          </kbd>
          <span>{s.action}</span>
        </span>
      ))}
    </div>
  );
}
