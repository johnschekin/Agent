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
  fetchEdgeCaseClauseDetail,
  fetchSectionFrequency,
  fetchArticleConcepts,
  fetchCorpusQuery,
  type CorpusQueryParams,
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

export function useEdgeCaseClauseDetail(docId: string | null, category: string | null) {
  return useQuery({
    queryKey: ["edge-cases", "clause-detail", docId, category],
    queryFn: () => fetchEdgeCaseClauseDetail(docId!, category!),
    enabled: !!docId && !!category,
    staleTime: 60_000,
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
// Corpus Query Builder
// ---------------------------------------------------------------------------

export function useArticleConcepts(cohortOnly = true) {
  return useQuery({
    queryKey: ["articles", "concepts", cohortOnly],
    queryFn: () => fetchArticleConcepts(cohortOnly),
    staleTime: 300_000,
  });
}

export function useCorpusQuery() {
  return useMutation({
    mutationFn: (params: CorpusQueryParams) => fetchCorpusQuery(params),
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

// ---------------------------------------------------------------------------
// Phase 3: Bulk Section-to-Ontology-Family Linking
// ---------------------------------------------------------------------------

import {
  fetchLinks,
  fetchLink,
  fetchLinkSummary,
  unlinkLink,
  relinkLink,
  bookmarkLink,
  addLinkNote,
  deferLink,
  updateLinkRole,
  batchUnlink,
  batchRelink,
  batchBookmark,
  fetchWhyMatched,
  fetchContextStrip,
  fetchComparables,
  fetchReassignSuggestions,
  reassignLink,
  createPreview,
  fetchPreviewCandidates,
  fetchPreviewCandidatesPage,
  updateCandidateVerdicts,
  applyPreview,
  fetchLinkRules,
  fetchLinkRule,
  createLinkRule,
  updateLinkRule,
  deleteLinkRule,
  publishLinkRule,
  archiveLinkRule,
  fetchRulePins,
  createRulePin,
  deleteRulePin,
  evaluateRulePins,
  validateDslStandalone,
  fetchConflicts,
  fetchConflictPolicies,
  createConflictPolicy,
  fetchMacros,
  createMacro,
  deleteMacro,
  fetchTemplateBaselines,
  createTemplateBaseline,
  createSession,
  fetchSession,
  updateSessionCursor,
  addReviewMark,
  claimSessionBatch,
  undoLastAction,
  redoLastAction,
  fetchLinkRuns,
  fetchLinkJobs,
  fetchLinkJobStatus,
  cancelLinkJob,
  submitLinkJob,
  exportLinks,
  fetchDriftAlerts,
  fetchDriftChecks,
  fetchAnalyticsDashboard,
  fetchCalibrations,
  fetchCrossrefPeek,
  fetchCounterfactual,
  fetchEmbeddingsStats,
  computeEmbeddings,
  fetchFamilyCentroids,
  fetchStarterKits,
  fetchStarterKit,
  fetchCompoundCovenants,
  resolveCompoundCovenant,
  fetchTemplateBaselineText,
  fetchCoverageGaps,
  fetchWhyNotCoverage,
  fetchExpandTerm,
  fetchRuleAutocomplete,
  fetchQueryCount,
  fetchSemanticCandidates,
  fetchCanaryApply,
  createPreviewFromAst,
  evaluateRuleText,
  compareLinkRules,
  acknowledgeDriftAlert,
  importLabels,
  cloneLinkRule,
  promoteRule,
  lockRule,
  unlockRule,
  checkPromotionGates,
  fetchVintageHeatmap,
  type LinksQueryParams,
  type LinkRulesQueryParams,
  type TemplateBaselinesQueryParams,
} from "./api";

// ── Links ──────────────────────────────────────────────────────────────────

export function useLinks(params: LinksQueryParams = {}) {
  return useQuery({
    queryKey: ["links", "list", params],
    queryFn: () => fetchLinks(params),
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });
}

export function useLink(linkId: string | null) {
  return useQuery({
    queryKey: ["links", "detail", linkId],
    queryFn: () => fetchLink(linkId!),
    enabled: !!linkId,
    staleTime: 30_000,
  });
}

export function useLinkSummary() {
  return useQuery({
    queryKey: ["links", "summary"],
    queryFn: fetchLinkSummary,
    staleTime: 15_000,
  });
}

export function useUnlinkMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ linkId, reason }: { linkId: string; reason: string }) =>
      unlinkLink(linkId, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useRelinkMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (linkId: string) => relinkLink(linkId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useBookmarkMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (linkId: string) => bookmarkLink(linkId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useAddNoteMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ linkId, note }: { linkId: string; note: string }) =>
      addLinkNote(linkId, note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useDeferMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (linkId: string) => deferLink(linkId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useUpdateRoleMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ linkId, role }: { linkId: string; role: string }) =>
      updateLinkRole(linkId, role),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useBatchUnlinkMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ linkIds, reason }: { linkIds: string[]; reason: string }) =>
      batchUnlink(linkIds, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useBatchRelinkMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (linkIds: string[]) => batchRelink(linkIds),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useBatchBookmarkMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (linkIds: string[]) => batchBookmark(linkIds),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

// ── Why matched ────────────────────────────────────────────────────────────

export function useWhyMatched(linkId: string | null) {
  return useQuery({
    queryKey: ["links", "why-matched", linkId],
    queryFn: () => fetchWhyMatched(linkId!),
    enabled: !!linkId,
    staleTime: 60_000,
  });
}

// ── Context strip ──────────────────────────────────────────────────────────

export function useContextStrip(linkId: string | null) {
  return useQuery({
    queryKey: ["links", "context-strip", linkId],
    queryFn: () => fetchContextStrip(linkId!),
    enabled: !!linkId,
    staleTime: 60_000,
  });
}

// ── Comparables ────────────────────────────────────────────────────────────

export function useComparables(linkId: string | null) {
  return useQuery({
    queryKey: ["links", "comparables", linkId],
    queryFn: () => fetchComparables(linkId!),
    enabled: !!linkId,
    staleTime: 60_000,
  });
}

// ── Reassign ───────────────────────────────────────────────────────────────

export function useReassignSuggestions(linkId: string | null) {
  return useQuery({
    queryKey: ["links", "reassign-suggestions", linkId],
    queryFn: () => fetchReassignSuggestions(linkId!),
    enabled: !!linkId,
    staleTime: 60_000,
  });
}

export function useReassignMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ linkId, newFamilyId }: { linkId: string; newFamilyId: string }) =>
      reassignLink(linkId, newFamilyId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

// ── Preview / Apply ────────────────────────────────────────────────────────

export function useCreatePreviewMutation() {
  return useMutation({
    mutationFn: ({ familyId, ruleId }: { familyId: string; ruleId?: string }) =>
      createPreview(familyId, ruleId),
  });
}

export function usePreviewCandidates(
  previewId: string | null,
  params: {
    pageSize?: number;
    confidenceTier?: import("./types").ConfidenceTier;
    afterScore?: number | null;
    afterDocId?: string | null;
  } = {},
) {
  return useQuery({
    queryKey: ["links", "preview-candidates", previewId, params],
    queryFn: () =>
      Object.keys(params).length > 0
        ? fetchPreviewCandidatesPage(previewId!, params)
        : fetchPreviewCandidates(previewId!),
    enabled: !!previewId,
    staleTime: 30_000,
  });
}

export function useUpdateVerdictsMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      previewId,
      verdicts,
    }: {
      previewId: string;
      verdicts: { doc_id: string; section_number: string; verdict: string }[];
    }) => updateCandidateVerdicts(previewId, verdicts),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({
        queryKey: ["links", "preview-candidates", variables.previewId],
      });
    },
  });
}

