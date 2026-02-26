"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import {
  useAnalyticsDashboard,
  useLinkRuns,
  useLinkRules,
  useDriftAlerts,
  useSubmitLinkJobMutation,
} from "@/lib/queries";

interface BatchRunDashboardProps {
  className?: string;
  scopeFilter?: string;
}

const EMPTY_PLACEHOLDER = "—";

function canonicalFamilyToken(value?: string | null): string {
  const raw = String(value ?? "").trim().toLowerCase();
  if (!raw) return "";
  const stripped = raw
    .replace(/^fam[-_.]/, "")
    .replace(/[^a-z0-9]+/g, ".")
    .replace(/\.+/g, ".")
    .replace(/^\./, "")
    .replace(/\.$/, "");
  if (!stripped) return "";
  const parts = stripped.split(".").filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : stripped;
}

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d ago`;
}

export function BatchRunDashboard({ className, scopeFilter }: BatchRunDashboardProps) {
  const { data: analytics, isLoading: analyticsLoading } = useAnalyticsDashboard(scopeFilter);
  const { data: runsData } = useLinkRuns({ familyId: scopeFilter });
  const { data: rulesData } = useLinkRules({ status: "published", familyId: scopeFilter });
  const { data: alertsData } = useDriftAlerts();
  const submitJobMut = useSubmitLinkJobMutation();
  const [submittingScopeId, setSubmittingScopeId] = useState<string | null>(null);

  const runs = runsData?.runs ?? [];
  const rules = rulesData?.rules ?? [];
  const alerts = useMemo(() => {
    const all = alertsData?.alerts ?? [];
    const requestedScope = String(scopeFilter ?? "").trim();
    if (!requestedScope) return all;
    const requestedToken = canonicalFamilyToken(requestedScope);
    return all.filter((alert) => {
      const alertScope = String(alert.family_id ?? "").trim();
      if (!alertScope) return false;
      if (alertScope === requestedScope) return true;
      if (alertScope.startsWith(`${requestedScope}.`)) return true;
      if (!requestedToken) return false;
      return canonicalFamilyToken(alertScope) === requestedToken;
    });
  }, [alertsData?.alerts, scopeFilter]);
  const unacknowledgedAlerts = alerts.filter((a) => !a.resolved);

  // Compute coverage % from links_by_status: accepted / total
  const coverageDisplay = useMemo(() => {
    const totalLinks = analytics?.total_links ?? 0;
    if (totalLinks === 0) return EMPTY_PLACEHOLDER;
    const accepted =
      analytics?.links_by_status?.find((s) => s.status === "accepted")?.count ?? 0;
    const pct = (accepted / totalLinks) * 100;
    return `${pct.toFixed(1)}%`;
  }, [analytics]);

  const getScopeIdFromRun = (run: (typeof runs)[number]): string => {
    const scopeId = String(run.scope_id ?? run.ontology_node_id ?? run.family_id ?? "").trim();
    return scopeId || String(run.family_id ?? "").trim() || "unassigned";
  };

  const getScopeIdFromRule = (rule: (typeof rules)[number]): string => {
    const scopeId = String(rule.ontology_node_id ?? rule.family_id ?? "").trim();
    return scopeId || String(rule.family_id ?? "").trim() || "unassigned";
  };

  // Build a lookup: scope_id -> most recent run for that scope
  const latestRunByScope = useMemo(() => {
    const map = new Map<string, (typeof runs)[number]>();
    for (const run of runs) {
      const scopeId = getScopeIdFromRun(run);
      const existing = map.get(scopeId);
      if (!existing || new Date(run.started_at) > new Date(existing.started_at)) {
        map.set(scopeId, run);
      }
    }
    return map;
  }, [runs]);

  // Build a lookup: scope_id -> pending run count.
  // Since analytics.links_by_status is global, we derive pending count from runs data
  const pendingByScope = useMemo(() => {
    const map = new Map<string, number>();
    for (const run of runs) {
      if (run.status === "running") {
        const scopeId = getScopeIdFromRun(run);
        map.set(scopeId, (map.get(scopeId) ?? 0) + 1);
      }
    }
    return map;
  }, [runs]);

  // Coverage by scope: links_created / corpus_doc_count from the latest run
  const coverageByScope = useMemo(() => {
    const map = new Map<string, number | null>();
    latestRunByScope.forEach((run, scopeId) => {
      if (run.corpus_doc_count > 0 && run.status === "completed") {
        map.set(scopeId, (run.links_created / run.corpus_doc_count) * 100);
      } else {
        map.set(scopeId, null);
      }
    });
    return map;
  }, [latestRunByScope]);

  const matrixFamilies = useMemo(() => {
    const rows = new Map<
      string,
      {
        scope_id: string;
        family_id: string;
        ontology_node_id?: string | null;
        count: number;
      }
    >();
    const upsert = (row: {
      scope_id: string;
      family_id: string;
      ontology_node_id?: string | null;
      count: number;
    }) => {
      const scopeId = String(row.scope_id ?? "").trim();
      if (!scopeId) return;
      const existing = rows.get(scopeId);
      if (!existing) {
        rows.set(scopeId, row);
        return;
      }
      rows.set(scopeId, {
        scope_id: scopeId,
        family_id: existing.family_id || row.family_id,
        ontology_node_id: existing.ontology_node_id ?? row.ontology_node_id ?? null,
        count: Math.max(existing.count, row.count),
      });
    };

    for (const family of analytics?.links_by_family ?? []) {
      const scopeId = String(family.scope_id ?? family.family_id ?? "").trim();
      const baseFamily = String(family.base_family_id ?? family.family_id ?? scopeId).trim();
      upsert({
        scope_id: scopeId || baseFamily || "unassigned",
        family_id: baseFamily || scopeId || "unassigned",
        ontology_node_id:
          family.ontology_node_id === null || family.ontology_node_id === undefined
            ? null
            : String(family.ontology_node_id),
        count: Number(family.count ?? 0),
      });
    }

    for (const [scopeId, run] of Array.from(latestRunByScope.entries())) {
      const baseFamily = String(run.base_family_id ?? run.family_id ?? scopeId).trim();
      upsert({
        scope_id: scopeId,
        family_id: baseFamily || scopeId,
        ontology_node_id:
          run.ontology_node_id === null || run.ontology_node_id === undefined
            ? null
            : String(run.ontology_node_id),
        count: Number(run.links_created ?? 0),
      });
    }

    for (const rule of rules) {
      const scopeId = getScopeIdFromRule(rule);
      const familyId = String(rule.family_id ?? scopeId).trim();
      upsert({
        scope_id: scopeId,
        family_id: familyId || scopeId,
        ontology_node_id:
          rule.ontology_node_id === null || rule.ontology_node_id === undefined
            ? null
            : String(rule.ontology_node_id),
        count: 0,
      });
    }

    for (const alert of alerts.filter((a) => !a.resolved)) {
      const familyId = String(alert.family_id ?? "").trim();
      if (!familyId) continue;
      upsert({
        scope_id: familyId,
        family_id: familyId,
        ontology_node_id: null,
        count: 0,
      });
    }

    if (rows.size === 0) {
      return [{ scope_id: "unassigned", family_id: "unassigned", count: 0 }];
    }
    return Array.from(rows.values()).sort(
      (a, b) => b.count - a.count || a.scope_id.localeCompare(b.scope_id),
    );
  }, [analytics, latestRunByScope, rules, alerts]);

  const publishedRuleScopeIds = useMemo(() => {
    const ids = new Set<string>();
    for (const rule of rules) {
      const scopeId = getScopeIdFromRule(rule);
      if (scopeId) ids.add(scopeId);
      const familyId = String(rule.family_id ?? "").trim();
      if (familyId) ids.add(familyId);
    }
    return ids;
  }, [rules]);

  const publishedRuleTokenCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const scopeId of Array.from(publishedRuleScopeIds)) {
      const token = canonicalFamilyToken(scopeId);
      if (!token) continue;
      counts.set(token, (counts.get(token) ?? 0) + 1);
    }
    return counts;
  }, [publishedRuleScopeIds]);

  const getRunEligibility = (scopeId: string, baseFamilyId?: string) => {
    if (publishedRuleScopeIds.has(scopeId)) {
      return { canRun: true, reason: "" };
    }
    if (baseFamilyId && publishedRuleScopeIds.has(baseFamilyId)) {
      return { canRun: true, reason: "" };
    }
    const token = canonicalFamilyToken(scopeId || baseFamilyId);
    if (!token) {
      return { canRun: false, reason: "No published rule for this scope" };
    }
    const tokenMatches = publishedRuleTokenCounts.get(token) ?? 0;
    if (tokenMatches === 1) {
      return { canRun: true, reason: "" };
    }
    if (tokenMatches > 1) {
      return { canRun: false, reason: "Ambiguous scope alias: multiple published scopes match this token" };
    }
    return { canRun: false, reason: "No published rule for this scope" };
  };

  // Most recent run overall for staleness indicator
  const mostRecentRun = useMemo(() => {
    if (runs.length === 0) return null;
    return runs.reduce((latest, run) =>
      new Date(run.started_at) > new Date(latest.started_at) ? run : latest,
    );
  }, [runs]);

  return (
    <div className={cn("space-y-4", className)} data-testid="batch-run-dashboard">
      {/* KPI row */}
      <KpiCardGrid className="grid-cols-2 md:grid-cols-4">
        <KpiCard
          title="Total Links"
          value={analytics?.total_links ?? 0}
          color="blue"
        />
        <KpiCard
          title="Coverage %"
          value={coverageDisplay}
          color="green"
        />
        <KpiCard
          title="Pending Review"
          value={
            analytics?.links_by_status?.find((s) => s.status === "pending_review")?.count ?? 0
          }
          color="orange"
        />
        <KpiCard
          title="Drift Alerts"
          value={unacknowledgedAlerts.length}
          color="red"
        />
      </KpiCardGrid>

      {/* Scope matrix */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
            Ontology Scope Matrix
          </h4>
          <button
            type="button"
            onClick={() => {
              setSubmittingScopeId(null);
              submitJobMut.mutate({
                job_type: "batch_run",
                params: scopeFilter ? { family_id: scopeFilter } : {},
              });
            }}
            disabled={submitJobMut.isPending}
            className="px-3 py-1.5 bg-accent-blue text-white text-xs rounded-lg hover:opacity-90 disabled:opacity-50"
            data-testid="run-all-rules-btn"
          >
            {submitJobMut.isPending ? "Submitting..." : scopeFilter ? "Run Scope Rules" : "Run All Rules"}
          </button>
        </div>

        {/* Staleness indicator */}
        {mostRecentRun && (
          <p
            className="text-xs text-text-muted mb-2"
            data-testid="staleness-indicator"
          >
            Last batch run: {timeAgo(mostRecentRun.started_at)}
            {mostRecentRun.completed_at
              ? ` (completed ${timeAgo(mostRecentRun.completed_at)})`
              : mostRecentRun.status === "running"
                ? " (still running)"
                : ""}
          </p>
        )}

        {analyticsLoading ? (
          <p className="text-sm text-text-muted py-6 text-center">Loading analytics...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse" data-testid="family-matrix">
              <thead>
                <tr>
                  <th className="px-3 py-2 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Scope
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Links
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Coverage %
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Pending
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Status
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Last Run
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Drift
                  </th>
                  <th className="px-3 py-2 text-right text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                    Run
                  </th>
                </tr>
              </thead>
              <tbody>
                {matrixFamilies.map((fam) => {
                  const familyAlerts = alerts.filter(
                    (a) =>
                      !a.resolved &&
                      (
                        a.family_id === fam.scope_id
                        || a.family_id === fam.family_id
                      ),
                  );
                  const latestRun = latestRunByScope.get(fam.scope_id);
                  const coverage = coverageByScope.get(fam.scope_id);
                  const pending = pendingByScope.get(fam.scope_id) ?? 0;
                  const runEligibility = getRunEligibility(fam.scope_id, fam.family_id);
                  const isSubmittingRow = submitJobMut.isPending && submittingScopeId === fam.scope_id;
                  return (
                    <tr
                      key={fam.scope_id}
                      className="border-b border-border/30 hover:bg-surface-2/50"
                      data-testid={`matrix-family-${fam.scope_id}`}
                    >
                      <td className="px-3 py-2 text-sm text-text-primary">
                        <div>{fam.scope_id}</div>
                        {fam.family_id !== fam.scope_id ? (
                          <div className="text-[10px] text-text-muted">
                            base: {fam.family_id}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 text-sm text-text-primary text-right tabular-nums">
                        {fam.count}
                      </td>
                      <td
                        className="px-3 py-2 text-sm text-text-primary text-right tabular-nums"
                        data-testid={`matrix-coverage-${fam.scope_id}`}
                      >
                        {coverage != null ? `${coverage.toFixed(1)}%` : EMPTY_PLACEHOLDER}
                      </td>
                      <td
                        className="px-3 py-2 text-sm text-right tabular-nums"
                        data-testid={`matrix-pending-${fam.scope_id}`}
                      >
                        {pending > 0 ? (
                          <Badge variant="orange">{pending} running</Badge>
                        ) : (
                          <span className="text-text-muted">{EMPTY_PLACEHOLDER}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {latestRun ? (
                          <Badge
                            variant={
                              latestRun.status === "completed"
                                ? "green"
                                : latestRun.status === "running"
                                  ? "blue"
                                  : "red"
                            }
                          >
                            {latestRun.status}
                          </Badge>
                        ) : (
                          <span className="text-xs text-text-muted">{EMPTY_PLACEHOLDER}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs text-text-muted text-right tabular-nums">
                        {latestRun ? timeAgo(latestRun.started_at) : EMPTY_PLACEHOLDER}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {familyAlerts.length > 0 ? (
                          <Badge variant="red">{familyAlerts.length} alerts</Badge>
                        ) : (
                          <span className="text-xs text-text-muted">{EMPTY_PLACEHOLDER}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => {
                            setSubmittingScopeId(fam.scope_id);
                            submitJobMut.mutate(
                              { job_type: "batch_run", params: { family_id: fam.scope_id } },
                              { onSettled: () => setSubmittingScopeId(null) },
                            );
                          }}
                          disabled={submitJobMut.isPending || !runEligibility.canRun}
                          title={runEligibility.canRun ? `Run published rules for ${fam.scope_id}` : runEligibility.reason}
                          className="px-2 py-1 bg-surface-2 text-text-secondary text-xs rounded-md hover:text-text-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          data-testid={`run-family-${fam.scope_id}`}
                        >
                          {isSubmittingRow ? "Submitting..." : "Run"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent runs */}
      {runs.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
            Recent Runs
          </h4>
          <div className="space-y-1">
            {runs.slice(0, 5).map((run) => (
              <div
                key={run.run_id}
                className="flex items-center justify-between px-3 py-2 bg-surface-2 rounded-lg"
                data-testid={`run-${run.run_id}`}
              >
                <div className="flex items-center gap-2">
                  <Badge variant={run.status === "completed" ? "green" : run.status === "running" ? "blue" : "red"}>
                    {run.status}
                  </Badge>
                  <span className="text-xs text-text-primary">{getScopeIdFromRun(run)}</span>
                  <span className="text-xs text-text-muted">{run.run_type}</span>
                </div>
                <span className="text-xs text-text-muted tabular-nums">
                  {run.links_created} links
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
