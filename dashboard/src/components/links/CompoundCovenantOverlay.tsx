"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";

interface FamilyInfo {
  family_id: string;
  family_name: string;
  color: string;
}

interface CompoundCovenantOverlayProps {
  sectionText: string;
  families: FamilyInfo[];
  activeFamily?: string;
}

export function CompoundCovenantOverlay({
  sectionText,
  families,
  activeFamily: initialActive,
}: CompoundCovenantOverlayProps) {
  const [activeFamily, setActiveFamily] = useState<string | undefined>(
    initialActive,
  );

  return (
    <div data-testid="compound-overlay">
      {/* Legend bar */}
      <div className="flex flex-wrap gap-1.5 mb-2">
        {families.map((fam) => {
          const isActive = activeFamily === fam.family_id;
          return (
            <button
              key={fam.family_id}
              type="button"
              onClick={() =>
                setActiveFamily(
                  activeFamily === fam.family_id ? undefined : fam.family_id,
                )
              }
              className={cn(
                "inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-all",
                isActive
                  ? "ring-2 ring-offset-1 ring-offset-surface-1"
                  : "opacity-60 hover:opacity-100",
              )}
              style={{
                backgroundColor: `${fam.color}20`,
                color: fam.color,
                ...(isActive ? { ringColor: fam.color } : {}),
              }}
              data-testid={`compound-family-${fam.family_id}`}
            >
              <div
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: fam.color }}
              />
              {fam.family_name}
            </button>
          );
        })}
      </div>

      {/* Section text with colored left-border overlays */}
      <div className="relative bg-surface-2 rounded-lg p-3 text-sm text-text-primary font-mono whitespace-pre-wrap">
        {/* Family color borders */}
        <div className="absolute left-0 top-0 bottom-0 flex">
          {families.map((fam, idx) => {
            const isActive = activeFamily === fam.family_id;
            const isNoneActive = !activeFamily;
            return (
              <div
                key={fam.family_id}
                className="transition-opacity"
                style={{
                  width: 3,
                  backgroundColor: fam.color,
                  opacity: isActive || isNoneActive ? 1 : 0.3,
                  marginLeft: idx > 0 ? 1 : 0,
                }}
              />
            );
          })}
        </div>

        <div className="pl-4">{sectionText}</div>
      </div>
    </div>
  );
}