export function useApplyPreviewMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      previewId,
      candidateSetHash,
    }: {
      previewId: string;
      candidateSetHash: string;
    }) => applyPreview(previewId, candidateSetHash),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

// ── Rules ──────────────────────────────────────────────────────────────────

export function useLinkRules(params: LinkRulesQueryParams = {}) {
  return useQuery({
    queryKey: ["links", "rules", params],
    queryFn: () => fetchLinkRules(params),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useLinkRule(ruleId: string | null) {
  return useQuery({
    queryKey: ["links", "rules", "detail", ruleId],
    queryFn: () => fetchLinkRule(ruleId!),
    enabled: !!ruleId,
    staleTime: 30_000,
  });
}

export function useCreateRuleMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createLinkRule,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "rules"] });
    },
  });
}

export function useUpdateRuleMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ruleId, data }: { ruleId: string; data: Record<string, unknown> }) =>
      updateLinkRule(ruleId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "rules"] });
    },
  });
}

export function useDeleteRuleMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ruleId: string) => deleteLinkRule(ruleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "rules"] });
    },
  });
}

export function usePublishRuleMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ruleId: string) => publishLinkRule(ruleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "rules"] });
    },
  });
}

export function useArchiveRuleMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ruleId: string) => archiveLinkRule(ruleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "rules"] });
    },
  });
}

