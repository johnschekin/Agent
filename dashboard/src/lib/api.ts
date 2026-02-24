const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// --- Health ---
export function fetchHealth() {
  return fetchJson<import("./types").HealthResponse>("/api/health");
}

// --- Overview ---
export function fetchOverviewKpis(cohortOnly = false) {
  const params = new URLSearchParams({
    cohort_only: String(cohortOnly),
  });
  return fetchJson<import("./types").OverviewKpis>(
    `/api/overview/kpis?${params}`
  );
}

export function fetchDistribution(
  metric: string,
  bins = 25,
  cohortOnly = true
) {
  const params = new URLSearchParams({
    metric,
    bins: String(bins),
    cohort_only: String(cohortOnly),
  });
  return fetchJson<import("./types").Distribution>(
    `/api/overview/distributions?${params}`
  );
}

export function fetchCohortFunnel() {
  return fetchJson<import("./types").CohortFunnel>("/api/overview/cohort-funnel");
}

// --- Documents ---
export interface DocumentQueryParams {
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortDir?: "asc" | "desc";
  search?: string;
  docType?: string;
  marketSegment?: string;
  cohortOnly?: boolean;
}

export function fetchDocuments(params: DocumentQueryParams = {}) {
  const searchParams = new URLSearchParams();
  if (params.page !== undefined) searchParams.set("page", String(params.page));
  if (params.pageSize !== undefined)
    searchParams.set("page_size", String(params.pageSize));
  if (params.sortBy) searchParams.set("sort_by", params.sortBy);
  if (params.sortDir) searchParams.set("sort_dir", params.sortDir);
  if (params.search) searchParams.set("search", params.search);
  if (params.docType) searchParams.set("doc_type", params.docType);
  if (params.marketSegment)
    searchParams.set("market_segment", params.marketSegment);
  if (params.cohortOnly) searchParams.set("cohort_only", "true");
  return fetchJson<import("./types").DocumentsResponse>(
    `/api/documents?${searchParams}`
  );
}

export function fetchDocument(docId: string) {
  return fetchJson<import("./types").DocumentDetail>(
    `/api/documents/${encodeURIComponent(docId)}`
  );
}

// --- Scatter ---
export interface ScatterQueryParams {
  x?: string;
  y?: string;
  color?: string;
  cohortOnly?: boolean;
  limit?: number;
}

export function fetchScatter(params: ScatterQueryParams = {}) {
  const sp = new URLSearchParams();
  if (params.x) sp.set("x", params.x);
  if (params.y) sp.set("y", params.y);
  if (params.color) sp.set("color", params.color);
  if (params.cohortOnly) sp.set("cohort_only", "true");
  if (params.limit !== undefined) sp.set("limit", String(params.limit));
  return fetchJson<import("./types").ScatterResponse>(`/api/scatter?${sp}`);
}

// --- Stats ---
export interface MetricStatsParams {
  metric?: string;
  groupBy?: string;
  cohortOnly?: boolean;
  bins?: number;
}

export function fetchMetricStats(params: MetricStatsParams = {}) {
  const sp = new URLSearchParams();
  if (params.metric) sp.set("metric", params.metric);
  if (params.groupBy) sp.set("group_by", params.groupBy);
  if (params.cohortOnly) sp.set("cohort_only", "true");
  if (params.bins !== undefined) sp.set("bins", String(params.bins));
  return fetchJson<import("./types").MetricStatsResponse>(`/api/stats/metric?${sp}`);
}

// --- Search (KWIC) ---
export interface SearchTextParams {
  q: string;
  contextChars?: number;
  maxResults?: number;
  cohortOnly?: boolean;
}

export function fetchSearchText(params: SearchTextParams) {
  const sp = new URLSearchParams({ q: params.q });
  if (params.contextChars !== undefined)
    sp.set("context_chars", String(params.contextChars));
  if (params.maxResults !== undefined)
    sp.set("max_results", String(params.maxResults));
  if (params.cohortOnly !== undefined)
    sp.set("cohort_only", String(params.cohortOnly));
  return fetchJson<import("./types").SearchTextResponse>(
    `/api/search/text?${sp}`
  );
}

// --- Definitions ---
export interface DefinitionFrequencyParams {
  termPattern?: string;
  cohortOnly?: boolean;
  limit?: number;
}

