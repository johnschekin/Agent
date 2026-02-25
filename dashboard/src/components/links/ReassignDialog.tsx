"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { useReassignSuggestions, useReassignMutation } from "@/lib/queries";
import { Badge } from "@/components/ui/Badge";

interface ReassignDialogProps {
  linkId: string;
  currentFamilyId: string;
  currentFamilyName?: string;
  open: boolean;
  onClose: () => void;
  onSuccess?: (newFamilyId: string) => void;
}

export function ReassignDialog({
  linkId,
  currentFamilyId,
  currentFamilyName,
  open,
  onClose,
  onSuccess,
}: ReassignDialogProps) {
  const { data } = useReassignSuggestions(open ? linkId : null);
  const reassignMut = useReassignMutation();
  const [selectedIdx, setSelectedIdx] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);

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
        onClose();
      } else if (e.key === "ArrowDown" || e.key === "j") {
        e.preventDefault();
        setSelectedIdx((prev) =>
          Math.min(prev + 1, (data?.suggestions.length ?? 1) - 1)
        );
      } else if (e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        setSelectedIdx((prev) => Math.max(prev - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const suggestion = data?.suggestions[selectedIdx];
        if (suggestion) {
          handleReassign(suggestion.family_id);
        }
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, data, selectedIdx, onClose]);

  const handleReassign = (newFamilyId: string) => {
    reassignMut.mutate(
      { linkId, newFamilyId },
      {
        onSuccess: () => {
          onSuccess?.(newFamilyId);
          onClose();
        },
      }
    );
  };

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-50 bg-black/50" onClick={onClose} />
      {/* Dialog */}
      <div
        ref={dialogRef}
        className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 bg-surface-1 border border-border rounded-xl shadow-overlay animate-fade-in"
      >
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary">
            Reassign to Family
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Currently: <span className="text-text-secondary">{currentFamilyName || currentFamilyId}</span>
          </p>
        </div>
        <div className="p-2">
          {!data ? (
            <div className="px-4 py-6 text-center text-xs text-text-muted">
              Loading suggestions...
            </div>
          ) : data.suggestions.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-text-muted">
              No alternative families suggested.
            </div>
          ) : (
            <div className="space-y-0.5">
              {data.suggestions.map((s, i) => (
                <button
                  key={s.family_id}
                  onClick={() => handleReassign(s.family_id)}
                  className={cn(
                    "w-full text-left px-3 py-2.5 rounded-lg transition-colors",
                    i === selectedIdx
                      ? "bg-glow-blue shadow-inset-blue"
                      : "hover:bg-surface-3"
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-text-primary font-medium">
                      {s.family_name}
                    </span>
                    <Badge variant={s.confidence >= 0.7 ? "green" : s.confidence >= 0.4 ? "orange" : "default"}>
                      {(s.confidence * 100).toFixed(0)}%
                    </Badge>
                  </div>
                  <p className="text-xs text-text-muted mt-0.5">{s.reason}</p>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="px-4 py-2 border-t border-border flex items-center justify-between">
          <span className="text-[10px] text-text-muted">
            j/k navigate &middot; Enter select &middot; Esc cancel
          </span>
          <button onClick={onClose} className="btn-ghost text-xs">
            Cancel
          </button>
        </div>
      </div>
    </>
  );
}
