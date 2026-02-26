# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Pattern discovery platform for credit agreement ontology linking. Agents iteratively
discover patterns (heading, keyword, DNA phrase, structural position) that locate
ontology concepts in leveraged finance credit agreements parsed from EDGAR HTML filings.

## Commands

```bash
# Setup — core library + dev tools (pytest, ruff, pyright)
python3 -m pip install -e ".[dev]"

# Server deps (not in pyproject.toml — install separately)
python3 -m pip install fastapi uvicorn[standard] pydantic starlette

# Run all tests
python3 -m pytest

# Run a single test file or test
python3 -m pytest tests/test_strategy.py
python3 -m pytest tests/test_strategy.py::test_merge_strategies -x

# Lint and type-check (Python)
ruff check src/ tests/ scripts/
pyright src/

# Type-check dashboard frontend
cd dashboard && npx tsc --noEmit

# Dashboard E2E tests (Playwright — requires servers running)
cd dashboard && npm run test:e2e        # all tests
cd dashboard && npm run test:e2e:smoke  # smoke suite only
```

## Conventions

- Python >=3.12, type hints everywhere
- Use `python3` not `python`
- `orjson` for JSON (not stdlib json) — all modules use try/except import with stdlib fallback
- All contracts: `@dataclass(frozen=True, slots=True)`
- pyright strict mode, zero errors
- DuckDB corpus index is immutable per run (read-only in CLI tools)
- All char offsets reference normalized text (global, never section-relative)
- Strategy versions are monotonically numbered per concept
- CLI tools output structured JSON to stdout, human-readable messages to stderr
- When running scripts directly (not via `python3 -m`), set `PYTHONPATH=src` or install the package

## Architecture

### Core library (`src/agent/`)

The scoring pipeline flows: **HTML → normalized text → sections → scoring → strategy persistence**.

- `html_utils.py` — HTML-to-text with character-level inverse map (UTF-8 → CP1252 → replace fallback for EDGAR docs). Post-extraction cleanup: `strip_zero_width()`, `strip_boilerplate()`, `normalize_quotes()`
- `section_parser.py` / `doc_parser.py` — 3-phase document parsing: articles → sections → headings. Delegates to `DocOutline.from_text()`. Includes TOC dedup with heading inheritance, monotonic section enforcement, heading quality scoring, reserved section detection, `Sec.`/`Sec` abbreviation support, and standalone section number look-ahead
- `clause_parser.py` — Multi-level clause AST parser for enumerated provisions `(a)/(i)/(A)/(1)`. Stack-walk algorithm with alpha/roman disambiguation and confidence scoring
- `definitions.py` — 5-engine defined term extractor (quoted, smart-quote, parenthetical, colon, unquoted) with deduplication by engine priority
- `textmatch.py` — Pure scoring primitives: `heading_matches`, `keyword_density`, `section_dna_density`, `score_in_range`
- `dna.py` — Statistical phrase discovery via TF-IDF + Monroe log-odds rank fusion. Produces tiered DNA phrases
- `strategy.py` — Strategy dataclass (40+ fields), versioned persistence, and **parent inheritance** via `inherits_from` (resolves to latest `{concept}_v*.json`)
- `corpus.py` — DuckDB read-only interface (`CorpusIndex`). Tables: `documents`, `sections`, `clauses`, `definitions`, `section_text`, `section_features`, `clause_features`
- `confidence.py` / `scope_parity.py` / `preemption.py` / `structural_fingerprint.py` — Feature modules used by pattern_tester's acceptance gates
- `classifier.py` — Rule-based classifier absorbing 17 regex patterns from upstream
- `rule_dsl.py` — Full DSL parser (Lark grammar) with proximity operators (`/s` same sentence, `/p` same paragraph, `/N` within N words), regex, `@macro` refs, field prefixes (`heading:`, `article:`, `clause:`, `section:`, `defined_term:`, `template:`, `vintage:`, etc.). Public API: `parse_dsl()`, `serialize_dsl()`, `validate_dsl()`
- `document_processor.py` — Shared document processing pipeline for both corpus builders. Entry point: `process_document_text()` → `DocumentResult` with all 7 record lists
- `link_confidence.py` — 7-factor composite confidence scoring (0.0–1.0): article_match (0.22), heading_exactness (0.28), clause_signal (0.13), template_consistency (0.10), defined_term_grounding (0.09), structural_prior (0.08), semantic_similarity (0.10). Tiers: High >=0.8, Medium 0.5–0.8, Low <0.5
- `conflict_matrix.py` — Ontology-aware conflict policy matrix. Policies: `exclusive`, `warn`, `compound_covenant`, `shared_ok`, `expected_overlap`, `independent`. Built from ontology edges at server startup
- `parsing_types.py` — Core shared types: `SpanRef`, `Ok[T]/Err[E]` Result type, `OutlineSection`, `OutlineArticle`, `RetrievalPolicy`
- `io_utils.py` — orjson-accelerated JSON/JSONL file I/O with stdlib fallback

