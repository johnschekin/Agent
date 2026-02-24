"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

interface NavItem {
  label: string;
  href: string;
  icon?: string;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    title: "CORPUS",
    items: [
      { label: "Overview", href: "/overview" },
      { label: "Explorer", href: "/explorer" },
      { label: "Search", href: "/search" },
      { label: "Scatter", href: "/scatter" },
    ],
  },
  {
    title: "DOCUMENTS",
    items: [{ label: "Reader", href: "/reader" }],
  },
  {
    title: "ANALYSIS",
    items: [
      { label: "Statistics", href: "/stats" },
      { label: "Definitions", href: "/definitions" },
      { label: "Quality", href: "/quality" },
      { label: "Edge Cases", href: "/edge-cases" },
    ],
  },
  {
    title: "ONTOLOGY",
    items: [{ label: "Ontology Explorer", href: "/ontology" }],
  },
  {
    title: "DISCOVERY LAB",
    items: [
      { label: "Pattern Testing", href: "/lab/patterns" },
      { label: "DNA Discovery", href: "/lab/dna" },
      { label: "Heading Discovery", href: "/lab/headings" },
      { label: "Coverage Analysis", href: "/lab/coverage" },
      { label: "Clause Deep Dive", href: "/lab/clauses" },
    ],
  },
  {
    title: "STRATEGIES",
    items: [
      { label: "Strategy Manager", href: "/strategies" },
      { label: "Strategy Results", href: "/strategies/results" },
    ],
  },
  {
    title: "ML & LEARNING",
    items: [
      { label: "Review Queue", href: "/ml/review" },
      { label: "Clause Clusters", href: "/ml/clusters" },
    ],
  },
  {
    title: "FEEDBACK",
    items: [{ label: "Feedback Backlog", href: "/feedback" }],
  },
  {
    title: "REVIEW OPS",
    items: [
      { label: "Review Home", href: "/review" },
      { label: "Strategy Timeline", href: "/review/strategy" },
      { label: "Evidence Browser", href: "/review/evidence" },
      { label: "Coverage Heatmap", href: "/review/coverage" },
      { label: "Judge History", href: "/review/judge" },
      { label: "Agent Activity", href: "/review/activity" },
    ],
  },
  {
    title: "SYSTEM",
    items: [{ label: "Jobs", href: "/jobs" }],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-screen w-sidebar bg-surface-secondary border-r border-border overflow-y-auto z-40 flex flex-col">
      {/* Logo / Title */}
      <div className="px-4 py-4 border-b border-border">
        <h1 className="text-lg font-semibold text-text-primary tracking-tight">
          Corpus Dashboard
        </h1>
        <p className="text-xs text-text-muted mt-0.5">
          Pattern Discovery Swarm
        </p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-2 overflow-y-auto">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="mb-1">
            <div className="px-4 py-1.5 text-xs font-semibold text-text-muted uppercase tracking-wider">
              {group.title}
            </div>
            {group.items.map((item) => {
              // Exact match, or pathname starts with href followed by / (prevents
              // /strategies matching when on /strategies/results)
              const isActive =
                pathname === item.href ||
                (item.href !== "/" && pathname.startsWith(item.href + "/"));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "block px-4 py-1.5 text-sm transition-colors",
                    isActive
                      ? "text-text-primary bg-accent-blue/10 border-l-2 border-l-accent-blue"
                      : "text-text-secondary hover:text-text-primary hover:bg-surface-tertiary border-l-2 border-l-transparent"
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-border text-xs text-text-muted">
        Schema v0.2.0
      </div>
    </aside>
  );
}
