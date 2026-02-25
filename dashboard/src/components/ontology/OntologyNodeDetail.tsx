"use client";

import { useState, useEffect, useCallback } from "react";
import { useOntologyNode, useSaveOntologyNotes } from "@/lib/queries";
import { LoadingState } from "@/components/ui/Spinner";
import { Badge } from "@/components/ui/Badge";
import { MetadataGrid } from "@/components/detail/MetadataGrid";
import { EdgeList } from "./EdgeList";
import { cn } from "@/lib/cn";
import type { OntologyNodeType } from "@/lib/types";

// --- Prevalence badge colors ---
const PREVALENCE_VARIANT: Record<string, "green" | "blue" | "orange" | "default"> = {
  high: "green",
  medium: "blue",
  low: "orange",
};

// --- Difficulty badge colors ---
const DIFFICULTY_VARIANT: Record<string, "green" | "orange" | "red" | "default"> = {
  low: "green",
  medium: "orange",
  high: "red",
};

// --- Type badge color ---
const TYPE_VARIANT: Record<OntologyNodeType, "blue" | "green" | "orange" | "red" | "default"> = {
  domain: "blue",
  family: "green",
  concept: "orange",
  sub_component: "default",
  parameter: "red",
};

interface OntologyNodeDetailProps {
  nodeId: string | null;
  onClose: () => void;
  onNodeClick: (nodeId: string) => void;
  onShowGraph: (nodeId: string) => void;
}