export function fetchDefinitionFrequency(
  params: DefinitionFrequencyParams = {}
) {
  const sp = new URLSearchParams();
  if (params.termPattern) sp.set("term_pattern", params.termPattern);
  if (params.cohortOnly !== undefined)
    sp.set("cohort_only", String(params.cohortOnly));
  if (params.limit !== undefined) sp.set("limit", String(params.limit));
  return fetchJson<import("./types").DefinitionFrequencyResponse>(
    `/api/definitions/frequency?${sp}`
  );
}

export function fetchDefinitionVariants(
  term: string,
  cohortOnly = true,
  limit = 50
) {
  const sp = new URLSearchParams({
    cohort_only: String(cohortOnly),
    limit: String(limit),
  });
  return fetchJson<import("./types").DefinitionVariantsResponse>(
    `/api/definitions/variants/${encodeURIComponent(term)}?${sp}`
  );
}

// --- Quality ---
export function fetchQualitySummary() {
  return fetchJson<import("./types").QualitySummary>("/api/quality/summary");
}

export interface QualityAnomalyParams {
  anomalyType?: string;
  page?: number;
  pageSize?: number;
}

export function fetchQualityAnomalies(params: QualityAnomalyParams = {}) {
  const sp = new URLSearchParams();
  if (params.anomalyType) sp.set("anomaly_type", params.anomalyType);
  if (params.page !== undefined) sp.set("page", String(params.page));
  if (params.pageSize !== undefined) sp.set("page_size", String(params.pageSize));
  return fetchJson<import("./types").QualityAnomaliesResponse>(
    `/api/quality/anomalies?${sp}`
  );
}

// --- Edge Cases ---
export interface EdgeCaseParams {
  category?: string;
  page?: number;
  pageSize?: number;
  cohortOnly?: boolean;
}

export function fetchEdgeCases(params: EdgeCaseParams = {}) {
  const sp = new URLSearchParams();
  if (params.category) sp.set("category", params.category);
  if (params.page !== undefined) sp.set("page", String(params.page));
  if (params.pageSize !== undefined) sp.set("page_size", String(params.pageSize));
  if (params.cohortOnly !== undefined) sp.set("cohort_only", String(params.cohortOnly));
  return fetchJson<import("./types").EdgeCasesResponse>(`/api/edge-cases?${sp}`);
}

// --- Section Frequency ---
export interface SectionFrequencyParams {
  cohortOnly?: boolean;
  minPresence?: number;
  limit?: number;
}

export function fetchSectionFrequency(params: SectionFrequencyParams = {}) {
  const sp = new URLSearchParams();
  if (params.cohortOnly !== undefined) sp.set("cohort_only", String(params.cohortOnly));
  if (params.minPresence !== undefined)
    sp.set("min_presence", String(params.minPresence));
  if (params.limit !== undefined) sp.set("limit", String(params.limit));
  return fetchJson<import("./types").SectionFrequencyResponse>(
    `/api/stats/section-frequency?${sp}`
  );
}

// ---------------------------------------------------------------------------
// Phase 6: Discovery Lab
// ---------------------------------------------------------------------------

// --- Heading Discovery ---
export interface HeadingDiscoveryParams {
  searchPattern?: string;
  articleMin?: number;
  articleMax?: number;
  minFrequency?: number;
  limit?: number;
  cohortOnly?: boolean;
}

export function fetchHeadingDiscovery(params: HeadingDiscoveryParams = {}) {
  return fetchJson<import("./types").HeadingDiscoveryResponse>(
    "/api/lab/heading-discover",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        search_pattern: params.searchPattern || undefined,
        article_min: params.articleMin,
        article_max: params.articleMax,
        min_frequency: params.minFrequency ?? 2,
        limit: params.limit ?? 200,
        cohort_only: params.cohortOnly ?? true,
      }),
    }
  );
}

// --- Pattern Testing ---
export interface PatternTestParams {
  headingPatterns: string[];
  keywordPatterns?: string[];
  sectionFilter?: string;
  sampleSize?: number;
  cohortOnly?: boolean;
}