// ── Rule comparison ────────────────────────────────────────────────────

export function useRuleCompareMutation() {
  return useMutation({
    mutationFn: ({ ruleIdA, ruleIdB }: { ruleIdA: string; ruleIdB: string }) =>
      compareLinkRules(ruleIdA, ruleIdB),
  });
}

// ── Rule pins ──────────────────────────────────────────────────────────────

export function useRulePins(ruleId: string | null) {
  return useQuery({
    queryKey: ["links", "rule-pins", ruleId],
    queryFn: () => fetchRulePins(ruleId!),
    enabled: !!ruleId,
    staleTime: 30_000,
  });
}

export function useCreatePinMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      ruleId,
      data,
    }: {
      ruleId: string;
      data: {
        doc_id: string;
        section_number: string;
        expected_verdict: "true_positive" | "true_negative";
        note?: string;
      };
    }) => createRulePin(ruleId, data),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["links", "rule-pins", v.ruleId] });
    },
  });
}

export function useDeletePinMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ruleId, pinId }: { ruleId: string; pinId: string }) =>
      deleteRulePin(ruleId, pinId),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["links", "rule-pins", v.ruleId] });
    },
  });
}

export function useEvaluatePinsMutation() {
  return useMutation({
    mutationFn: (ruleId: string) => evaluateRulePins(ruleId),
  });
}

// ── DSL validation ─────────────────────────────────────────────────────────

export function useValidateDslMutation() {
  return useMutation({
    mutationFn: (text: string) => validateDslStandalone(text),
  });
}

// ── Conflicts ──────────────────────────────────────────────────────────────

export function useConflicts() {
  return useQuery({
    queryKey: ["links", "conflicts"],
    queryFn: fetchConflicts,
    staleTime: 30_000,
  });
}

export function useConflictPolicies() {
  return useQuery({
    queryKey: ["links", "conflict-policies"],
    queryFn: fetchConflictPolicies,
    staleTime: 60_000,
  });
}

export function useCreateConflictPolicyMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createConflictPolicy,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "conflict-policies"] });
      qc.invalidateQueries({ queryKey: ["links", "conflicts"] });
    },
  });
}

// ── Macros ─────────────────────────────────────────────────────────────────

export function useMacros() {
  return useQuery({
    queryKey: ["links", "macros"],
    queryFn: fetchMacros,
    staleTime: 60_000,
  });
}

export function useCreateMacroMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createMacro,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "macros"] });
    },
  });
}

export function useDeleteMacroMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => deleteMacro(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "macros"] });
    },
  });
}

// ── Template baselines ─────────────────────────────────────────────────────

export function useTemplateBaselines(params: TemplateBaselinesQueryParams = {}) {
  return useQuery({
    queryKey: ["links", "template-baselines", params],
    queryFn: () => fetchTemplateBaselines(params),
    staleTime: 60_000,
  });
}

export function useCreateBaselineMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createTemplateBaseline,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "template-baselines"] });
    },
  });
}

// ── Sessions ───────────────────────────────────────────────────────────────

export function useCreateSessionMutation() {
  return useMutation({
    mutationFn: (familyId?: string) => createSession(familyId),
  });
}

