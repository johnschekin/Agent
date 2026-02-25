"use client";

import { cn } from "@/lib/cn";

interface HierarchyBreadcrumbsProps {
  article?: string | null;
  section?: string | null;
  clause?: string | null;
  className?: string;
}

export function HierarchyBreadcrumbs({
  article,
  section,
  clause,
  className,
}: HierarchyBreadcrumbsProps) {
  const crumbs = [
    article && { label: article, type: "Article" },
    section && { label: section, type: "Section" },
    clause && { label: clause, type: "Clause" },
  ].filter(Boolean) as { label: string; type: string }[];

  if (crumbs.length === 0) return null;

  return (
    <div
      className={cn(
        "sticky top-0 z-20 flex items-center gap-1.5 px-4 py-2 bg-surface-2 border-b border-border text-xs",
        className
      )}
    >
      {crumbs.map((crumb, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <span className="text-text-muted">&rsaquo;</span>}
          <span className="text-text-muted">{crumb.type}</span>
          <span className="text-text-primary font-medium">{crumb.label}</span>
        </span>
      ))}
    </div>
  );
}
