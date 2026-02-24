# Agent: Pattern Discovery Swarm for Credit Agreement Ontology Linking

## Context

We have a 3,538-node leveraged finance ontology (49 families) and a current full corpus of 12,583 credit agreements.
The goal: discover reliable patterns (heading, keyword, DNA phrase, structural position) for each
node that can locate it across thousands of CAs — producing labeled data (node-to-clause mappings)
without per-doc LLM calls.

**Approach**: Agent-driven discovery — one Claude Code agent per concept family, running in tmux,
using a suite of CLI tools to iteratively hypothesize/test/refine patterns against the corpus.

**Pilot**: Indebtedness family — two levels deep (family → children → grandchildren).
Richest expert materials, 13+ structural components.

**New repo**: `/Users/johnchtchekine/Projects/Agent`

### Corpus Location

**S3 Bucket**: `s3://edgar-pipeline-documents-216213517387/` (us-east-1)

```
edgar-pipeline-documents-216213517387/
├── documents/                    # HTML credit agreements
│   ├── cik=0000001750/          # Partitioned by EDGAR CIK (company)
│   │   ├── {accession}_{exhibit}.htm    (500KB–1.8MB each)
│   │   └── ...
│   └── ... (999+ CIK folders)
└── metadata/                    # Per-document metadata JSON
    ├── cik=0000001750/
    │   ├── {accession}.meta.json        (~450 bytes each)
    │   └── ...
    └── ...
```

**Decision**: Use staged ingestion gates before full scale:
- Gate 1 (MVP): 500 docs (local)
- Gate 2: 5,000 docs (local)
- Gate 3: full corpus (currently 12,583 docs; Ray cluster optional for refresh-scale runs, Phase E)

### Template Discovery

