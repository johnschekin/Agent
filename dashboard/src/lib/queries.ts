"use client";

import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import {
  fetchOverviewKpis,
  fetchDistribution,
  fetchCohortFunnel,
  fetchDocuments,
  fetchDocument,
  fetchScatter,
  fetchMetricStats,
  fetchSearchText,
  fetchDefinitionFrequency,
  fetchDefinitionVariants,
  fetchQualitySummary,
  fetchQualityAnomalies,
  fetchEdgeCases,
  fetchSectionFrequency,
  fetchHeadingDiscovery,
  fetchPatternTest,
  fetchDnaDiscovery,
  fetchCoverage,
  fetchClauseSearch,
  fetchJobs,
  fetchJobStatus,
  submitJob,
  cancelJob,
  fetchOntologyStats,
  fetchOntologyTree,
  fetchOntologyNode,
  fetchOntologySearch,
  fetchOntologyGraph,
  saveOntologyNodeNotes,
  type DocumentQueryParams,
  type ScatterQueryParams,
  type MetricStatsParams,
  type SearchTextParams,
  type DefinitionFrequencyParams,
  type QualityAnomalyParams,
  type EdgeCaseParams,
  type SectionFrequencyParams,
  type HeadingDiscoveryParams,
  type PatternTestParams,
  type DnaDiscoveryParams,
  type CoverageParams,
  type ClauseSearchParams,
  type OntologyTreeParams,
  type OntologyGraphParams,
  fetchReaderSection,
  fetchReaderDefinitions,
  fetchReaderSearch,
  fetchStrategies,
  fetchStrategy,
  fetchStrategyStats,
  fetchFeedback,
  createFeedback,
  updateFeedback,
  deleteFeedback,
  type StrategyQueryParams,
  type FeedbackQueryParams,
  fetchReviewStrategyTimeline,
  fetchReviewEvidence,
  fetchReviewCoverageHeatmap,
  fetchReviewJudgeHistory,
  fetchReviewAgentActivity,
  type ReviewEvidenceParams,
  type ReviewCoverageHeatmapParams,
  fetchReviewQueue,
  fetchHeadingClusters,
  fetchConceptsWithEvidence,
  type ReviewQueueParams,
} from "./api";

export function useOverviewKpis(cohortOnly = true) {
  return useQuery({
    queryKey: ["overview", "kpis", cohortOnly],
    queryFn: () => fetchOverviewKpis(cohortOnly),
    staleTime: 60_000,
  });
}

export function useDistribution(
  metric: string,
  bins = 25,
  cohortOnly = true
) {
  return useQuery({
    queryKey: ["distribution", metric, bins, cohortOnly],
    queryFn: () => fetchDistribution(metric, bins, cohortOnly),
    staleTime: 60_000,
  });
}

export function useCohortFunnel() {
  return useQuery({
    queryKey: ["overview", "cohort-funnel"],
    queryFn: fetchCohortFunnel,
    staleTime: 60_000,
  });
}