### CLI tools (`scripts/`)

Agent-callable tools with `--help` for usage. Key tools in the discovery loop:

- `pattern_tester.py` — Core evaluation: scores strategy against corpus, produces hit/miss analysis with outlier detection, confidence distribution, and did-not-find metrics
- `strategy_writer.py` — Versioned strategy persistence with regression circuit breaker, template stability gates, outlier policy enforcement, and optional LLM judge gate
- `evidence_collector.py` — Normalizes match/miss results into `evidence_v2` JSONL rows with provenance
- `heading_discoverer.py` / `dna_discoverer.py` — Discovery tools for heading patterns and DNA phrases
- `build_corpus_index.py` — Builds the DuckDB index single-threaded (only writer; all other tools read-only)
- `build_corpus_ray_v2.py` — Ray-parallel DuckDB builder with Parquet-sharded architecture. Supports `--local-corpus` (reads from disk, ~3x faster than S3) and `--local` (local Ray, no cluster). Default: trimmed corpus (3,298 docs). Use `--doc-prefix documents` for full 34K
- `corpus_search.py` / `section_reader.py` / `definition_finder.py` — Corpus exploration tools
- `compile_section_map.py` — Per-concept section prevalence matrix with HHI stability scoring and location strategies
- `numbering_census.py` — Corpus-wide numbering format taxonomy (article format, section depth, zero-padding, anomalies)
- `section_headers_survey.py` — Broad-range heading survey with category classification and long-tail analysis
- `setup_workspace.py` — Creates per-family workspace directories with bootstrap strategies
- `bulk_family_linker.py` — Bootstraps ontology family links across corpus with 7-factor confidence scoring, cross-family conflict detection, canary mode (`--canary N`), and dry-run mode
- `link_worker.py` — Background job processor for linking system. Polls `job_queue` table in `links.duckdb`. Job types: `preview`, `apply`, `canary`, `batch_run`, `embeddings_compute`, `check_drift`, `export`. Auto-started by API server — typically not run manually

### Swarm orchestration (`swarm/`)

Shell-based multi-agent orchestration. `swarm.conf` defines families and agent assignments.
`launch.sh` / `dispatch-wave.sh` start waves of parallel agents per ontology family.
Wave scheduling and status tracking via `scripts/wave_scheduler.py`, `wave_transition_gate.py`, `swarm_watchdog.py`.

### Other directories

- `data/` — `ontology/` (active: `r36a_production_ontology_v2.5.1.json`), `bootstrap/` (bootstrap strategies), `family_link_rules.json` (10 bootstrap DSL rules — `filter_dsl` is primary, `heading_filter_ast` kept for backward compat), `ontology_notes.json` (mutable sidecar for dashboard notes)
- `corpus/` — S3-synced HTML documents (gitignored)
- `corpus_index/` — DuckDB databases (gitignored)
- `workspaces/` — Per-family agent working directories (gitignored)
- `dashboard/` — Next.js review dashboard (must run `npx next dev` from this directory, not the repo root)
- `plans/` — Architecture docs and operational artifacts

## Dashboard Servers

```bash
# Backend API (run from dashboard/ directory)
cd dashboard && python3 -m uvicorn api.server:app --host 127.0.0.1 --port 8000

# Frontend (run from dashboard/ directory — separate shell)
cd dashboard && NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run dev -- --hostname 127.0.0.1 --port 3000

# Verify
curl -s http://127.0.0.1:8000/api/health
```

**Important:**
- Always start the frontend and backend as **separate** shell commands (separate Bash calls). Never chain them with `&&` or newlines in a single command — this causes CWD drift.
- Frontend **must** set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` to avoid same-origin `/api` calls hitting port 3000 instead of 8000.
- Use `--hostname` (not `--host`) for Next.js CLI.
- The API server auto-spawns `link_worker.py` as a subprocess on startup — no need to start it manually.
- Server must run single-worker (`--workers 1`, the default). All endpoints are `async def`.
- If `corpus_index/corpus.duckdb` is missing, server starts in demo mode (corpus endpoints return 503, links endpoints work).

## Corpus Build

The DuckDB corpus index must be rebuilt after changes to parsing logic (`doc_parser.py`, `html_utils.py`, `section_parser.py`, `clause_parser.py`, `definitions.py`).

```bash
# Preferred — Ray with local corpus (fastest, ~7 min for 3,298 docs)
python3 scripts/build_corpus_ray_v2.py \
  --local-corpus corpus \
  --output corpus_index/corpus.duckdb \
  --local --force -v

