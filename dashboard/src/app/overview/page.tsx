"use client";

import { useState } from "react";
import { ViewContainer } from "@/components/layout/ViewContainer";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { ChartCard } from "@/components/ui/ChartCard";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { HistogramChart } from "@/components/charts/HistogramChart";
import { DonutChart } from "@/components/charts/DonutChart";
import { useOverviewKpis, useDistribution, useCohortFunnel } from "@/lib/queries";
import { formatNumber, formatPercent, formatCurrencyMM } from "@/lib/formatters";
import { CohortFunnel } from "./CohortFunnel";

export default function OverviewPage() {
  const [cohortOnly, setCohortOnly] = useState(true);

  const kpis = useOverviewKpis(cohortOnly);
  const docTypeDist = useDistribution("doc_type", 25, cohortOnly);
  const segmentDist = useDistribution("market_segment", 25, cohortOnly);
  const wordCountDist = useDistribution("word_count", 25, cohortOnly);
  const defCountDist = useDistribution("definition_count", 25, cohortOnly);
  const facilityDist = useDistribution("facility_size_mm", 25, cohortOnly);
  const sectionDist = useDistribution("section_count", 25, cohortOnly);
  const funnel = useCohortFunnel();

  if (kpis.isLoading) return <LoadingState message="Loading corpus data..." />;
  if (kpis.error) {
    return (
      <ViewContainer title="Corpus Overview">
        <EmptyState
          title="Corpus Not Available"
          message="Could not connect to the corpus index. Make sure the API server is running and corpus.duckdb exists."
        />
      </ViewContainer>
    );
  }

  const k = kpis.data!;

  return (
    <ViewContainer title="Corpus Overview" subtitle={`Schema v${k.schema_version}`}>
      {/* Cohort Toggle */}
      <div className="flex items-center gap-3 mb-4">
        <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={cohortOnly}
            onChange={(e) => setCohortOnly(e.target.checked)}
            className="accent-accent-blue"
          />
          Cohort Only
        </label>
      </div>

      {/* KPI Cards */}
      <KpiCardGrid>
        <KpiCard
          title={cohortOnly ? "Cohort Documents" : "Total Documents"}
          value={formatNumber(k.total_docs)}
          subtitle={cohortOnly ? "Leveraged CAs" : undefined}
          color="blue"
        />
        {!cohortOnly && (
          <KpiCard
            title="Cohort Documents"
            value={formatNumber(k.cohort_docs)}
            subtitle="Leveraged CAs"
            color="green"
          />
        )}
        <KpiCard
          title="Parse Success"
          value={formatPercent(k.parse_success_rate)}
          color="green"
        />
        <KpiCard
          title="Total Sections"
          value={formatNumber(k.total_sections)}
        />
        <KpiCard
          title="Total Definitions"
          value={formatNumber(k.total_definitions)}
        />
        <KpiCard
          title="Total Clauses"
          value={formatNumber(k.total_clauses)}
        />
      </KpiCardGrid>

      {/* Cohort Funnel */}
      {funnel.data && (
        <div className="mb-6">
          <ChartCard title="Cohort Funnel" height="auto">
            <CohortFunnel data={funnel.data} />
          </ChartCard>
        </div>
      )}

      {/* Distribution Charts - Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <ChartCard title="Document Type Distribution">
          {docTypeDist.error ? (
            <EmptyState title="Failed to load" message="Distribution query failed" />
          ) : docTypeDist.data?.categories ? (
            <DonutChart data={docTypeDist.data.categories} />
          ) : (
            <LoadingState />
          )}
        </ChartCard>
        <ChartCard title="Market Segment Distribution">
          {segmentDist.error ? (
            <EmptyState title="Failed to load" message="Distribution query failed" />
          ) : segmentDist.data?.categories ? (
            <DonutChart data={segmentDist.data.categories} />
          ) : (
            <LoadingState />
          )}
        </ChartCard>
      </div>

      {/* Distribution Charts - Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <ChartCard title="Word Count Distribution">
          {wordCountDist.error ? (
            <EmptyState title="Failed to load" message="Distribution query failed" />
          ) : wordCountDist.data?.histogram ? (
            <HistogramChart
              data={wordCountDist.data.histogram}
              xLabel="Word Count"
            />
          ) : (
            <LoadingState />
          )}
        </ChartCard>
        <ChartCard title="Definition Count Distribution">
          {defCountDist.error ? (
            <EmptyState title="Failed to load" message="Distribution query failed" />
          ) : defCountDist.data?.histogram ? (
            <HistogramChart
              data={defCountDist.data.histogram}
              xLabel="Definitions"
              color="#27AE60"
            />
          ) : (
            <LoadingState />
          )}
        </ChartCard>
      </div>

      {/* Distribution Charts - Row 3 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Facility Size Distribution (MM)">
          {facilityDist.error ? (
            <EmptyState title="Failed to load" message="Distribution query failed" />
          ) : facilityDist.data?.histogram ? (
            <HistogramChart
              data={facilityDist.data.histogram}
              xLabel="Facility Size ($M)"
              color="#D9822B"
              tooltipFormatter={(v) => formatCurrencyMM(v)}
            />
          ) : (
            <LoadingState />
          )}
        </ChartCard>
        <ChartCard title="Sections per Document">
          {sectionDist.error ? (
            <EmptyState title="Failed to load" message="Distribution query failed" />
          ) : sectionDist.data?.histogram ? (
            <HistogramChart
              data={sectionDist.data.histogram}
              xLabel="Section Count"
              color="#8F56BF"
            />
          ) : (
            <LoadingState />
          )}
        </ChartCard>
      </div>
    </ViewContainer>
  );
}