export function useSession(sessionId: string | null) {
  return useQuery({
    queryKey: ["links", "session", sessionId],
    queryFn: () => fetchSession(sessionId!),
    enabled: !!sessionId,
    staleTime: 10_000,
    refetchInterval: 30_000,
  });
}

export function useUpdateCursorMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, cursor }: { sessionId: string; cursor: string }) =>
      updateSessionCursor(sessionId, cursor),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["links", "session", v.sessionId] });
    },
  });
}

export function useAddReviewMarkMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      data,
    }: {
      sessionId: string;
      data: { link_id: string; action: string; reason?: string };
    }) => addReviewMark(sessionId, data),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["links", "session", v.sessionId] });
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useClaimSessionBatchMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, batchSize }: { sessionId: string; batchSize?: number }) =>
      claimSessionBatch(sessionId, batchSize ?? 50),
    onSuccess: (_d, variables) => {
      qc.invalidateQueries({ queryKey: ["links", "session", variables.sessionId] });
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

// ── Undo / Redo ────────────────────────────────────────────────────────────

export function useUndoMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: undoLastAction,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useRedoMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: redoLastAction,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

// ── Runs ───────────────────────────────────────────────────────────────────

export function useLinkRuns(params: { familyId?: string; limit?: number } = {}) {
  return useQuery({
    queryKey: ["links", "runs", params.familyId, params.limit],
    queryFn: () => fetchLinkRuns(params),
    staleTime: 30_000,
  });
}

// ── Link Jobs ──────────────────────────────────────────────────────────────

export function useLinkJobs() {
  return useQuery({
    queryKey: ["links", "jobs"],
    queryFn: fetchLinkJobs,
    staleTime: 15_000,
    refetchInterval: 10_000,
  });
}

export function useLinkJobStatus(jobId: string | null) {
  return useQuery({
    queryKey: ["links", "job-status", jobId],
    queryFn: () => fetchLinkJobStatus(jobId!),
    enabled: !!jobId,
    staleTime: 5_000,
    refetchInterval: 3_000,
  });
}

export function useCancelLinkJobMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelLinkJob(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "jobs"] });
    },
  });
}

export function useSubmitLinkJobMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: submitLinkJob,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
      qc.invalidateQueries({ queryKey: ["links", "runs"] });
      qc.invalidateQueries({ queryKey: ["links", "analytics"] });
      qc.invalidateQueries({ queryKey: ["links", "summary"] });
      qc.invalidateQueries({ queryKey: ["links", "families"] });
      qc.invalidateQueries({ queryKey: ["links", "jobs"] });
    },
  });
}

// ── Export ──────────────────────────────────────────────────────────────────

export function useExportLinksMutation() {
  return useMutation({
    mutationFn: ({ format, familyId }: { format: string; familyId?: string }) =>
      exportLinks(format, familyId),
  });
}

// ── Drift & Analytics ──────────────────────────────────────────────────────

export function useDriftAlerts() {
  return useQuery({
    queryKey: ["links", "drift-alerts"],
    queryFn: fetchDriftAlerts,
    staleTime: 30_000,
  });
}

export function useDriftChecks() {
  return useQuery({
    queryKey: ["links", "drift-checks"],
    queryFn: fetchDriftChecks,
    staleTime: 60_000,
  });
}

export function useAnalyticsDashboard(scopeId?: string) {
  return useQuery({
    queryKey: ["links", "analytics", scopeId],
    queryFn: () => fetchAnalyticsDashboard(scopeId),
    staleTime: 30_000,
  });
}

// ── Calibrations ───────────────────────────────────────────────────────────

export function useCalibrations() {
  return useQuery({
    queryKey: ["links", "calibrations"],
    queryFn: fetchCalibrations,
    staleTime: 60_000,
  });
}

// ── Crossref peek ──────────────────────────────────────────────────────────

export function useCrossrefPeek(sectionRef: string | null) {
  return useQuery({
    queryKey: ["links", "crossref-peek", sectionRef],
    queryFn: () => fetchCrossrefPeek(sectionRef!),
    enabled: !!sectionRef,
    staleTime: 120_000,
  });
}

// ── Counterfactual ─────────────────────────────────────────────────────────

export function useCounterfactualMutation() {
  return useMutation({
    mutationFn: fetchCounterfactual,
  });
}

