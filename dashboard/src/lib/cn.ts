import { twMerge } from "tailwind-merge";

/** Merge class names, filtering falsy values and resolving Tailwind conflicts. */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return twMerge(classes.filter(Boolean).join(" "));
}

/** Shared input/select styling for filter controls (L1: extracted from page duplication). */
export const SELECT_CLASS =
  "bg-surface-tertiary border border-border rounded-sm px-2 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-blue";