# From S3 full 34K docs
python3 scripts/build_corpus_ray_v2.py \
  --bucket edgar-pipeline-documents-216213517387 \
  --doc-prefix documents --meta-prefix metadata \
  --output corpus_index/corpus.duckdb \
  --local --force -v

# Single-threaded, no Ray dependency
python3 scripts/build_corpus_index.py \
  --corpus-dir corpus/documents --output corpus_index/corpus.duckdb --force -v
```

**Requirements:** `ray`, `pyarrow`, `duckdb`, and local corpus in `corpus/documents/` + `corpus/metadata/`.

**Key flags:** `--local-corpus <dir>` (local filesystem), `--local` (local Ray), `--force` (overwrite), `--limit N` (test subset), `--one-per-cik` (dedup by CIK).

**Output:** `corpus_index/corpus.duckdb` (~6 GB) with tables: `documents`, `sections`, `clauses`, `definitions`, `section_text`, `section_features`, `clause_features`.

## Key Concepts

**Strategy inheritance**: Strategies can set `inherits_from` (path or concept-id stem) to inherit fields from a parent strategy. Child values override parent. Resolved via `resolve_strategy_dict()`.

**Acceptance policy v2**: When `acceptance_policy_version: "v2"`, strategies must pass multiple gates before `strategy_writer.py` accepts them: regression circuit breaker, template stability policy, outlier policy, did-not-find policy, confidence policy, and optional LLM judge gate.

**Workspace checkpoints**: Each workspace has a `checkpoint.json` tracking iteration count, last strategy version, and status. Updated automatically by `strategy_writer.py` and `evidence_collector.py`.

## Rules

1. NEVER fabricate domain content from training knowledge. All patterns must trace to corpus evidence.
2. All char offsets are GLOBAL (in normalized text), never section-relative.
3. DuckDB files are opened read-only by CLI tools. Only `build_corpus_index.py` and `build_corpus_ray_v2.py` write.
4. CLI tools output structured JSON to stdout. Human-readable messages go to stderr.
5. Strategy versions are immutable once written. New versions create new files.
6. Evidence must include `(doc_id, char_start, char_end)` as canonical coordinates.

## Linking Workflow

Interactive workflow for creating ontology family link rules via the dashboard API. Full agent prompt: **`swarm/prompts/linking_agent.md`**.

**Quick reference:**
- DSL operators: `|` (OR), `&` (AND), `!` (NOT), quoted strings for multi-word (`"Restricted Payments"`)
- DSL field prefixes: `heading:`, `article:`, `clause:`, `section:`, `defined_term:` (text fields); `template:`, `vintage:`, `market:`, `doc_type:`, `admin_agent:`, `facility_size_mm:` (metadata fields)
- DSL proximity operators: `/s` (same sentence), `/p` (same paragraph), `/N` (within N words)
- API base: `http://127.0.0.1:8000/api/links`, auth: `Authorization: Bearer local-dev-links-token`
- Embeddings: Voyage AI (`voyage-finance-2`, 1024-dim) — requires `VOYAGE_API_KEY` in `.env`
- Link storage: `corpus_index/links.duckdb` (DuckDB single-writer — stop server before running direct scripts that write)
- Family IDs: API uses `FAM-` prefix (e.g., `FAM-indebtedness`); ontology uses dotted notation (`debt_capacity.indebtedness`). Link store accepts either
- Key `links.duckdb` tables: `family_link_rules`, `family_links`, `link_events`, `previews`, `preview_candidates`, `job_queue`, `action_log` (undo/redo), `review_sessions`, `review_marks`, `section_embeddings`, `family_centroids`, `conflict_policies`, `starter_kits`

**Workflow steps:** Draft rule → Preview matches → Publish → Apply to create links → Embed linked sections → Find similar unlinked sections → Iterate.

**Key modules:** `src/agent/query_filters.py` (DSL→SQL), `src/agent/embeddings.py` (VoyageEmbeddingModel + EmbeddingManager), `src/agent/link_store.py` (LinkStore), `data/family_link_rules.json` (bootstrap rules), `docs/ontology_family_notes.json` (expert location notes).
