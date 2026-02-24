"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ChartCard } from "@/components/ui/ChartCard";
import { OntologyTree } from "@/components/ontology/OntologyTree";
import { OntologyNodeDetail } from "@/components/ontology/OntologyNodeDetail";
import { OntologyGraph } from "@/components/ontology/OntologyGraph";
import { useOntologyStats, useOntologyTree } from "@/lib/queries";
import { formatNumber } from "@/lib/formatters";
import { cn, SELECT_CLASS } from "@/lib/cn";

type ViewMode = "tree" | "graph";

export default function OntologyPage() {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("tree");
  const [graphCenterId, setGraphCenterId] = useState<string | null>(null);
  const [graphDepth, setGraphDepth] = useState(2);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [domainFilter, setDomainFilter] = useState("");

  // M1 RT5 FIX: Debounce search to avoid API call per keystroke
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    debounceRef.current = setTimeout(() => setDebouncedSearch(searchInput), 300);
    return () => clearTimeout(debounceRef.current);
  }, [searchInput]);

  const stats = useOntologyStats();
  const tree = useOntologyTree({
    domain: domainFilter || undefined,
    search: debouncedSearch || undefined,
  });

  const handleSelectNode = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
  }, []);

  const handleCloseDetail = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  const handleShowGraph = useCallback((nodeId: string) => {
    setGraphCenterId(nodeId);
    setViewMode("graph");
  }, []);

  const handleGraphNodeClick = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
  }, []);

  // Extract domain names from stats for filter dropdown
  const domainOptions = useMemo(() => {
    if (!stats.data?.domain_breakdown) return [];
    return stats.data.domain_breakdown.map((d) => ({
      id: d.domain_id,
      name: d.domain_name,
    }));
  }, [stats.data]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-border">
        <div>
          <h2 className="text-xl font-semibold text-text-primary">Ontology Explorer</h2>
          {stats.data && (
            <p className="text-sm text-text-secondary mt-0.5">
              v{stats.data.version} — {stats.data.production_date}
            </p>
          )}
        </div>
        {/* View mode toggle */}
        <div className="flex gap-1.5">
          <button
            onClick={() => setViewMode("tree")}
            className={cn(
              "px-2.5 py-1 rounded-sm text-xs font-medium transition-colors",
              viewMode === "tree"
                ? "bg-accent-blue/20 text-accent-blue"
                : "bg-surface-tertiary text-text-muted hover:text-text-secondary border border-border"
            )}
          >
            Tree
          </button>
          <button
            onClick={() => {
              setViewMode("graph");
              if (!graphCenterId && selectedNodeId) {
                setGraphCenterId(selectedNodeId);
              }
            }}
            className={cn(
              "px-2.5 py-1 rounded-sm text-xs font-medium transition-colors",
              viewMode === "graph"
                ? "bg-accent-blue/20 text-accent-blue"
                : "bg-surface-tertiary text-text-muted hover:text-text-secondary border border-border"
            )}
          >
            Graph
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="px-6 pt-4">
        <KpiCardGrid className="mb-0">
          <KpiCard
            title="Nodes"
            value={stats.data ? formatNumber(stats.data.node_count) : "\u2014"}
            color="blue"
          />
          <KpiCard
            title="Edges"
            value={stats.data ? formatNumber(stats.data.edge_count) : "\u2014"}
            color="green"
          />
          <KpiCard
            title="Domains"
            value={stats.data ? formatNumber(stats.data.domain_count) : "\u2014"}
          />
          <KpiCard
            title="Families"
            value={stats.data ? formatNumber(stats.data.family_count) : "\u2014"}
          />
          <KpiCard
            title="Concepts"
            value={stats.data ? formatNumber(stats.data.concept_count) : "\u2014"}
            color="orange"
          />
          <KpiCard
            title="Parameters"
            value={stats.data ? formatNumber(stats.data.parameter_count) : "\u2014"}
            color="red"
          />
        </KpiCardGrid>
      </div>

      {/* Main content area */}
      <div
        className="flex-1 min-h-0 flex px-6 pb-6 gap-4"
        style={{ marginRight: selectedNodeId ? 480 : 0, transition: "margin-right 200ms" }}
      >
        {/* Left sidebar: tree */}
        <div className="w-[320px] flex-shrink-0 flex flex-col bg-surface-secondary border border-border rounded overflow-hidden">
          {/* Search + filter */}
          <div className="p-2 space-y-2 border-b border-border">
            <input
              type="text"
              placeholder="Search nodes..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className={cn(SELECT_CLASS, "w-full")}
              aria-label="Search ontology nodes"
            />
            <select
              value={domainFilter}
              onChange={(e) => setDomainFilter(e.target.value)}
              className={cn(SELECT_CLASS, "w-full")}
              aria-label="Filter by domain"
            >
              <option value="">All Domains</option>
              {domainOptions.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>

          {/* Tree content */}
          {tree.isLoading && !tree.data && (
            <div className="p-4">
              <LoadingState message="Loading tree..." />
            </div>
          )}
          {tree.error && !tree.data && (
            <div className="p-4">
              <EmptyState title="Failed to load" message="Check the API server." />
            </div>
          )}
          {tree.data && (
            <OntologyTree
              roots={tree.data.roots}
              selectedId={selectedNodeId}
              onSelectNode={handleSelectNode}
              searchQuery={searchInput}
            />
          )}
        </div>

        {/* Right: main content */}
        <div className="flex-1 min-w-0 bg-surface-secondary border border-border rounded overflow-hidden flex flex-col">
          {viewMode === "tree" ? (
            // Tree mode — show welcome / stats
            <div className="flex-1 flex items-center justify-center p-8">
              {!selectedNodeId ? (
                <EmptyState
                  title="Explore the ontology"
                  message="Select a node in the tree to view its details, or switch to Graph mode to visualize relationships."
                />
              ) : (
                <div className="text-center space-y-3">
                  <p className="text-sm text-text-secondary">
                    Node <span className="font-mono text-text-primary">{selectedNodeId}</span> selected.
                  </p>
                  <p className="text-xs text-text-muted">
                    View details in the panel on the right, or click "Show Graph" to visualize its neighborhood.
                  </p>
                </div>
              )}
            </div>
          ) : (
            // Graph mode
            graphCenterId ? (
              <OntologyGraph
                centerId={graphCenterId}
                depth={graphDepth}
                onDepthChange={setGraphDepth}
                onNodeClick={handleGraphNodeClick}
              />
            ) : (
              <div className="flex-1 flex items-center justify-center p-8">
                <EmptyState
                  title="No graph center"
                  message="Select a node from the tree to center the graph visualization."
                />
              </div>
            )
          )}
        </div>
      </div>

      {/* Detail panel */}
      <OntologyNodeDetail
        nodeId={selectedNodeId}
        onClose={handleCloseDetail}
        onNodeClick={handleSelectNode}
        onShowGraph={handleShowGraph}
      />
    </div>
  );
}