export function fetchPatternTest(params: PatternTestParams) {
  return fetchJson<import("./types").PatternTestResponse>(
    "/api/lab/pattern-test",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        heading_patterns: params.headingPatterns,
        keyword_patterns: params.keywordPatterns || [],
        section_filter: params.sectionFilter || undefined,
        sample_size: params.sampleSize ?? 500,
        cohort_only: params.cohortOnly ?? true,
      }),
    }
  );
}

// --- DNA Discovery ---
export interface DnaDiscoveryParams {
  positiveHeadingPattern: string;
  topK?: number;
  minSectionRate?: number;
  maxBackgroundRate?: number;
  ngramMin?: number;
  ngramMax?: number;
  cohortOnly?: boolean;
}

export function fetchDnaDiscovery(params: DnaDiscoveryParams) {
  return fetchJson<import("./types").DnaDiscoveryResponse>(
    "/api/lab/dna-discover",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        positive_heading_pattern: params.positiveHeadingPattern,
        top_k: params.topK ?? 30,
        min_section_rate: params.minSectionRate ?? 0.2,
        max_background_rate: params.maxBackgroundRate ?? 0.05,
        ngram_min: params.ngramMin ?? 1,
        ngram_max: params.ngramMax ?? 3,
        cohort_only: params.cohortOnly ?? true,
      }),
    }
  );
}

// --- Coverage Analysis ---
export interface CoverageParams {
  headingPatterns: string[];
  keywordPatterns?: string[];
  groupBy: string;
  sampleSize?: number;
  cohortOnly?: boolean;
}

export function fetchCoverage(params: CoverageParams) {
  return fetchJson<import("./types").CoverageResponse>(
    "/api/lab/coverage",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        heading_patterns: params.headingPatterns,
        keyword_patterns: params.keywordPatterns || [],
        group_by: params.groupBy,
        sample_size: params.sampleSize ?? 0,
        cohort_only: params.cohortOnly ?? true,
      }),
    }
  );
}

// --- Clause Search ---
export interface ClauseSearchParams {
  sectionNumber?: string;
  keywords?: string[];
  headingPattern?: string;
  minDepth?: number;
  maxDepth?: number;
  limit?: number;
  cohortOnly?: boolean;
}

export function fetchClauseSearch(params: ClauseSearchParams = {}) {
  return fetchJson<import("./types").ClauseSearchResponse>(
    "/api/lab/clause-search",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        section_number: params.sectionNumber || undefined,
        keywords: params.keywords || [],
        heading_pattern: params.headingPattern || undefined,
        min_depth: params.minDepth ?? 1,
        max_depth: params.maxDepth ?? 6,
        limit: params.limit ?? 200,
        cohort_only: params.cohortOnly ?? true,
      }),
    }
  );
}

// ---------------------------------------------------------------------------
// Phase 6: Jobs
// ---------------------------------------------------------------------------

export function fetchJobs(status?: string) {
  const sp = new URLSearchParams();
  if (status) sp.set("status", status);
  return fetchJson<import("./types").JobListResponse>(
    `/api/jobs?${sp}`
  );
}

export function fetchJobStatus(jobId: string) {
  return fetchJson<import("./types").Job>(
    `/api/jobs/${encodeURIComponent(jobId)}/status`
  );
}

export function submitJob(jobType: string, params: Record<string, unknown>) {
  return fetchJson<import("./types").JobSubmitResponse>(
    "/api/jobs/submit",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_type: jobType, params }),
    }
  );
}