Statistical clustering approach (improved from TI's boilerplate shingle clustering),
then user labels clusters. Leverages `round12_boilerplate_shingles.py` and
`round5_boilerplate_vintage.py` patterns from TermIntelligence.

### Pilot Scope

Indebtedness family, **two levels deep** (family → ~22 children → grandchildren).
Tests both the family-level section finding and the drill-down workflow.

---

## Phase 1: Project Skeleton & Core Library

### 1.1 Initialize repo

```
Agent/
├── pyproject.toml              # Python 3.12+, deps: orjson, beautifulsoup4, lxml, scikit-learn, pyarrow, duckdb, streamlit
├── CLAUDE.md                   # Project conventions
├── src/agent/
│   ├── __init__.py
│   ├── textmatch.py            # Port from vantage_platform/infra/textmatch.py
│   ├── html_utils.py           # strip_html(), read_file() — from TI _shared.py patterns
│   ├── corpus.py               # Corpus index loader (DuckDB-backed), iter_corpus()
│   ├── section_parser.py       # Two-phase section extraction — hybrid VP+TI
│   ├── clause_parser.py        # Clause-level AST — from VP clause_tree infrastructure
│   ├── dna.py                  # TF-IDF + log-odds discovery — from VP section_analyzer.py
│   ├── definitions.py          # 5-engine definition extractor — from TI corpus_classifier.py
│   ├── metadata.py             # Borrower/agent/facility extraction — from TI metadata_extractor.py
│   └── strategy.py             # Strategy dataclass + load/save/merge/version
├── scripts/                    # CLI tools (agent-callable)
│   ├── corpus_search.py
│   ├── section_reader.py        # --auto-unroll appends linked definitions
│   ├── pattern_tester.py        # Smart failure summarization (log-odds on misses)
│   ├── coverage_reporter.py
│   ├── dna_discoverer.py
│   ├── heading_discoverer.py
│   ├── definition_finder.py
│   ├── child_locator.py         # --auto-unroll appends linked definitions
│   ├── evidence_collector.py
│   ├── strategy_writer.py       # Regression circuit breaker (rejects degrading updates)
│   ├── llm_judge.py             # Precision self-evaluation on random match samples
│   ├── metadata_reader.py
│   ├── template_classifier.py
│   ├── sample_selector.py
│   ├── structural_mapper.py
│   └── setup_workspace.py       # Populate agent workspace from expert materials
├── dashboard/                   # Review dashboard (for human expert)
│   ├── app.py                   # Streamlit/Panel app
│   ├── views/                   # Dashboard views (strategy, evidence, coverage, judge)
│   └── static/
├── swarm/                      # Tmux infrastructure (shell scripts)
│   ├── launch.sh
│   ├── start-agent.sh
│   ├── send-to-agent.sh
│   ├── broadcast.sh
│   ├── status.sh
│   ├── kill.sh
│   ├── dispatch-wave.sh
│   ├── swarm.conf
│   └── prompts/
│       ├── family_agent_base.md    # Base prompt template
│       └── indebtedness.md         # Pilot family prompt
├── workspaces/                 # Agent working directories (gitignored data)
│   └── indebtedness/
│       ├── context/            # Expert materials (copied from TI/analysis)
│       ├── strategies/         # Evolving strategy JSON files
│       ├── evidence/           # Matched spans with provenance
│       └── results/            # Coverage reports, labeled data
├── corpus_index/               # Pre-built corpus data (gitignored)
│   ├── corpus.duckdb           # DuckDB: master index + sections + clauses + definitions
│   └── templates/              # Template family classifications
├── tests/
│   └── ...
└── data/                       # Symlinks or small reference data
    └── ontology_subtrees/      # Per-family JSON extracts from production ontology
```

### 1.2 Core library (`src/agent/`)

Source selection based on detailed comparison of VP L0 vs TI scripts:

**Use VP** (superior implementation):
- `textmatch.py` — Port verbatim from VP. Zero-domain-logic, already clean.
  - Source: `vantage_platform/infra/textmatch.py`
- `html_utils.py` — Use VP's normalize approach (inverse-map tracking for span provenance).
  TI's strip_html() is too simple — no offset tracking for agent evidence citing.
  Add TI's encoding fallback (UTF-8→CP1252→replace) for read_file().
  - Source: `vantage_platform/l0/normalize.py` + `TI/scripts/_shared.py` (read_file only)

**Hybrid VP+TI** (combine strengths):
- `section_parser.py` — VP's typed architecture (OutlineArticle, OutlineSection, char spans)
  + TI's two-phase DOM extraction (3 BeautifulSoup styles + plain-text fallback).
  VP alone misses ~5-10% of EDGAR HTML variants that TI's DOM phase handles.
  - Source: `vantage_platform/l0/outline.py` (core) + `TI/scripts/section_level_parser.py` (DOM phase)

**Use TI** (clearly superior for this area):
- `definitions.py` — TI has 5 parallel regex engines vs VP's single pattern.
  VP misses ~5-8% of definition formats (colon-based, unquoted, HTML-tag variants).
  - Source: `TI/scripts/corpus_classifier.py` (all 5 patterns + guards)
- `metadata.py` — Borrower, admin agent, facility size, dates, entity type.
  - Source: `TI/scripts/metadata_extractor.py`

**Use VP L1** (standalone version):
- `dna.py` — TF-IDF + log-odds ratio (Monroe 2008) + validation gates
  - Source: `vantage_platform/l1/discovery/section_analyzer.py`
  - Config: min_section_rate=0.20, max_bg_rate=0.05, alpha=0.01, tfidf_weight=0.70

**New**:
- `corpus.py` — CorpusIndex class: load index.json, iterate docs, read doc text, filter by metadata
- `strategy.py` — Rich strategy dataclass (see Strategy Schema section below) + versioned persistence

---

## Phase 2: Corpus Ingestion (Staged: 500 → 5K → Full Corpus)

### 2.0 AWS Setup (prerequisite)

Configure AWS CLI for S3 access:
```bash
aws configure  # Set access key, secret, region=us-east-1
aws s3 ls s3://edgar-pipeline-documents-216213517387/  # Verify access
```

### 2.1 S3 Sync

**`scripts/sync_corpus.py`** — Download corpus from S3 to local (used across all gates):
```bash
python3 scripts/sync_corpus.py --bucket edgar-pipeline-documents-216213517387 \
  --local-dir corpus/ --parallel 32
```
- Syncs both `documents/` and `metadata/` prefixes
- Preserves CIK-partitioned structure locally
- Resume-safe (skip existing files by size/etag)
- Merge S3 `.meta.json` into corpus index (filing date, form type, CIK)

Local structure after sync:
```
corpus/
├── documents/cik=XXXXXXXXXX/{accession}_{exhibit}.htm
└── metadata/cik=XXXXXXXXXX/{accession}.meta.json
```

### 2.2 Ray-Based Ingestion Pipeline (AWS Ray Cluster)

**Infrastructure**: Transient AWS Ray cluster for fast parallel processing.
- `infra/ray_cluster.yaml` — Ray cluster config (auto-scaling EC2 spot instances)
- Head node: m5.xlarge, Workers: m5.large × 16-32
- Estimated runtime: environment-dependent; current 12,583-doc full corpus is materially smaller than earlier large-scale assumptions.

**`scripts/build_corpus_index.py`** — Process corpus by stage:
```bash
# Gate 1 (MVP): 500-doc local build
python3 scripts/build_corpus_index.py --corpus-dir corpus/ --output corpus_index/ --workers 8 --limit 500

# Gate 2: 5,000-doc local build
python3 scripts/build_corpus_index.py --corpus-dir corpus/ --output corpus_index/ --workers 8 --limit 5000

# Gate 3 / Phase E: Production full-corpus run on Ray cluster (current full corpus: 12,583 docs)
ray submit infra/ray_cluster.yaml scripts/build_corpus_index.py -- \
  --corpus-dir /mnt/efs/corpus/ --output /mnt/efs/corpus_index/ --ray
```

Per-document processing (parallelized via Ray):
1. Read HTML + merge S3 metadata JSON
2. `html_utils.strip_html()` → normalized text with inverse map
3. `section_parser.extract_sections()` → section boundaries (articles + sections)
4. **`clause_parser.parse_clauses()`** → clause-level AST within each section
   - Enumerations: (a), (b), (i), (ii), (A), (B) → nested ClauseNode tree
   - Depth tracking: section → clause → sub-clause → sub-sub-clause
   - Char spans at every level (for evidence provenance)
   - Adapted from VP's clause_tree infrastructure (ClauseNode with depth, spans)
5. `definitions.extract_definitions()` → all defined terms with text + char offsets
6. `metadata.extract_metadata()` → borrower, agent, dates, facility size

**Storage: DuckDB** (not per-document JSON files — concurrent agent I/O would bottleneck)

All per-doc results written to a single `corpus_index/corpus.duckdb` database:
- **`documents`** table: master index (one row per doc)
- **`sections`** table: section boundaries (one row per section, FK to documents)
- **`clauses`** table: clause AST nodes (one row per clause, FK to sections, self-FK for parent)
- **`definitions`** table: defined terms (one row per definition, FK to documents)
- **`section_text`** table: full section text (lazy-loaded, not held in memory)

Why DuckDB over alternatives:
- **vs JSON files**: per-doc files × 49 concurrent agents = I/O catastrophe. DuckDB handles
  concurrent reads with zero contention (single-writer, multi-reader).
- **vs Parquet**: DuckDB reads Parquet natively, but also supports SQL queries, joins,
  and aggregations that CLI tools need (e.g., "find all sections with heading LIKE '%Indebtedness%'").
  We can always `EXPORT` to Parquet for interop.
- **vs SQLite**: DuckDB is columnar — analytics queries (aggregations, scans across full corpus)
  are 10-100x faster. SQLite is row-oriented and struggles with analytical workloads.
- **vs PostgreSQL**: No server to manage. Single file, zero config, embedded.

**Documents table schema**:
```sql
CREATE TABLE documents (
  doc_id        VARCHAR PRIMARY KEY,  -- sha256_hex[:16]
  cik           VARCHAR,
  accession     VARCHAR,
  path          VARCHAR,
  borrower      VARCHAR,
  admin_agent   VARCHAR,
  facility_size_mm DOUBLE,
  closing_date  DATE,
  filing_date   DATE,
  form_type     VARCHAR,
  doc_type      VARCHAR,
  market_segment VARCHAR,
  template_family VARCHAR,
  section_count  INTEGER,
  clause_count   INTEGER,
  definition_count INTEGER,
  text_length    INTEGER
);
```

### 2.3 Template Discovery (Boilerplate Shingle Clustering, Phase B+)

**`scripts/template_classifier.py`** — Two-phase template discovery:

**Phase A: Boilerplate fingerprinting** (recreated from TI `round12_boilerplate_shingles.py`):
1. Extract boilerplate sections (preamble, recitals, signature blocks, standard definitions)
2. Compute character n-gram shingles (MinHash for scalability)
3. Build similarity matrix via LSH (Locality-Sensitive Hashing)
4. Cluster via DBSCAN or agglomerative clustering

**Phase B: Cluster labeling** (human expert + automated heuristics):
1. For each cluster, show representative excerpts
2. Automated heuristics: search preamble for law firm names, search signature block for
   arranging banks, extract filing date for vintage
3. User labels remaining clusters with law firm / bank / vintage
4. Persist template_family assignment back to corpus_index

Output: `corpus_index/templates/classifications.json` mapping doc_id → template metadata:
```json
{
  "doc_id": {
    "law_firm_borrower": "kirkland",
    "law_firm_lender": "cahill",
    "arranging_bank": "jpmorgan",
    "vintage_era": "2021-2023",
    "cluster_id": 7,
    "confidence": 0.92
  }
}
```

---

## Phase 3: CLI Tool Suite (Final Target — 16 tools)

MVP Phase A uses a focused subset (12 tools + setup workspace). The following are **deferred to Phase B+**:
- `structural_mapper.py`
- `template_classifier.py`
- `llm_judge.py`

Each tool: standalone Python script, argparse CLI, structured JSON output to stdout.
All tools query `corpus.duckdb` via the `corpus.py` library (DuckDB-backed, read-only).

### Group A: Search & Access (4 tools)

**1. `corpus_search.py`** — Full-text pattern search
```
python3 scripts/corpus_search.py --pattern "Limitation on Indebtedness" \
  --context-chars 200 --max-results 50 --sample 500
# Output: [{doc_id, section_path, char_offset, matched_text, context_before, context_after}]
```

**2. `section_reader.py`** — Read a specific section (with optional definition unrolling)
```
python3 scripts/section_reader.py --doc-id abc123 --section "7.01"
python3 scripts/section_reader.py --doc-id abc123 --article VII --auto-unroll
# Output: {doc_id, section_path, heading, text, char_start, char_end, subsection_count,
#          clause_tree: [{depth, enum, text, char_start, char_end, children: [...]}],
#          unrolled_definitions: [{"term": "Indebtedness", "text": "...", "source": "1.01"}]}
# --auto-unroll: appends full text of every capitalized defined term found in the section
```

**3. `sample_selector.py`** — Stratified sample selection
```
python3 scripts/sample_selector.py --n 200 --stratify template_family --seed 42
# Output: [{doc_id, template_family, borrower, facility_size_mm}]
```

**4. `metadata_reader.py`** — Query corpus metadata
```
python3 scripts/metadata_reader.py --doc-id abc123
python3 scripts/metadata_reader.py --filter "admin_agent=JPMorgan" --limit 20
# Output: index entries matching filter
```

### Group B: Pattern Testing (3 tools)

**5. `pattern_tester.py`** — Test a strategy against documents

**Smart failure summarization** — never dumps raw text of missed docs. Instead:
- Log-odds analysis on missed vs. hit documents (which headings/phrases distinguish misses?)
- Template-cluster breakdown (are misses concentrated in one template family?)
- Structural position deviation (misses in Article VI vs. expected Article VII?)
- Heading frequency table on misses (what headings do missed docs actually use?)
- Nearest-miss ranking (docs that *almost* matched, sorted by composite score)

These mathematical summaries give the agent exact, actionable hints without context blowout.

```
python3 scripts/pattern_tester.py --strategy strategies/indebtedness.json \
  --doc-ids sample.txt --verbose
# Output: {
#   hit_rate: 0.87, total_docs: 200, hits: 174, misses: 26,
#   hit_summary: {avg_score: 0.72, heading_hit_rate: 0.95, avg_clause_depth: 2.1},
#   miss_summary: {
#     by_template: {"cahill": 12, "kirkland": 3, "unknown": 11},
#     top_headings_in_misses: [{"Limitation on Debt": 8}, {"Covenants—Debt": 4}],
#     log_odds_discriminators: [
#       {"phrase": "European term loan", "miss_rate": 0.62, "hit_rate": 0.03},
#       {"phrase": "Limitation on Debt", "miss_rate": 0.45, "hit_rate": 0.01}
#     ],
#     structural_deviation: {"article_VI": 15, "article_VIII": 5, "no_article": 6},
#     nearest_misses: [{doc_id, score: 0.41, reason: "heading_variant"}]
#   }
# }
```

**6. `coverage_reporter.py`** — Hit rates by template group
```
python3 scripts/coverage_reporter.py --strategy strategies/indebtedness.json \
  --group-by template_family
# Output: {
#   overall: {hit_rate: 0.87, n: 500},
#   by_group: {"kirkland": {hit_rate: 0.92, n: 85}, "cahill": {hit_rate: 0.78, n: 42}, ...}
# }
```

**7. `heading_discoverer.py`** — Discover heading variants
```
python3 scripts/heading_discoverer.py --seed-headings "Indebtedness,Limitation on Indebtedness" \
  --article-range "6-8" --sample 500
# Output: [{heading_text, frequency, article, section_number, example_doc_ids}]
```

### Group C: Discovery (3 tools)

**8. `dna_discoverer.py`** — Statistical phrase discovery
```
python3 scripts/dna_discoverer.py --positive-sections positive_hits.json \
  --background-sections background.json --top-k 30
# Output: [{phrase, combined_score, tfidf_pctile, log_odds_pctile,
#           section_rate, background_rate, passed_gates: bool}]
```

**9. `definition_finder.py`** — Extract defined terms
```
python3 scripts/definition_finder.py --doc-id abc123
python3 scripts/definition_finder.py --doc-id abc123 --term "Consolidated EBITDA"
# Output: [{term, definition_text, pattern_engine, char_offset}]
```

**10. `structural_mapper.py`** — Map structural positions (**Phase B+; deferred from MVP**)
```
python3 scripts/structural_mapper.py --concept "indebtedness" \
  --heading-patterns "Indebtedness,Limitation on Indebtedness" --sample 500
# Output: {article_distribution: {"VII": 312, "VI": 88, "VIII": 45},
#          section_distribution: {"7.01": 280, "6.01": 75, ...},
#          typical_position: {article: "VII", section: ".01"}}
```

### Group D: Drill-Down (1 tool)

**11. `child_locator.py`** — Find child patterns within parent sections

Exposes full clause AST depth to the agent — not flat text. The agent can write
structural rules (e.g., `target_depth=3, enumeration="(a)"`) instead of fragile regex.

```
python3 scripts/child_locator.py --parent-matches parent_hits.json \
  --child-patterns '{"heading": ["ratio debt", "Ratio-Based"], "keywords": ["leverage ratio"]}' \
  --auto-unroll
# Output: [{doc_id, parent_section, clause_path: "7.01.(a).(ii)",
#           clause_depth: 3, enumeration: "(a)", clause_text: "...",
#           char_start, char_end, match_type: "keyword",
#           unrolled_definitions: [{"term": "...", "text": "..."}]}]
```

### Group E: Persistence & Validation (4 tools)

**12. `evidence_collector.py`** — Save matched spans
```
python3 scripts/evidence_collector.py --matches matches.json \
  --concept-id debt_capacity.indebtedness --workspace workspaces/indebtedness
# Writes: workspaces/indebtedness/evidence/{concept_id}_{timestamp}.jsonl
```

**13. `strategy_writer.py`** — Persist strategy with versioning + regression circuit breaker

Before saving, automatically runs the new strategy against a **regression test set**
(the template clusters where the previous version had >70% hit rate). If any cluster
degrades by more than a configurable threshold (default: 10%), the save is **rejected**
with a diagnostic message.

```
python3 scripts/strategy_writer.py --concept-id debt_capacity.indebtedness \
  --workspace workspaces/indebtedness --strategy updated.json --note "Added Cahill heading variant"
# On success:
#   Writes: workspaces/indebtedness/strategies/debt_capacity.indebtedness_v003.json
#   Updates: workspaces/indebtedness/strategies/current.json (symlink)
# On regression:
#   REJECTED: "Your update improved cahill templates by 2% (78%→80%), but broke
#   kirkland templates by 15% (92%→77%). Revert or fix kirkland before saving."
```

**14. `llm_judge.py`** — Precision self-evaluation via LLM (**Phase B+; deferred from MVP**)

**Phase B+ release gate (not MVP blocking).** Agents should self-evaluate precision, not just recall.
Samples N random matches (default: 20), sends each match + surrounding context to an LLM
judge (Claude Haiku for cost efficiency), asks: "Does this extracted clause actually express
the concept {concept_name}? Rate: correct / partial / wrong."

```
python3 scripts/llm_judge.py --matches matches.json --concept-id debt_capacity.indebtedness \
  --sample 20 --model haiku
# Output: {
#   precision_estimate: 0.85, n_sampled: 20,
#   correct: 17, partial: 2, wrong: 1,
#   wrong_examples: [{doc_id, clause_text, judge_reasoning: "This clause is about Liens, not Indebtedness"}],
#   partial_examples: [{doc_id, clause_text, judge_reasoning: "Contains indebtedness but primarily about acquisitions"}]
# }
```

In Phase B+, require `llm_judge.py` before release-candidate strategy commits.
In MVP Phase A, `llm_judge.py` is advisory/optional.
Results are persisted alongside the strategy version for the human reviewer's dashboard.

**15. `setup_workspace.py`** — Initialize agent workspace
```
python3 scripts/setup_workspace.py --family indebtedness \
  --expert-materials ~/Projects/TermIntelligence/analysis/indebtedness \
  --ontology ~/Projects/vantage_platform/data/ontology/r36a_production_ontology_v2.5.1.json \
  --bootstrap ~/Projects/vantage_platform/src/vantage_platform/configs/search_strategies/bootstrap_all.json
# Creates: workspaces/indebtedness/ with context/, strategies/, evidence/, results/
```

---

## Phase 4: Swarm Infrastructure

Adapted from `/Users/johnchtchekine/Projects/Neutron/tools/swarm/` and `/swarm-phase0/`.

### 4.1 Shell scripts (`swarm/`)

**`launch.sh`** — Create tmux session with configurable pane count
```bash
# Usage: ./swarm/launch.sh [--panes N] [--session NAME]
# Creates N-pane tiled layout, names each pane, sets working dir
```

**`start-agent.sh`** — Start Claude Code in a pane with family prompt
```bash
# Usage: ./swarm/start-agent.sh <family-name> [--backend claude|gemini|codex] [--pane N]
# Starts claude with --dangerously-skip-permissions, waits, sends kickoff prompt
# Applies BSL retrospective lesson: file-based prompts, not CLI args
```

**`send-to-agent.sh`** — Route message to specific agent
```bash
# Usage: ./swarm/send-to-agent.sh <family-name> "<message>"
# Uses temp file for reliable special-char handling
```

**`broadcast.sh`** — Send to all active agents

**`status.sh`** — Show all panes with last output line

**`kill.sh`** — Clean shutdown with "commit WIP" broadcast first

**`dispatch-wave.sh`** — Launch a wave of family agents
```bash
# Usage: ./swarm/dispatch-wave.sh <wave-number> [--dry-run]
# Reads swarm.conf, checks shared progress log, assigns families to panes
```

### 4.2 Agent prompt (`swarm/prompts/family_agent_base.md`)

Each family gets a **base template + domain expert enrichment file**. The domain expert
(user) provides per-family structural guidance that the agent can't discover on its own.

The production ontology (`r36a_production_ontology_v2.5.1.json`) is copied into
`Agent/data/ontology/` during Step 1. The 49 families in this ontology are the
top-level concepts that define the agent swarm's unit of work.

**Per-family expert enrichment** (`swarm/prompts/enrichment/{family}.md`):
User provides for each family — **lightweight, mainly structural location hints**
(user estimates ~15-30 min per family to produce):
- **Primary structural location**: Where this concept lives in the agreement
  (e.g., Incremental → Article II + definitions; Indebtedness → Negative Covenants article + definitions)
- **Key defined terms**: Which Section 1.01 definitions are critical for this family
- **Conceptual article/section name**: "Negative Covenants", "Affirmative Covenants", "Conditions Precedent"
- **Article number hint** (if consistent): "usually Article VII" or "varies"
- Optional: secondary signal locations, edge cases, drafting conventions (added if user knows off-hand)

Template structure:
```markdown
# You are a Pattern Discovery Agent for the {FAMILY} concept family.

## Your Mission
Discover reliable patterns (headings, keywords, DNA phrases) that locate {FAMILY}
concepts in leveraged finance credit agreements. Work iteratively: hypothesize → test → refine.

## Your Expert Context
Read the files in your workspace context/ directory:
- trace.md — domain knowledge, risk flags, market positioning
- components.json — structural sub-components to find 
- relationships.json — how this family connects to others
- ontology_subtree.json — full node tree (children/grandchildren to eventually cover)
- domain_guidance.md — **structural location hints and drafting conventions from domain expert**

## Domain Guidance (from expert)
{DOMAIN_GUIDANCE}
<!-- Injected from swarm/prompts/enrichment/{family}.md -->
<!-- Includes: primary location, secondary signals, drafting conventions, edge cases -->

## Your Tools
[List of all CLI tools with usage examples]

## Your Workflow
1. UNDERSTAND: Read all context files. Start with domain_guidance.md — it tells you WHERE
   to look. Then read trace.md for WHAT to look for. Then components.json for HOW DEEP to go.
2. BOOTSTRAP: Load current strategy. If none, create from expert materials + domain guidance.
3. MAP STRUCTURE: In MVP, start with heading_discoverer + coverage_reporter to validate location hints.
   In Phase B+, run structural_mapper first for explicit structural priors.
4. TEST: Run pattern_tester against sample. Examine coverage_reporter by template family.
5. ANALYZE: Why do misses occur? Different heading? Different article? Different structure entirely?
   Look for secondary signal locations mentioned in domain guidance.
6. REFINE: Update strategy. Add heading variants, keywords, DNA phrases.
7. REPEAT: Test again. Target 85%+ coverage across all template families.
8. DRILL DOWN: Once family-level is solid, work through child concepts via child_locator.
   Within the parent section, look for sub-headings, enumerated baskets ((a), (b), (c)),
   and defined-term boundaries.
9. PERSIST: Save final strategies + evidence. Write labeled_data output.

## Rules
- ALL patterns must be grounded in corpus evidence, never fabricated from training knowledge
- Save evidence for every pattern decision (which docs, which clauses)
- Version your strategies (strategy_writer creates version history)
- **Phase B+ release gate**: run `llm_judge.py` on 20 random matches before release-candidate saves.
  In MVP, this step is optional/advisory and does not block iteration.
- When stuck, examine the miss_summary from pattern_tester — it gives you mathematical hints
  (log-odds discriminators, template breakdown, structural deviation) without raw text
- Target CLAUSE-level matches, not section-level. Use child_locator with clause_depth
  and enumeration patterns, not fragile regex on flat text
- Use --auto-unroll on section_reader and child_locator to see operational reality of clauses
- Check BOTH the primary location AND secondary signal locations from domain guidance
- Report back patterns you discover that weren't in the domain guidance — the expert wants to learn too
- **Circuit breaker**: strategy_writer rejects updates that regress. If you break a template
  cluster that was working, you must fix it before the save is accepted
```

---

## Phase 5: Pilot Execution (Indebtedness)

### 5.1 Setup
1. Run `setup_workspace.py` for indebtedness family
2. Build corpus_index against pilot corpus
3. (Phase B+) Run `template_classifier.py` to classify docs (even partial classification helps)

### 5.2 Manual agent run (before swarm)
First run the pilot agent manually in a terminal (not tmux) to validate the tool suite:
1. Load workspace, read expert materials
2. Test bootstrap strategy from vantage_platform's bootstrap_all.json
3. Run pattern_tester, examine results
4. Iterate on strategy
5. Document what tools were missing or awkward

### 5.3 Swarm pilot
Once tools are validated, run via tmux swarm infrastructure.

---

## Phase 6: Review Dashboard

An **extremely intuitive, customized** dashboard for the domain expert to review
results alongside the coding terminal. Built with Streamlit (rapid iteration,
rich components, zero frontend boilerplate).

### Dashboard views:

**1. Strategy Evolution** — Per-concept timeline:
- Version history with hit rate / precision trend line
- Side-by-side diff of strategy changes between versions
- LLM-judge precision scores per version
- Circuit breaker rejections (what was tried and rejected)

**2. Evidence Browser** — Matched clauses with context:
- Filterable by concept, template family, confidence band
- Click-to-expand: full section text with matched clause highlighted
- Unrolled definitions shown inline
- "Flag as wrong" button → feeds back into agent's next iteration

**3. Coverage Heatmap** — Template family × concept matrix:
- Color-coded cells: green (>80%), yellow (60-80%), red (<60%)
- Click into any cell → drills down to per-doc hits/misses
- Template family rows sorted by corpus share (biggest clusters first)

**4. LLM Judge Review** — Random sample spot-check:
- Shows the same samples the LLM judge evaluated
- Human can override judge verdict (correct/partial/wrong)
- Human overrides fed back as calibration data for future judge runs
- Precision comparison: LLM-judge vs. human agreement rate

**5. Agent Activity** — Live swarm monitoring:
- Per-agent: current concept, iteration count, last strategy version, hit rate trajectory
- Alert panel: agents that have plateaued (no improvement in N iterations)
- "Send message to agent" → routes through tmux `send-to-agent.sh`

### Build approach:
- `dashboard/app.py` — Streamlit entry point, reads DuckDB + workspace files
- `dashboard/views/` — One module per view
- Connects directly to `corpus.duckdb` (read-only) and workspace directories
- Served locally alongside tmux terminal (split screen or second monitor)

---

## Verification

### Unit tests
- textmatch.py: verify heading_matches, keyword_density, dna_density against known inputs
- html_utils.py: verify strip_html on real CA HTML samples
- section_parser.py: verify section extraction on 3-5 known CAs
- clause_parser.py: verify enumeration parsing, depth tracking, nested AST on real sections
- strategy.py: verify load/save/merge/version round-trip
- (Phase B+) llm_judge.py: verify prompt construction, response parsing, precision calculation

### Integration tests
- Build corpus_index on 10-doc mini corpus
- Run each tool against mini corpus, verify JSON output
- Run full agent workflow manually on 3 docs

### Pilot acceptance (clause-level precision)
- Indebtedness family-level: >80% **clause-level** hit rate across pilot corpus.
  "Hit" means the pattern locates the specific clause(s) within a section where the
  concept is expressed — not just the parent section. Where applicable, the
  corresponding defined terms must also be identified (e.g., locating "Indebtedness"
  clause requires also linking to the "Indebtedness" definition in Section 1.01).
  VP's clause_tree infrastructure (ClauseNode AST with depth, spans, confidence)
  provides the clause-level granularity needed for this.
- At least 5 child concepts (general_basket, ratio_debt, ied, contribution_debt,
  acquisition_debt) have working clause-level patterns with definition linkage
- Evidence files contain provenance-grounded matches at clause granularity:
  `{doc_id, section_path, clause_offset, clause_text, linked_definitions[], confidence}`
- Strategy versioning shows iterative refinement history with measurable improvement
- Coverage reporter shows >70% hit rate across each template family (no blind spots)
- (Phase B+) LLM-judge precision ≥ 80% on family-level matches (verified by human spot-check via dashboard)
- No regression: every strategy version in history shows monotonic improvement on regression set

---

## Build Order (Bottom-Up, Each Layer Tested Before Next)

### Step 1: Project Foundation
- `pyproject.toml`, directory structure, `CLAUDE.md`
- `git init`, `.gitignore` (corpus/, corpus_index/, workspaces/)
- Copy ontology into `Agent/data/ontology/` from VP
  (`r36a_production_ontology_v2.5.1.json` — the 49 families are the top-level concepts)
- Copy bootstrap strategies into `Agent/data/bootstrap/` from VP
  (`bootstrap_all.json` — 344 concepts as starting point)
- Basic test structure + a few sample HTML files as fixtures

### Step 2: Core Library (src/agent/)
- `textmatch.py` — **port from VP** verbatim, unit test all 4 functions
- `html_utils.py` — **VP** normalize (with inverse map) + **TI** read_file() encoding fallback
- `strategy.py` — new (schema from VP's ValidatedStrategy + enrichments), test round-trip
- `corpus.py` — new, test with small fixture corpus

### Step 3: Parsing Library (src/agent/)
- `section_parser.py` — **hybrid VP+TI**: VP's typed output architecture (OutlineArticle,
  OutlineSection, char-level spans) + TI's DOM extraction phase (3 BeautifulSoup styles
  for EDGAR variant handling). Test on 5+ real CAs covering different formatting styles.
