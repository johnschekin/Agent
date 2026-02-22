# MVP Phase A: Single-Agent Pilot with Full Tool Suite

**Status**: Active implementation target
**Goal**: One human-driven agent (Indebtedness family) with a complete, effective CLI tool suite
**Prerequisite for**: Phase B (quality hardening), Phase C (swarm), Phase D (dashboard)

---

## Scope

### Core Library (src/agent/) — 8 modules

| Module | Source | Description |
|--------|--------|-------------|
| `textmatch.py` | VP `infra/textmatch.py` (verbatim port) | PhraseHit, heading_matches, keyword_density, section_dna_density |
| `html_utils.py` | VP `infra/html.py` + VP `infra/io.py` | strip_html, normalize_html (inverse map), read_file (encoding fallback) |
| `section_parser.py` | VP `l0/_doc_parser.py` + `l0/_parsing_types.py` | OutlineArticle, OutlineSection, article/section extraction |
| `clause_parser.py` | VP `l0/_clause_tree.py` + `l0/_enumerator.py` | ClauseNode AST, enumeration parsing, depth tracking |
| `definitions.py` | TI `corpus_classifier.py` patterns | 5-engine parallel regex extraction |
| `dna.py` | VP `l1/discovery/section_analyzer.py` | TF-IDF + log-odds rank fusion, validation gates |
| `corpus.py` | New (DuckDB-backed) | CorpusIndex class, iter_docs, query sections/clauses/definitions |
| `strategy.py` | VP `contracts/discovery.py` + enrichments | Strategy dataclass, load/save/merge/version |

### CLI Tools (scripts/) — 12 tools

**Group A: Search & Access (4)**
1. `corpus_search.py` — Full-text pattern search across corpus
2. `section_reader.py` — Read section with --auto-unroll definitions
3. `sample_selector.py` — Stratified sample selection
4. `metadata_reader.py` — Query corpus metadata

**Group B: Pattern Testing (3)**
5. `pattern_tester.py` — Test strategy with smart failure summaries (log-odds on misses)
6. `coverage_reporter.py` — Hit rates by template group
7. `heading_discoverer.py` — Discover heading variants

**Group C: Discovery (2)**
8. `dna_discoverer.py` — Statistical phrase discovery (TF-IDF + log-odds)
9. `definition_finder.py` — Extract defined terms from documents

**Group D: Drill-Down (1)**
10. `child_locator.py` — Find child patterns within parent sections (clause-level AST)

**Group E: Persistence (2)**
11. `evidence_collector.py` — Save matched spans with provenance
12. `strategy_writer.py` — Persist strategy with regression circuit breaker

**Plus workspace setup:**
13. `setup_workspace.py` — Initialize agent workspace from expert materials

### Corpus Ingestion

- `scripts/build_corpus_index.py` — Process docs → DuckDB (staged: 500 first)
- `scripts/sync_corpus.py` — Download from S3 (staged: 500 → 5K → 30K)

### NOT in MVP (deferred to Phase B+)

- `llm_judge.py` — Deferred to Phase B (advisory, not blocking)
- `template_classifier.py` — Deferred to Phase B
- `structural_mapper.py` — Deferred to Phase B
- Swarm infrastructure — Deferred to Phase C
- Dashboard — Deferred to Phase D
- Full 30K Ray ingestion — Deferred to Phase E

---

## Key Design Decisions (incorporating feedback)

### 1. Staged Ingestion (not all 30K at once)
- **Gate 1**: 500 docs → validate parser quality, concept precision
- **Gate 2**: 5,000 docs → validate template diversity, strategy robustness
- **Gate 3**: 30,000 docs → full production run (Phase E, Ray cluster)

### 2. DuckDB as Immutable Snapshots
- One writer job produces versioned `corpus.duckdb` files
- All CLI tools open read-only (`read_only=True`)
- No concurrent write contention by design
- Schema version table in every DuckDB file

### 3. Gold Set Before Tuning
- Create fixed, stratified human-labeled ground truth (family + child level)
- Reserve blind holdout (20% of gold set)
- Measure precision/recall against gold set, not just self-reported hit rates
- Gold set protocol defined before first strategy iteration

### 4. Non-Regression with Confidence Bounds
- `strategy_writer.py` checks regression on fixed regression set
- Allows explicit exceptions for known tradeoffs
- Uses confidence intervals, not hard thresholds
- Monotonic improvement is a goal, not a hard gate

### 5. Canonical Offset Contract
- All char offsets reference normalized text (output of `normalize_html`)
- InverseMap provides normalized→raw HTML mapping
- Sections use global char offsets (never section-relative)
- Clauses use global char offsets (inherited from sections)
- Evidence spans carry (doc_id, char_start, char_end) as canonical coordinates

### 6. Schema Versioning
- `_schema_version` table in corpus.duckdb: `(table_name, version, created_at)`
- Every CLI tool checks schema version on startup
- Migration scripts in `scripts/migrations/`

---

## Build Order

### Step 1: Project Skeleton ✓
- pyproject.toml, CLAUDE.md, .gitignore, directory structure
- git init, copy ontology + bootstrap data from VP

### Step 2: Core Library
- textmatch.py (verbatim port from VP)
- html_utils.py (VP normalize + encoding fallback)
- strategy.py (rich schema + versioned persistence)
- corpus.py (DuckDB-backed corpus index)

### Step 3: Parsing Library
- section_parser.py (hybrid VP+TI)
- clause_parser.py (VP clause_tree)
- definitions.py (TI 5-engine)
- dna.py (VP L1 TF-IDF + log-odds)

### Step 4: Corpus Ingestion
- sync_corpus.py (S3 → local, staged)
- build_corpus_index.py (local, 500-doc gate)

### Step 5: CLI Tools (Search + Test + Discovery + Persist)
- All 12 tools + setup_workspace

### Step 6: Pilot Execution
- setup_workspace.py for indebtedness
- Manual agent run (human in terminal, not swarm)
- Iterate strategies against 500-doc corpus

---

## Verification

### Unit Tests
- textmatch: heading_matches, keyword_density, dna_density
- html_utils: strip_html, normalize_html inverse map correctness
- section_parser: article/section extraction on real HTML samples
- clause_parser: enumeration parsing, depth tracking, nested AST
- definitions: all 5 regex engines on known patterns
- strategy: load/save/merge round-trip
- corpus: DuckDB read/write/query

### Integration Tests
- Build corpus_index on 10-doc fixture corpus
- Run each CLI tool, verify JSON output structure
- End-to-end: ingest → search → test → refine → persist

### MVP Acceptance Criteria
- Indebtedness family-level: >80% clause-level hit rate on 500-doc corpus
- At least 5 child concepts with working patterns
- Evidence files with provenance-grounded matches
- Strategy versioning with iterative improvement history
- Coverage >70% across observed template variants
- Gold set precision measured (target: ≥80%)
