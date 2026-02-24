// Mirrors the DuckDB schema + API response shapes

export interface DocSummary {
  doc_id: string;
  borrower: string;
  admin_agent: string;
  facility_size_mm: number | null;
  closing_date: string | null;
  doc_type: string;
  doc_type_confidence: string | null;
  market_segment: string;
  segment_confidence: string | null;
  cohort_included: boolean;
  word_count: number;
  section_count: number;
  clause_count: number;
  definition_count: number;
  text_length: number;
}

export interface DocRecord extends DocSummary {
  cik: string;
  accession: string;
  path: string;
  filing_date: string | null;
  form_type: string;
  template_family: string;
}

export interface SectionRecord {
  section_number: string;
  heading: string;
  article_num: number;
  word_count: number;
}

export interface OverviewKpis {
  total_docs: number;
  cohort_docs: number;
  parse_success_rate: number;
  total_sections: number;
  total_definitions: number;
  total_clauses: number;
  avg_sections_per_doc: number;
  avg_definitions_per_doc: number;
  avg_word_count: number;
  median_word_count: number;
  median_facility_size_mm: number | null;
  schema_version: string;
}

export interface CategoryItem {
  label: string;
  count: number;
}

export interface HistogramBin {
  bin_center: number;
  count: number;
}

export interface DistributionStats {
  count: number;
  mean: number;
  median: number;
  stdev: number;
  min: number;
  max: number;
  p5: number;
  p95: number;
}

export interface Distribution {
  metric: string;
  type: "categorical" | "numeric";
  categories?: CategoryItem[];
  histogram?: HistogramBin[];
  stats?: DistributionStats | null;
}

export interface CohortFunnel {
  total: number;
  by_doc_type: CategoryItem[];
  by_market_segment: CategoryItem[];
  cohort_count: number;
}

export interface DocumentsResponse {
  total: number;
  page: number;
  page_size: number;
  documents: DocSummary[];
}

export interface DocumentDetail {
  doc: DocRecord;
  sections: SectionRecord[];
  definition_count: number;
  clause_count: number;
}

export interface HealthResponse {
  status: string;
  corpus_loaded: boolean;
  doc_count: number;
}

// --- Scatter ---
export interface ScatterPoint {
  doc_id: string;
  borrower: string;
  x: number;
  y: number;
  color?: string | number | null;
}

export interface QuickStats {
  count: number;
  mean: number;
  median: number;
  min: number;
  max: number;
}

export interface ScatterResponse {
  x_metric: string;
  y_metric: string;
  color_metric: string | null;
  total_points: number;
  points: ScatterPoint[];
  x_stats: QuickStats;
  y_stats: QuickStats;
}

// --- Stats ---
export interface OverallStats {
  count: number;
  mean: number;
  median: number;
  stdev: number;
  min: number;
  max: number;
  p5: number;
  p95: number;
  sum: number;
}

export interface GroupStats {
  group: string;
  count: number;
  mean: number;
  median: number;
  stdev: number;
  min: number;
  max: number;
  p5: number;
  p95: number;
}

export interface OutlierRecord {
  doc_id: string;
  borrower: string;
  value: number;
  direction: "high" | "low";
  group: string | null;
}

export interface MetricStatsResponse {
  metric: string;
  group_by: string | null;
  overall: OverallStats | null;
  histogram: HistogramBin[];
  groups: GroupStats[];
  outliers: OutlierRecord[];
  fences: { lower: number; upper: number };
}

// --- Search (KWIC) ---
export interface SearchTextMatch {
  doc_id: string;
  borrower: string;
  section_number: string;
  heading: string;
  article_num: number;
  char_offset: number;
  matched_text: string;
  context_before: string;
  context_after: string;
}

export interface SearchTextResponse {
  query: string;
  total_matches: number;
  unique_documents: number;
  context_chars: number;
  truncated: boolean;
  matches: SearchTextMatch[];
}

// --- Definition Explorer ---
export interface DefinitionFrequency {
  term: string;
  doc_count: number;
  total_occurrences: number;
  avg_confidence: number;
  engines: string[];
}

export interface DefinitionFrequencyResponse {
  total_terms: number;
  terms: DefinitionFrequency[];
}

export interface DefinitionVariant {
  doc_id: string;
  term: string;
  definition_text: string;
  confidence: number;
  engine: string;
  borrower: string;
}