- `clause_parser.py` — **VP** clause_tree infrastructure: parse enumerations ((a), (i), (A))
  into nested ClauseNode AST with depth, spans, parent references. This is what enables
  clause-level matching instead of section-level. Test on 5+ real sections with deep nesting.
- `definitions.py` — **TI** 5-engine parallel regex extraction (quoted, colon, unquoted,
  U-tag, bold-italic). VP only has 1 pattern. Test all 5 engines.
- `metadata.py` — **TI** borrower/agent/facility extraction. Test on diverse preambles.
- `dna.py` — **VP L1** TF-IDF + log-odds (Monroe 2008). Test on known sections.

### Step 4: AWS Setup + S3 Sync (staged)
- Configure AWS CLI with bucket access
- `scripts/sync_corpus.py` — sync corpus locally for staged builds
- Inspect `.meta.json` files, incorporate into index format

### Step 5: Corpus Ingestion (gated)
- Gate 1: `scripts/build_corpus_index.py --limit 500`
- Gate 2: `scripts/build_corpus_index.py --limit 5000`
- Validate DuckDB tables: documents, sections, clauses, definitions
- Gate 3 / Phase E: Ray cluster config + full-corpus ingestion (current full corpus: 12,583 docs)
- Verify clause-level parsing quality on sample docs before full run

