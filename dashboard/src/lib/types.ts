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

export interface ArticleRecord {
  article_num: number;
  label: string;
  title: string;
  concept: string | null;
  char_start: number;
  char_end: number;
  is_synthetic: boolean;
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
  articles: ArticleRecord[];
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
  categories: { category: string; count: number; tier: string }[];
  cases: EdgeCaseRecord[];
}

// --- Edge Case Clause Detail (drill-down) ---
export interface EdgeCaseClauseDetail {
  section_number: string;
  section_heading: string;
  clause_id: string;
  label: string;
  depth: number;
  level_type: string;
  parent_id: string;
  is_structural: boolean;
  parse_confidence: number;
  header_text: string;
  span_start: number;
  span_end: number;
  tree_level: number;
}

export interface EdgeCaseClauseDetailResponse {
  doc_id: string;
  category: string;
  total_flagged: number;
  clauses: EdgeCaseClauseDetail[];
}

// --- Edge Case Definition Detail (drill-down) ---
export interface EdgeCaseDefinitionDetail {
  term: string;
  pattern_engine: string;
  char_start: number | null;
  char_end: number | null;
  definition_length: number;
  section_number: string;
  section_heading: string;
  tail_snippet: string;
}

export interface EdgeCaseDefinitionDetailResponse {
  doc_id: string;
  category: string;
  total_flagged: number;
  definitions: EdgeCaseDefinitionDetail[];
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
// Corpus Query Builder
// ---------------------------------------------------------------------------

export interface ArticleConceptsResponse {
  concepts: string[];
}

export interface CorpusQueryArticleRow {
  concept: string | null;
  title: string;
  doc_count: number;
  section_count: number;
  example_doc_ids: string[];
}

export interface CorpusQuerySectionRow {
  heading: string;
  frequency: number;
  doc_count: number;
  avg_word_count: number;
  example_doc_ids: string[];
}

export interface CorpusQueryClauseRow {
  doc_id: string;
  borrower: string;
  article_num: number;
  article_title: string;
  article_concept: string | null;
  section_number: string;
  section_heading: string;
  clause_id: string;
  label: string;
  depth: number;
  header_text: string;
  clause_text: string;
}

export interface CorpusQueryResponse {
  total_articles: number;
  total_sections: number;
  total_clauses: number;
  unique_docs: number;
  articles: CorpusQueryArticleRow[];
  sections: CorpusQuerySectionRow[];
  clauses: CorpusQueryClauseRow[];
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
  section_char_start?: number | null;
  section_char_end?: number | null;
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
// Phase 9: Feedback Backlog
// ---------------------------------------------------------------------------

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
// Phase 3: Bulk Section-to-Ontology-Family Linking
// ---------------------------------------------------------------------------

// ── Link roles ────────────────────────────────────────────────────────────

export type LinkRole = "primary_covenant" | "definitions_support" | "secondary_signal" | "xref_support";

export type LinkStatus = "active" | "pending_review" | "unlinked" | "deferred" | "bookmarked";

export type ConfidenceTier = "high" | "medium" | "low";

// ── Core link types ──────────────────────────────────────────────────────

export interface FamilyLink {
  link_id: string;
  doc_id: string;
  borrower: string;
  section_number: string;
  scope_id?: string;
  ontology_node_id?: string | null;
  clause_id?: string | null;
  clause_char_start?: number | null;
  clause_char_end?: number | null;
  clause_text?: string | null;
  heading: string;
  family_id: string;
  family_name: string;
  confidence: number;
  confidence_tier: ConfidenceTier;
  confidence_breakdown?: Record<string, unknown> | null;
  link_role: LinkRole;
  status: LinkStatus;
  rule_id: string | null;
  run_id: string | null;
  created_at: string;
  updated_at: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  note: string | null;
  section_text_hash?: string | null;
}

export interface FamilyLinkSummary {
  total: number;
  by_family: { family_id: string; family_name: string; count: number; pending: number }[];
  by_status: { status: LinkStatus; count: number }[];
  by_confidence_tier: { tier: ConfidenceTier; count: number }[];
  unique_docs: number;
  pending_review: number;
  unlinked: number;
  drift_alerts: number;
}

export interface LinksListResponse {
  total: number;
  page: number;
  page_size: number;
  links: FamilyLink[];
  summary: FamilyLinkSummary;
}

// ── Filter types ─────────────────────────────────────────────────────────

export interface FilterMatch {
  type: "match";
  field?: string;
  value: string;
  case_sensitive?: boolean;
}

export interface FilterGroup {
  type: "group";
  operator: "and" | "or" | "not";
  children: FilterExpression[];
}

export type FilterExpression = FilterMatch | FilterGroup;

// ── Confidence & Why-matched ─────────────────────────────────────────────

export interface WhyMatchedFactor {
  factor: string;
  score: number;
  weight: number;
  detail: string;
  /** Evidence items (e.g., matched DNA phrases, keyword hits) */
  evidence?: string[];
}

export interface WhyMatched {
  link_id: string;
  confidence: number;
  confidence_tier: ConfidenceTier;
  factors: WhyMatchedFactor[];
  heading_matched: boolean;
  keyword_density: number;
  dna_density: number;
  embedding_similarity: number | null;
}

export interface WhyNotMatched {
  doc_id: string;
  section_number: string;
  family_id: string;
  nearest_score: number;
  missing_factors: string[];
  suggestion: string;
  rule_ast?: Record<string, unknown>;
  traffic_tree?: TrafficLightNode | null;
  evaluated_heading?: string;
}

// ── Preview / Apply ─────────────────────────────────────────────────────

export interface PreviewCandidate {
  candidate_id: string;
  doc_id: string;
  borrower: string;
  section_number: string;
  clause_id?: string;
  clause_path?: string;
  clause_key?: string;
  clause_label?: string;
  clause_char_start?: number | null;
  clause_char_end?: number | null;
  clause_text?: string;
  defined_term?: string;
  definition_char_start?: number | null;
  definition_char_end?: number | null;
  definition_text?: string;
  heading: string;
  confidence: number;
  confidence_tier: ConfidenceTier;
  factors: WhyMatchedFactor[];
  verdict: "pending" | "accepted" | "rejected" | "deferred";
  priority_score?: number;
  existing_link_id: string | null;
}

export interface LinkPreviewResponse {
  preview_id: string;
  family_id: string;
  ontology_node_id?: string | null;
  rule_id: string | null;
  candidate_count: number;
  by_confidence_tier: { high: number; medium: number; low: number };
  candidate_set_hash: string;
  created_at: string;
  expires_at: string;
}

export interface PreviewCandidatesResponse {
  total: number;
  items: PreviewCandidate[];
  candidate_set_hash?: string;
  next_cursor?: {
    after_score: number;
    after_doc_id: string;
    after_candidate_id?: string;
  } | null;
  page?: number;
  page_size?: number;
}

export interface LinkApplyRequest {
  preview_id: string;
  candidate_set_hash: string;
}

export interface LinkApplyResponse {
  job_id: string;
  preview_id: string;
  status: string;
}

// ── Rules ──────────────────────────────────────────────────────────────

export interface LinkRule {
  rule_id: string;
  family_id: string;
  ontology_node_id?: string | null;
  family_name: string;
  parent_family_id?: string | null;
  parent_rule_id?: string | null;
  parent_run_id?: string | null;
  scope_mode?: "corpus" | "inherited";
  name: string;
  filter_dsl: string;                                     // NEW: full multi-field DSL
  result_granularity: "section" | "clause" | "defined_term"; // NEW
  heading_filter_ast: Record<string, unknown>;            // KEPT: backward compat
  heading_filter_dsl: string;                             // KEPT: backward compat
  keyword_anchors: string[];
  dna_phrases: string[];
  status: "draft" | "published" | "archived";
  version: number;
  created_at: string;
  updated_at: string | null;
  pin_count: number;
  last_eval_pass_rate: number | null;
  locked_by?: string | null;
  locked_at?: string | null;
}

export interface LinkRuleListResponse {
  total: number;
  rules: LinkRule[];
}

export interface RulePin {
  pin_id: string;
  rule_id: string;
  doc_id: string;
  section_number: string;
  heading: string;
  expected_verdict: "true_positive" | "true_negative";
  created_at: string;
  note: string | null;
}

export interface RulePinListResponse {
  total: number;
  pins: RulePin[];
}

export interface PinEvaluation {
  pin_id: string;
  rule_id: string;
  passed: boolean;
  actual_confidence: number;
  actual_tier: ConfidenceTier;
  expected_verdict: string;
  detail: string;
}

export interface PinEvaluationResponse {
  rule_id: string;
  total_pins: number;
  passed: number;
  failed: number;
  pass_rate: number;
  evaluations: PinEvaluation[];
}

// ── DSL Validation ──────────────────────────────────────────────────────

export interface DslError {
  message: string;
  position: number;
  field?: string;
}

export interface DslValidationResponse {
  text_fields: Record<string, unknown>;
  meta_fields: Record<string, unknown>;
  normalized_text: string;
  errors: DslError[];
  query_cost: number;
}

// ── Runs ──────────────────────────────────────────────────────────────

export interface LinkRun {
  run_id: string;
  run_type: "full" | "canary" | "apply";
  family_id: string;
  base_family_id?: string;
  scope_id?: string;
  ontology_node_id?: string | null;
  rule_id: string | null;
  parent_family_id?: string | null;
  parent_run_id?: string | null;
  scope_mode?: "corpus" | "inherited";
  corpus_version: string;
  corpus_doc_count: number;
  parser_version: string;
  links_created: number;
  conflicts_detected: number;
  started_at: string;
  completed_at: string | null;
  status: "running" | "completed" | "failed";
}

export interface LinkRunListResponse {
  total: number;
  runs: LinkRun[];
}

// ── Link Jobs ──────────────────────────────────────────────────────────

export type LinkJobStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface LinkJob {
  job_id: string;
  job_type: string;
  status: LinkJobStatus;
  submitted_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: number;
  progress_message: string;
  params: Record<string, unknown>;
  result_summary: Record<string, unknown> | null;
  error: string | null;
}

export interface LinkJobListResponse {
  total: number;
  jobs: LinkJob[];
}

export interface LinkJobSubmitResponse {
  job_id: string;
  status: LinkJobStatus;
}

// ── Conflicts ──────────────────────────────────────────────────────────

export interface ConflictPolicy {
  family_a: string;
  family_b: string;
  policy: "coexist" | "exclusive" | "subsumes" | "compound_covenant";
  reason: string | null;
  is_override: boolean;
}

export interface ConflictGroup {
  doc_id: string;
  section_number: string;
  heading: string;
  family_count: number;
  families: string[];
  policies: ConflictPolicy[];
  links?: {
    link_id: string;
    family_id: string;
    evidence_count: number;
  }[];
  evidence_by_family?: Record<
    string,
    {
      link_id: string;
      total_count: number;
      unique_count: number;
    }
  >;
}

export interface ConflictsResponse {
  total: number;
  conflicts: ConflictGroup[];
}

export interface ConflictPoliciesResponse {
  total: number;
  policies: ConflictPolicy[];
}

// ── Macros ──────────────────────────────────────────────────────────────

export interface LinkMacro {
  name: string;
  description: string;
  family_id: string | null;
  ast_json: string;
  created_at: string;
  usage_count?: number;
}

export interface MacrosResponse {
  total: number;
  macros: LinkMacro[];
}

// ── Template Baselines ──────────────────────────────────────────────────

export interface TemplateBaseline {
  id: string;
  family_id: string;
  template: string;
  expected_sections: string[];
  min_confidence: number;
  description: string | null;
  created_at: string;
}

export interface TemplateBaselinesResponse {
  total: number;
  baselines: TemplateBaseline[];
}

// ── Review Sessions ─────────────────────────────────────────────────────

export interface ReviewSession {
  session_id: string;
  family_id: string | null;
  started_at: string;
  last_cursor: string | null;
  total_reviewed: number;
  total_unlinked: number;
  total_bookmarked: number;
  total_links: number;
}

export interface ReviewSessionResponse {
  session: ReviewSession;
}

export interface ReviewMark {
  mark_id: string;
  session_id: string;
  link_id: string;
  action: "reviewed" | "unlinked" | "relinked" | "bookmarked" | "pinned_tp" | "pinned_tn" | "deferred" | "reassigned" | "noted";
  reason: string | null;
  created_at: string;
}

export interface ReviewMarksResponse {
  total: number;
  marks: ReviewMark[];
}

// ── Undo / Redo ─────────────────────────────────────────────────────────

export interface UndoBatch {
  batch_id: string;
  action_type: string;
  affected_link_ids: string[];
  created_at: string;
  undone: boolean;
}

export interface UndoResponse {
  undone: boolean;
  batch_id: string;
  restored_count: number;
}

export interface RedoResponse {
  redone: boolean;
  batch_id: string;
  restored_count: number;
}

// ── Drift & Analytics ───────────────────────────────────────────────────

export interface DriftAlert {
  alert_id: string;
  family_id: string;
  rule_id: string | null;
  drift_type: string;
  severity: "high" | "medium" | "low";
  detail: string;
  detected_at: string;
  resolved: boolean;
}

export interface DriftAlertsResponse {
  total: number;
  alerts: DriftAlert[];
}

export interface DriftCheck {
  check_id: string;
  family_id: string;
  run_at: string;
  baseline_run_id: string;
  current_run_id: string;
  link_count_delta: number;
  confidence_delta: number;
  new_conflicts: number;
  drift_detected: boolean;
}

export interface DriftChecksResponse {
  total: number;
  checks: DriftCheck[];
}

export interface BatchRunSummary {
  run_id: string;
  run_type: string;
  family_id: string;
  base_family_id?: string;
  scope_id?: string;
  ontology_node_id?: string | null;
  links_created: number;
  conflicts_detected: number;
  started_at: string;
  completed_at: string | null;
  status: string;
}

export interface AnalyticsDashboard {
  total_links: number;
  total_runs: number;
  total_conflicts: number;
  total_drift_alerts: number;
  links_by_family: {
    family_id: string;
    scope_id?: string;
    base_family_id?: string;
    ontology_node_id?: string | null;
    count: number;
  }[];
  links_by_status: { status: string; count: number }[];
  confidence_distribution: { tier: string; count: number }[];
  recent_runs: BatchRunSummary[];
  recent_alerts: DriftAlert[];
}

// ── Intelligence overlay ─────────────────────────────────────────────────

export interface LinkIntelligenceValueCount {
  value: string;
  count: number;
}

export interface LinkIntelligenceStrategySignal {
  concept_id: string;
  concept_name: string;
  family_id?: string | null;
  family: string;
  validation_status: string;
  version: number;
  heading_pattern_count: number;
  keyword_anchor_count: number;
  dna_phrase_count: number;
  heading_hit_rate: number;
  keyword_precision: number;
  cohort_coverage: number;
  corpus_prevalence: number;
  last_updated: string;
}

export interface LinkIntelligenceSignalsResponse {
  scope_id?: string | null;
  scope_name: string;
  total_strategies: number;
  strategies: LinkIntelligenceStrategySignal[];
  top_heading_patterns: LinkIntelligenceValueCount[];
  top_keyword_anchors: LinkIntelligenceValueCount[];
  top_dna_phrases: LinkIntelligenceValueCount[];
}

export interface LinkIntelligenceEvidenceRow {
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

export interface LinkIntelligenceEvidenceTemplate {
  template_family: string;
  hits: number;
  total: number;
  hit_rate: number;
}

export interface LinkIntelligenceEvidenceResponse {
  scope_id?: string | null;
  scope_name: string;
  filters: {
    record_type: string;
    limit: number;
    offset: number;
  };
  summary: {
    files_scanned: number;
    rows_scanned: number;
    rows_matched: number;
    rows_returned: number;
    scope_total: number;
    scope_hits: number;
    scope_hit_rate: number;
    has_prev: boolean;
    has_next: boolean;
  };
  templates: LinkIntelligenceEvidenceTemplate[];
  rows: LinkIntelligenceEvidenceRow[];
}

export interface LinkIntelligenceOpsAgent {
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

export interface LinkIntelligenceOpsJob {
  job_id: string;
  job_type: string;
  status: string;
  submitted_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  progress: number;
  progress_message: string;
  scope_id?: string | null;
  error?: string | null;
}

export interface LinkIntelligenceOpsRun {
  run_id: string;
  run_type: string;
  family_id: string;
  scope_id: string;
  ontology_node_id?: string | null;
  links_created: number;
  conflicts_detected: number;
  started_at: string | null;
  completed_at: string | null;
  status: string;
}

export interface LinkIntelligenceOpsResponse {
  scope_id?: string | null;
  scope_name: string;
  stale_minutes: number;
  agents: {
    total: number;
    stale_count: number;
    items: LinkIntelligenceOpsAgent[];
  };
  jobs: {
    total: number;
    pending: number;
    running: number;
    failed: number;
    items: LinkIntelligenceOpsJob[];
  };
  runs: {
    total: number;
    running: number;
    completed: number;
    items: LinkIntelligenceOpsRun[];
  };
}

// ── Calibration ─────────────────────────────────────────────────────────

export interface LinkCalibration {
  family_id: string;
  threshold_high: number;
  threshold_medium: number;
  sample_size: number;
  calibrated_at: string;
}

export interface CalibrationsResponse {
  total: number;
  calibrations: LinkCalibration[];
}

// ── Reassign & Roles ────────────────────────────────────────────────────

export interface ReassignSuggestion {
  family_id: string;
  family_name: string;
  confidence: number;
  reason: string;
}

export interface ReassignSuggestionsResponse {
  link_id: string;
  current_family_id: string;
  suggestions: ReassignSuggestion[];
}

export interface RoleUpdateResponse {
  link_id: string;
  old_role: LinkRole;
  new_role: LinkRole;
  updated: boolean;
}

// ── Context strip ───────────────────────────────────────────────────────

export interface ContextStripDefinition {
  term: string;
  definition_text: string;
}

export interface ContextStripXref {
  section_ref: string;
  heading: string;
  text_preview: string;
}

export interface ContextStripData {
  link_id: string;
  primary_covenant_heading: string;
  primary_covenant_preview: string;
  definitions: ContextStripDefinition[];
  xrefs: ContextStripXref[];
  section_text?: string | null;
  section_families?: {
    family_id: string;
    family_name: string;
    is_current?: boolean;
  }[];
}

// ── Comparables ─────────────────────────────────────────────────────────

export interface ComparableSection {
  doc_id: string;
  borrower: string;
  section_number: string;
  heading: string;
  template_family: string;
  similarity_score: number;
  text_preview: string;
}

export interface ComparablesResponse {
  link_id: string;
  comparables: ComparableSection[];
}

// ── Cross-ref peek ──────────────────────────────────────────────────────

export interface CrossrefPeekResponse {
  section_ref: string;
  heading: string;
  text: string;
}

// ── Rule evaluate-text ──────────────────────────────────────────────────

export interface RuleEvaluateTextResponse {
  matched: boolean;
  traffic_light: "green" | "yellow" | "red";
  matched_nodes: Record<string, unknown>[];
  traffic_tree?: TrafficLightNode | null;
  match_type?: string;
  matched_value?: string;
}

// ── Counterfactual coverage ─────────────────────────────────────────────

export interface CounterfactualResponse {
  new_hits: number;
  false_positives: number;
  total_matched: number;
}

// ── Embeddings ──────────────────────────────────────────────────────────

export interface SectionEmbedding {
  doc_id: string;
  section_number: string;
  embedding_dim: number;
  computed_at: string;
}

export interface FamilyCentroid {
  family_id: string;
  family_name: string;
  centroid_dim: number;
  sample_size: number;
  computed_at: string;
}

export interface EmbeddingsStatsResponse {
  total_embeddings: number;
  total_centroids: number;
  embeddings: SectionEmbedding[];
  centroids: FamilyCentroid[];
}

// ── Starter Kits ────────────────────────────────────────────────────────

export interface StarterKit {
  family_id: string;
  family_name: string;
  suggested_headings: string[];
  suggested_keywords: string[];
  suggested_dna_phrases: string[];
  suggested_defined_terms?: string[];
  location_priors?: { article_concept?: string; section_range?: string; probability?: number }[];
  exclusions?: string[];
  template_rule_ast: Record<string, unknown>;
  example_doc_ids: string[];
  notes: string;
}

export interface StarterKitsResponse {
  total: number;
  kits: StarterKit[];
}

// ── Compound covenants ──────────────────────────────────────────────────

export interface CompoundCovenantState {
  doc_id: string;
  section_number: string;
  heading: string;
  families: string[];
  policy: string;
  is_compound: boolean;
  compound_type: string | null;
  resolution: string | null;
}

export interface CompoundCovenantsResponse {
  total: number;
  compounds: CompoundCovenantState[];
}

// ── Export ───────────────────────────────────────────────────────────────

export interface ExportJobResponse {
  job_id: string;
  format: string;
  status: string;
}

// ── RuleCompareResult ───────────────────────────────────────────────────

export interface RuleCompareDetailItem {
  doc_id: string;
  section_number: string;
  heading: string;
  reason?: string;
}

export interface RuleCompareResult {
  rule_id_a: string;
  rule_id_b: string;
  shared_matches: number;
  only_a_matches: number;
  only_b_matches: number;
  overlap_ratio: number;
  only_a_sample?: RuleCompareDetailItem[];
  only_b_sample?: RuleCompareDetailItem[];
}

// ── Cognitive velocity ──────────────────────────────────────────────────

export interface CognitiveVelocityMetrics {
  reviews_per_minute: number;
  avg_decision_time_ms: number;
  accuracy_estimate: number;
  session_duration_minutes: number;
}

// ── Meta field values ───────────────────────────────────────────────────

export interface MetaFieldValue {
  field: string;
  value: string;
  doc_count: number;
}

// ── Phase 4: Filter AST types ───────────────────────────────────────────

export interface FilterMatchNode {
  value: string;
  negate?: boolean;
}

export interface FilterGroupNode {
  op: "and" | "or";
  children: FilterExpressionNode[];
}

export type FilterExpressionNode = FilterMatchNode | FilterGroupNode;

export function isFilterGroup(node: FilterExpressionNode): node is FilterGroupNode {
  return "op" in node && "children" in node;
}

// ── Phase 4: Coverage gaps ──────────────────────────────────────────────

export interface CoverageGap {
  doc_id: string;
  section_number?: string;
  heading: string;
  template: string;
  nearest_miss_score: number;
  family_id: string;
  is_trivially_fixable: boolean;
  facility_size_mm: number | null;
}

export interface CoverageGapsResponse {
  total_gap_docs: number;
  gap_by_family: Record<string, number>;
  coverage_pct: number;
  gaps: CoverageGap[];
}

// ── Phase 4: Traffic light evaluation tree ──────────────────────────────

export interface TrafficLightNode {
  node: string;
  result: boolean;
  children?: TrafficLightNode[];
  muted?: boolean;
}

// ── Phase 4: Semantic candidates ────────────────────────────────────────

export interface SemanticCandidate {
  doc_id: string;
  section_number: string;
  heading: string;
  similarity: number;
  family_id: string;
}
