"use client";

import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import {
  useDriftChecks,
  useDriftAlerts,
  useAcknowledgeDriftAlertMutation,
} from "@/lib/queries";
import type { DriftAlert, DriftCheck } from "@/lib/types";

interface DriftDiffViewProps {
  className?: string;
}

// ── Delta indicator ──────────────────────────────────────────────────────────

function DeltaIndicator({
  value,
  format = "number",
  id,
}: {
  value: number;
  format?: "number" | "percent";
  id: string;
}) {
  const isPositive = value > 0;
  const isNegative = value < 0;
  const formatted =
    format === "percent"
      ? `${isPositive ? "+" : ""}${(value * 100).toFixed(1)}%`
      : `${isPositive ? "+" : ""}${value}`;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 tabular-nums text-xs font-medium",
        isPositive && "text-accent-green",
        isNegative && "text-accent-red",
        !isPositive && !isNegative && "text-text-muted",
      )}
      data-testid={`drift-delta-${id}`}
    >
      {isPositive && (
        <svg
          className="w-3 h-3"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M6 2L10 8H2L6 2Z"
            fill="currentColor"
          />
        </svg>
      )}
      {isNegative && (
        <svg
          className="w-3 h-3"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M6 10L2 4H10L6 10Z"
            fill="currentColor"
          />
        </svg>
      )}
      {formatted}
    </span>
  );
}

// ── Baseline vs Current column card ─────────────────────────────────────────

function StatColumn({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex-1 min-w-0 bg-surface-2 rounded-xl p-3 space-y-2">
      <h5 className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">
        {label}
      </h5>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-xs text-text-secondary truncate">{label}</span>
      <span className="text-xs font-medium text-text-primary tabular-nums shrink-0">
        {value}
      </span>
    </div>
  );
}

// ── Per-family check row ─────────────────────────────────────────────────────