### Step 6: Search & Access Tools
- `corpus_search.py`, `section_reader.py`, `sample_selector.py`, `metadata_reader.py`
- Test each against the built corpus_index

### Step 7: Pattern Testing Tools
- `pattern_tester.py`, `coverage_reporter.py`, `heading_discoverer.py`
- Test with bootstrap strategies from VP's bootstrap_all.json

### Step 8: Discovery Tools
- MVP: `dna_discoverer.py`, `definition_finder.py`
- Phase B+: `structural_mapper.py`
- Test DNA discovery on known Indebtedness sections

### Step 9: Drill-Down + Persistence + Validation Tools
- `child_locator.py` — test with Indebtedness basket sub-sections (clause-level AST)
- `evidence_collector.py`, `strategy_writer.py` (with regression circuit breaker), `setup_workspace.py`
- (Phase B+) `llm_judge.py` — test with known correct/incorrect matches, verify LLM can distinguish

### Step 10: Template Discovery (Phase B+)
- `template_classifier.py` — boilerplate shingle clustering
- Run on full corpus, present clusters for user labeling
- Persist template classifications to corpus_index

### Step 11: Swarm Infrastructure
- Adapt shell scripts from Neutron (`launch.sh`, `start-agent.sh`, etc.)
- `swarm.conf` for family assignments
- Test tmux session creation + message passing