export function useDocuments(params: DocumentQueryParams) {
  return useQuery({
    queryKey: ["documents", params],
    queryFn: () => fetchDocuments(params),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useDocument(docId: string | null) {
  return useQuery({
    queryKey: ["document", docId],
    queryFn: () => fetchDocument(docId!),
    enabled: !!docId,
    staleTime: 120_000,
  });
}

// M13: Use keepPreviousData for proper isPlaceholderData tracking.
// Consumers should check result.isPlaceholderData to show stale indicators.

export function useScatter(params: ScatterQueryParams) {
  return useQuery({
    queryKey: ["scatter", params],
    queryFn: () => fetchScatter(params),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useMetricStats(params: MetricStatsParams) {
  return useQuery({
    queryKey: ["stats", "metric", params],
    queryFn: () => fetchMetricStats(params),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

// --- Search ---

export function useSearchText(params: SearchTextParams | null) {
  return useQuery({
    queryKey: ["search", "text", params],
    queryFn: () => fetchSearchText(params!),
    enabled: !!params?.q,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

// --- Definitions ---

export function useDefinitionFrequency(params: DefinitionFrequencyParams) {
  return useQuery({
    queryKey: ["definitions", "frequency", params],
    queryFn: () => fetchDefinitionFrequency(params),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useDefinitionVariants(
  term: string | null,
  cohortOnly = true
) {
  return useQuery({
    queryKey: ["definitions", "variants", term, cohortOnly],
    queryFn: () => fetchDefinitionVariants(term!, cohortOnly),
    enabled: !!term,
    staleTime: 120_000,
  });
}

// --- Quality ---

export function useQualitySummary() {
  return useQuery({
    queryKey: ["quality", "summary"],
    queryFn: fetchQualitySummary,
    staleTime: 60_000,
  });
}

export function useQualityAnomalies(params: QualityAnomalyParams) {
  return useQuery({
    queryKey: ["quality", "anomalies", params],
    queryFn: () => fetchQualityAnomalies(params),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

// --- Edge Cases ---

export function useEdgeCases(params: EdgeCaseParams) {
  return useQuery({
    queryKey: ["edge-cases", params],
    queryFn: () => fetchEdgeCases(params),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

// --- Section Frequency ---

export function useSectionFrequency(params: SectionFrequencyParams) {
  return useQuery({
    queryKey: ["stats", "section-frequency", params],
    queryFn: () => fetchSectionFrequency(params),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

// ---------------------------------------------------------------------------
// Phase 6: Discovery Lab (mutations — user-triggered POST operations)
// ---------------------------------------------------------------------------

export function useHeadingDiscovery() {
  return useMutation({
    mutationFn: (params: HeadingDiscoveryParams) =>
      fetchHeadingDiscovery(params),
  });
}

export function usePatternTest() {
  return useMutation({
    mutationFn: (params: PatternTestParams) => fetchPatternTest(params),
  });
}

export function useDnaDiscovery() {
  return useMutation({
    mutationFn: (params: DnaDiscoveryParams) => fetchDnaDiscovery(params),
  });
}

export function useCoverage() {
  return useMutation({
    mutationFn: (params: CoverageParams) => fetchCoverage(params),
  });
}

export function useClauseSearch() {
  return useMutation({
    mutationFn: (params: ClauseSearchParams) => fetchClauseSearch(params),
  });
}

// ---------------------------------------------------------------------------
// Phase 6: Jobs
// ---------------------------------------------------------------------------

export function useJobs(status?: string, refetchInterval?: number) {
  return useQuery({
    queryKey: ["jobs", status],
    queryFn: () => fetchJobs(status),
    staleTime: 5_000,
    refetchInterval: refetchInterval ?? 10_000,
  });
}

export function useJobStatus(jobId: string | null) {
  return useQuery({
    queryKey: ["jobs", jobId, "status"],
    queryFn: () => fetchJobStatus(jobId!),
    enabled: !!jobId,
    staleTime: 2_000,
    refetchInterval: 3_000,
  });
}

export function useSubmitJob() {
  return useMutation({
    mutationFn: ({ jobType, params }: { jobType: string; params: Record<string, unknown> }) =>
      submitJob(jobType, params),
  });
}

export function useCancelJob() {
  return useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
  });
}

// ---------------------------------------------------------------------------
// Phase 7: Ontology Explorer
// ---------------------------------------------------------------------------

export function useOntologyStats() {
  return useQuery({
    queryKey: ["ontology", "stats"],
    queryFn: fetchOntologyStats,
    staleTime: 300_000,
  });
}

export function useOntologyTree(params: OntologyTreeParams = {}) {
  return useQuery({
    queryKey: ["ontology", "tree", params],
    queryFn: () => fetchOntologyTree(params),
    staleTime: 300_000,
    placeholderData: keepPreviousData,
  });
}

export function useOntologyNode(nodeId: string | null) {
  return useQuery({
    queryKey: ["ontology", "node", nodeId],
    queryFn: () => fetchOntologyNode(nodeId!),
    enabled: !!nodeId,
    staleTime: 300_000,
  });
}

export function useOntologySearch(q: string, limit = 20) {
  return useQuery({
    queryKey: ["ontology", "search", q, limit],
    queryFn: () => fetchOntologySearch(q, limit),
    enabled: q.length >= 2,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useOntologyGraph(params: OntologyGraphParams | null) {
  return useQuery({
    queryKey: ["ontology", "graph", params],
    queryFn: () => fetchOntologyGraph(params!),
    enabled: !!params?.center,
    staleTime: 300_000,
  });
}

export function useSaveOntologyNotes() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ nodeId, notes }: { nodeId: string; notes: string }) =>
      saveOntologyNodeNotes(nodeId, notes),
    onSuccess: (_data, variables) => {
      // Optimistically update the cache so navigating away and back shows the saved note
      queryClient.setQueryData<import("./types").OntologyNodeDetail>(
        ["ontology", "node", variables.nodeId],
        (old) => old ? { ...old, notes: variables.notes } : old,
      );
    },
  });
}

// ---------------------------------------------------------------------------
// Phase 8: Credit Agreement Reader
// ---------------------------------------------------------------------------

export function useReaderSection(docId: string | null, sectionNumber: string | null) {
  return useQuery({
    queryKey: ["reader", "section", docId, sectionNumber],
    queryFn: () => fetchReaderSection(docId!, sectionNumber!),
    enabled: !!docId && !!sectionNumber,
    staleTime: 300_000,
  });
}

export function useReaderDefinitions(docId: string | null) {
  return useQuery({
    queryKey: ["reader", "definitions", docId],
    queryFn: () => fetchReaderDefinitions(docId!),
    enabled: !!docId,
    staleTime: 300_000,
  });
}

export function useReaderSearch(docId: string | null, q: string, limit = 50) {
  return useQuery({
    queryKey: ["reader", "search", docId, q, limit],
    queryFn: () => fetchReaderSearch(docId!, q, limit),
    enabled: !!docId && q.length >= 2,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

// ---------------------------------------------------------------------------
// Phase 9: Strategies + Feedback
// ---------------------------------------------------------------------------

export function useStrategies(params: StrategyQueryParams = {}) {
  return useQuery({
    queryKey: ["strategies", params],
    queryFn: () => fetchStrategies(params),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useStrategy(conceptId: string | null) {
  return useQuery({
    queryKey: ["strategy", conceptId],
    queryFn: () => fetchStrategy(conceptId!),
    enabled: !!conceptId,
    staleTime: 120_000,
  });
}

export function useStrategyStats() {
  return useQuery({
    queryKey: ["strategies", "stats"],
    queryFn: fetchStrategyStats,
    staleTime: 60_000,
  });
}

export function useFeedback(params: FeedbackQueryParams = {}) {
  return useQuery({
    queryKey: ["feedback", params],
    queryFn: () => fetchFeedback(params),
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });
}

export function useCreateFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: import("./types").FeedbackCreateRequest) =>
      createFeedback(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["feedback"] });
    },
  });
}

export function useUpdateFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: import("./types").FeedbackUpdateRequest }) =>
      updateFeedback(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["feedback"] });
    },
  });
}

export function useDeleteFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteFeedback(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["feedback"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Phase 10: Review Operations
// ---------------------------------------------------------------------------

export function useReviewStrategyTimeline(conceptId: string | null) {
  return useQuery({
    queryKey: ["review", "strategy-timeline", conceptId],
    queryFn: () => fetchReviewStrategyTimeline(conceptId!),
    enabled: !!conceptId,
    staleTime: 60_000,
  });
}

export function useReviewEvidence(params: ReviewEvidenceParams = {}) {
  return useQuery({
    queryKey: ["review", "evidence", params],
    queryFn: () => fetchReviewEvidence(params),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useReviewCoverageHeatmap(
  params: ReviewCoverageHeatmapParams = {}
) {
  return useQuery({
    queryKey: ["review", "coverage-heatmap", params],
    queryFn: () => fetchReviewCoverageHeatmap(params),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useReviewJudgeHistory(conceptId: string | null) {
  return useQuery({
    queryKey: ["review", "judge-history", conceptId],
    queryFn: () => fetchReviewJudgeHistory(conceptId!),
    enabled: !!conceptId,
    staleTime: 60_000,
  });
}

export function useReviewAgentActivity(staleMinutes = 60) {
  return useQuery({
    queryKey: ["review", "agent-activity", staleMinutes],
    queryFn: () => fetchReviewAgentActivity(staleMinutes),
    staleTime: 15_000,
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
  });
}

// ---------------------------------------------------------------------------
// Phase 11: ML & Learning
// ---------------------------------------------------------------------------

export function useReviewQueue(params: ReviewQueueParams = {}) {
  return useQuery({
    queryKey: ["ml", "review-queue", params],
    queryFn: () => fetchReviewQueue(params),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useHeadingClusters(conceptId: string | null) {
  return useQuery({
    queryKey: ["ml", "heading-clusters", conceptId],
    queryFn: () => fetchHeadingClusters(conceptId!),
    enabled: !!conceptId,
    staleTime: 60_000,
  });
}

export function useConceptsWithEvidence() {
  return useQuery({
    queryKey: ["ml", "concepts-with-evidence"],
    queryFn: fetchConceptsWithEvidence,
    staleTime: 60_000,
  });
}
