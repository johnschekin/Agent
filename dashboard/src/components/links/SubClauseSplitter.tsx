"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { CHART_COLORS } from "@/lib/colors";

export interface SplitAssignment {
  family_id: string;
  start: number;
  end: number;
}

interface SubClauseSplitterProps {
  sectionText: string;
  families: { family_id: string; family_name: string; color: string }[];
  onSplit: (assignments: SplitAssignment[]) => void;
  onCancel: () => void;
}

// Derived from CHART_COLORS at 20% opacity for inline highlight overlays
const ASSIGNMENT_COLORS = [
  `${CHART_COLORS.blue}33`,    // blue 20%
  `${CHART_COLORS.green}33`,   // green 20%
  `${CHART_COLORS.orange}33`,  // amber 20%
  `${CHART_COLORS.purple}33`,  // purple 20%
  `${CHART_COLORS.teal}33`,    // teal 20%
  `${CHART_COLORS.red}33`,     // red 20%
];

export function SubClauseSplitter({
  sectionText,
  families,
  onSplit,
  onCancel,
}: SubClauseSplitterProps) {
  const [assignments, setAssignments] = useState<SplitAssignment[]>([]);
  const [activeFamilyIdx, setActiveFamilyIdx] = useState(0);
  const textRef = useRef<HTMLDivElement>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const activeFamily = families[activeFamilyIdx] ?? null;

  // Validate no overlapping ranges
  const validateAssignments = useCallback((items: SplitAssignment[]): string | null => {
    const sorted = [...items].sort((a, b) => a.start - b.start);
    for (let i = 0; i < sorted.length - 1; i++) {
      if (sorted[i].end > sorted[i + 1].start) {
        return "Overlapping ranges detected. Remove or adjust conflicting selections.";
      }
    }
    return null;
  }, []);

  // Handle text selection
  const handleMouseUp = useCallback(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !activeFamily) return;

    const range = selection.getRangeAt(0);
    const container = textRef.current;
    if (!container || !container.contains(range.startContainer)) return;

    // Calculate offsets relative to the text container
    const preRange = document.createRange();
    preRange.setStart(container, 0);
    preRange.setEnd(range.startContainer, range.startOffset);
    const start = preRange.toString().length;
    const end = start + range.toString().length;

    if (end <= start) return;

    const newAssignment: SplitAssignment = {
      family_id: activeFamily.family_id,
      start,
      end,
    };

    const updated = [...assignments, newAssignment];
    const error = validateAssignments(updated);
    if (error) {
      setValidationError(error);
    } else {
      setValidationError(null);
      setAssignments(updated);
    }

    selection.removeAllRanges();
  }, [activeFamily, assignments, validateAssignments]);

  // Remove assignment on click
  const removeAssignment = useCallback((idx: number) => {
    setAssignments((prev) => prev.filter((_, i) => i !== idx));
    setValidationError(null);
  }, []);

  // Build highlighted text segments
  const renderedSegments = useMemo(() => {
    if (assignments.length === 0) {
      return [{ text: sectionText, bg: undefined, assignmentIdx: -1 }];
    }

    const sorted = [...assignments]
      .map((a, i) => ({ ...a, idx: i }))
      .sort((a, b) => a.start - b.start);

    const segments: { text: string; bg: string | undefined; assignmentIdx: number }[] = [];
    let pos = 0;
    for (const a of sorted) {
      if (a.start > pos) {
        segments.push({ text: sectionText.slice(pos, a.start), bg: undefined, assignmentIdx: -1 });
      }
      const familyIdx = families.findIndex((f) => f.family_id === a.family_id);
      segments.push({
        text: sectionText.slice(a.start, a.end),
        bg: families[familyIdx]?.color ?? ASSIGNMENT_COLORS[familyIdx % ASSIGNMENT_COLORS.length],
        assignmentIdx: a.idx,
      });
      pos = a.end;
    }
    if (pos < sectionText.length) {
      segments.push({ text: sectionText.slice(pos), bg: undefined, assignmentIdx: -1 });
    }
    return segments;
  }, [sectionText, assignments, families]);

  // Keyboard: Escape to cancel, 1-6 to switch family
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
      const num = parseInt(e.key, 10);
      if (num >= 1 && num <= families.length) {
        e.preventDefault();
        setActiveFamilyIdx(num - 1);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [families.length, onCancel]);

  const handleApply = useCallback(() => {
    const error = validateAssignments(assignments);
    if (error) {
      setValidationError(error);
      return;
    }
    onSplit(assignments);
  }, [assignments, validateAssignments, onSplit]);

  return (
    <div className="space-y-3" data-testid="sub-clause-splitter">
      {/* Family selector */}
      <div>
        <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1.5">
          Active family (select text to assign)
        </p>
        <div className="flex flex-wrap gap-1.5">
          {families.map((fam, idx) => (
            <button
              key={fam.family_id}
              type="button"
              onClick={() => setActiveFamilyIdx(idx)}
              className={cn(
                "px-2 py-1 rounded text-xs font-medium transition-colors border",
                idx === activeFamilyIdx
                  ? "border-accent-blue bg-glow-blue text-accent-blue"
                  : "border-border text-text-secondary hover:bg-surface-2",
              )}
              data-testid={`splitter-family-${fam.family_id}`}
            >
              <span
                className="inline-block w-2 h-2 rounded-full mr-1.5"
                style={{ backgroundColor: fam.color }}
              />
              {fam.family_name}
              <span className="ml-1 text-text-muted">({idx + 1})</span>
            </button>
          ))}
        </div>
      </div>

      {/* Text with highlights */}
      <div
        ref={textRef}
        onMouseUp={handleMouseUp}
        className="p-3 bg-surface-2 rounded-lg text-sm text-text-primary leading-relaxed cursor-text select-text border border-border"
        data-testid="splitter-text"
      >
        {renderedSegments.map((seg, idx) => (
          <span
            key={idx}
            style={seg.bg ? { backgroundColor: seg.bg } : undefined}
            className={cn(seg.bg && "rounded px-0.5")}
            onClick={seg.assignmentIdx >= 0 ? () => removeAssignment(seg.assignmentIdx) : undefined}
            title={seg.assignmentIdx >= 0 ? "Click to remove assignment" : undefined}
          >
            {seg.text}
          </span>
        ))}
      </div>

      {/* Assignments summary */}
      {assignments.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-text-muted uppercase tracking-wider">
            Assignments ({assignments.length})
          </p>
          {assignments.map((a, idx) => {
            const fam = families.find((f) => f.family_id === a.family_id);
            return (
              <div
                key={idx}
                className="flex items-center justify-between px-2 py-1 bg-surface-2 rounded text-xs"
                data-testid={`assignment-${idx}`}
              >
                <span className="flex items-center gap-1.5">
                  <Badge variant="blue">{fam?.family_name ?? a.family_id}</Badge>
                  <span className="text-text-muted tabular-nums">
                    chars {a.start}–{a.end}
                  </span>
                  <span className="text-text-secondary truncate max-w-48">
                    &ldquo;{sectionText.slice(a.start, Math.min(a.end, a.start + 40))}
                    {a.end - a.start > 40 ? "..." : ""}&rdquo;
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => removeAssignment(idx)}
                  className="text-text-muted hover:text-accent-red transition-colors ml-2"
                  data-testid={`remove-assignment-${idx}`}
                >
                  &times;
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Validation error */}
      {validationError && (
        <p className="text-xs text-accent-red" data-testid="splitter-validation-error">
          {validationError}
        </p>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleApply}
          disabled={assignments.length === 0}
          className="px-3 py-1.5 bg-accent-blue text-white text-sm rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
          data-testid="splitter-apply"
        >
          Apply Split
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 bg-surface-2 text-text-secondary text-sm rounded-lg hover:text-text-primary transition-colors"
          data-testid="splitter-cancel"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
