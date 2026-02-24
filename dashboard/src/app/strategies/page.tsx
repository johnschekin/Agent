"use client";

import { useState, useCallback, useMemo } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { StrategyTable } from "@/components/strategy/StrategyTable";
import { StrategyDetailPanel } from "@/components/strategy/StrategyDetailPanel";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useStrategies } from "@/lib/queries";
import type { StrategySummary } from "@/lib/types";
import type { SortingState, OnChangeFn } from "@tanstack/react-table";
import { cn, SELECT_CLASS } from "@/lib/cn";

export default function StrategiesPage() {
  const [familyFilter, setFamilyFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([
    { id: "concept_name", desc: false },
  ]);
  const [selectedConceptId, setSelectedConceptId] = useState<string | null>(
    null
  );

  const sortBy = sorting.length > 0 ? sorting[0].id : "concept_name";
  const sortDir = sorting.length > 0 && sorting[0].desc ? "desc" : "asc";

  const { data, isLoading, error } = useStrategies({
    family: familyFilter || undefined,
    validationStatus: statusFilter || undefined,
    sortBy,
    sortDir,
  });

  // Client-side search filter
  const filteredStrategies = useMemo(() => {
    if (!data?.strategies) return [];
    if (!search) return data.strategies;
    const q = search.toLowerCase();
    return data.strategies.filter(
      (s) =>
        s.concept_name.toLowerCase().includes(q) ||
        s.concept_id.toLowerCase().includes(q)
    );
  }, [data?.strategies, search]);

  const handleRowClick = useCallback((row: StrategySummary) => {
    setSelectedConceptId((prev) =>
      prev === row.concept_id ? null : row.concept_id
    );
  }, []);

  const handleSortingChange: OnChangeFn<SortingState> = useCallback(
    (updater) => {
      setSorting(updater);
    },
    []
  );

  if (error) {
    return (
      <ViewContainer title="Strategy Manager">
        <EmptyState
          title="Strategies Unavailable"
          message="Could not load strategies. Make sure the API server is running."
        />
      </ViewContainer>
    );
  }

  return (
    <ViewContainer
      title="Strategy Manager"
      subtitle={
        data ? `${data.total} strategies in ${data.families.length} families` : undefined
      }
    >
      {/* Filters */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-border flex-wrap">
        <input
          type="text"
          placeholder="Search concepts..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className={cn(SELECT_CLASS, "w-[200px]")}
        />
        <select
          value={familyFilter}
          onChange={(e) => setFamilyFilter(e.target.value)}
          className={cn(SELECT_CLASS, "w-[160px]")}
        >
          <option value="">All families</option>
          {data?.families.map((f) => (
            <option key={f.family} value={f.family}>
              {f.family} ({f.count})
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={cn(SELECT_CLASS, "w-[180px]")}
        >
          <option value="">All statuses</option>
          {data?.validation_statuses.map((s) => (
            <option key={s.status} value={s.status}>
              {s.status.replace("_", " ")} ({s.count})
            </option>
          ))}
        </select>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0">
        {isLoading && !data ? (
          <div className="flex items-center justify-center p-8">
            <LoadingState message="Loading strategies..." />
          </div>
        ) : (
          <StrategyTable
            strategies={filteredStrategies}
            sorting={sorting}
            onSortingChange={handleSortingChange}
            onRowClick={handleRowClick}
            selectedConceptId={selectedConceptId}
          />
        )}
      </div>

      {/* Detail panel */}
      <StrategyDetailPanel
        conceptId={selectedConceptId}
        onClose={() => setSelectedConceptId(null)}
      />
    </ViewContainer>
  );
}
