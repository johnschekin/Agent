"use client";

import { cn } from "@/lib/cn";

interface FocusModeToggleProps {
  active: boolean;
  onToggle: () => void;
}

export function FocusModeToggle({ active, onToggle }: FocusModeToggleProps) {
  return (
    <button
      onClick={onToggle}
      title={active ? "Exit focus mode (Cmd+Shift+F)" : "Enter focus mode (Cmd+Shift+F)"}
      className={cn(
        "btn-ghost flex items-center gap-1.5",
        active && "text-accent-blue bg-glow-blue"
      )}
    >
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="opacity-70">
        {active ? (
          <path d="M1 5V1h4M9 1h4v4M13 9v4H9M5 13H1V9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        ) : (
          <path d="M5 1H1v4M13 5V1H9M9 13h4V9M1 9v4h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        )}
      </svg>
      <span className="text-xs">{active ? "Exit Focus" : "Focus"}</span>
    </button>
  );
}
