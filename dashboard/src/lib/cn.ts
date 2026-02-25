import { twMerge } from "tailwind-merge";

/** Merge class names, filtering falsy values and resolving Tailwind conflicts. */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return twMerge(classes.filter(Boolean).join(" "));
}

/** Shared input/select styling for filter controls. */
export const SELECT_CLASS =
  "bg-surface-2 border border-border rounded-md px-2.5 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-blue/40 focus:border-accent-blue shadow-focus-ring transition-colors";