export interface DefinitionVariantsResponse {
  term: string;
  total_variants: number;
  variants: DefinitionVariant[];
}

// --- Quality ---
export interface QualityDocTypeRate {
  doc_type: string;
  total: number;
  section_rate: number;
  definition_rate: number;
  clause_rate: number;
}

export interface QualitySummary {
  total_docs: number;
  docs_with_sections: number;
  docs_with_clauses: number;
  docs_with_definitions: number;
  parse_success_rate: number;
  section_extraction_rate: number;
  clause_extraction_rate: number;
  definition_extraction_rate: number;
  anomaly_counts: {
    no_sections: number;
    no_definitions: number;
    extreme_word_count: number;
    zero_clauses: number;
  };
  by_doc_type: QualityDocTypeRate[];
}

export interface AnomalyRecord {
  doc_id: string;
  borrower: string;
  anomaly_type: string;
  severity: "high" | "medium" | "low";
  detail: string;
  doc_type: string;
  market_segment: string;
  word_count: number;
  section_count: number;
  definition_count: number;
  clause_count: number;
  facility_size_mm: number | null;
}

export interface QualityAnomaliesResponse {
  total: number;
  page: number;
  page_size: number;
  anomalies: AnomalyRecord[];
}

// --- Edge Cases ---
export interface EdgeCaseRecord {
  doc_id: string;
  borrower: string;
  category: string;
  severity: "high" | "medium" | "low";
  detail: string;
  doc_type: string;
  market_segment: string;
  word_count: number;
  section_count: number;
  definition_count: number;
  clause_count: number;
  facility_size_mm: number | null;
}

export interface EdgeCasesResponse {
  total: number;
  page: number;
  page_size: number;
  categories: { category: string; count: number }[];
  cases: EdgeCaseRecord[];
}

// --- Section Frequency ---
export interface SectionFrequency {
  section_number: string;
  heading: string;
  doc_count: number;
  presence_rate: number;
  avg_word_count: number;
  median_word_count: number;
}

export interface SectionFrequencyResponse {
  total_docs: number;
  sections: SectionFrequency[];
}

// ---------------------------------------------------------------------------
// Phase 6: Discovery Lab + Jobs
// ---------------------------------------------------------------------------

// --- Heading Discovery ---
export interface HeadingDiscoveryResult {
  heading: string;
  frequency: number;
  article_nums: number[];
  doc_count: number;
  example_doc_ids: string[];
}

export interface HeadingDiscoveryResponse {
  total_headings: number;
  total_sections_scanned: number;
  headings: HeadingDiscoveryResult[];
}

// --- Pattern Testing ---
export interface PatternMatch {
  doc_id: string;
  borrower: string;
  section_number: string;
  heading: string;
  article_num: number | null;  // H2 FIX: null when article_num not available
  match_method: string;
  score: number;
}

export interface PatternMiss {
  doc_id: string;
  borrower: string;
  best_section: string;
  best_heading: string;
  best_score: number;
}

export interface PatternTestResponse {
  hit_rate: number;
  total_docs: number;
  hits: number;
  misses: number;
  matches: PatternMatch[];
  miss_details: PatternMiss[];
  by_article: { article_num: number; hit_rate: number; n: number }[];
}

// --- DNA Discovery ---
export interface DnaCandidate {
  phrase: string;
  combined_score: number;
  tfidf_score: number;
  log_odds_ratio: number;
  section_rate: number;
  background_rate: number;
  doc_count: number;
}

export interface DnaDiscoveryResponse {
  positive_count: number;
  background_count: number;
  total_candidates: number;
  candidates: DnaCandidate[];
}

// --- Coverage Analysis ---
export interface CoverageGroup {
  group: string;
  hit_rate: number;
  hits: number;
  total: number;
}

export interface CoverageResponse {
  overall_hit_rate: number;
  total_docs: number;
  total_hits: number;
  groups: CoverageGroup[];
}

// --- Clause Search ---
export interface ClauseMatch {
  doc_id: string;
  borrower: string;
  section_number: string;
  section_heading: string;
  clause_path: string;
  clause_label: string;
  depth: number;
  header_text: string;
  clause_text: string;
  word_count: number;
}