export function OntologyNodeDetail({
  nodeId,
  onClose,
  onNodeClick,
  onShowGraph,
}: OntologyNodeDetailProps) {
  const { data, isLoading, error } = useOntologyNode(nodeId);
  const saveNotes = useSaveOntologyNotes();
  const [localNotes, setLocalNotes] = useState("");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saved">("idle");

  // Sync local state when data loads or node changes
  useEffect(() => {
    setLocalNotes(data?.notes ?? "");
    setSaveStatus("idle");
  }, [data?.notes, nodeId]);

  const isDirty = localNotes !== (data?.notes ?? "");

  const handleSave = useCallback(() => {
    if (!nodeId || !isDirty) return;
    saveNotes.mutate(
      { nodeId, notes: localNotes },
      { onSuccess: () => setSaveStatus("saved") }
    );
  }, [nodeId, localNotes, isDirty, saveNotes]);

  return (
    <div
      className={cn(
        "fixed top-0 right-0 h-full bg-surface-2 border-l border-border",
        "w-[480px] max-w-[calc(100vw-260px)]",
        "transform transition-transform duration-200 ease-in-out z-30",
        "flex flex-col overflow-hidden",
        nodeId ? "translate-x-0" : "translate-x-full"
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface-3 flex-shrink-0">
        <h3 className="text-sm font-medium text-text-primary truncate pr-4">
          {data?.name || nodeId || "Node Detail"}
        </h3>
        <button
          className="text-text-muted hover:text-text-primary text-lg leading-none flex-shrink-0"
          onClick={onClose}
          aria-label="Close detail panel"
        >
          ×
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {isLoading && <LoadingState message="Loading node..." />}

        {error && (
          <div className="text-sm text-accent-red p-3 bg-accent-red/10 rounded">
            Failed to load node details
          </div>
        )}

        {data && (
          <>
            {/* Identity badges */}
            <div className="flex flex-wrap gap-2">
              <Badge variant={TYPE_VARIANT[data.type] ?? "default"}>
                {data.type.replace(/_/g, " ")}
              </Badge>
              <Badge variant="default">Level {data.level}</Badge>
              {data.corpus_prevalence && (
                <Badge variant={PREVALENCE_VARIANT[data.corpus_prevalence] ?? "default"}>
                  {data.corpus_prevalence} prevalence
                </Badge>
              )}
              {data.extraction_difficulty && (
                <Badge variant={DIFFICULTY_VARIANT[data.extraction_difficulty] ?? "default"}>
                  {data.extraction_difficulty} difficulty
                </Badge>
              )}
            </div>

            {/* Action buttons */}
            <div className="flex gap-2">
              <button
                onClick={() => onShowGraph(data.id)}
                className="px-3 py-1.5 text-xs font-medium rounded-sm bg-accent-blue text-white hover:bg-accent-blue/80 transition-colors"
              >
                Show Graph
              </button>
            </div>

            {/* Metadata grid */}
            <div>
              <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                Identity
              </h4>
              <MetadataGrid
                items={[
                  { label: "ID", value: data.id },
                  { label: "Domain", value: data.domain_id },
                  { label: "Family", value: data.family_id },
                  { label: "Definition Source", value: data.definition_source },
                ]}
              />
            </div>

            {/* Definition */}
            {data.definition && (
              <div>
                <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                  Definition
                </h4>
                <p className="text-sm text-text-secondary leading-relaxed">
                  {data.definition}
                </p>
              </div>
            )}

            {/* Notes */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide">
                  Notes
                </h4>
                {saveStatus === "saved" && !isDirty && (
                  <span className="text-[10px] text-accent-green" data-testid="notes-saved">Saved</span>
                )}
                {saveNotes.isPending && (
                  <span className="text-[10px] text-text-muted">Saving...</span>
                )}
              </div>
              <textarea
                className="w-full bg-surface-3 border border-border rounded px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent-blue resize-y min-h-[72px]"
                placeholder="Add notes about this node..."
                value={localNotes}
                onChange={(e) => { setLocalNotes(e.target.value); setSaveStatus("idle"); }}
                data-testid="notes-textarea"
                rows={3}
              />
              <div className="flex justify-end mt-1.5">
                <button
                  onClick={handleSave}
                  disabled={!isDirty || saveNotes.isPending}
                  className={cn(
                    "px-3 py-1 text-xs font-medium rounded-sm transition-colors",
                    isDirty && !saveNotes.isPending
                      ? "bg-accent-blue text-white hover:bg-accent-blue/80"
                      : "bg-surface-3 text-text-muted cursor-not-allowed"
                  )}
                  data-testid="notes-save-btn"
                >
                  {saveNotes.isPending ? "Saving..." : "Save Notes"}
                </button>
              </div>
            </div>

            {/* Market Benchmarks */}
            {data.market_benchmarks && Object.keys(data.market_benchmarks).length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                  Market Benchmarks
                </h4>
                <div className="bg-surface-3 rounded p-3 space-y-1.5">
                  {Object.entries(data.market_benchmarks).map(([key, val]) => (
                    <div key={key} className="flex justify-between text-xs">
                      <span className="text-text-muted">{key.replace(/_/g, " ")}</span>
                      <span className="text-text-primary font-mono">
                        {typeof val === "object" ? JSON.stringify(val) : String(val)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Red Flags */}
            {data.red_flags && data.red_flags.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                  Red Flags ({data.red_flags.length})
                </h4>
                <ul className="space-y-1.5">
                  {data.red_flags.map((rf, i) => (
                    <li
                      key={i}
                      className={cn(
                        "text-xs px-2.5 py-1.5 rounded border border-border",
                        rf.severity === "high"
                          ? "bg-accent-red/10 text-accent-red"
                          : rf.severity === "medium"
                            ? "bg-accent-orange/10 text-accent-orange"
                            : "bg-surface-3 text-text-secondary"
                      )}
                    >
                      {rf.text}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Negotiation Spectrum */}
            {data.negotiation_spectrum && Object.keys(data.negotiation_spectrum).length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                  Negotiation Spectrum
                </h4>
                <div className="bg-surface-3 rounded p-3 space-y-1.5">
                  {Object.entries(data.negotiation_spectrum).map(([key, val]) => (
                    <div key={key} className="flex justify-between gap-3 text-xs">
                      <span className="text-text-muted capitalize flex-shrink-0">
                        {key.replace(/_/g, " ")}
                      </span>
                      <span className="text-text-primary text-right">{val}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Outgoing Edges */}
            <div>
              <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                Outgoing Edges ({data.outgoing_edges.length})
              </h4>
              <EdgeList
                edges={data.outgoing_edges}
                direction="outgoing"
                onNodeClick={onNodeClick}
              />
            </div>

            {/* Incoming Edges */}
            <div>
              <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                Incoming Edges ({data.incoming_edges.length})
              </h4>
              <EdgeList
                edges={data.incoming_edges}
                direction="incoming"
                onNodeClick={onNodeClick}
              />
            </div>

            {/* References */}
            {(data.dls_ref?.length || data.r18_concept_ids?.length) && (
              <div>
                <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                  References
                </h4>
                {data.dls_ref && data.dls_ref.length > 0 && (
                  <div className="mb-2">
                    <span className="text-[10px] text-text-muted uppercase">DLS Refs:</span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {data.dls_ref.map((ref) => (
                        <span key={ref} className="text-xs px-1.5 py-0.5 bg-surface-3 rounded font-mono">
                          {ref}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {data.r18_concept_ids && data.r18_concept_ids.length > 0 && (
                  <div>
                    <span className="text-[10px] text-text-muted uppercase">R18 Concepts:</span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {data.r18_concept_ids.map((ref) => (
                        <span key={ref} className="text-xs px-1.5 py-0.5 bg-surface-3 rounded font-mono">
                          {ref}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Children */}
            {data.children_ids.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                  Children ({data.children_ids.length})
                </h4>
                <div className="flex flex-wrap gap-1">
                  {data.children_ids.map((childId) => (
                    <button
                      key={childId}
                      className="text-xs px-1.5 py-0.5 bg-surface-3 rounded font-mono text-accent-blue hover:underline hover:bg-accent-blue/10 transition-colors"
                      onClick={() => onNodeClick(childId)}
                    >
                      {childId.split(".").pop()}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