// ── Embeddings ─────────────────────────────────────────────────────────────

export function useEmbeddingsStats() {
  return useQuery({
    queryKey: ["links", "embeddings-stats"],
    queryFn: fetchEmbeddingsStats,
    staleTime: 60_000,
  });
}

export function useComputeEmbeddingsMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (familyId?: string) => computeEmbeddings(familyId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "embeddings-stats"] });
    },
  });
}

export function useFamilyCentroids() {
  return useQuery({
    queryKey: ["links", "centroids"],
    queryFn: fetchFamilyCentroids,
    staleTime: 60_000,
  });
}

// ── Starter kits ───────────────────────────────────────────────────────────

export function useStarterKits() {
  return useQuery({
    queryKey: ["links", "starter-kits"],
    queryFn: fetchStarterKits,
    staleTime: 120_000,
  });
}

export function useStarterKit(familyId: string | null) {
  return useQuery({
    queryKey: ["links", "starter-kits", familyId],
    queryFn: () => fetchStarterKit(familyId!),
    enabled: !!familyId,
    staleTime: 120_000,
  });
}

// ── Compound covenants ─────────────────────────────────────────────────────

export function useCompoundCovenants() {
  return useQuery({
    queryKey: ["links", "compound-covenants"],
    queryFn: fetchCompoundCovenants,
    staleTime: 30_000,
  });
}

export function useResolveCompoundMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      docId,
      sectionNumber,
      resolution,
    }: {
      docId: string;
      sectionNumber: string;
      resolution: string;
    }) => resolveCompoundCovenant(docId, sectionNumber, resolution),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "compound-covenants"] });
      qc.invalidateQueries({ queryKey: ["links", "conflicts"] });
    },
  });
}

// ── Template baseline text ─────────────────────────────────────────────────

export function useTemplateBaselineText(familyId: string | null, template: string | null) {
  return useQuery({
    queryKey: ["links", "baseline-text", familyId, template],
    queryFn: () => fetchTemplateBaselineText(familyId!, template!),
    enabled: !!familyId && !!template,
    staleTime: 120_000,
  });
}

// ---------------------------------------------------------------------------
// Phase 4: Coverage, Query, Conflicts hooks
// ---------------------------------------------------------------------------

export function useCoverageGaps(familyId?: string) {
  return useQuery({
    queryKey: ["links", "coverage-gaps", familyId],
    queryFn: () => fetchCoverageGaps(familyId),
    staleTime: 30_000,
  });
}

export function useQueryCount(familyId?: string, headingAst?: Record<string, unknown> | null) {
  return useQuery({
    queryKey: ["links", "query-count", familyId, headingAst],
    queryFn: ({ signal }) =>
      fetchQueryCount(familyId, headingAst ?? undefined, undefined, signal),
    enabled: !!headingAst,
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });
}

export function useQueryCountWithMeta(
  familyId?: string,
  headingAst?: Record<string, unknown> | null,
  metaFilters?: Record<string, unknown> | null,
  filterDsl?: string,
  scope?: {
    scopeMode?: "corpus" | "inherited";
    parentFamilyId?: string | null;
    parentRunId?: string | null;
  },
) {
  const hasFilter = !!filterDsl || !!headingAst || (!!metaFilters && Object.keys(metaFilters).length > 0);
  return useQuery({
    queryKey: ["links", "query-count", familyId, headingAst, metaFilters, filterDsl, scope?.scopeMode, scope?.parentFamilyId, scope?.parentRunId],
    queryFn: ({ signal }) =>
      fetchQueryCount(
        familyId,
        headingAst ?? undefined,
        metaFilters ?? undefined,
        signal,
        filterDsl,
        scope,
      ),
    enabled: hasFilter,
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });
}

export function useSemanticCandidates(familyId: string | null) {
  return useQuery({
    queryKey: ["links", "semantic-candidates", familyId],
    queryFn: () => fetchSemanticCandidates(familyId!),
    enabled: !!familyId,
    staleTime: 60_000,
  });
}

export function useExpandTermMutation() {
  return useMutation({
    mutationFn: (term: string) => fetchExpandTerm(term),
  });
}

