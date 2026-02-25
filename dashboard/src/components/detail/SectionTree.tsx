"use client";

import { useState } from "react";
import type { SectionRecord, ArticleRecord } from "@/lib/types";
import { formatNumber } from "@/lib/formatters";
import { cn } from "@/lib/cn";

interface SectionTreeProps {
  sections: SectionRecord[];
  articles?: ArticleRecord[];
}

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

export function SectionTree({ sections, articles }: SectionTreeProps) {
  const [expandedArticles, setExpandedArticles] = useState<Set<number>>(new Set());
  const groups = groupByArticle(sections);
  const articleMap = new Map<number, ArticleRecord>();
  if (articles) {
    for (const a of articles) articleMap.set(a.article_num, a);
  }

  if (sections.length === 0) {
    return (
      <div className="text-sm text-text-muted py-4 text-center">
        No sections parsed
      </div>
    );
  }

  const toggleArticle = (num: number) => {
    setExpandedArticles((prev) => {
      const next = new Set(prev);
      if (next.has(num)) next.delete(num);
      else next.add(num);
      return next;
    });
  };

  return (
    <div className="space-y-1">
      {groups.map((group) => {
        const expanded = expandedArticles.has(group.articleNum);
        const article = articleMap.get(group.articleNum);
        return (
          <div key={group.articleNum}>
            {/* Article header */}
            <button
              className="flex items-center gap-2 w-full px-2 py-1.5 rounded hover:bg-surface-3 text-left"
              onClick={() => toggleArticle(group.articleNum)}
            >
              <span className="text-[10px] text-text-muted w-4">
                {expanded ? "▾" : "▸"}
              </span>
              <span className="text-xs font-medium text-text-primary truncate">
                {article
                  ? `${article.label}${article.title ? ` — ${article.title}` : ""}`
                  : `Article ${group.articleNum}`}
              </span>
              {article?.concept && (
                <span className="text-[10px] text-text-muted bg-surface-3 rounded px-1 py-0.5 flex-shrink-0">
                  {article.concept}
                </span>
              )}
              <span className="text-[11px] text-text-muted ml-auto flex-shrink-0">
                {group.sections.length} sections
              </span>
            </button>

            {/* Sections */}
            {expanded && (
              <div className="ml-6 border-l border-border/50 pl-2 space-y-0.5">
                {group.sections.map((s) => (
                  <div
                    key={s.section_number}
                    className={cn(
                      "flex items-center gap-2 px-2 py-1 rounded text-xs",
                      "hover:bg-surface-3/50 cursor-default"
                    )}
                  >
                    <span className="text-accent-blue tabular-nums w-10 flex-shrink-0">
                      {s.section_number}
                    </span>
                    <span className="text-text-primary truncate flex-1" title={s.heading}>
                      {s.heading || "(no heading)"}
                    </span>
                    <span className="text-text-muted tabular-nums text-[11px] flex-shrink-0">
                      {formatNumber(s.word_count)}w
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
