"use client";

import { useState } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useReviewAgentActivity } from "@/lib/queries";
import { cn, SELECT_CLASS } from "@/lib/cn";

export default function ReviewAgentActivityPage() {
  const [staleMinutes, setStaleMinutes] = useState(60);
  const query = useReviewAgentActivity(staleMinutes);

  return (
    <ViewContainer
      title="Review: Agent Activity"
      subtitle="Checkpoint-driven swarm activity and stale-agent monitoring."
      actions={
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Stale threshold</span>
          <select
            value={staleMinutes}
            onChange={(e) => setStaleMinutes(Number(e.target.value))}
            className={cn(SELECT_CLASS, "w-[130px]")}
          >
            <option value={15}>15 min</option>
            <option value={30}>30 min</option>
            <option value={60}>60 min</option>
            <option value={120}>120 min</option>
            <option value={240}>240 min</option>
          </select>
        </div>
      }
    >
      {query.isLoading && <LoadingState message="Loading agent activity..." />}
      {query.error && (
        <EmptyState
          title="Agent Activity Unavailable"
          message="Could not read checkpoint activity from workspace directories."
        />
      )}

      {query.data && (
        <>
          <KpiCardGrid className="mb-4">
            <KpiCard title="Agents" value={query.data.total} color="blue" />
            <KpiCard title="Stale Agents" value={query.data.stale_count} color={query.data.stale_count > 0 ? "red" : "green"} />
            <KpiCard title="Stale Threshold" value={`${query.data.stale_minutes}m`} />
          </KpiCardGrid>

          {query.data.agents.length === 0 ? (
            <EmptyState title="No Checkpoints" message="No family checkpoint files exist yet." />
          ) : (
            <div className="overflow-auto border border-border rounded-md">
              <table className="w-full text-xs">
                <thead className="bg-surface-3 text-text-muted uppercase">
                  <tr>
                    <th className="px-3 py-2 text-left">Family</th>
                    <th className="px-3 py-2 text-left">Status</th>
                    <th className="px-3 py-2 text-right">Iteration</th>
                    <th className="px-3 py-2 text-left">Current Concept</th>
                    <th className="px-3 py-2 text-right">Strategy V</th>
                    <th className="px-3 py-2 text-right">Coverage</th>
                    <th className="px-3 py-2 text-left">Session/Pane</th>
                    <th className="px-3 py-2 text-left">Last Update</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.agents.map((a) => (
                    <tr key={a.family} className="border-t border-border hover:bg-surface-3/40">
                      <td className="px-3 py-2">{a.family}</td>
                      <td className="px-3 py-2">
                        <span
                          className={cn(
                            "inline-block px-1.5 py-0.5 rounded text-[11px]",
                            a.stale
                              ? "bg-accent-red/20 text-accent-red"
                              : a.status === "running"
                                ? "bg-accent-blue/20 text-accent-blue"
                                : "bg-surface-3 text-text-secondary"
                          )}
                        >
                          {a.status}
                          {a.stale ? " (stale)" : ""}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{a.iteration_count}</td>
                      <td className="px-3 py-2 font-mono">{a.current_concept_id || "—"}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{a.last_strategy_version || 0}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {a.last_coverage_hit_rate ? `${(a.last_coverage_hit_rate * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className="px-3 py-2 font-mono">
                        {a.last_session || "—"}
                        {a.last_pane ? `:${a.last_pane}` : ""}
                      </td>
                      <td className="px-3 py-2">{a.last_update || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </ViewContainer>
  );
}