export function useRuleAutocompleteMutation() {
  return useMutation({
    mutationFn: ({
      field,
      prefix,
      limit,
    }: {
      field: "heading" | "article" | "clause" | "section" | "defined_term" | "template" | "admin_agent" | "vintage" | "market" | "doc_type" | "facility_size_mm" | "macro";
      prefix?: string;
      limit?: number;
    }) => fetchRuleAutocomplete(field, prefix ?? "", limit ?? 8),
  });
}

export function useWhyNotCoverageMutation() {
  return useMutation({
    mutationFn: ({
      docId,
      ruleId,
      sectionNumber,
    }: {
      docId: string;
      ruleId: string;
      sectionNumber?: string;
    }) => fetchWhyNotCoverage(docId, ruleId, sectionNumber),
  });
}

export function useCanaryApplyMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ previewId, limit }: { previewId: string; limit?: number }) =>
      fetchCanaryApply(previewId, limit),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

export function useSaveAsRuleMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createLinkRule,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "rules"] });
    },
  });
}

export function useEvaluateTextMutation() {
  return useMutation({
    mutationFn: (data: {
      rule_ast: Record<string, unknown>;
      raw_text: string;
      heading?: string;
    }) => evaluateRuleText(data),
  });
}

export function useCreatePreviewFromAstMutation() {
  return useMutation({
    mutationFn: ({
      familyId,
      ast,
      metaFilters,
      textFields,
      filterDsl,
      resultGranularity,
      ontologyNodeId,
      scope,
    }: {
      familyId: string;
      ast: Record<string, unknown>;
      metaFilters?: Record<string, unknown>;
      textFields?: Record<string, unknown>;
      filterDsl?: string;
      resultGranularity?: "section" | "clause";
      ontologyNodeId?: string | null;
      scope?: {
        scopeMode?: "corpus" | "inherited";
        parentFamilyId?: string | null;
        parentRuleId?: string | null;
        parentRunId?: string | null;
      };
    }) =>
      createPreviewFromAst(
        familyId,
        ast,
        metaFilters,
        textFields,
        filterDsl,
        resultGranularity,
        ontologyNodeId,
        scope,
      ),
  });
}

// ── Phase 5: Acknowledge drift alert ────────────────────────────────────────

export function useAcknowledgeDriftAlertMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (alertId: string) =>
      acknowledgeDriftAlert(alertId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "drift-alerts"] });
    },
  });
}

// ── Phase 5: Import labels ──────────────────────────────────────────────────

export function useImportLabelsMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => importLabels(file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links"] });
    },
  });
}

// ── Phase 5: Clone rule ─────────────────────────────────────────────────────

export function useCloneRuleMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ruleId: string) => cloneLinkRule(ruleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "rules"] });
    },
  });
}

// ── Phase 5: Promote rule ───────────────────────────────────────────────────

export function usePromoteRuleMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ruleIdFrom, ruleIdTo }: { ruleIdFrom: string; ruleIdTo: string }) =>
      promoteRule(ruleIdFrom, ruleIdTo),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["links", "rules"] });
    },
  });
}

// ── Phase 5: Lock/unlock rule ───────────────────────────────────────────────

export function useLockRuleMutation() {
  return useMutation({
    mutationFn: (ruleId: string) => lockRule(ruleId),
  });
}

export function useUnlockRuleMutation() {
  return useMutation({
    mutationFn: (ruleId: string) => unlockRule(ruleId),
  });
}

// ── Phase 5: Promotion gates ────────────────────────────────────────────────

export function usePromotionGates(ruleId: string | null) {
  return useQuery({
    queryKey: ["links", "promotion-gates", ruleId],
    queryFn: () => checkPromotionGates(ruleId!),
    enabled: !!ruleId,
    staleTime: 30_000,
  });
}

// ── Phase 5: Vintage heatmap data ───────────────────────────────────────────

export function useVintageHeatmap(familyId?: string) {
  return useQuery({
    queryKey: ["links", "vintage-heatmap", familyId],
    queryFn: () => fetchVintageHeatmap(familyId),
    staleTime: 60_000,
  });
}
