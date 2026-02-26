"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/cn";

// ─── Icon SVGs (inline, 20x20) ────────────────────────────────────────────

function IconCorpus({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M3 4h14M3 8h14M3 12h10M3 16h7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function IconDocuments({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M6 2h6l4 4v10a2 2 0 01-2 2H6a2 2 0 01-2-2V4a2 2 0 012-2z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 2v4h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconLinking({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M8.5 11.5l3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M11.5 8.5l1.4-1.4a2.1 2.1 0 013 3L14.5 11.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8.5 11.5l-1.4 1.4a2.1 2.1 0 003 3l1.4-1.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconAnalysis({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="10" width="3" height="7" rx="0.5" stroke="currentColor" strokeWidth="1.5" />
      <rect x="8.5" y="6" width="3" height="11" rx="0.5" stroke="currentColor" strokeWidth="1.5" />
      <rect x="14" y="3" width="3" height="14" rx="0.5" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function IconDiscovery({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="9" cy="9" r="5.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M13 13l3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M9 6.5v5M6.5 9h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function IconSystem({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="10" cy="10" r="3" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 3v2M10 15v2M3 10h2M15 10h2M5.05 5.05l1.4 1.4M13.55 13.55l1.4 1.4M5.05 14.95l1.4-1.4M13.55 6.45l1.4-1.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

// ─── Navigation structure ──────────────────────────────────────────────────

interface NavItem {
  label: string;
  href: string;
}

interface NavModule {
  id: string;
  title: string;
  icon: React.FC<{ className?: string }>;
  items: NavItem[];
}

const NAV_MODULES: NavModule[] = [
  {
    id: "corpus",
    title: "Corpus",
    icon: IconCorpus,
    items: [
      { label: "Overview", href: "/overview" },
      { label: "Explorer", href: "/explorer" },
      { label: "Search", href: "/search" },
      { label: "Corpus Query", href: "/corpus/query" },
      { label: "Scatter", href: "/scatter" },
    ],
  },
  {
    id: "documents",
    title: "Documents",
    icon: IconDocuments,
    items: [
      { label: "Reader", href: "/reader" },
    ],
  },
  {
    id: "linking",
    title: "Linking",
    icon: IconLinking,
    items: [
      { label: "Ontology Links", href: "/links" },
    ],
  },
  {
    id: "analysis",
    title: "Analysis",
    icon: IconAnalysis,
    items: [
      { label: "Statistics", href: "/stats" },
      { label: "Definitions", href: "/definitions" },
      { label: "Quality", href: "/quality" },
      { label: "Edge Cases", href: "/edge-cases" },
      { label: "Ontology Explorer", href: "/ontology" },
      { label: "Strategies", href: "/strategies" },
      { label: "Strategy Results", href: "/strategies/results" },
      { label: "Feedback Backlog", href: "/feedback" },
    ],
  },
  {
    id: "discovery",
    title: "Discovery",
    icon: IconDiscovery,
    items: [
      { label: "Pattern Testing", href: "/lab/patterns" },
      { label: "DNA Discovery", href: "/lab/dna" },
      { label: "Heading Discovery", href: "/lab/headings" },
      { label: "Coverage Analysis", href: "/lab/coverage" },
      { label: "Clause Deep Dive", href: "/lab/clauses" },
      { label: "Review Queue", href: "/ml/review" },
      { label: "Clause Clusters", href: "/ml/clusters" },
    ],
  },
  {
    id: "system",
    title: "System",
    icon: IconSystem,
    items: [
      { label: "Review Home", href: "/review" },
      { label: "Strategy Timeline", href: "/review/strategy" },
      { label: "Evidence Browser", href: "/review/evidence" },
      { label: "Coverage Heatmap", href: "/review/coverage" },
      { label: "Judge History", href: "/review/judge" },
      { label: "Agent Activity", href: "/review/activity" },
      { label: "Jobs", href: "/jobs" },
    ],
  },
];

// ─── Helpers ───────────────────────────────────────────────────────────────

/** Determine which module owns the current route */
function getActiveModuleId(pathname: string): string | null {
  for (const mod of NAV_MODULES) {
    for (const item of mod.items) {
      if (pathname === item.href || pathname.startsWith(item.href + "/")) {
        return mod.id;
      }
    }
  }
  return null;
}

// ─── Sidebar component ────────────────────────────────────────────────────

export function Sidebar() {
  const pathname = usePathname();
  const [openModuleId, setOpenModuleId] = useState<string | null>(null);
  const activeModuleId = getActiveModuleId(pathname);

  // Auto-close flyout on route change
  useEffect(() => {
    setOpenModuleId(null);
  }, [pathname]);

  const handleModuleClick = useCallback(
    (moduleId: string) => {
      setOpenModuleId((prev) => (prev === moduleId ? null : moduleId));
    },
    []
  );

  const openModule = NAV_MODULES.find((m) => m.id === openModuleId);

  return (
    <>
      {/* ── Icon Rail (56px) ──────────────────────────────────────── */}
      <aside className="fixed left-0 top-0 h-screen w-rail bg-surface-1 border-r border-border z-50 flex flex-col">
        {/* Logo */}
        <div className="flex items-center justify-center h-14 border-b border-border">
          <span className="text-lg font-bold text-accent-blue tracking-tight">CD</span>
        </div>

        {/* Module icons */}
        <nav className="flex-1 flex flex-col items-center py-2 gap-1">
          {NAV_MODULES.map((mod) => {
            const isActive = activeModuleId === mod.id;
            const isOpen = openModuleId === mod.id;
            const Icon = mod.icon;
            return (
              <button
                key={mod.id}
                onClick={() => handleModuleClick(mod.id)}
                title={mod.title}
                className={cn(
                  "relative flex items-center justify-center w-10 h-10 rounded-lg transition-all",
                  isActive && !isOpen
                    ? "text-accent-blue bg-glow-blue shadow-glow-blue"
                    : isOpen
                    ? "text-accent-blue bg-accent-blue/15"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-3"
                )}
              >
                <Icon className="w-5 h-5" />
                {/* Active indicator dot */}
                {isActive && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-r bg-accent-blue" />
                )}
              </button>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="flex items-center justify-center py-3 border-t border-border">
          <span className="text-[10px] text-text-muted">v0.3</span>
        </div>
      </aside>

      {/* ── Flyout Panel (240px) ──────────────────────────────────── */}
      {openModule && (
        <>
          {/* Backdrop — click to close */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpenModuleId(null)}
            aria-hidden
          />
          {/* Panel */}
          <aside
            className="fixed left-rail top-0 h-screen w-flyout bg-surface-1 border-r border-border z-50 animate-palette-slide-in flex flex-col"
          >
            {/* Module header */}
            <div className="px-4 py-4 border-b border-border">
              <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wider">
                {openModule.title}
              </h2>
            </div>

            {/* Sub-nav links */}
            <nav className="flex-1 py-2 overflow-y-auto">
              {openModule.items.map((item) => {
                const isActive =
                  pathname === item.href ||
                  (item.href !== "/" && pathname.startsWith(item.href + "/"));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "block px-4 py-2 text-sm transition-colors border-l-2",
                      isActive
                        ? "text-text-primary bg-glow-blue border-l-accent-blue"
                        : "text-text-secondary hover:text-text-primary hover:bg-surface-3 border-l-transparent"
                    )}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </aside>
        </>
      )}
    </>
  );
}