export interface ClauseSearchResponse {
  total: number;
  matches: ClauseMatch[];
}

// --- Jobs ---
export type JobStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface Job {
  job_id: string;
  job_type: string;
  status: JobStatus;
  submitted_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: number;
  progress_message: string;
  params: Record<string, unknown>;
  result_summary: Record<string, unknown> | null;
  error: string | null;
}

export interface JobListResponse {
  total: number;
  jobs: Job[];
}

export interface JobSubmitResponse {
  job_id: string;
  status: JobStatus;
}

// ---------------------------------------------------------------------------
// Phase 7: Ontology Explorer
// ---------------------------------------------------------------------------

export type OntologyNodeType = "domain" | "family" | "concept" | "sub_component" | "parameter";

export interface OntologyTreeNode {
  id: string;
  name: string;
  type: OntologyNodeType;
  level: number;
  domain_id: string;
  family_id?: string;
  corpus_prevalence?: string;
  extraction_difficulty?: string;
  child_count: number;
  children?: OntologyTreeNode[];
}

export interface OntologyTreeResponse {
  roots: OntologyTreeNode[];
  total_nodes: number;
}

export interface OntologyEdge {
  source_id: string;
  target_id: string;
  edge_type: string;
  description: string;
  directionality?: string;
  source_name?: string;
  target_name?: string;
}

export interface OntologyNodeDetail {
  id: string;
  name: string;
  type: OntologyNodeType;
  level: number;
  domain_id: string;
  family_id?: string;
  definition: string;
  definition_source?: string;
  corpus_prevalence?: string;
  extraction_difficulty?: string;
  market_benchmarks?: Record<string, unknown>;
  red_flags?: { severity?: string; text?: string; category?: string; id?: string }[];
  negotiation_spectrum?: Record<string, string>;
  dls_ref?: string[];
  review_ref?: unknown[];
  r18_concept_ids?: string[];
  children_ids: string[];
  incoming_edges: OntologyEdge[];
  outgoing_edges: OntologyEdge[];
  notes: string;
}

export interface OntologyStatsResponse {
  node_count: number;
  edge_count: number;
  domain_count: number;
  family_count: number;
  concept_count: number;
  sub_component_count: number;
  parameter_count: number;
  edge_type_counts: Record<string, number>;
  domain_breakdown: {
    domain_id: string;
    domain_name: string;
    family_count: number;
    node_count: number;
  }[];
  version: string;
  production_date: string;
}

export interface OntologySearchResult {
  id: string;
  name: string;
  type: OntologyNodeType;
  level: number;
  domain_id: string;
  family_id?: string;
  definition_snippet: string;
  match_field: string;
  corpus_prevalence?: string;
}

export interface OntologySearchResponse {
  query: string;
  total: number;
  results: OntologySearchResult[];
}

export interface OntologyEdgesResponse {
  total: number;
  edges: OntologyEdge[];
}

export interface OntologyGraphNode {
  id: string;
  name: string;
  type: OntologyNodeType;
  level: number;
  domain_id: string;
}

export interface OntologyGraphEdge {
  source: string;
  target: string;
  edge_type: string;
  description: string;
}

export interface OntologyGraphResponse {
  center_id: string;
  depth: number;
  nodes: OntologyGraphNode[];
  edges: OntologyGraphEdge[];
}

// ---------------------------------------------------------------------------
// Phase 8: Credit Agreement Reader
// ---------------------------------------------------------------------------

export interface ReaderClause {
  clause_id: string;
  label: string;
  depth: number;
  level_type: string;
  span_start: number;
  span_end: number;
  header_text: string;
  parent_id: string;
  is_structural: boolean;
  parse_confidence: number;
}

export interface ReaderSectionDetail {
  section_number: string;
  heading: string;
  article_num: number;
  word_count: number;
  text: string;
  clauses: ReaderClause[];
}

export interface ReaderDefinition {
  term: string;
  definition_text: string;
  char_start: number;
  char_end: number;
  confidence: number;
}

export interface ReaderDefinitionsResponse {
  doc_id: string;
  definitions: ReaderDefinition[];
}

export interface ReaderSearchResult {
  section_number: string;
  heading: string;
  char_offset: number;
  matched_text: string;
  context_before: string;
  context_after: string;
}

export interface ReaderSearchResponse {
  query: string;
  total: number;
  results: ReaderSearchResult[];
}