### Step 12: Review Dashboard
- `dashboard/app.py` — Streamlit app with 5 views (strategy evolution, evidence browser,
  coverage heatmap, LLM judge review, agent activity)
- Connects to corpus.duckdb (read-only) + workspace directories
- Test with pilot data from manual Indebtedness run

### Step 13: Agent Prompts + Pilot
- `family_agent_base.md` template
- `indebtedness.md` pilot prompt (expert materials copied from
  `TermIntelligence/analysis/indebtedness/` → `workspaces/indebtedness/context/`)
- Manual pilot run (no tmux) to validate end-to-end workflow
- Tmux swarm pilot run

---

## Key Source Files (for recreation, not import)

| Target | Primary Source | Secondary Source | What to port |
|--------|---------------|-----------------|-------------|
| `src/agent/textmatch.py` | VP `infra/textmatch.py` | — | Port verbatim: PhraseHit, heading_matches, keyword_density, section_dna_density |
| `src/agent/html_utils.py` | VP `l0/normalize.py` | TI `_shared.py` | VP: normalize + inverse map. TI: read_file() encoding fallback |
| `src/agent/section_parser.py` | VP `l0/outline.py` | TI `section_level_parser.py` | VP: typed output (OutlineArticle/Section). TI: DOM extraction phase (3 BS4 styles) |
| `src/agent/clause_parser.py` | VP `l0/clause_tree.py` | — | ClauseNode AST: enumeration parsing, depth tracking, char spans |
| `src/agent/dna.py` | VP `l1/discovery/section_analyzer.py` | — | TF-IDF + log-odds, validation gates |
| `src/agent/definitions.py` | TI `corpus_classifier.py` | — | All 5 regex engines + guards (VP only has 1 pattern) |
| `src/agent/metadata.py` | TI `metadata_extractor.py` | — | Borrower, agent, facility, dates, entity type |
| `src/agent/strategy.py` | VP `contracts/discovery.py` | VP `configs/bootstrap_all.json` | Strategy schema + ValidatedStrategy fields |
| `swarm/*.sh` | Neutron `swarm/*.sh` | Neutron `swarm-phase0/` | Tmux management + wave dispatch |

---

## Resolved Decisions

1. ~~Corpus location~~ → S3: `s3://edgar-pipeline-documents-216213517387/`, CIK-partitioned
2. ~~Pilot corpus~~ → Staged ingestion: 500 → 5,000 → full corpus (currently 12,583 docs; Ray at Phase E optional)
3. ~~Template discovery~~ → Statistical clustering (improved from TI), user labels clusters
4. ~~Pilot scope~~ → Two levels deep (family → children → grandchildren)

---

## Strategy Schema (enriched from VP analysis)

Based on deep analysis of vantage_platform's bootstrap_all.json, ValidatedStrategy contract,
and family-level configs (retrieval_policy.json, taxonomy.json):

```python
@dataclass(frozen=True, slots=True)
class Strategy:
    """Search strategy for a concept — what agents create and refine."""

    # Identity
    concept_id: str                              # "debt_capacity.indebtedness.general_basket"
    concept_name: str                            # "General Debt Basket"
    family: str                                  # "indebtedness"

    # Core search vocabulary (3-tier keyword architecture from VP)
    heading_patterns: tuple[str, ...]            # Section heading patterns
    keyword_anchors: tuple[str, ...]             # Global keywords across all documents
    keyword_anchors_section_only: tuple[str, ...] # Keywords only meaningful within section
    concept_specific_keywords: tuple[str, ...]   # Highly targeted keywords for this concept

    # DNA phrases (discovered statistically, tiered by confidence)
    dna_tier1: tuple[str, ...] = ()              # High-confidence distinctive phrases
    dna_tier2: tuple[str, ...] = ()              # Secondary distinctive phrases

    # Domain knowledge
    defined_term_dependencies: tuple[str, ...] = ()  # Required defined terms
    concept_notes: tuple[str, ...] = ()              # Research notes, edge cases
    fallback_escalation: str | None = None           # What to try when primary search fails
    xref_follow: tuple[str, ...] = ()                # Cross-reference guidance

    # Structural location (from domain expert)
    primary_articles: tuple[int, ...] = ()       # Expected article numbers (e.g., (6, 7))
    primary_sections: tuple[str, ...] = ()       # Expected section patterns (e.g., ("7.01",))
    definitions_article: int | None = None       # Where definitions live (usually 1)

    # Corpus validation metrics (filled after testing)
    heading_hit_rate: float = 0.0
    keyword_precision: float = 0.0
    corpus_prevalence: float = 0.0
    cohort_coverage: float = 0.0
    dna_phrase_count: int = 0

    # QC indicators
    dropped_headings: tuple[str, ...] = ()       # Headings that failed validation
    false_positive_keywords: tuple[str, ...] = () # Low-precision keywords

    # Template-specific overrides (discovered during refinement)
    template_overrides: dict[str, dict] = field(default_factory=dict)
    # e.g., {"cahill": {"heading_patterns": ["Limitation on Debt"]}}

    # Provenance
    validation_status: str = "bootstrap"         # bootstrap → corpus_validated → production
    version: int = 1
    last_updated: str = ""
    update_notes: tuple[str, ...] = ()
```

---

## S3 Metadata Content (Resolved)

The `.meta.json` files contain:
```json
{
  "s3_key": "documents/cik=.../accession_exhibit.htm",
  "company_name": "AAR CORP  (AIR)  (CIK 0000001750)",
  "cik": "0000001750",
  "accession": "000104746915006136",
  "filename": "a2225345z10-k.htm",
  "file_type": "html",
  "original_url": "https://www.sec.gov/Archives/edgar/...",
  "file_size": 1886611,
  "downloaded_at": "2026-02-20T03:30:48.021869",
  "worker_id": "399ff465"
}
```

**Free metadata**: company_name, CIK, accession, original_url, file_size, download timestamp.
**Still need extraction**: borrower (clean name), admin_agent, facility_size, closing_date,
form_type, market_segment. The filename hints at form type (e.g., `ex10d1` = EX-10.1 exhibit).

---

## All Resolved Decisions

