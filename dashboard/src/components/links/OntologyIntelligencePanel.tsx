"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import {
  useLinkIntelligenceSignals,
  useLinkIntelligenceEvidence,
  useLinkIntelligenceOps,
} from "@/lib/queries";

interface OntologyIntelligencePanelProps {
  scopeId?: string;
  className?: string;
}

function pct(value: number): string {
  if (!Number.isFinite(value)) return "0%";
  return `${(value * 100).toFixed(0)}%`;
}

function compactTime(value?: string | null): string {
  const iso = String(value ?? "").trim();
  if (!iso) return "n/a";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

export function OntologyIntelligencePanel({ scopeId, className }: OntologyIntelligencePanelProps) {
  const [recordType, setRecordType] = useState<"" | "HIT" | "NOT_FOUND">("HIT");
  const signalsQuery = useLinkIntelligenceSignals(scopeId);
  const evidenceQuery = useLinkIntelligenceEvidence(scopeId, {
    recordType: recordType || undefined,
    limit: 25,
    offset: 0,
  });
  const opsQuery = useLinkIntelligenceOps(scopeId, 60);

  const topStrategies = useMemo(
    () => (signalsQuery.data?.strategies ?? []).slice(0, 6),
    [signalsQuery.data?.strategies],
  );

  return (
    <aside className={cn("w-[360px] border-l border-border bg-surface-1 flex flex-col", className)}>
      <div className="px-3 py-2 border-b border-border">
        <p className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
          Intelligence Overlay
        </p>
        <div className="mt-1 flex items-center gap-2">
          {scopeId ? (
            <Badge variant="blue" className="max-w-full truncate">
              {signalsQuery.data?.scope_name || scopeId}
            </Badge>
          ) : (
            <Badge variant="default">All Ontology Scopes</Badge>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-auto space-y-3 p-3">
        <section className="rounded-lg border border-border bg-surface-2 p-3">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-text-primary">Signals</h4>
            <span className="text-[11px] text-text-muted tabular-nums">
              {(signalsQuery.data?.total_strategies ?? 0).toLocaleString()} strategies
            </span>
          </div>
          {signalsQuery.isLoading ? (
            <p className="mt-2 text-xs text-text-muted">Loading strategy signals...</p>
          ) : topStrategies.length === 0 ? (
            <p className="mt-2 text-xs text-text-muted">No strategy signals for this scope.</p>
          ) : (
            <div className="mt-2 space-y-2">
              {topStrategies.map((row) => (
                <div key={row.concept_id} className="rounded-md bg-surface-1 px-2 py-1.5">
                  <p className="text-xs text-text-primary truncate" title={row.concept_id}>
                    {row.concept_name || row.concept_id}
                  </p>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-text-muted">
                    <span>hit {pct(row.heading_hit_rate)}</span>
                    <span>precision {pct(row.keyword_precision)}</span>
                    <span>v{row.version}</span>
                  </div>
                </div>
              ))}
              {(signalsQuery.data?.top_keyword_anchors?.length ?? 0) > 0 && (
                <div className="pt-1">
                  <p className="text-[10px] uppercase tracking-wider text-text-muted mb-1">
                    Top Keyword Anchors
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {signalsQuery.data?.top_keyword_anchors.slice(0, 6).map((item) => (
                      <Badge key={item.value} variant="default">
                        {item.value} ({item.count})
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-border bg-surface-2 p-3">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-text-primary">Evidence</h4>
            <div className="flex items-center gap-1">
              {(["HIT", "NOT_FOUND"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setRecordType(value)}
                  className={cn(
                    "px-2 py-0.5 rounded text-[10px] transition-colors",
                    recordType === value
                      ? "bg-accent-blue text-white"
                      : "bg-surface-1 text-text-muted hover:text-text-primary",
                  )}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
          {evidenceQuery.isLoading ? (
            <p className="mt-2 text-xs text-text-muted">Loading evidence rows...</p>
          ) : (
            <div className="mt-2 space-y-2">
              <div className="flex items-center gap-2 text-[11px] text-text-muted">
                <span>
                  {evidenceQuery.data?.summary.rows_returned ?? 0} / {evidenceQuery.data?.summary.rows_matched ?? 0}
                </span>
                <span>hit-rate {pct(evidenceQuery.data?.summary.scope_hit_rate ?? 0)}</span>
              </div>
              {(evidenceQuery.data?.rows ?? []).slice(0, 6).map((row, idx) => (
                <div key={`${row.doc_id}-${row.section_number}-${idx}`} className="rounded-md bg-surface-1 px-2 py-1.5">
                  <p className="text-xs text-text-primary truncate" title={row.heading}>
                    {row.section_number || "—"} {row.heading || row.doc_id}
                  </p>
                  <p className="text-[11px] text-text-muted truncate">
                    {row.doc_id} · {row.template_family} · {row.record_type}
                  </p>
                </div>
              ))}
              {(evidenceQuery.data?.rows?.length ?? 0) === 0 && (
                <p className="text-xs text-text-muted">No evidence rows for this filter.</p>
              )}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-border bg-surface-2 p-3">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-text-primary">Ops</h4>
            <span className="text-[11px] text-text-muted">last 60m stale check</span>
          </div>
          {opsQuery.isLoading ? (
            <p className="mt-2 text-xs text-text-muted">Loading ops telemetry...</p>
          ) : (
            <div className="mt-2 space-y-2">
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded bg-surface-1 px-2 py-1">
                  <p className="text-[10px] text-text-muted uppercase">Agents</p>
                  <p className="text-xs text-text-primary tabular-nums">{opsQuery.data?.agents.total ?? 0}</p>
                </div>
                <div className="rounded bg-surface-1 px-2 py-1">
                  <p className="text-[10px] text-text-muted uppercase">Jobs</p>
                  <p className="text-xs text-text-primary tabular-nums">{opsQuery.data?.jobs.running ?? 0}</p>
                </div>
                <div className="rounded bg-surface-1 px-2 py-1">
                  <p className="text-[10px] text-text-muted uppercase">Runs</p>
                  <p className="text-xs text-text-primary tabular-nums">{opsQuery.data?.runs.running ?? 0}</p>
                </div>
              </div>
              {(opsQuery.data?.runs.items ?? []).slice(0, 4).map((run) => (
                <div key={run.run_id} className="rounded-md bg-surface-1 px-2 py-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs text-text-primary truncate">{run.scope_id || run.family_id}</span>
                    <Badge variant={run.status === "completed" ? "green" : "blue"}>{run.status}</Badge>
                  </div>
                  <p className="text-[11px] text-text-muted">
                    {run.links_created} links · {compactTime(run.started_at)}
                  </p>
                </div>
              ))}
              {(opsQuery.data?.runs.items?.length ?? 0) === 0 && (
                <p className="text-xs text-text-muted">No run telemetry for this scope.</p>
              )}
            </div>
          )}
        </section>
      </div>
    </aside>
  );
}