// ---------------------------------------------------------------------------
// Phase 9: Strategy Manager + Feedback Backlog
// ---------------------------------------------------------------------------

// --- Strategy ---

export interface StrategySummary {
  concept_id: string;
  concept_name: string;
  family: string;
  validation_status: string;
  version: number;
  heading_pattern_count: number;
  keyword_anchor_count: number;
  dna_phrase_count: number;
  heading_hit_rate: number;
  keyword_precision: number;
  corpus_prevalence: number;
  cohort_coverage: number;
  last_updated: string;
  has_qc_issues: boolean;
}

export interface StrategyListResponse {
  total: number;
  families: { family: string; count: number }[];
  validation_statuses: { status: string; count: number }[];
  strategies: StrategySummary[];
}

export interface StrategyDetail {
  concept_id: string;
  concept_name: string;
  family: string;
  heading_patterns: string[];
  keyword_anchors: string[];
  keyword_anchors_section_only: string[];
  concept_specific_keywords: string[];
  dna_tier1: string[];
  dna_tier2: string[];
  defined_term_dependencies: string[];
  concept_notes: string[];
  fallback_escalation: string | null;
  xref_follow: string[];
  primary_articles: number[];
  primary_sections: string[];
  definitions_article: number | null;
  heading_hit_rate: number;
  keyword_precision: number;
  corpus_prevalence: number;
  cohort_coverage: number;
  dna_phrase_count: number;
  dropped_headings: string[];
  false_positive_keywords: string[];
  template_overrides: [string, string][];
  validation_status: string;
  version: number;
  last_updated: string;
  update_notes: string[];
}

export interface StrategyFamilyStats {
  family: string;
  strategy_count: number;
  avg_heading_hit_rate: number;
  avg_keyword_precision: number;
  avg_corpus_prevalence: number;
  avg_cohort_coverage: number;
  total_dna_phrases: number;
}

export interface StrategyStatsResponse {
  total_strategies: number;
  total_families: number;
  by_validation_status: { status: string; count: number }[];
  by_family: StrategyFamilyStats[];
  overall_avg_heading_hit_rate: number;
  overall_avg_keyword_precision: number;
  overall_avg_corpus_prevalence: number;
  overall_avg_cohort_coverage: number;
}

// --- Feedback ---

export type FeedbackType = "bug" | "improvement" | "question";
export type FeedbackPriority = "high" | "medium" | "low";
export type FeedbackStatus = "open" | "in_progress" | "resolved";

export interface FeedbackItem {
  id: string;
  title: string;
  type: FeedbackType;
  priority: FeedbackPriority;
  status: FeedbackStatus;
  related_concept_id: string | null;
  description: string;
  created_at: string;
  updated_at: string | null;
}

export interface FeedbackListResponse {
  total: number;
  items: FeedbackItem[];
  status_counts: { status: string; count: number }[];
  type_counts: { type: string; count: number }[];
}

export interface FeedbackCreateRequest {
  title: string;
  type: FeedbackType;
  priority?: FeedbackPriority;
  related_concept_id?: string | null;
  description?: string;
}

export interface FeedbackUpdateRequest {
  title?: string;
  type?: FeedbackType;
  priority?: FeedbackPriority;
  status?: FeedbackStatus;
  related_concept_id?: string | null;
  description?: string;
}

// ---------------------------------------------------------------------------
// Phase 10: Review Operations
// ---------------------------------------------------------------------------

export interface ReviewStrategyTimelineVersion {
  version: number;
  path: string;
  resolved_path: string;
  raw_path: string;
  note: string;
  previous_version: number | null;
  heading_pattern_count: number;
  keyword_anchor_count: number;
  dna_phrase_count: number;
  heading_hit_rate: number;
  keyword_precision: number;
  cohort_coverage: number;
  judge: {
    exists: boolean;
    path: string;
    precision_estimate: number;
    weighted_precision_estimate: number;
    n_sampled: number;
  };
  delta: {
    heading_pattern_count?: number;
    keyword_anchor_count?: number;
    dna_phrase_count?: number;
    heading_hit_rate?: number;
    keyword_precision?: number;
    cohort_coverage?: number;
  };
}