1. ~~Corpus location~~ → S3: `s3://edgar-pipeline-documents-216213517387/`, CIK-partitioned
2. ~~Pilot corpus~~ → Staged ingestion: 500 → 5,000 → full corpus (currently 12,583 docs; Ray at Phase E optional)
3. ~~Template discovery~~ → Statistical clustering (improved from TI), user labels clusters
4. ~~Pilot scope~~ → Two levels deep (family → children → grandchildren)
5. ~~AWS CLI~~ → Needs configuration (Step 4 in build order)
6. ~~Ray compute~~ → AWS Ray cluster (transient, spot instances)
7. ~~Build approach~~ → Bottom-up (solid foundations, each layer tested)
8. ~~S3 metadata~~ → Provides company_name, CIK, accession, URL; borrower/agent/facility need extraction
9. ~~VP vs TI parsing~~ → HTML: VP; Sections: Hybrid VP+TI; Definitions: TI; Metadata: TI; Clauses: VP
10. ~~Strategy format~~ → Rich multi-tier schema (see above) with corpus metrics + template overrides
11. ~~Agent prompt~~ → Base template + per-family domain expert enrichment (structural locations, drafting conventions)
12. ~~Labeled data output~~ → Start with JSONL, add Parquet export later
13. ~~Agent autonomy~~ → `--dangerously-skip-permissions` per BSL retrospective lessons
14. ~~Clause-level ingestion~~ → Ray pipeline parses down to clause-level AST, not just sections
15. ~~Precision validation~~ → LLM-judge tool (Haiku) is a Phase B+ release gate (advisory in MVP) + human dashboard review
16. ~~Failure summarization~~ → pattern_tester returns mathematical summaries (log-odds, template breakdown, structural deviation), never raw missed text
17. ~~Definition auto-unroll~~ → `--auto-unroll` flag on section_reader.py and child_locator.py
18. ~~Corpus storage~~ → DuckDB (not per-document JSON files) — concurrent agent reads, SQL queries, columnar analytics
19. ~~Regression circuit breaker~~ → strategy_writer.py rejects updates that degrade previously-solved template clusters
20. ~~Hybrid VP+TI~~ → Keep hybrid approach, do not simplify to single source
21. ~~Swarm orchestration~~ → Tmux + shell scripts (subscriptions, not API — ~4 Claude Code Max subs)
22. ~~User involvement~~ → Hands-on via custom Streamlit review dashboard alongside terminal
23. ~~Domain guidance~~ → Mainly structural location hints (Article/Section), user can produce quickly
24. ~~Escalation~~ → When agent plateaus, alert user ("call John"); no auto-sub-agent for now
25. ~~Integration to VP~~ → Keep separate for initial rounds; multiple validation passes before linking to L0-L3 DAG
26. ~~Pilot depth evolution~~ → Start 1 agent per family covering full subtree; revisit sub-agent approach only if a family proves too deep/complex after pilot. Simpler orchestration wins initially — most families are 2-3 levels, only a handful reach 4-5.
27. ~~Full-corpus ingestion cost~~ → depends on cluster size and refresh cadence; current 12,583-doc baseline is below prior large-scale estimates. Track actual cost per run in manifest/benchmark artifacts.

---

## Appendix A: Cross-Repository Source Audit

Results from 9 Opus subagents scanning 5 repos (TI, VP, Neutron, TermIntel, auto).
Identifies every high-value file to port into Agent/, organized by target module.

### A.1 Expanded Source File Map