function DriftCheckRow({ check }: { check: DriftCheck }) {
  return (
    <div
      className="rounded-lg border border-border-subtle bg-surface-1 overflow-hidden"
      data-testid={`drift-check-${check.check_id}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border-subtle bg-surface-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-text-primary">
            {check.family_id}
          </span>
          <Badge variant={check.drift_detected ? "red" : "green"}>
            {check.drift_detected ? "Drift detected" : "Stable"}
          </Badge>
        </div>
        <span className="text-[10px] text-text-muted">
          {new Date(check.run_at).toLocaleDateString()}
        </span>
      </div>

      {/* Two-column baseline vs current */}
      <div className="flex gap-2 p-2">
        <StatColumn label="Baseline">
          <StatRow label="Run ID" value={check.baseline_run_id.slice(0, 8) + "…"} />
        </StatColumn>
        <StatColumn label="Current">
          <StatRow label="Run ID" value={check.current_run_id.slice(0, 8) + "…"} />
        </StatColumn>
      </div>

      {/* Delta summary */}
      <div className="flex items-center gap-4 px-3 pb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-text-muted">Links</span>
          <DeltaIndicator
            value={check.link_count_delta}
            format="number"
            id={`${check.check_id}-links`}
          />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-text-muted">Confidence</span>
          <DeltaIndicator
            value={check.confidence_delta}
            format="percent"
            id={`${check.check_id}-conf`}
          />
        </div>
        {check.new_conflicts > 0 && (
          <Badge variant="red">{check.new_conflicts} new conflicts</Badge>
        )}
      </div>
    </div>
  );
}

// ── Alert row with acknowledge button ───────────────────────────────────────

function DriftAlertRow({ alert }: { alert: DriftAlert }) {
  const ackMutation = useAcknowledgeDriftAlertMutation();
  const isPending = ackMutation.isPending;

  return (
    <tr
      className={cn(
        "border-b border-border-subtle last:border-0 transition-colors",
        alert.resolved ? "opacity-50" : "hover:bg-surface-2",
      )}
      data-testid={`drift-alert-${alert.alert_id}`}
    >
      {/* Severity */}
      <td className="px-3 py-2 whitespace-nowrap">
        <Badge
          variant={
            alert.severity === "high"
              ? "red"
              : alert.severity === "medium"
                ? "orange"
                : "default"
          }
        >
          {alert.severity}
        </Badge>
      </td>

      {/* Family */}
      <td className="px-3 py-2 whitespace-nowrap">
        <span className="text-xs font-medium text-text-primary">
          {alert.family_id}
        </span>
      </td>

      {/* Type + detail */}
      <td className="px-3 py-2 max-w-xs">
        <p className="text-xs text-text-primary truncate">{alert.detail}</p>
        <p className="text-[10px] text-text-muted mt-0.5">{alert.drift_type}</p>
      </td>

      {/* Date */}
      <td className="px-3 py-2 whitespace-nowrap text-[10px] text-text-muted">
        {new Date(alert.detected_at).toLocaleDateString()}
      </td>

      {/* Status / Acknowledge */}
      <td className="px-3 py-2 whitespace-nowrap text-right">
        {alert.resolved ? (
          <Badge variant="green">Resolved</Badge>
        ) : (
          <button
            className={cn(
              "px-2.5 py-1 rounded-lg text-xs font-medium transition-colors",
              "bg-surface-3 text-text-secondary hover:bg-accent-blue hover:text-white",
              "disabled:opacity-50 disabled:cursor-not-allowed",
            )}
            onClick={() => ackMutation.mutate(alert.alert_id)}
            disabled={isPending}
            data-testid={`ack-drift-${alert.alert_id}`}
          >
            {isPending ? "…" : "Acknowledge"}
          </button>
        )}
      </td>
    </tr>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export function DriftDiffView({ className }: DriftDiffViewProps) {
  const { data: checksData, isLoading: checksLoading } = useDriftChecks();
  const { data: alertsData, isLoading: alertsLoading } = useDriftAlerts();

  const checks = checksData?.checks ?? [];
  const alerts = alertsData?.alerts ?? [];

  const isLoading = checksLoading || alertsLoading;

  return (
    <div
      className={cn("space-y-6", className)}
      data-testid="drift-diff-view"
    >
      {/* ── Baseline vs Current per family ── */}
      <section>
        <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
          Baseline vs Current ({checks.length})
        </h4>

        {isLoading ? (
          <p className="text-sm text-text-muted py-6 text-center">Loading…</p>
        ) : checks.length === 0 ? (
          <p className="text-sm text-text-muted py-6 text-center">
            No drift checks recorded
          </p>
        ) : (
          <div className="space-y-2">
            {checks.slice(0, 15).map((check) => (
              <DriftCheckRow key={check.check_id} check={check} />
            ))}
          </div>
        )}
      </section>

      {/* ── Drift alerts table ── */}
      <section>
        <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
          Drift Alerts ({alerts.length})
        </h4>

        {isLoading ? (
          <p className="text-sm text-text-muted py-6 text-center">Loading…</p>
        ) : alerts.length === 0 ? (
          <p className="text-sm text-text-muted py-6 text-center">
            No drift alerts
          </p>
        ) : (
          <div className="rounded-xl border border-border-subtle overflow-hidden bg-surface-1">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-surface-2 border-b border-border-subtle">
                  <th className="px-3 py-2 text-[10px] font-semibold text-text-muted uppercase tracking-wider">
                    Severity
                  </th>
                  <th className="px-3 py-2 text-[10px] font-semibold text-text-muted uppercase tracking-wider">
                    Family
                  </th>
                  <th className="px-3 py-2 text-[10px] font-semibold text-text-muted uppercase tracking-wider">
                    Detail
                  </th>
                  <th className="px-3 py-2 text-[10px] font-semibold text-text-muted uppercase tracking-wider">
                    Detected
                  </th>
                  <th className="px-3 py-2 text-[10px] font-semibold text-text-muted uppercase tracking-wider text-right">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <DriftAlertRow key={alert.alert_id} alert={alert} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
