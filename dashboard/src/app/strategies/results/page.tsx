"use client";

import { useState, useMemo } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { Badge } from "@/components/ui/Badge";
import { StrategyMetricsBar } from "@/components/strategy/StrategyMetricsBar";
import { useStrategyStats, useStrategies } from "@/lib/queries";
import { cn, SELECT_CLASS } from "@/lib/cn";

function formatPct(v: number): string {
  if (v === 0) return "—";
  return `${Math.round(v * 100)}%`;
}

export default function StrategyResultsPage() {
  const [groupBy, setGroupBy] = useState<"family" | "status">("family");
  const stats = useStrategyStats();
  const strategies = useStrategies();

  // Group strategies
  const groups = useMemo(() => {
    if (!strategies.data?.strategies) return [];
    const map = new Map<string, typeof strategies.data.strategies>();
    for (const s of strategies.data.strategies) {
      const key = groupBy === "family" ? s.family : s.validation_status;
      const list = map.get(key) ?? [];
      list.push(s);
      map.set(key, list);
    }
    return Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, items]) => ({
        name,
        items,
        avgHitRate:
          items.reduce((sum, s) => sum + s.heading_hit_rate, 0) / items.length,
        avgPrecision:
          items.reduce((sum, s) => sum + s.keyword_precision, 0) / items.length,
        avgPrevalence:
          items.reduce((sum, s) => sum + s.corpus_prevalence, 0) / items.length,
        avgCoverage:
          items.reduce((sum, s) => sum + s.cohort_coverage, 0) / items.length,
      }));
  }, [strategies.data, groupBy]);

  if (stats.error || strategies.error) {
    return (
      <ViewContainer title="Strategy Results">
        <EmptyState
          title="Results Unavailable"
          message="Could not load strategy results. Make sure the API server is running."
        />
      </ViewContainer>
    );
  }

  const isLoading =
    (stats.isLoading && !stats.data) ||
    (strategies.isLoading && !strategies.data);

  return (
    <ViewContainer title="Strategy Results">
      {isLoading ? (
        <div className="flex items-center justify-center p-8">
          <LoadingState message="Loading results..." />
        </div>
      ) : (
        <>
          {/* KPI Cards */}
          {stats.data && (
            <div className="px-6 pt-4">
              <KpiCardGrid>
                <KpiCard
                  title="Strategies"
                  value={stats.data.total_strategies}
                  color="blue"
                />
                <KpiCard
                  title="Families"
                  value={stats.data.total_families}
                  color="green"
                />
                <KpiCard
                  title="Avg Hit Rate"
                  value={formatPct(stats.data.overall_avg_heading_hit_rate)}
                  color={
                    stats.data.overall_avg_heading_hit_rate >= 0.8
                      ? "green"
                      : stats.data.overall_avg_heading_hit_rate >= 0.5
                        ? "orange"
                        : "red"
                  }
                />
                <KpiCard
                  title="Avg Precision"
                  value={formatPct(stats.data.overall_avg_keyword_precision)}
                  color={
                    stats.data.overall_avg_keyword_precision >= 0.8
                      ? "green"
                      : stats.data.overall_avg_keyword_precision >= 0.5
                        ? "orange"
                        : "red"
                  }
                />
                <KpiCard
                  title="Avg Prevalence"
                  value={formatPct(stats.data.overall_avg_corpus_prevalence)}
                />
                <KpiCard
                  title="Avg Coverage"
                  value={formatPct(stats.data.overall_avg_cohort_coverage)}
                  color={
                    stats.data.overall_avg_cohort_coverage >= 0.8
                      ? "green"
                      : stats.data.overall_avg_cohort_coverage >= 0.5
                        ? "orange"
                        : "red"
                  }
                />
              </KpiCardGrid>
            </div>
          )}

          {/* Group by selector */}
          <div className="px-6 py-3 border-b border-border flex items-center gap-3">
            <label className="text-xs text-text-muted">Group by:</label>
            <select
              value={groupBy}
              onChange={(e) =>
                setGroupBy(e.target.value as "family" | "status")
              }
              className={cn(SELECT_CLASS, "w-[140px]")}
            >
              <option value="family">Family</option>
              <option value="status">Status</option>
            </select>
            <span className="text-xs text-text-muted ml-auto">
              {strategies.data?.total ?? 0} strategies in {groups.length} groups
            </span>
          </div>

          {/* Grouped results */}
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
            {groups.map((group) => (
              <div
                key={group.name}
                className="border border-border rounded-md overflow-hidden"
              >
                {/* Group header */}
                <div className="flex items-center gap-3 px-4 py-2.5 bg-surface-tertiary border-b border-border">
                  <Badge variant="green">{group.name}</Badge>
                  <span className="text-xs text-text-muted">
                    {group.items.length} strategies
                  </span>
                  <div className="ml-auto flex items-center gap-4">
                    <div className="w-20">
                      <StrategyMetricsBar
                        value={group.avgHitRate}
                        showLabel={false}
                      />
                    </div>
                    <div className="w-20">
                      <StrategyMetricsBar
                        value={group.avgPrecision}
                        showLabel={false}
                      />
                    </div>
                  </div>
                </div>

                {/* Strategy rows */}
                <div className="divide-y divide-border">
                  {group.items.map((s) => (
                    <div
                      key={s.concept_id}
                      className="flex items-center gap-3 px-4 py-2 hover:bg-surface-tertiary/40 transition-colors"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-text-primary truncate">
                          {s.concept_name}
                        </div>
                        <div className="text-[10px] text-text-muted font-mono truncate">
                          {s.concept_id}
                        </div>
                      </div>
                      <div className="w-24">
                        <StrategyMetricsBar
                          value={s.heading_hit_rate}
                          showLabel={false}
                        />
                      </div>
                      <div className="w-24">
                        <StrategyMetricsBar
                          value={s.keyword_precision}
                          showLabel={false}
                        />
                      </div>
                      <div className="w-24">
                        <StrategyMetricsBar
                          value={s.corpus_prevalence}
                          showLabel={false}
                        />
                      </div>
                      <div className="w-24">
                        <StrategyMetricsBar
                          value={s.cohort_coverage}
                          showLabel={false}
                        />
                      </div>
                      <span className="text-xs text-text-muted tabular-nums w-8 text-right">
                        {s.dna_phrase_count}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </ViewContainer>
  );
}
