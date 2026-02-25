"use client";

import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";

interface CrossFamilyInspectorProps {
  families: { family_id: string; family_name: string; is_current?: boolean }[];
  className?: string;
}

const FAMILY_VARIANT_MAP: Record<string, "blue" | "green" | "red" | "orange" | "purple" | "cyan" | "teal" | "default"> = {
  indebtedness: "blue",
  liens: "orange",
  dividends: "green",
  investments: "purple",
  mergers: "red",
  asset_sales: "cyan",
  affiliate_transactions: "teal",
};

export function CrossFamilyInspector({ families, className }: CrossFamilyInspectorProps) {
  if (families.length === 0) return null;

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      <span className="text-xs text-text-muted mr-1">Families:</span>
      {families.map((f) => {
        const variant = FAMILY_VARIANT_MAP[f.family_id] ?? "default";
        return (
          <Badge
            key={f.family_id}
            variant={variant}
            className={cn(f.is_current && "ring-1 ring-accent-blue")}
          >
            {f.family_name}
          </Badge>
        );
      })}
      {families.length > 1 && (
        <span className="text-xs text-accent-orange font-medium ml-1">
          ({families.length} families)
        </span>
      )}
    </div>
  );
}