| Agent Target | Source File | Lines | Priority | What to Port |
|---|---|---|---|---|
| **`textmatch.py`** | VP `infra/textmatch.py` | 134 | P0 | Port verbatim: PhraseHit, heading_matches, keyword_density, section_dna_density, score_in_range |
| | VP `l2/_matcher.py` | 202 | P1 | Aho-Corasick multi-pattern matching with Protocol interface |
| | VP `l2/tagger/_tagger_impl.py` | 275 | P1 | Bayesian 3-channel scoring (heading 2.0, keyword 1.0, DNA 1.5), softmax competition |
| | TI `round6_actor_modality.py` | 1164 | P2 | 6 modality families (40+ regex), 16 actor patterns, 120-char lookback proximity |
| | TI `round6_numeric_time.py` | 1320 | P2 | Dollar/percentage/ratio/time regex library, magnitude bucketing, deadline extraction |
| | TI `round8_friction_index.py` | 1414 | P2 | 29-token friction lexicon with directional polarity weights, Power Balance Ratio |
| | TI `round9_boolean_parity.py` | 600+ | P2 | 16 boolean operators (PERMIT/RESTRICT signs), boolean depth parity for scope |
| | TI `round9_epistemic_gates.py` | 400+ | P2 | HALT/ORACLE/THRESHOLD computability classification, "deemed" type coercion patterns |
| **`html_utils.py`** | VP `infra/html.py` | 261 | P0 | 5-phase normalize_html() with RLE-compressed inverse map, image-overlay PDF detection |
| | VP `l0/normalize.py` | 123 | P0 | Content-addressed doc_id via SHA-256 |
| | TI `_shared.py` | 191 | P0 | read_file() with UTF-8→CP1252→replace encoding fallback |
| | TI `round5_html_typography.py` | 1495 | P1 | is_bold/underline/centered, get_font_size, ancillary boundary detection, 3-toolchain awareness |
| | TI `round7_cssom_visual_syntax.py` | 1200+ | P2 | CSS indent parsing for scope, unit conversion table, proviso patterns, effective indent computation |
| | TI `round9_typographical_entropy.py` | 400+ | P1 | Fast regex-based toolchain detector (no BS4), paragraph feature extractor, enumeration gap detection |
| **`section_parser.py`** | VP `l0/_doc_parser.py` | 2200 | P0 | 3-phase parser, DocOutline, `_KEYWORD_CONCEPT_MAP` (40+ entries), Lark EBNF xref grammar |
| | VP `l0/_parsing_types.py` | 700 | P0 | OutlineSection, OutlineArticle, SpanRef, InverseMap with O(log N) lookup |
| | TI `section_level_parser.py` | 1539 | P0 | Two-phase DOM+text extraction, 3 HTML styles (Workiva, Donnelley, SGML), plain-text fallback |
| | TI `round11_article_boundary.py` | 1229 | P1 | Two-pass article extraction with TOC zone detection (3 strategies), Article I definition validation |
| | TI `round11_numbering_census.py` | 1181 | P1 | 5-dimension numbering schema fingerprint, parenthetical nesting order detection |
| | Neutron BSL `build_section_index.py` | 286 | P1 | 5 regex patterns for legal section heading variants, TOC-vs-body dedup with heading quality scoring |
| **`clause_parser.py`** | VP `l0/_clause_tree.py` | 710 | P0 | ClauseTree with 9-step construction, stack-walk parent-child, 5 confidence constraints |
| | VP `l0/_enumerator.py` | 525 | P0 | 4 enumerator types, disambiguate_i(), scan_enumerators() |
| | TI `round5_def_type_classifier.py` | 887 | P1 | 7-type definition structural classifier (DIRECT/FORMULAIC/ENUMERATIVE/etc.), multi-signal scoring |
| | TI `round6_baskets_mirroring.py` | 1500+ | P1 | 11 NegCov topic patterns, per-covenant action verbs, basket extraction, mirroring detection |
| | TI `round7_algebraic_graph.py` | 1200+ | P2 | 12-operator typed AST (ADD/SUBTRACT/RATIO/IF_THEN/etc.), expression tree building |
| | TI `round8_ast_scope_integration.py` | 1857 | P2 | Three-tier scope resolution, enumeration position classifier, scope impact quantification |
| | TI `round13_definition_anatomy.py` | 954 | P1 | 9-component definition decomposition (HEAD/SCOPE/THRESHOLD/EXCEPTION/etc.) |
| **`definitions.py`** | TI `corpus_classifier.py` | 1380 | P0 | 5-engine parallel regex extraction (quoted, colon, unquoted, U-tag, bold-italic) |
| | TI `round5_definition_graph.py` | 2200+ | P1 | 3-strategy reference finder, PageRank, Louvain community detection, graph fingerprinting |
| | TI `round9_ast_isomorphism.py` | 800+ | P2 | Merkle hashing for AST structural equivalence, variable shadowing detection |
| | Neutron BSL `extract_defined_terms.py` | 184 | P1 | Unicode smart quote regex (U+201C/U+201D), cross-reference extraction |
| **`metadata.py`** | TI `metadata_extractor.py` | 1378 | P0 | 7-pass borrower extraction, 40+ admin agent normalizer, EBITDA mode clustering |
| | VP `l0/_metadata_impl.py` | 1100+ | P1 | 6 extractors, 60+ KNOWN_AGENTS bank names, aggregate+tranche facility size |
| **`dna.py`** | VP `l1/discovery/section_analyzer.py` | 598 | P0 | TF-IDF + log-odds rank fusion, validation gates |
| | TI `discovery_provision_dna.py` | 796 | P1 | Colon-separated DNA encoding, reduce_dna() normalization, cross-family analytics |
| | TI `structural_clustering.py` | 634 | P1 | Wildcard edit distance, hierarchical clustering |
| **`strategy.py`** | VP `contracts/discovery.py` | 165 | P0 | ValidatedStrategy, StrategyMetrics, DnaPhraseCandidate, FamilyProfile |
| | VP `l1/discovery/strategy_compiler.py` | 415 | P0 | compile_strategy() merging bootstrap with corpus evidence, false positive detection |
| | TI `generate_search_strategies.py` | 537 | P0 | FAMILY_CONFIG (20 families), derive_concept_keywords() auto-derivation, ontology tree walker |
| | TI `compile_section_map.py` | 705 | P1 | HHI-based location stability scoring, fallback strategy determination |
| **`pattern_tester.py`** | VP `l1/discovery/section_locator.py` | 361 | P0 | Heading→keyword→DNA fallback chain with confidence ranges (0.80, 0.40-0.70, 0.25-0.55) |
| | TI `evaluate_search_strategies.py` | 496 | P0 | Two-stage evaluate engine, FamilyResult/TermResult, confidence distribution bucketing, family-found-but-term-missed diagnostic |
| **`heading_discoverer`** | TI `round7_super_graph.py` | 1500+ | P0 | **133-concept CANONICAL_CONCEPTS registry** — the "Rosetta Stone" defeating naming tax |
| | TI `round8_registry_expansion.py` | 2500+ | P0 | V2 expansion to 170+ canonical concepts (agent delegation, FATCA, QFC, etc.) |
| | TI `round6_concept_triage.py` | 1200+ | P1 | ~60 HEADING_TO_CONCEPT entries, golden NegCov section extraction |
| | TI `round13_concept_boundary.py` | 980 | P1 | 45-pattern concept normalizer, cross-reference asymmetry analysis |
| **`structural_mapper`** | TI `round11_structural_fingerprint.py` | 960 | P1 | 31-feature fingerprint (6 groups), PCA, discrimination scoring, archetype bucketing |
| | TI `round9_preemption_dag.py` | 400+ | P2 | 7 override patterns ("notwithstanding"), 3 yield patterns ("subject to"), legal precedence DAG |
| **`template_classifier`** | TI `round12_boilerplate_shingles.py` | 817 | P0 | Manual MinHash (128 hashes, Mersenne prime 2^61-1), TOC-aware section locator, phrasing family clustering |
| | TI `round11_structural_fingerprint.py` | 960 | P1 | 31-feature structural fingerprint for template classification |
| **`corpus.py`** | TI `corpus_validation_suite.py` | 1247 | P1 | 10-check validation framework, cross-reference integrity, quote balance |
| | VP `datasets/catalog.py` | 404 | P1 | DatasetVersion frozen dataclass, ICatalogBackend Protocol, pluggable backend pattern |
| **`llm_judge.py`** | *(new — no existing source)* | — | P0 | Build from scratch using Haiku API calls |
| **`evidence_collector`** | Neutron `extraction-handoff.ts` | 383 | P1 | EvidenceKind hierarchy, EvidenceBundle, RetrievalPlan, RETRIEVAL_LIMITS |
| | Neutron `provenance.ts` | 425 | P1 | ReferenceKind, ResolvedReferenceTarget, HighlightTarget union types |
| **`strategy_writer`** | TI `generate_search_strategies.py` | 537 | P0 | Ontology walker, strategy merge-with-existing pattern |
| | VP `release/gates.py` | 338 | P1 | Composable quality gate pattern (GateResult + STANDARD_GATES registry + run_all_gates) |
| **`setup_workspace`** | Neutron BSL `extraction-protocol.md` | 218 | P1 | 13-step extraction protocol, 18-category-to-section routing table |
| **`swarm/*.sh`** | Neutron BSL `launch-swarm.sh` | varied | P0 | Data validation at launch, multi-pane setup, auto-accept dialog navigation |
| | Neutron BSL `start-agent.sh` | varied | P0 | `--dangerously-skip-permissions` + auto-accept subshell, `unset CLAUDECODE`, multi-fragment CLAUDE.md composition |
| | Neutron phase0 `dispatch-wave.sh` | 79 | P0 | Wave-based dispatch with dependency checking against shared log, `--dry-run` |
| | Neutron BSL `swarm-status.sh` | 123 | P0 | Comprehensive status: pane status, task ledger, output counts, "Ready to Dispatch" section |
| | Neutron BSL `reextract.sh` | 198 | P1 | Targeted re-execution with modified scope |
| **`prompts/`** | Neutron `specialist-prompts.md` | 410 | P0 | ROLE + SCOPE + FAILURE MODES + INVESTIGATION CHECKLIST prompt structure |
| | Neutron BSL `common-rules.md` | 119 | P0 | Shared rules, three-pass NOT_FOUND protocol, concept-first traversal |
| | Neutron BSL `extraction-protocol.md` | 218 | P0 | 13-step protocol, 6-tier match assessment (EXACT→VINTAGE_MISMATCH) |
| | Neutron BSL `golden-record-schema.json` | 323 | P1 | Full extraction record schema with provenance |
| **Pipeline infra** | VP `pipeline/registry.py` | 133 | P2 | TransformDeclaration, TransformRegistry, DAG validation with cycle detection |
| | VP `pipeline/manifest.py` | 198 | P2 | Kahn's topo sort, staleness detection, minimal build planning |
| | VP `runtime/runner.py` | 350 | P2 | 7-step idempotent execution protocol with cache-based skip |
| | VP `datasets/store.py` | 428 | P2 | 10-step failure-atomic transactional write protocol, crash recovery |
| | VP `infra/lineage.py` | varies | P2 | Content-addressed dataset_id computation from (name, version, inputs, config) |
| | VP `datasets/lineage.py` | 352 | P2 | Event-driven incremental lineage, BFS ancestor/descendant queries, staleness detection |
| **Dashboard** | VP `dashboard/_template.py` | 4300+ | Ref | 7-view architecture, Plotly dark theme, data injection pattern (adapt concepts for Streamlit) |
| **Orchestrator** | Neutron `route-failure.ts` | 464 | P2 | Failure diagnosis routing decision tree, investigation checklists |
| | Neutron `memory.ts` | 285 | P2 | Fix-pattern memory store, similar-fix retrieval, recursive improvement |
| | Neutron `confidence.ts` | 332 | P1 | CalibratedConfidence, presence vs absence distinction, threshold constants |
| | Neutron `extraction-unified.ts` | 441 | P1 | 6-state ExtractionStatus, DidNotFindEvidence (structured proof of absence) |

### A.2 Pattern Registries to Port (Crown Jewels)

These curated pattern dictionaries represent thousands of hours of domain expert validation:

| Registry | Source | Size | Description |
|---|---|---|---|
| **CANONICAL_CONCEPTS** | TI `round7_super_graph.py` + `round8_registry_expansion.py` | 170+ concepts | Section title → canonical concept mapping. Defeats the "naming tax" across all EDGAR variants |
| **FAMILY_CONFIG** | TI `generate_search_strategies.py` | 20 families | Heading patterns + keyword anchors per concept family across 6 domains |
| **FRICTION_LEXICON** | TI `round8_friction_index.py` | 29 tokens | Directional polarity weights (+1.0 to -0.85) for power balance scoring |
| **MODALITY_PATTERNS** | TI `round6_actor_modality.py` | 6 families, 40+ sub-patterns | OBLIGATION/PROHIBITION/PERMISSION/DISCRETION/EXCULPATION/CONDITION |
| **ACTOR_PATTERNS** | TI `round6_actor_modality.py` | 16 actors | Canonical actor normalization (Borrower, Agent, Lenders, etc.) |
| **BOOLEAN_OPERATORS** | TI `round9_boolean_parity.py` | 16 operators | PERMIT (sign=-1) / RESTRICT (sign=+1) for algebraic scope resolution |
| **NEGCOV_TOPICS** | TI `round6_baskets_mirroring.py` | 11 topics | Negative covenant classification patterns (indebtedness, liens, RP, etc.) |
| **GATE_TAXONOMY** | TI `round9_epistemic_gates.py` | 19 patterns | HALT/ORACLE/THRESHOLD computability classification for subjective clauses |
| **DEEMED_PATTERNS** | TI `round9_epistemic_gates.py` | 4 patterns | Implicit type casts across covenant categories |
| **OVERRIDE_PATTERNS** | TI `round9_preemption_dag.py` | 7 patterns | "Notwithstanding" variants establishing legal precedence |
| **YIELD_PATTERNS** | TI `round9_preemption_dag.py` | 3 patterns | "Subject to" variants establishing legal dependency |
| **_KEYWORD_CONCEPT_MAP** | VP `l0/_doc_parser.py` | 40+ entries | Keyword → concept ID mapping for section classification |
| **KNOWN_AGENTS** | VP `l0/_metadata_impl.py` | 60+ names | Admin agent bank name normalization |
| **BOILERPLATE_SIGNATURES** | TI `round5_definition_graph.py` | 10 signatures | Definition community taxonomy labels |

