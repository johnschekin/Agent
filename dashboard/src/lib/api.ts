const EXPLICIT_API_BASE = (process.env.NEXT_PUBLIC_API_URL || "").trim();
const IS_BROWSER = typeof window !== "undefined";
const API_BASE_FALLBACKS = EXPLICIT_API_BASE
  ? [EXPLICIT_API_BASE]
  : IS_BROWSER
    ? [""]
    : ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"];
const API_BASE = API_BASE_FALLBACKS[0] ?? "";
const LINKS_API_TOKEN =
  process.env.NEXT_PUBLIC_LINKS_API_TOKEN || "local-dev-links-token";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (path.startsWith("/api/links")) {
    if (!headers.has("X-Links-Token")) {
      headers.set("X-Links-Token", LINKS_API_TOKEN);
    }
  }
  let lastError: unknown;
  for (const base of API_BASE_FALLBACKS) {
    try {
      const url = base ? `${base}${path}` : path;
      const res = await fetch(url, {
        ...init,
        headers,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`API error ${res.status}: ${text}`);
      }
      return res.json() as Promise<T>;
    } catch (error) {
      lastError = error;
      // Retry only transport/CORS-style failures on fallback hosts.
      if (!(error instanceof TypeError)) {
        throw error;
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error("API request failed");
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
  group?: string;
  detectorStatus?: string;
  tier?: string;
  page?: number;
  pageSize?: number;
  cohortOnly?: boolean;
}

export function fetchEdgeCases(params: EdgeCaseParams = {}) {
  const sp = new URLSearchParams();
  if (params.category) sp.set("category", params.category);
  if (params.group) sp.set("group", params.group);
  if (params.detectorStatus) sp.set("detector_status", params.detectorStatus);
  if (params.tier) sp.set("tier", params.tier);
  if (params.page !== undefined) sp.set("page", String(params.page));
  if (params.pageSize !== undefined) sp.set("page_size", String(params.pageSize));
  if (params.cohortOnly !== undefined) sp.set("cohort_only", String(params.cohortOnly));
  return fetchJson<import("./types").EdgeCasesResponse>(`/api/edge-cases?${sp}`);
}

// --- Edge Case Clause Detail ---
export function fetchEdgeCaseClauseDetail(docId: string, category: string) {
  const sp = new URLSearchParams({ category });
  return fetchJson<import("./types").EdgeCaseClauseDetailResponse>(
    `/api/edge-cases/${encodeURIComponent(docId)}/clause-detail?${sp}`
  );
}

// --- Edge Case Definition Detail ---
export function fetchEdgeCaseDefinitionDetail(docId: string, category: string) {
  const sp = new URLSearchParams({ category });
  return fetchJson<import("./types").EdgeCaseDefinitionDetailResponse>(
    `/api/edge-cases/${encodeURIComponent(docId)}/definition-detail?${sp}`
  );
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
// Corpus Query Builder
// ---------------------------------------------------------------------------

export function fetchArticleConcepts(cohortOnly = true) {
  const sp = new URLSearchParams({ cohort_only: String(cohortOnly) });
  return fetchJson<import("./types").ArticleConceptsResponse>(
    `/api/articles/concepts?${sp}`
  );
}

export interface FilterChip {
  value: string;
  op: "or" | "and" | "not" | "and_not";
}

export interface CorpusQueryParams {
  concept?: string;
  articleNum?: number;
  articleTitleFilters?: FilterChip[];
  headingFilters?: FilterChip[];
  sectionNumber?: string;
  clauseTextFilters?: FilterChip[];
  clauseHeaderFilters?: FilterChip[];
  minDepth?: number;
  maxDepth?: number;
  minClauseChars?: number;
  cohortOnly?: boolean;
  limit?: number;
}

export function fetchCorpusQuery(params: CorpusQueryParams) {
  return fetchJson<import("./types").CorpusQueryResponse>(
    "/api/corpus/query",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        concept: params.concept || undefined,
        article_num: params.articleNum,
        article_title_filters: params.articleTitleFilters?.length
          ? params.articleTitleFilters
          : undefined,
        heading_filters: params.headingFilters?.length
          ? params.headingFilters
          : undefined,
        section_number: params.sectionNumber || undefined,
        clause_text_filters: params.clauseTextFilters?.length
          ? params.clauseTextFilters
          : undefined,
        clause_header_filters: params.clauseHeaderFilters?.length
          ? params.clauseHeaderFilters
          : undefined,
        min_depth: params.minDepth ?? 0,
        max_depth: params.maxDepth ?? 10,
        min_clause_chars: params.minClauseChars ?? 0,
        cohort_only: params.cohortOnly ?? true,
        limit: params.limit ?? 200,
      }),
    }
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
// Phase 9: Feedback Backlog
// ---------------------------------------------------------------------------

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
// Phase 3: Bulk Section-to-Ontology-Family Linking
// ---------------------------------------------------------------------------

// ── Helpers ────────────────────────────────────────────────────────────────

async function postJson<T>(path: string, data: unknown): Promise<T> {
  return fetchJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

async function patchJson<T>(path: string, data: unknown): Promise<T> {
  return fetchJson<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

async function deleteJson<T>(path: string): Promise<T> {
  return fetchJson<T>(path, { method: "DELETE" });
}

// ── Links CRUD ─────────────────────────────────────────────────────────────

export interface LinksQueryParams {
  familyId?: string;
  status?: string;
  confidenceTier?: string;
  docId?: string;
  templateFamily?: string;
  vintageYear?: number;
  search?: string;
  sortBy?: string;
  sortDir?: "asc" | "desc";
  page?: number;
  pageSize?: number;
  cursor?: string;
}

export function fetchLinks(params: LinksQueryParams = {}) {
  const sp = new URLSearchParams();
  if (params.familyId) sp.set("family_id", params.familyId);
  if (params.status) sp.set("status", params.status);
  if (params.confidenceTier) sp.set("confidence_tier", params.confidenceTier);
  if (params.docId) sp.set("doc_id", params.docId);
  if (params.templateFamily) sp.set("template_family", params.templateFamily);
  if (params.vintageYear !== undefined) sp.set("vintage_year", String(params.vintageYear));
  if (params.search) sp.set("search", params.search);
  if (params.sortBy) sp.set("sort_by", params.sortBy);
  if (params.sortDir) sp.set("sort_dir", params.sortDir);
  if (params.page !== undefined) sp.set("page", String(params.page));
  if (params.pageSize !== undefined) sp.set("page_size", String(params.pageSize));
  if (params.cursor) sp.set("cursor", params.cursor);
  return fetchJson<Record<string, unknown>>(`/api/links?${sp}`).then((raw) => {
    const links = Array.isArray(raw.links)
      ? raw.links
      : Array.isArray(raw.items)
      ? raw.items
      : [];
    const total = typeof raw.total === "number" ? raw.total : links.length;
    const page = typeof raw.page === "number" ? raw.page : params.page ?? 1;
    const pageSize =
      typeof raw.page_size === "number"
        ? raw.page_size
        : params.pageSize ?? 50;
    const summaryRaw =
      raw.summary && typeof raw.summary === "object"
        ? (raw.summary as Record<string, unknown>)
        : {};
    const summary: import("./types").FamilyLinkSummary = {
      total:
        typeof summaryRaw.total === "number"
          ? summaryRaw.total
          : total,
      by_family: Array.isArray(summaryRaw.by_family)
        ? (summaryRaw.by_family as import("./types").FamilyLinkSummary["by_family"])
        : [],
      by_status: Array.isArray(summaryRaw.by_status)
        ? (summaryRaw.by_status as import("./types").FamilyLinkSummary["by_status"])
        : [],
      by_confidence_tier: Array.isArray(summaryRaw.by_confidence_tier)
        ? (summaryRaw.by_confidence_tier as import("./types").FamilyLinkSummary["by_confidence_tier"])
        : [],
      unique_docs:
        typeof summaryRaw.unique_docs === "number"
          ? summaryRaw.unique_docs
          : 0,
      pending_review:
        typeof summaryRaw.pending_review === "number"
          ? summaryRaw.pending_review
          : 0,
      unlinked:
        typeof summaryRaw.unlinked === "number"
          ? summaryRaw.unlinked
          : 0,
      drift_alerts:
        typeof summaryRaw.drift_alerts === "number"
          ? summaryRaw.drift_alerts
          : 0,
    };
    return {
      ...raw,
      links,
      items: links,
      total,
      page,
      page_size: pageSize,
      summary,
    } as import("./types").LinksListResponse;
  });
}

export function fetchLink(linkId: string) {
  return fetchJson<import("./types").FamilyLink>(
    `/api/links/${encodeURIComponent(linkId)}`
  );
}

export function fetchLinkSummary() {
  return fetchJson<import("./types").FamilyLinkSummary>("/api/links/summary");
}

export function unlinkLink(linkId: string, reason: string) {
  return patchJson<{ updated: boolean }>(
    `/api/links/${encodeURIComponent(linkId)}/unlink`,
    { reason }
  );
}

export function relinkLink(linkId: string) {
  return patchJson<{ updated: boolean }>(
    `/api/links/${encodeURIComponent(linkId)}/relink`,
    {}
  );
}

export function bookmarkLink(linkId: string) {
  return patchJson<{ updated: boolean }>(
    `/api/links/${encodeURIComponent(linkId)}/bookmark`,
    {}
  );
}

export function addLinkNote(linkId: string, note: string) {
  return patchJson<{ updated: boolean }>(
    `/api/links/${encodeURIComponent(linkId)}/note`,
    { note }
  );
}

export function deferLink(linkId: string) {
  return patchJson<{ updated: boolean }>(
    `/api/links/${encodeURIComponent(linkId)}/defer`,
    {}
  );
}

export function updateLinkRole(linkId: string, role: string) {
  return patchJson<import("./types").RoleUpdateResponse>(
    `/api/links/${encodeURIComponent(linkId)}/role`,
    { role }
  );
}

export function batchUnlink(linkIds: string[], reason: string) {
  return postJson<{ updated: number }>("/api/links/batch/unlink", {
    link_ids: linkIds,
    reason,
  });
}

export function batchRelink(linkIds: string[]) {
  return postJson<{ updated: number }>("/api/links/batch/relink", {
    link_ids: linkIds,
  });
}

export function batchBookmark(linkIds: string[]) {
  return postJson<{ updated: number }>("/api/links/batch/bookmark", {
    link_ids: linkIds,
  });
}

// ── Why matched / not matched ──────────────────────────────────────────────

export function fetchWhyMatched(linkId: string) {
  return fetchJson<import("./types").WhyMatched>(
    `/api/links/${encodeURIComponent(linkId)}/why-matched`
  );
}

export function fetchWhyNotMatched(docId: string, sectionNumber: string, familyId: string) {
  const sp = new URLSearchParams({
    doc_id: docId,
    section_number: sectionNumber,
    family_id: familyId,
  });
  return fetchJson<import("./types").WhyNotMatched>(`/api/links/why-not-matched?${sp}`);
}

// ── Context strip ──────────────────────────────────────────────────────────

export function fetchContextStrip(linkId: string) {
  return fetchJson<Record<string, unknown>>(
    `/api/links/${encodeURIComponent(linkId)}/context-strip`
  ).then((raw) => {
    const definitions = Array.isArray(raw.definitions)
      ? raw.definitions
      : Array.isArray(raw.defined_terms)
      ? raw.defined_terms
      : [];
    const xrefs = Array.isArray(raw.xrefs)
      ? raw.xrefs
      : Array.isArray(raw.related_links)
      ? raw.related_links
      : [];
    return {
      link_id: String(raw.link_id ?? linkId),
      primary_covenant_heading: String(raw.primary_covenant_heading ?? ""),
      primary_covenant_preview: String(raw.primary_covenant_preview ?? ""),
      definitions: definitions.map((def) => {
        const item = def as Record<string, unknown>;
        return {
          term: String(item.term ?? ""),
          definition_text: String(
            item.definition_text ??
              item.definition ??
              (item.definition_section_path
                ? `Defined in section ${String(item.definition_section_path)}`
                : ""),
          ),
        };
      }),
      xrefs: xrefs.map((xref) => {
        const item = xref as Record<string, unknown>;
        return {
          section_ref: String(item.section_ref ?? item.section_number ?? ""),
          heading: String(item.heading ?? ""),
          text_preview: String(item.text_preview ?? item.heading ?? ""),
        };
      }),
      section_text:
        typeof raw.section_text === "string" ? raw.section_text : null,
      section_families: Array.isArray(raw.section_families)
        ? raw.section_families
        : [],
    } as import("./types").ContextStripData;
  });
}

// ── Comparables ────────────────────────────────────────────────────────────

export function fetchComparables(linkId: string) {
  return fetchJson<Record<string, unknown>>(
    `/api/links/${encodeURIComponent(linkId)}/comparables`
  ).then((raw) => {
    const comparables = Array.isArray(raw.comparables) ? raw.comparables : [];
    return {
      link_id: String(raw.link_id ?? linkId),
      comparables: comparables as import("./types").ComparableSection[],
    } as import("./types").ComparablesResponse;
  });
}

// ── Reassign ───────────────────────────────────────────────────────────────

export function fetchReassignSuggestions(linkId: string) {
  return fetchJson<Record<string, unknown>>(
    `/api/links/${encodeURIComponent(linkId)}/reassign-suggestions`
  ).then((raw) => {
    const suggestionsRaw = Array.isArray(raw.suggestions) ? raw.suggestions : [];
    const suggestions = suggestionsRaw.map((item) => {
      const row = item as Record<string, unknown>;
      const familyId = String(row.family_id ?? "");
      return {
        family_id: familyId,
        family_name:
          String(row.family_name ?? "") ||
          familyId.replace(/^FAM-/, "").replace(/[-_]/g, " "),
        confidence:
          typeof row.confidence === "number"
            ? row.confidence
            : row.match_type === "exact"
            ? 0.7
            : 0.55,
        reason: String(
          row.reason ??
            (row.match_type ? `Matched via ${String(row.match_type)}` : "Rule match"),
        ),
      };
    });
    return {
      link_id: linkId,
      current_family_id: String(raw.current_family_id ?? ""),
      suggestions,
    } as import("./types").ReassignSuggestionsResponse;
  });
}

export function reassignLink(linkId: string, newFamilyId: string) {
  return postJson<{ reassigned: boolean; new_link_id: string }>(
    `/api/links/${encodeURIComponent(linkId)}/reassign`,
    { new_family_id: newFamilyId }
  );
}

// ── Preview / Apply ────────────────────────────────────────────────────────

export function createPreview(familyId: string, ruleId?: string) {
  return postJson<import("./types").LinkPreviewResponse>(
    "/api/links/query/preview",
    { family_id: familyId, rule_id: ruleId }
  );
}

export function fetchPreviewCandidates(previewId: string) {
  return fetchPreviewCandidatesPage(previewId, {});
}

export function fetchPreviewCandidatesPage(
  previewId: string,
  params: {
    pageSize?: number;
    confidenceTier?: import("./types").ConfidenceTier;
    afterScore?: number | null;
    afterDocId?: string | null;
    afterCandidateId?: string | null;
  }
) {
  const sp = new URLSearchParams();
  if (params.pageSize !== undefined) sp.set("page_size", String(params.pageSize));
  if (params.confidenceTier) sp.set("confidence_tier", params.confidenceTier);
  if (
    params.afterScore !== undefined &&
    params.afterScore !== null &&
    params.afterDocId
  ) {
    sp.set("after_score", String(params.afterScore));
    sp.set("after_doc_id", params.afterDocId);
    if (params.afterCandidateId) sp.set("after_candidate_id", params.afterCandidateId);
  }
  return fetchJson<Record<string, unknown>>(
    `/api/links/previews/${encodeURIComponent(previewId)}/candidates?${sp}`
  ).then((raw) => {
    const itemsRaw = Array.isArray(raw.items) ? raw.items : [];
    const items = itemsRaw.map((row) => {
      const r = row as Record<string, unknown>;
      return {
        candidate_id: String(
          r.candidate_id
          ?? `${String(r.doc_id ?? "")}::${String(r.section_number ?? "")}::${String(r.clause_id ?? r.clause_path ?? "__section__")}`,
        ),
        doc_id: String(r.doc_id ?? ""),
        borrower: String(r.borrower ?? r.doc_id ?? ""),
        section_number: String(r.section_number ?? ""),
        clause_id: String(r.clause_id ?? ""),
        clause_path: String(r.clause_path ?? ""),
        clause_key: String(r.clause_key ?? r.clause_id ?? r.clause_path ?? "__section__"),
        clause_label: String(r.clause_label ?? ""),
        clause_char_start:
          r.clause_char_start === null || r.clause_char_start === undefined
            ? null
            : Number(r.clause_char_start),
        clause_char_end:
          r.clause_char_end === null || r.clause_char_end === undefined
            ? null
            : Number(r.clause_char_end),
        clause_text: String(r.clause_text ?? ""),
        defined_term: String(r.defined_term ?? ""),
        definition_char_start:
          r.definition_char_start === null || r.definition_char_start === undefined
            ? null
            : Number(r.definition_char_start),
        definition_char_end:
          r.definition_char_end === null || r.definition_char_end === undefined
            ? null
            : Number(r.definition_char_end),
        definition_text: String(r.definition_text ?? ""),
        heading: String(r.heading ?? ""),
        confidence: Number(r.confidence ?? 0),
        confidence_tier: String(r.confidence_tier ?? "low") as import("./types").ConfidenceTier,
        factors: [],
        verdict: String(r.user_verdict ?? r.verdict ?? "pending") as
          | "pending"
          | "accepted"
          | "rejected"
          | "deferred",
        existing_link_id:
          r.existing_link_id === null || r.existing_link_id === undefined
            ? null
            : String(r.existing_link_id),
        priority_score: Number(r.priority_score ?? 0),
      } satisfies import("./types").PreviewCandidate;
    });
    const nextCursorRaw =
      raw.next_cursor && typeof raw.next_cursor === "object"
        ? (raw.next_cursor as Record<string, unknown>)
        : null;
    return {
      total: Number(raw.total ?? items.length),
      items,
      candidate_set_hash: String(raw.candidate_set_hash ?? ""),
      next_cursor: nextCursorRaw
        ? {
            after_score: Number(nextCursorRaw.after_score ?? 0),
            after_doc_id: String(nextCursorRaw.after_doc_id ?? ""),
            after_candidate_id:
              nextCursorRaw.after_candidate_id === null || nextCursorRaw.after_candidate_id === undefined
                ? undefined
                : String(nextCursorRaw.after_candidate_id),
          }
        : null,
      page: Number(raw.page ?? 1),
      page_size: Number(raw.page_size ?? params.pageSize ?? 50),
    } satisfies import("./types").PreviewCandidatesResponse;
  });
}

export function updateCandidateVerdicts(
  previewId: string,
  verdicts: {
    verdict: string;
    candidate_id?: string;
    doc_id?: string;
    section_number?: string;
    clause_id?: string;
    clause_path?: string;
  }[]
) {
  return patchJson<{ updated: number }>(
    `/api/links/previews/${encodeURIComponent(previewId)}/candidates/verdict`,
    { verdicts }
  );
}

export function applyPreview(previewId: string, candidateSetHash: string) {
  return postJson<import("./types").LinkApplyResponse>(
    "/api/links/query/apply",
    { preview_id: previewId, candidate_set_hash: candidateSetHash }
  );
}

// ── Rules ──────────────────────────────────────────────────────────────────

export interface LinkRulesQueryParams {
  familyId?: string;
  status?: string;
  page?: number;
  pageSize?: number;
}

function normalizeLinkRule(raw: Record<string, unknown>): import("./types").LinkRule {
  const headingDsl = String(raw.heading_filter_dsl ?? "");
  const filterDsl = String(raw.filter_dsl ?? "").trim();
  const granularity = String(raw.result_granularity ?? "section");
  return {
    rule_id: String(raw.rule_id ?? ""),
    family_id: String(raw.family_id ?? ""),
    ontology_node_id:
      raw.ontology_node_id === null || raw.ontology_node_id === undefined
        ? null
        : String(raw.ontology_node_id),
    family_name: String(raw.family_name ?? raw.family_id ?? ""),
    parent_family_id:
      raw.parent_family_id === null || raw.parent_family_id === undefined
        ? null
        : String(raw.parent_family_id),
    parent_rule_id:
      raw.parent_rule_id === null || raw.parent_rule_id === undefined
        ? null
        : String(raw.parent_rule_id),
    parent_run_id:
      raw.parent_run_id === null || raw.parent_run_id === undefined
        ? null
        : String(raw.parent_run_id),
    scope_mode:
      String(raw.scope_mode ?? "corpus") === "inherited" ? "inherited" : "corpus",
    name: String(raw.name ?? ""),
    filter_dsl: filterDsl || headingDsl,
    result_granularity:
      granularity === "clause"
        ? "clause"
        : granularity === "defined_term"
          ? "defined_term"
          : "section",
    heading_filter_ast:
      raw.heading_filter_ast && typeof raw.heading_filter_ast === "object"
        ? (raw.heading_filter_ast as Record<string, unknown>)
        : {},
    heading_filter_dsl: headingDsl,
    keyword_anchors: Array.isArray(raw.keyword_anchors)
      ? raw.keyword_anchors.map((value) => String(value))
      : [],
    dna_phrases: Array.isArray(raw.dna_phrases)
      ? raw.dna_phrases.map((value) => String(value))
      : [],
    status:
      String(raw.status ?? "draft") === "published" || String(raw.status ?? "") === "archived"
        ? (String(raw.status) as "published" | "archived")
        : "draft",
    version: Number(raw.version ?? 1),
    created_at: String(raw.created_at ?? ""),
    updated_at: raw.updated_at === null || raw.updated_at === undefined ? null : String(raw.updated_at),
    pin_count: Number(raw.pin_count ?? 0),
    last_eval_pass_rate:
      raw.last_eval_pass_rate === null || raw.last_eval_pass_rate === undefined
        ? null
        : Number(raw.last_eval_pass_rate),
    locked_by:
      raw.locked_by === null || raw.locked_by === undefined
        ? null
        : String(raw.locked_by),
    locked_at:
      raw.locked_at === null || raw.locked_at === undefined
        ? null
        : String(raw.locked_at),
  };
}

export function fetchLinkRules(params: LinkRulesQueryParams = {}) {
  const sp = new URLSearchParams();
  if (params.familyId) sp.set("family_id", params.familyId);
  if (params.status) sp.set("status", params.status);
  if (params.page !== undefined) sp.set("page", String(params.page));
  if (params.pageSize !== undefined) sp.set("page_size", String(params.pageSize));
  return fetchJson<Record<string, unknown>>(`/api/links/rules?${sp}`).then((raw) => ({
    total: Number(raw.total ?? 0),
    rules: Array.isArray(raw.rules)
      ? raw.rules
          .filter((value): value is Record<string, unknown> => !!value && typeof value === "object")
          .map(normalizeLinkRule)
      : [],
  }));
}

export function fetchLinkRule(ruleId: string) {
  return fetchJson<Record<string, unknown>>(
    `/api/links/rules/${encodeURIComponent(ruleId)}`
  ).then(normalizeLinkRule);
}

export function createLinkRule(data: {
  family_id: string;
  ontology_node_id?: string | null;
  filter_dsl?: string;
  result_granularity?: "section" | "clause" | "defined_term";
  heading_filter_dsl?: string;
  heading_filter_ast?: Record<string, unknown>;
  keyword_anchors?: string[];
  dna_phrases?: string[];
  parent_family_id?: string | null;
  parent_rule_id?: string | null;
  parent_run_id?: string | null;
  scope_mode?: "corpus" | "inherited";
}) {
  return postJson<{ rule_id: string; status: string }>("/api/links/rules", data);
}

export function updateLinkRule(ruleId: string, data: Record<string, unknown>) {
  return patchJson<{ updated: boolean }>(
    `/api/links/rules/${encodeURIComponent(ruleId)}`,
    data
  );
}

export function deleteLinkRule(ruleId: string) {
  return deleteJson<{ deleted: boolean; rule_id: string }>(
    `/api/links/rules/${encodeURIComponent(ruleId)}`
  );
}

export function publishLinkRule(ruleId: string) {
  return postJson<{ published: boolean }>(
    `/api/links/rules/${encodeURIComponent(ruleId)}/publish`,
    {}
  );
}

export function archiveLinkRule(ruleId: string) {
  return postJson<{ archived: boolean }>(
    `/api/links/rules/${encodeURIComponent(ruleId)}/archive`,
    {}
  );
}

export function compareLinkRules(ruleIdA: string, ruleIdB: string) {
  const sp = new URLSearchParams({ rule_id_a: ruleIdA, rule_id_b: ruleIdB });
  return fetchJson<import("./types").RuleCompareResult>(`/api/links/rules/compare?${sp}`);
}

// ── DSL validation ─────────────────────────────────────────────────────────

export function validateDslStandalone(text: string) {
  return postJson<import("./types").DslValidationResponse>(
    "/api/links/rules/validate-dsl-standalone",
    { text }
  );
}

export function validateDslForRule(ruleId: string, text: string) {
  return postJson<import("./types").DslValidationResponse>(
    `/api/links/rules/${encodeURIComponent(ruleId)}/validate-dsl`,
    { text }
  );
}

// ── Rule evaluate-text ─────────────────────────────────────────────────────

export function evaluateRuleText(data: {
  rule_ast: Record<string, unknown>;
  raw_text: string;
  heading?: string;
}) {
  return postJson<import("./types").RuleEvaluateTextResponse>(
    "/api/links/rules/evaluate-text",
    data
  );
}

export function fetchRuleAutocomplete(
  field: "heading" | "article" | "clause" | "section" | "defined_term" | "template" | "admin_agent" | "vintage" | "market" | "doc_type" | "facility_size_mm",
  prefix = "",
  limit = 8
) {
  const sp = new URLSearchParams({
    field,
    prefix,
    limit: String(limit),
  });
  return fetchJson<{ field: string; suggestions: string[] }>(
    `/api/links/rules-autocomplete?${sp}`
  );
}

// ── Conflicts ──────────────────────────────────────────────────────────────

export function fetchConflicts() {
  return fetchJson<import("./types").ConflictsResponse>("/api/links/conflicts");
}

export function fetchConflictPolicies() {
  return fetchJson<import("./types").ConflictPoliciesResponse>(
    "/api/links/conflict-policies"
  );
}

export function createConflictPolicy(data: {
  family_a: string;
  family_b: string;
  policy: string;
  reason?: string;
}) {
  return postJson<{ status: string }>("/api/links/conflict-policies", data);
}

// ── Template baselines ─────────────────────────────────────────────────────

export interface TemplateBaselinesQueryParams {
  familyId?: string;
}

export function fetchTemplateBaselines(params: TemplateBaselinesQueryParams = {}) {
  const sp = new URLSearchParams();
  if (params.familyId) sp.set("family_id", params.familyId);
  return fetchJson<import("./types").TemplateBaselinesResponse>(
    `/api/links/template-baselines?${sp}`
  );
}

export function createTemplateBaseline(data: {
  family_id: string;
  template: string;
  expected_sections: string[];
  min_confidence: number;
  description?: string;
}) {
  return postJson<{ status: string }>("/api/links/template-baselines", data);
}

// ── Sessions ───────────────────────────────────────────────────────────────

function normalizeReviewSessionResponse(
  raw: Record<string, unknown>,
  fallbackFamilyId?: string,
): import("./types").ReviewSessionResponse {
  const source =
    raw.session && typeof raw.session === "object"
      ? (raw.session as Record<string, unknown>)
      : raw;
  return {
    session: {
      session_id: String(source.session_id ?? ""),
      family_id:
        source.family_id === null || source.family_id === undefined
          ? fallbackFamilyId ?? null
          : String(source.family_id),
      started_at: String(source.started_at ?? ""),
      last_cursor:
        source.last_cursor === null || source.last_cursor === undefined
          ? null
          : String(source.last_cursor),
      total_reviewed: Number(source.total_reviewed ?? 0),
      total_unlinked: Number(source.total_unlinked ?? 0),
      total_bookmarked: Number(source.total_bookmarked ?? 0),
      total_links: Number(source.total_links ?? 0),
    },
  };
}

export function createSession(familyId?: string) {
  return postJson<Record<string, unknown>>(
    "/api/links/sessions",
    { family_id: familyId }
  ).then((raw) => normalizeReviewSessionResponse(raw, familyId));
}

export function fetchSession(sessionId: string) {
  return fetchJson<Record<string, unknown>>(
    `/api/links/sessions/${encodeURIComponent(sessionId)}`
  ).then((raw) => normalizeReviewSessionResponse(raw));
}

export function updateSessionCursor(sessionId: string, cursor: string) {
  return patchJson<{ updated: boolean }>(
    `/api/links/sessions/${encodeURIComponent(sessionId)}/cursor`,
    { cursor, cursor_link_id: cursor }
  );
}

export function addReviewMark(sessionId: string, data: {
  link_id: string;
  action: string;
  reason?: string;
}) {
  const actionToMark: Record<string, string> = {
    reviewed: "viewed",
    bookmarked: "bookmarked",
    unlinked: "unlinked",
    relinked: "relinked",
    pinned_tp: "flagged",
    pinned_tn: "flagged",
    deferred: "deferred",
    reassigned: "reassigned",
    noted: "noted",
  };
  return postJson<{ mark_id: string }>(
    `/api/links/sessions/${encodeURIComponent(sessionId)}/marks`,
    {
      ...data,
      mark_type: actionToMark[data.action] ?? "viewed",
      note: data.reason,
    }
  );
}

export function fetchReviewMarks(sessionId: string) {
  return fetchJson<import("./types").ReviewMarksResponse>(
    `/api/links/sessions/${encodeURIComponent(sessionId)}/marks`
  );
}

export function claimSessionBatch(sessionId: string, batchSize = 50) {
  return postJson<{ claimed: string[]; count: number }>(
    `/api/links/sessions/${encodeURIComponent(sessionId)}/claim-batch`,
    { batch_size: batchSize },
  );
}

// ── Undo / Redo ────────────────────────────────────────────────────────────

export function undoLastAction() {
  return postJson<import("./types").UndoResponse>("/api/links/undo", {});
}

export function redoLastAction() {
  return postJson<import("./types").RedoResponse>("/api/links/redo", {});
}

// ── Runs ───────────────────────────────────────────────────────────────────

export function fetchLinkRuns(params: { familyId?: string; limit?: number } = {}) {
  const sp = new URLSearchParams();
  if (params.familyId) sp.set("family_id", params.familyId);
  if (params.limit !== undefined) sp.set("limit", String(params.limit));
  return fetchJson<import("./types").LinkRunListResponse>(`/api/links/runs?${sp}`);
}

// ── Link Jobs ──────────────────────────────────────────────────────────────

export function fetchLinkJobs() {
  return fetchJson<import("./types").LinkJobListResponse>("/api/links/jobs");
}

export function fetchLinkJobStatus(jobId: string) {
  return fetchJson<import("./types").LinkJob>(
    `/api/links/jobs/${encodeURIComponent(jobId)}`
  );
}

export function cancelLinkJob(jobId: string) {
  return deleteJson<{ cancelled: boolean }>(
    `/api/links/jobs/${encodeURIComponent(jobId)}`
  );
}

export function submitLinkJob(data: { job_type: string; params: Record<string, unknown> }) {
  if (data.job_type === "batch_run") {
    return postJson<import("./types").LinkJobSubmitResponse>("/api/links/batch-run", {
      family_id: data.params?.family_id,
    });
  }
  throw new Error(`Unsupported link job_type: ${data.job_type}`);
}

// ── Export ──────────────────────────────────────────────────────────────────

export function exportLinks(format: string, familyId?: string) {
  return postJson<import("./types").ExportJobResponse>("/api/links/export", {
    format,
    family_id: familyId,
  });
}

// ── Analytics ──────────────────────────────────────────────────────────────

export function fetchAnalyticsDashboard(scopeId?: string) {
  const sp = new URLSearchParams();
  if (scopeId) sp.set("family_id", scopeId);
  const suffix = sp.toString();
  return fetchJson<import("./types").AnalyticsDashboard>(
    suffix ? `/api/links/analytics?${suffix}` : "/api/links/analytics"
  );
}

// ── Intelligence overlay ──────────────────────────────────────────────────

export interface LinkIntelligenceEvidenceParams {
  recordType?: string;
  limit?: number;
  offset?: number;
}

export function fetchLinkIntelligenceSignals(scopeId?: string) {
  const sp = new URLSearchParams();
  if (scopeId) sp.set("scope_id", scopeId);
  const suffix = sp.toString();
  return fetchJson<import("./types").LinkIntelligenceSignalsResponse>(
    suffix
      ? `/api/links/intelligence/signals?${suffix}`
      : "/api/links/intelligence/signals"
  );
}

export function fetchLinkIntelligenceEvidence(
  scopeId?: string,
  params: LinkIntelligenceEvidenceParams = {},
) {
  const sp = new URLSearchParams();
  if (scopeId) sp.set("scope_id", scopeId);
  if (params.recordType) sp.set("record_type", params.recordType);
  if (params.limit !== undefined) sp.set("limit", String(params.limit));
  if (params.offset !== undefined) sp.set("offset", String(params.offset));
  return fetchJson<import("./types").LinkIntelligenceEvidenceResponse>(
    `/api/links/intelligence/evidence?${sp}`
  );
}

export function fetchLinkIntelligenceOps(scopeId?: string, staleMinutes = 60) {
  const sp = new URLSearchParams();
  if (scopeId) sp.set("scope_id", scopeId);
  sp.set("stale_minutes", String(staleMinutes));
  return fetchJson<import("./types").LinkIntelligenceOpsResponse>(
    `/api/links/intelligence/ops?${sp}`
  );
}

// ── Calibrations ───────────────────────────────────────────────────────────

export function fetchCalibrations() {
  return fetchJson<import("./types").CalibrationsResponse>("/api/links/calibrations");
}

// ── Crossref peek ──────────────────────────────────────────────────────────

export function fetchCrossrefPeek(sectionRef: string) {
  const sp = new URLSearchParams();
  let section = sectionRef;
  if (sectionRef.includes(":")) {
    const [docId, ...rest] = sectionRef.split(":");
    if (docId && rest.length > 0) {
      sp.set("doc_id", docId);
      section = rest.join(":");
    }
  }
  sp.set("section_ref", section);
  return fetchJson<import("./types").CrossrefPeekResponse>(
    `/api/links/crossref-peek?${sp}`
  );
}

// ── Counterfactual ─────────────────────────────────────────────────────────

export function fetchCounterfactual(data: {
  family_id: string;
  heading_filter_ast: Record<string, unknown>;
  muted_node_path?: string;
}) {
  return postJson<import("./types").CounterfactualResponse>(
    "/api/links/coverage/counterfactual",
    data
  );
}

// ── Embeddings ─────────────────────────────────────────────────────────────

export function fetchEmbeddingsStats() {
  return fetchJson<import("./types").EmbeddingsStatsResponse>("/api/links/embeddings/stats");
}

export function computeEmbeddings(familyId?: string) {
  return postJson<{ job_id: string }>("/api/links/embeddings/compute", {
    family_id: familyId,
  });
}

export function fetchFamilyCentroids() {
  return fetchJson<{ centroids: import("./types").FamilyCentroid[] }>(
    "/api/links/embeddings/centroids"
  );
}

// ── Starter kits ───────────────────────────────────────────────────────────

export function fetchStarterKits() {
  return fetchJson<import("./types").StarterKitsResponse>("/api/links/starter-kits");
}

export function fetchStarterKit(familyId: string) {
  return fetchJson<import("./types").StarterKit>(
    `/api/links/starter-kits/${encodeURIComponent(familyId)}`
  );
}

// ── Compound covenants ─────────────────────────────────────────────────────

export function fetchCompoundCovenants() {
  return fetchJson<import("./types").CompoundCovenantsResponse>(
    "/api/links/compound-covenants"
  );
}

export function resolveCompoundCovenant(docId: string, sectionNumber: string, resolution: string) {
  return postJson<{ resolved: boolean }>("/api/links/compound-covenants/resolve", {
    doc_id: docId,
    section_number: sectionNumber,
    resolution,
  });
}

// ── Template redline (baseline text for diff) ──────────────────────────────

export function fetchTemplateBaselineText(familyId: string, template: string) {
  const sp = new URLSearchParams({ family_id: familyId, template });
  return fetchJson<{ text: string | null; baseline_id: string | null }>(
    `/api/links/template-baselines/text?${sp}`
  );
}

// ── Phase 4: Coverage gaps ──────────────────────────────────────────────────

export function fetchCoverageGaps(familyId?: string) {
  const sp = new URLSearchParams();
  if (familyId) sp.set("family_id", familyId);
  return fetchJson<import("./types").CoverageGapsResponse>(
    `/api/links/coverage?${sp}`
  );
}

export function fetchWhyNotCoverage(
  docId: string,
  ruleId: string,
  sectionNumber?: string
) {
  return postJson<import("./types").WhyNotMatched>(
    "/api/links/coverage/why-not",
    { doc_id: docId, rule_id: ruleId, section_number: sectionNumber }
  );
}

// ── Phase 4: Term expansion ─────────────────────────────────────────────────

export function fetchExpandTerm(term: string) {
  return postJson<{ expansions: string[] }>(
    "/api/links/rules/expand-term",
    { term }
  );
}

// ── Phase 4: Query count ────────────────────────────────────────────────────

export function fetchQueryCount(
  familyId?: string,
  headingAst?: Record<string, unknown>,
  metaFilters?: Record<string, unknown>,
  signal?: AbortSignal,
  filterDsl?: string,
  scope?: {
    scopeMode?: "corpus" | "inherited";
    parentFamilyId?: string | null;
    parentRunId?: string | null;
  },
) {
  const sp = new URLSearchParams();
  if (familyId) sp.set("family_id", familyId);
  if (filterDsl) {
    sp.set("filter_dsl", filterDsl);
  } else if (headingAst) {
    sp.set("heading_filter_ast", JSON.stringify(headingAst));
  }
  if (metaFilters && Object.keys(metaFilters).length > 0) {
    sp.set("meta_filters", JSON.stringify(metaFilters));
  }
  if (scope?.scopeMode) sp.set("scope_mode", scope.scopeMode);
  if (scope?.parentFamilyId) sp.set("parent_family_id", scope.parentFamilyId);
  if (scope?.parentRunId) sp.set("parent_run_id", scope.parentRunId);
  return fetchJson<{ count: number; query_cost: number }>(
    `/api/links/query/count?${sp}`,
    { signal }
  );
}

// ── Phase 4: Semantic candidates ────────────────────────────────────────────

export function fetchSemanticCandidates(familyId: string) {
  const sp = new URLSearchParams({ family_id: familyId });
  return fetchJson<{ candidates: import("./types").SemanticCandidate[] }>(
    `/api/links/embeddings/similar?${sp}`
  );
}

// ── Phase 4: Canary apply ───────────────────────────────────────────────────

export function fetchCanaryApply(previewId: string, limit = 10) {
  return postJson<import("./types").LinkApplyResponse>(
    "/api/links/query/canary",
    { preview_id: previewId, canary_n: limit }
  );
}

// ── Phase 4: Preview from AST ───────────────────────────────────────────────

export function createPreviewFromAst(
  familyId: string,
  ast: Record<string, unknown>,
  metaFilters?: Record<string, unknown>,
  textFields?: Record<string, unknown>,
  filterDsl?: string,
  resultGranularity?: "section" | "clause" | "defined_term",
  ontologyNodeId?: string | null,
  scope?: {
    scopeMode?: "corpus" | "inherited";
    parentFamilyId?: string | null;
    parentRuleId?: string | null;
    parentRunId?: string | null;
  },
) {
  return postJson<import("./types").LinkPreviewResponse>(
    "/api/links/query/preview",
    {
      family_id: familyId,
      ontology_node_id: ontologyNodeId ?? undefined,
      heading_filter_ast: ast,
      filter_dsl: filterDsl,
      result_granularity: resultGranularity ?? "section",
      scope_mode: scope?.scopeMode ?? "corpus",
      parent_family_id: scope?.parentFamilyId ?? undefined,
      parent_rule_id: scope?.parentRuleId ?? undefined,
      parent_run_id: scope?.parentRunId ?? undefined,
      text_fields: textFields ?? {},
      meta_filters: metaFilters ?? {},
    }
  );
}

// ── Phase 5: Import labels ──────────────────────────────────────────────────

export function importLabels(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return fetch(`${API_BASE}/api/links/import`, {
    method: "POST",
    body: formData,
  }).then((r) => {
    if (!r.ok) throw new Error(`Import failed: ${r.status}`);
    return r.json() as Promise<{ job_id: string; rows_parsed: number }>;
  });
}

// ── Phase 5: Clone rule ─────────────────────────────────────────────────────

export function cloneLinkRule(ruleId: string) {
  return postJson<import("./types").LinkRule>(
    `/api/links/rules/${encodeURIComponent(ruleId)}/clone`,
    {}
  );
}

// ── Phase 5: Promote rule ───────────────────────────────────────────────────

export function promoteRule(ruleIdFrom: string, ruleIdTo: string) {
  return postJson<{ promoted: boolean }>(
    `/api/links/rules/promote`,
    { rule_id_from: ruleIdFrom, rule_id_to: ruleIdTo }
  );
}

// ── Phase 5: Lock / unlock rule ─────────────────────────────────────────────

export function lockRule(ruleId: string) {
  return postJson<{ locked: boolean }>(
    `/api/links/rules/${encodeURIComponent(ruleId)}/lock`,
    {}
  );
}

export function unlockRule(ruleId: string) {
  return postJson<{ unlocked: boolean }>(
    `/api/links/rules/${encodeURIComponent(ruleId)}/unlock`,
    {}
  );
}

// ── Phase 5: Promotion gate check ───────────────────────────────────────────

export function checkPromotionGates(ruleId: string) {
  return fetchJson<{
    rule_id: string;
    gates: { gate: string; passed: boolean; detail: string }[];
    all_passed: boolean;
  }>(`/api/links/rules/${encodeURIComponent(ruleId)}/promotion-gates`);
}
