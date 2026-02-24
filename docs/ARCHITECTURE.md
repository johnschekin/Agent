# System Architecture and Roadmap

This document explains the architecture of the Agent discovery system and how ontology-linked discovery works end to end.

Execution control for roadmap gates and sequencing:
- `plans/master_rollout_plan.md`
- `plans/master_execution_backlog_p0_p2.md`

## 1) System Goal

Create high-quality labeled data that links legal text to ontology concepts:

- Input: credit agreement corpus + ontology
- Output: `ontology_node_id -> clause` mappings with provenance

Design constraints:
- scale to thousands of agreements
- deterministic and inspectable retrieval
- minimal per-document LLM usage

## 2) High-Level Architecture

```text
Raw Corpus (HTML + sidecar metadata)
        |
        v
Ingestion + Parsing (build_corpus_index.py / build_corpus_ray.py)
        |
        v
DuckDB Corpus Index
  - documents
  - sections
  - clauses
  - definitions
  - section_text
        |
        v
Discovery Tooling (scripts/*.py)
  - search/access
  - pattern testing
  - heading/structure discovery
  - persistence/versioning
        |
        v
Workspace Artifacts (per family)
  - strategies/
  - evidence/
  - results/
  - gold_set.jsonl
        |
        v
Ontology-Linked Labeled Data
```

## 3) Core Components

### 3.1 Parsing + Normalization (`src/agent/`)

- `html_utils.py` normalizes document text and preserves offsets.
- `doc_parser.py`, `section_parser.py` extract section boundaries.
- `clause_parser.py` produces clause-level structure.
- `definitions.py` extracts defined terms.
- `metadata.py` extracts borrower/agent/date/facility signals.

### 3.2 Corpus Access Layer

- `corpus.py` is the read API over DuckDB:
  - fetch docs
  - search sections
  - fetch section text
  - fetch clauses and definitions
  - sample docs (optionally stratified)

### 3.3 Strategy Layer

- `strategy.py` defines the strategy contract.
- Strategy fields include:
  - heading patterns
  - keyword anchors
  - DNA tiers
  - structural hints
  - provenance/version status

### 3.4 CLI Discovery Layer (`scripts/`)

Main tools by purpose:

- Search/access:
  - `corpus_search.py`
  - `section_reader.py`
  - `sample_selector.py`
  - `metadata_reader.py`

- Testing:
  - `pattern_tester.py`
  - `coverage_reporter.py`

- Discovery:
  - `heading_discoverer.py`
  - `structural_mapper.py`
  - `dna_discoverer.py`
  - `definition_finder.py`
  - `child_locator.py`

- Persistence and workflow:
  - `evidence_collector.py`
  - `strategy_writer.py`
  - `setup_workspace.py`
  - `template_classifier.py`

## 4) Data Model (DuckDB)

Primary tables:

- `documents`: one row per document
- `sections`: section boundaries + article numbers
- `clauses`: clause tree nodes with spans and depth
- `definitions`: extracted defined terms
- `section_text`: full text for each section
- `_schema_version`: schema contract guard

Critical keys:
- `doc_id` (content-addressed)
- `(doc_id, section_number)` for section-level joins
- `clause_id` for clause identity

## 5) Ontology Integration Model

Ontology file:
- `data/ontology/r36a_production_ontology_v2.5.1.json`
- 6 domains -> 49 families -> 3,538 node IDs

Bootstrap strategy file:
- `data/bootstrap/bootstrap_all.json`

Linking contract:
1. Discover patterns for a family and its child nodes.
2. Test patterns against corpus.
3. Save strategy versions keyed by `concept_id`.
4. Collect evidence rows keyed by `ontology_node_id`.
5. Build labeled gold set and later exports.

Why IDs matter:
- all downstream quality checks and joins depend on stable ontology IDs, not free-text names.

## 6) Discovery Algorithm (Practical)

The family-level matcher uses layered signals:

1. Heading signal
2. Keyword density signal
3. DNA phrase density signal
4. Composite score

Then:
- best section per document is selected
- document is hit/miss via threshold
- misses are summarized mathematically (template split, headings, structural deviation)

Child-level discovery:
- uses clause tree structure and enumeration depth
- narrows matching within parent section context

## 7) Template-Aware Behavior

Template clustering gives `template_family` labels.
Coverage is tracked by template to avoid hidden blind spots.

Observed failure mode:
- some template clusters parse with `section_count=0`
- these can show perfect-looking overall metrics while hiding total failure in one cluster

Therefore:
- always evaluate by template family
- not only global hit rate

## 8) Runtime Modes

### Local mode
- `scripts/build_corpus_index.py`
- best for 500/5K-style gates and debugging parser behavior

### Ray distributed mode
- `scripts/build_corpus_ray.py`
- designed for full S3 corpus processing with checkpoint/resume

## 9) Quality Controls

Already in system:
- schema version check on DB open
- deterministic JSON output contracts in tools
- regression-aware strategy writing path
- cohort filtering (`cohort_included=true`)

Still needed for production-quality ontology linking:
- stronger parser fallback for zero-section templates
- child-concept coverage targets (not only family-level)
- broader gold-set precision auditing
- LLM judge integration phase (planned hardening stage)

## 10) Roadmap

This roadmap combines active plan intent with current implementation state.

### Stage A: Foundation and Core Tooling
Status: largely complete

- core parsing/indexing toolchain in place
- local/full-local ingestion path working
- strategy + coverage + discovery tools available

### Stage B: Indebtedness Pilot (current)
Status: in progress

- workspace setup done
- family-level structural/heading/coverage runs done
- gold set scaffold generated and prefilled suggestions
- remaining work:
  - manual label completion
  - child concept drill-down
  - evidence files for finalized strategy decisions
  - parser fixes for template blind spots

### Stage C: Quality Hardening
Status: next

- formal precision gates
- judge/review flow
- stronger template-stratified guarantees

### Stage D: Swarm Orchestration
Status: planned

- tmux orchestration scripts + prompts
- multi-family concurrent runs
- checkpoint/restart discipline

### Stage E: Production Scale
Status: planned

- full 30K+ ingestion on Ray
- all 49 ontology families
- export-ready ontology-node-to-clause dataset

## 11) Current Snapshot (2026-02-22)

Latest full-local run:
- DB: `/tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb`
- documents: `3411`
- cohort docs: `2834`

Pilot family metrics:
- sample-500 hit rate: `0.984`
- all-cohort hit rate: `0.9915`

Known blocker:
- one template cluster (`cluster_039`) has parse failure (`section_count=0`)
- this requires parser robustness improvements before claiming stable template coverage

## 12) Recommended Next Engineering Steps

1. Add parser fallback for cluster_039-like formats and re-run ingestion.
2. Recompute template clustering after parser fix.
3. Run child-level discovery for top indebtedness children.
4. Save strategy/evidence versions and validate against gold labels.
5. Promote to next family only after template-level blind spots are cleared.