export function cancelJob(jobId: string) {
  return fetchJson<{ cancelled: boolean }>(
    `/api/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" }
  );
}

// ---------------------------------------------------------------------------
// Phase 7: Ontology Explorer
// ---------------------------------------------------------------------------

export function fetchOntologyStats() {
  return fetchJson<import("./types").OntologyStatsResponse>(
    "/api/ontology/stats"
  );
}

export interface OntologyTreeParams {
  domain?: string;
  type?: string;
  levelMax?: number;
  search?: string;
}

export function fetchOntologyTree(params: OntologyTreeParams = {}) {
  const sp = new URLSearchParams();
  if (params.domain) sp.set("domain", params.domain);
  if (params.type) sp.set("type", params.type);
  if (params.levelMax !== undefined) sp.set("level_max", String(params.levelMax));
  if (params.search) sp.set("search", params.search);
  return fetchJson<import("./types").OntologyTreeResponse>(
    `/api/ontology/tree?${sp}`
  );
}

export function fetchOntologyNode(nodeId: string) {
  return fetchJson<import("./types").OntologyNodeDetail>(
    `/api/ontology/nodes/${encodeURIComponent(nodeId)}`
  );
}

export function saveOntologyNodeNotes(nodeId: string, notes: string) {
  return fetchJson<{ node_id: string; notes: string }>(
    `/api/ontology/nodes/${encodeURIComponent(nodeId)}/notes`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    }
  );
}

export interface OntologyEdgeParams {
  sourceId?: string;
  targetId?: string;
  edgeType?: string;
  limit?: number;
}

export function fetchOntologyEdges(params: OntologyEdgeParams = {}) {
  const sp = new URLSearchParams();
  if (params.sourceId) sp.set("source_id", params.sourceId);
  if (params.targetId) sp.set("target_id", params.targetId);
  if (params.edgeType) sp.set("edge_type", params.edgeType);
  if (params.limit !== undefined) sp.set("limit", String(params.limit));
  return fetchJson<import("./types").OntologyEdgesResponse>(
    `/api/ontology/edges?${sp}`
  );
}

export function fetchOntologySearch(q: string, limit = 20) {
  const sp = new URLSearchParams({ q, limit: String(limit) });
  return fetchJson<import("./types").OntologySearchResponse>(
    `/api/ontology/search?${sp}`
  );
}

export interface OntologyGraphParams {
  center: string;
  depth?: number;
  maxNodes?: number;
}

export function fetchOntologyGraph(params: OntologyGraphParams) {
  const sp = new URLSearchParams({ center: params.center });
  if (params.depth !== undefined) sp.set("depth", String(params.depth));
  if (params.maxNodes !== undefined) sp.set("max_nodes", String(params.maxNodes));
  return fetchJson<import("./types").OntologyGraphResponse>(
    `/api/ontology/graph?${sp}`
  );
}

// ---------------------------------------------------------------------------
// Phase 8: Credit Agreement Reader
// ---------------------------------------------------------------------------

export function fetchReaderSection(docId: string, sectionNumber: string) {
  return fetchJson<import("./types").ReaderSectionDetail>(
    `/api/reader/${encodeURIComponent(docId)}/section/${encodeURIComponent(sectionNumber)}`
  );
}

export function fetchReaderDefinitions(docId: string) {
  return fetchJson<import("./types").ReaderDefinitionsResponse>(
    `/api/reader/${encodeURIComponent(docId)}/definitions`
  );
}

export function fetchReaderSearch(docId: string, q: string, limit = 50) {
  const sp = new URLSearchParams({ q, limit: String(limit) });
  return fetchJson<import("./types").ReaderSearchResponse>(
    `/api/reader/${encodeURIComponent(docId)}/search?${sp}`
  );
}

// ---------------------------------------------------------------------------
// Phase 9: Strategies + Feedback
// ---------------------------------------------------------------------------

export interface StrategyQueryParams {
  family?: string;
  validationStatus?: string;
  sortBy?: string;
  sortDir?: "asc" | "desc";
}

export function fetchStrategies(params: StrategyQueryParams = {}) {
  const sp = new URLSearchParams();
  if (params.family) sp.set("family", params.family);
  if (params.validationStatus) sp.set("validation_status", params.validationStatus);
  if (params.sortBy) sp.set("sort_by", params.sortBy);
  if (params.sortDir) sp.set("sort_dir", params.sortDir);
  return fetchJson<import("./types").StrategyListResponse>(
    `/api/strategies?${sp}`
  );
}

export function fetchStrategy(conceptId: string) {
  return fetchJson<import("./types").StrategyDetail>(
    `/api/strategies/${encodeURIComponent(conceptId)}`
  );
}

export function fetchStrategyStats() {
  return fetchJson<import("./types").StrategyStatsResponse>(
    "/api/strategies/stats"
  );
}

export interface FeedbackQueryParams {
  status?: string;
  type?: string;
  priority?: string;
  conceptId?: string;
}

export function fetchFeedback(params: FeedbackQueryParams = {}) {
  const sp = new URLSearchParams();
  if (params.status) sp.set("status", params.status);
  if (params.type) sp.set("type", params.type);
  if (params.priority) sp.set("priority", params.priority);
  if (params.conceptId) sp.set("concept_id", params.conceptId);
  return fetchJson<import("./types").FeedbackListResponse>(
    `/api/feedback?${sp}`
  );
}

export function createFeedback(data: import("./types").FeedbackCreateRequest) {
  return fetchJson<import("./types").FeedbackItem>(
    "/api/feedback",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );
}

export function updateFeedback(
  id: string,
  data: import("./types").FeedbackUpdateRequest
) {
  return fetchJson<import("./types").FeedbackItem>(
    `/api/feedback/${encodeURIComponent(id)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );
}

export function deleteFeedback(id: string) {
  return fetchJson<{ deleted: boolean }>(
    `/api/feedback/${encodeURIComponent(id)}`,
    { method: "DELETE" }
  );
}

// ---------------------------------------------------------------------------
// Phase 10: Review Operations
// ---------------------------------------------------------------------------

export function fetchReviewStrategyTimeline(conceptId: string) {
  return fetchJson<import("./types").ReviewStrategyTimelineResponse>(
    `/api/review/strategy-timeline/${encodeURIComponent(conceptId)}`
  );
}

export interface ReviewEvidenceParams {
  conceptId?: string;
  templateFamily?: string;
  recordType?: string;
  limit?: number;
  offset?: number;
}

export function fetchReviewEvidence(params: ReviewEvidenceParams = {}) {
  const sp = new URLSearchParams();
  if (params.conceptId) sp.set("concept_id", params.conceptId);
  if (params.templateFamily) sp.set("template_family", params.templateFamily);
  if (params.recordType) sp.set("record_type", params.recordType);
  if (params.limit !== undefined) sp.set("limit", String(params.limit));
  if (params.offset !== undefined) sp.set("offset", String(params.offset));
  return fetchJson<import("./types").ReviewEvidenceResponse>(
    `/api/review/evidence?${sp}`
  );
}

export interface ReviewCoverageHeatmapParams {
  conceptId?: string;
  topConcepts?: number;
}

export function fetchReviewCoverageHeatmap(
  params: ReviewCoverageHeatmapParams = {}
) {
  const sp = new URLSearchParams();
  if (params.conceptId) sp.set("concept_id", params.conceptId);
  if (params.topConcepts !== undefined) {
    sp.set("top_concepts", String(params.topConcepts));
  }
  return fetchJson<import("./types").ReviewCoverageHeatmapResponse>(
    `/api/review/coverage-heatmap?${sp}`
  );
}

export function fetchReviewJudgeHistory(conceptId: string) {
  return fetchJson<import("./types").ReviewJudgeHistoryResponse>(
    `/api/review/judge/${encodeURIComponent(conceptId)}/history`
  );
}

export function fetchReviewAgentActivity(staleMinutes = 60) {
  const sp = new URLSearchParams({ stale_minutes: String(staleMinutes) });
  return fetchJson<import("./types").ReviewAgentActivityResponse>(
    `/api/review/agent-activity?${sp}`
  );
}

// ---------------------------------------------------------------------------
// Phase 11: ML & Learning
// ---------------------------------------------------------------------------

export interface ReviewQueueParams {
  priority?: string;
  conceptId?: string;
  templateFamily?: string;
  limit?: number;
  offset?: number;
}

export function fetchReviewQueue(params: ReviewQueueParams = {}) {
  const sp = new URLSearchParams();
  if (params.priority) sp.set("priority", params.priority);
  if (params.conceptId) sp.set("concept_id", params.conceptId);
  if (params.templateFamily) sp.set("template_family", params.templateFamily);
  if (params.limit !== undefined) sp.set("limit", String(params.limit));
  if (params.offset !== undefined) sp.set("offset", String(params.offset));
  return fetchJson<import("./types").ReviewQueueResponse>(
    `/api/ml/review-queue?${sp}`
  );
}

export function fetchHeadingClusters(conceptId: string) {
  const sp = new URLSearchParams({ concept_id: conceptId });
  return fetchJson<import("./types").HeadingClustersResponse>(
    `/api/ml/heading-clusters?${sp}`
  );
}

export function fetchConceptsWithEvidence() {
  return fetchJson<import("./types").ConceptsWithEvidenceResponse>(
    "/api/ml/concepts-with-evidence"
  );
}
