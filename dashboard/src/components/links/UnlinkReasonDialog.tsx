"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

interface UnlinkReasonDialogProps {
  open: boolean;
  onConfirm: (reason: string) => void;
  onClose: () => void;
}

const REASONS = [
  { key: "false_positive", label: "False Positive", description: "Section does not belong to this family" },
  { key: "duplicate", label: "Duplicate", description: "Already linked via another section" },
  { key: "wrong_family", label: "Wrong Family", description: "Section belongs to a different family" },
  { key: "other", label: "Other", description: "Unlink for a different reason" },
];

export function UnlinkReasonDialog({ open, onConfirm, onClose }: UnlinkReasonDialogProps) {
  const [selectedIdx, setSelectedIdx] = useState(0);

  // Reset selection when opened
  useEffect(() => {
    if (open) setSelectedIdx(0);
  }, [open]);

  // Keyboard navigation inside dialog
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      } else if (e.key === "ArrowDown" || e.key === "j") {
        e.preventDefault();
        setSelectedIdx((prev) => Math.min(prev + 1, REASONS.length - 1));
      } else if (e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        setSelectedIdx((prev) => Math.max(prev - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        onConfirm(REASONS[selectedIdx].key);
      } else if (e.key >= "1" && e.key <= "4") {
        e.preventDefault();
        const idx = Number(e.key) - 1;
        onConfirm(REASONS[idx].key);
      }
    }
    // Use capture phase so this fires before the page-level keydown handler
    document.addEventListener("keydown", handleKey, true);
    return () => document.removeEventListener("keydown", handleKey, true);
  }, [open, selectedIdx, onConfirm, onClose]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-50 bg-black/50" onClick={onClose} />
      {/* Dialog */}
      <div className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-80 bg-surface-1 border border-border rounded-xl shadow-overlay animate-fade-in">
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary">Unlink Reason</h3>
          <p className="text-xs text-text-muted mt-0.5">Why are you unlinking this section?</p>
        </div>
        <div className="p-2 space-y-0.5">
          {REASONS.map((reason, i) => (
            <button
              key={reason.key}
              onClick={() => onConfirm(reason.key)}
              className={cn(
                "w-full text-left px-3 py-2.5 rounded-lg transition-colors",
                i === selectedIdx
                  ? "bg-glow-red shadow-inset-blue"
                  : "hover:bg-surface-3"
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm text-text-primary font-medium">
                  {reason.label}
                </span>
                <kbd className="px-1.5 py-0.5 bg-surface-3 rounded text-[10px] font-mono text-text-muted">
                  {i + 1}
                </kbd>
              </div>
              <p className="text-xs text-text-muted mt-0.5">{reason.description}</p>
            </button>
          ))}
        </div>
        <div className="px-4 py-2 border-t border-border flex items-center justify-between">
          <span className="text-[10px] text-text-muted">
            j/k navigate &middot; Enter select &middot; 1-4 quick pick &middot; Esc cancel
          </span>
          <button onClick={onClose} className="btn-ghost text-xs">
            Cancel
          </button>
        </div>
      </div>
    </>
  );
}