### A.3 Key Innovations to Implement

Beyond what's already in the plan, the audit discovered these algorithms:

**P1 — Include in initial build:**

1. **Two-Stage Section-Then-Concept Locator** (TI `evaluate_search_strategies.py`)
   — Stage 1: find covenant section via heading/definition/keyword → FamilySection.
   Stage 2: find concept within bounded section via clause scoring/keyword/derived keyword.
   Caches family section per CA. Already implicitly planned but the TI source provides
   the proven implementation pattern including the family-found-but-term-missed diagnostic.

2. **Colon-Separated DNA Encoding** (TI `discovery_provision_dna.py`)
   — `encode_basket_dna()` encodes structural features as `BASKET:GENERAL:FIXED_DOLLAR:PCT_EBITDA:GREATER_OF:NO_RATIO_TEST`.
   `reduce_dna()` normalizes for cross-system comparison. Include in `dna_discoverer.py`.

3. **CANONICAL_CONCEPTS Integration** (TI R7-C + R8-C)
   — 170+ canonical section concept mappings. This IS the heading_discoverer's core data.
   Port as a frozen dict constant in `heading_discoverer.py`.

4. **Derive-Concept-Keywords Auto-Derivation** (TI `generate_search_strategies.py`)
   — Auto-extracts up to 8 keywords from concept name + definition using 3 regex strategies.
   Include in `strategy_writer.py` for bootstrapping new concept strategies.

5. **Confidence Distribution Bucketing** (TI `evaluate_search_strategies.py`)
   — High ≥0.7, Medium 0.4-0.7, Low <0.4. Include in `pattern_tester.py` output.

6. **Structured Proof of Absence** (Neutron `extraction-unified.ts`)
   — When NOT_FOUND, produce `DidNotFindEvidence` with search coverage metrics,
   strategies used, near-miss candidates, confidence-in-absence score.
   Include in `evidence_collector.py`.

**P2 — Include as later enhancement (post-pilot):**

7. **Three-Tier Scope Resolution** (TI R7-B + R8-B + R9-C)
   — CSS indentation (deterministic for block-start provisos) → AST-structural heuristics
   (moderate confidence) → Boolean depth parity (algebraic, text-only). Three complementary
   approaches that cascade. Add to `clause_parser.py` after pilot validation.

8. **Merkle Hashing for AST Isomorphism** (TI R9-B)
   — Hash definition AST shapes (ignoring labels) to find naming-tax equivalences.
   Sort commutative operators before hashing. Add to `definitions.py` for dedup.

9. **Variable Shadowing Detection** (TI R9-B)
   — Detect "for purposes of this Section" patterns that redefine terms locally.
   Classify as narrows/broadens/redefines. Add to `definitions.py`.

10. **Preemption DAG** (TI R9-A)
    — Parse "notwithstanding" as OVERRIDE edges, "subject to" as YIELD edges.
    Build legal precedence DAG. Add to `structural_mapper.py`.

11. **Learning Memory Store** (Neutron `memory.ts`)
    — Fix-pattern memory: records successful extraction patterns, retrieves
    similar fixes for new failures. Port Python version for cross-round learning.

12. **Failure Routing Decision Tree** (Neutron `route-failure.ts`)
    — Cascading diagnosis: no evidence → retrieval, missing definitions → definition
    specialist, unresolved xrefs → cross-ref, gate failures → extraction.

### A.4 Swarm Infrastructure — Neutron BSL Lessons

The Neutron BSL-Golden retrospective (565 lines, 12 hours of operational learnings)
provides battle-tested fixes. Critical lessons already incorporated:

| Lesson | Impact | Already in Plan? |
|---|---|---|
| Codex `--full-auto` does NOT prevent approval prompts | Use `claude --dangerously-skip-permissions` instead | Yes (Decision #13) |
| Claude eats kickoff message after permission dialog | Send prompt AFTER acceptance via background subshell (8s wait → Down → Enter) | Now added |
| Context exhaustion needs checkpoint files | Per-record checkpointing so context-exhausted agents' work is preserved | **NEW** — add to agent prompt |
| Concept whitelist per agent prevents boundary violations | Each agent gets a concept whitelist; extractions outside list are rejected | **NEW** — add to swarm.conf |
| Inline QA during extraction (not final-wave QA) | Aligned with Phase B+ llm_judge release-gate checks (advisory in MVP) | Yes (Decision #15) |
| `unset CLAUDECODE` for nested sessions | Prevents Claude from detecting it's running inside another Claude session | **NEW** — add to start-agent.sh |
| Multi-fragment CLAUDE.md composition | common-rules + extraction-protocol + family-prompt concatenated at launch | **NEW** — add to start-agent.sh |

**New items to add to swarm infrastructure:**
- **Checkpoint files**: Each agent writes periodic checkpoint files to `workspaces/{family}/checkpoint.json`
  with current strategy version, last-tested doc_id, iteration count, and coverage metrics.
  On context exhaustion + restart, agent resumes from checkpoint instead of starting over.
- **Concept whitelist**: `swarm.conf` maps each agent to a concept whitelist. The agent prompt
  instructs: "Only produce patterns for concepts in your whitelist. If you discover patterns
  for concepts outside your whitelist, log them in `out_of_scope_discoveries.jsonl` for
  the appropriate agent to pick up."
- **`unset CLAUDECODE`**: Added to `start-agent.sh` before launching claude to prevent
  nested-session detection issues.
- **Multi-fragment CLAUDE.md**: `start-agent.sh` assembles CLAUDE.md from:
  `prompts/common-rules.md` + `prompts/platform-conventions.md` + `prompts/enrichment/{family}.md`

### A.5 Gaps Identified (Not Covered by Any Source Repo)

| Gap | Where Needed | Plan |
|---|---|---|
| Amendment parsing ("hereby amended by deleting...") | `clause_parser.py` | Post-pilot: parse amendment diffs as structured changes |
| Cross-agreement reference resolution | `definitions.py` | Post-pilot: link Intercreditor Agreement references |
| Multi-agreement corpus linking (CA + amendments + security) | `corpus.py`, DuckDB schema | Post-pilot: add `deal_group` FK to documents table |
| Incremental re-processing (add new filings) | CLI tools, DuckDB pipeline | Design for from start but implement post-pilot |
| Multi-currency / multi-jurisdiction | `textmatch.py`, `clause_parser.py` | Post-pilot: USD-only for now (95%+ of EDGAR corpus) |
| Semantic clause similarity (embedding-based) | potential `clause_matcher.py` | Post-pilot: not needed for pattern-based discovery |
| Basket size computation (parsing dollar thresholds, ratios) | potential `basket_calculator.py` | Post-pilot: extraction-only for now, not computation |
| Agent heartbeat/watchdog (detect stalled agents) | swarm infrastructure | Include stub in Phase 4, implement when scaling to 49 agents |
| Automated wave transition | swarm infrastructure | Manual `dispatch-wave.sh` for pilot; auto-supervisor for production |
| Real-time dashboard updates during ingestion | dashboard | Streamlit session state polling (not WebSocket) |

### A.6 Updated Build Order Notes

Based on audit findings, these adjustments to the build order:

**Step 2 additions**: Include `derive_concept_keywords()` in `strategy.py`, port the
FAMILY_CONFIG dict as a typed constant.

**Step 3 additions**: Include ancillary boundary detection from TI `round5_html_typography.py`
in `section_parser.py` (separates credit agreement from bundled ancillary docs).
Include 5 heading regex patterns from Neutron BSL `build_section_index.py`.
Include smart-quote (U+201C/U+201D) handling from Neutron BSL `extract_defined_terms.py`
in `definitions.py`.

**Step 7 additions**: Include confidence distribution bucketing in `pattern_tester.py` and
the family-found-but-term-missed diagnostic from TI `evaluate_search_strategies.py`.

**Step 8 additions**: Include `encode_basket_dna()` and `reduce_dna()` in `dna_discoverer.py`.
Port merged CANONICAL_CONCEPTS (170+) into `heading_discoverer.py`.

**Step 11 additions**: Include checkpoint file protocol, concept whitelist in swarm.conf,
`unset CLAUDECODE`, multi-fragment CLAUDE.md composition in swarm scripts. Port
common-rules.md, three-pass NOT_FOUND protocol, and extraction protocol concepts from
Neutron BSL prompts.