export interface ReviewStrategyTimelineResponse {
  concept_id: string;
  total_versions: number;
  versions: ReviewStrategyTimelineVersion[];
}

export interface ReviewEvidenceRow {
  concept_id: string;
  record_type: string;
  doc_id: string;
  template_family: string;
  section_number: string;
  heading: string;
  clause_path: string;
  score: number | null;
  outlier_level: string;
  source_tool: string;
  created_at: string;
  path: string;
}

export interface ReviewEvidenceResponse {
  filters: {
    concept_id: string;
    template_family: string;
    record_type: string;
    limit: number;
    offset: number;
  };
  files_scanned: number;
  rows_scanned: number;
  rows_matched: number;
  rows_returned: number;
  has_prev: boolean;
  has_next: boolean;
  rows: ReviewEvidenceRow[];
}

export interface ReviewCoverageCell {
  concept_id: string;
  template_family: string;
  hits: number;
  total: number;
  hit_rate: number;
}

export interface ReviewCoverageHeatmapResponse {
  concepts: string[];
  templates: string[];
  cells: ReviewCoverageCell[];
  top_concepts: number;
}

export interface ReviewJudgeHistoryRow {
  version: number;
  path: string;
  precision_estimate: number;
  weighted_precision_estimate: number;
  n_sampled: number;
  correct: number;
  partial: number;
  wrong: number;
  generated_at: string;
  run_id: string;
}

export interface ReviewJudgeHistoryResponse {
  concept_id: string;
  history: ReviewJudgeHistoryRow[];
}

export interface ReviewAgentActivityRow {
  family: string;
  status: string;
  iteration_count: number;
  current_concept_id: string;
  last_strategy_version: number;
  last_coverage_hit_rate: number;
  last_session: string;
  last_pane: string;
  last_start_at: string;
  last_update: string;
  stale: boolean;
  checkpoint_path: string;
}

export interface ReviewAgentActivityResponse {
  total: number;
  stale_minutes: number;
  stale_count: number;
  agents: ReviewAgentActivityRow[];
}

// ---------------------------------------------------------------------------
// Phase 11: ML & Learning
// ---------------------------------------------------------------------------

export interface ReviewQueueKpis {
  total_queue: number;
  high_priority: number;
  medium_priority: number;
  low_priority: number;
  concepts_affected: number;
  families_affected: number;
}

export interface ReviewQueueConfidenceComponents {
  score: number;
  margin: number;
  channels: number;
  heading: number;
  keyword: number;
  dna: number;
}

export interface ReviewQueueItem {
  priority: "high" | "medium" | "low";
  priority_score: number;
  concept_id: string;
  doc_id: string;
  template_family: string;
  section_number: string;
  heading: string;
  score: number | null;
  match_type: string;
  confidence_final: number;
  confidence_components: ReviewQueueConfidenceComponents;
  outlier_level: string;
  outlier_score: number;
  outlier_flags: string[];
  risk_components: Record<string, number>;
  source_tool: string;
  strategy_version: number;
  review_reasons: string[];
}

export interface ReviewQueueResponse {
  kpis: ReviewQueueKpis;
  filters: {
    priority: string;
    concept_id: string;
    template_family: string;
    limit: number;
    offset: number;
  };
  total_matched: number;
  has_prev: boolean;
  has_next: boolean;
  items: ReviewQueueItem[];
  facets: {
    concepts: { concept_id: string; count: number }[];
    templates: { template_family: string; count: number }[];
  };
}

export interface HeadingCluster {
  heading_display: string;
  heading_normalized: string;
  doc_count: number;
  doc_ids: string[];
  template_families: string[];
  avg_score: number;
  min_score: number;
  max_score: number;
  match_types: string[];
  in_strategy: boolean;
  is_orphan: boolean;
}

export interface HeadingClusterKpis {
  total_clusters: number;
  known_headings: number;
  unknown_headings: number;
  orphan_headings: number;
  total_hits: number;
  unique_docs: number;
}

export interface HeadingClustersResponse {
  concept_id: string;
  concept_name: string;
  strategy_heading_patterns: string[];
  kpis: HeadingClusterKpis;
  clusters: HeadingCluster[];
}

export interface ConceptWithEvidence {
  concept_id: string;
  hit_count: number;
}

export interface ConceptsWithEvidenceResponse {
  concepts: ConceptWithEvidence[];
}
