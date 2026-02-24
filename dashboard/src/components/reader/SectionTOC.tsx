"use client";

import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import type { SectionRecord } from "@/lib/types";
import { formatNumber } from "@/lib/formatters";
import { cn, SELECT_CLASS } from "@/lib/cn";

interface ArticleGroup {
  articleNum: number;
  sections: SectionRecord[];
}

function groupByArticle(sections: SectionRecord[]): ArticleGroup[] {
  const map = new Map<number, SectionRecord[]>();
  for (const s of sections) {
    const list = map.get(s.article_num) ?? [];
    list.push(s);
    map.set(s.article_num, list);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a - b)
    .map(([articleNum, sects]) => ({ articleNum, sections: sects }));
}

interface SectionTOCProps {
  sections: SectionRecord[];
  activeSectionNumber: string | null;
  onSelectSection: (sectionNumber: string) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  searchMatchSections?: Set<string>;
  isSearching?: boolean;
}

export function SectionTOC({
  sections,
  activeSectionNumber,
  onSelectSection,
  searchQuery,
  onSearchChange,
  searchMatchSections,
  isSearching,
}: SectionTOCProps) {
  const [expandedArticles, setExpandedArticles] = useState<Set<number>>(
    () => new Set<number>()
  );
  const groups = useMemo(() => groupByArticle(sections), [sections]);
  const activeRef = useRef<HTMLButtonElement>(null);

  // Auto-expand the article containing the active section
  useEffect(() => {
    if (!activeSectionNumber) return;
    const section = sections.find(
      (s) => s.section_number === activeSectionNumber
    );
    if (section) {
      setExpandedArticles((prev) => {
        if (prev.has(section.article_num)) return prev;
        const next = new Set(prev);
        next.add(section.article_num);
        return next;
      });
    }
  }, [activeSectionNumber, sections]);

  // Scroll active section into view
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeSectionNumber]);

  const toggleArticle = useCallback((num: number) => {
    setExpandedArticles((prev) => {
      const next = new Set(prev);
      if (next.has(num)) next.delete(num);
      else next.add(num);
      return next;
    });
  }, []);

  return (
    <div className="flex flex-col h-full">
      {/* Section list */}
      <div className="flex-1 overflow-y-auto py-1">
        {groups.map((group) => {
          const expanded = expandedArticles.has(group.articleNum);
          const hasMatch =
            searchMatchSections &&
            group.sections.some((s) => searchMatchSections.has(s.section_number));

          return (
            <div key={group.articleNum}>
              {/* Article header */}
              <button
                className={cn(
                  "flex items-center gap-2 w-full px-3 py-1.5 hover:bg-surface-tertiary text-left",
                  hasMatch && "bg-accent-blue/5"
                )}
                onClick={() => toggleArticle(group.articleNum)}
              >
                <span className="text-[10px] text-text-muted w-3">
                  {expanded ? "▾" : "▸"}
                </span>
                <span className="text-xs font-medium text-text-primary">
                  Article {group.articleNum}
                </span>
                <span className="text-[11px] text-text-muted ml-auto tabular-nums">
                  {group.sections.length}
                </span>
              </button>

              {/* Sections */}
              {expanded && (
                <div className="ml-5 border-l border-border/50 pl-1">
                  {group.sections.map((s) => {
                    const isActive =
                      s.section_number === activeSectionNumber;
                    const isSearchMatch = searchMatchSections?.has(
                      s.section_number
                    );

                    return (
                      <button
                        key={s.section_number}
                        ref={isActive ? activeRef : undefined}
                        className={cn(
                          "w-full text-left flex items-center gap-1.5 px-2 py-1 text-xs rounded-sm transition-colors",
                          isActive
                            ? "bg-accent-blue/10 border-l-2 border-l-accent-blue text-text-primary"
                            : "border-l-2 border-l-transparent hover:bg-surface-tertiary/50 text-text-secondary",
                          isSearchMatch &&
                            !isActive &&
                            "bg-accent-blue/5"
                        )}
                        onClick={() => onSelectSection(s.section_number)}
                      >
                        <span className="tabular-nums text-accent-blue w-10 flex-shrink-0 font-mono text-[11px]">
                          {s.section_number}
                        </span>
                        <span className="truncate flex-1" title={s.heading}>
                          {s.heading || "(no heading)"}
                        </span>
                        <span className="text-text-muted tabular-nums text-[10px] flex-shrink-0">
                          {formatNumber(s.word_count)}w
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Search input */}
      <div className="p-2 border-t border-border space-y-1">
        <div className="relative">
          <input
            type="text"
            placeholder="Search in document…"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className={cn(SELECT_CLASS, "w-full")}
            aria-label="Search within document"
          />
          {isSearching && (
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-text-muted animate-pulse">
              …
            </span>
          )}
        </div>
        {searchMatchSections && searchMatchSections.size > 0 && (
          <div className="text-[10px] text-text-muted px-1">
            {searchMatchSections.size} section{searchMatchSections.size !== 1 ? "s" : ""} matched
          </div>
        )}
      </div>
    </div>
  );
}
