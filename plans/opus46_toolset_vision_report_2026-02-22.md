# Agent Review + Opus 4.6 Toolset Vision (2026-02-22)

## 1) Implementation Review (Findings First)

### High Severity

1. `child_locator.py` cannot reliably do keyword-based clause matching on current schema.
- Evidence:
  - Clauses table has no clause text column: `scripts/build_corpus_index.py:82`, `scripts/build_corpus_index.py:545`.
  - `child_locator.py` expects text-like clause fields (`text`, `content`, `clause_text`, etc.): `scripts/child_locator.py:245`.
  - Matching logic depends on `clause_text`: `scripts/child_locator.py:312`.
- Impact:
  - Keyword matching for child concepts is effectively disabled in most real runs.
  - `--auto-unroll` in `child_locator.py` is weakened because term extraction runs on missing text.
- Fix:
  - Add `clause_text` to `clauses` table at index-build time, or compute text from `section_text` + spans during query.

2. `strategy_writer.py` regression gate can silently pass invalid/empty strategies.
- Evidence:
  - If no valid patterns, evaluator returns `{}` with warning: `scripts/strategy_writer.py:219`.
  - Main regression flow does not fail on empty old/new evaluation groups: `scripts/strategy_writer.py:330`.
- Impact:
  - Circuit breaker can approve a strategy that matches nothing.
- Fix:
  - Treat empty evaluation result as hard failure unless `--skip-regression` is explicitly set.
  - Add minimum coverage assertion (for example, `evaluated_docs >= N` and `pattern_count >= 1`).

### Medium Severity

3. Strategy schema implementation diverges from target vision for template overrides.
- Evidence:
  - Runtime type is tuple serialization: `src/agent/strategy.py:67`.
  - Target plan expects `dict[str, dict]` with rich per-template override payloads.
- Impact:
  - Template-specific strategy refinement will be awkward and brittle.
- Fix:
  - Migrate `template_overrides` to dict shape with versioned migration logic.

4. Ingestion metadata is still minimal vs plan intent.
- Evidence:
  - Current build sets borrower from sidecar company name, leaves core fields blank: `scripts/build_corpus_index.py:327`.
  - `src/agent/metadata.py` is not present yet in repo.
- Impact:
  - Grouping/filtering quality is limited for pilot diagnostics.
- Fix:
  - Implement metadata extractor pass and wire into ingestion before broader pilot evaluation.

5. `section_reader --auto-unroll` misses many defined terms (especially all-caps forms).
- Evidence:
  - Candidate extraction uses title-case regex only: `scripts/section_reader.py:77`.
- Impact:
  - Definition linkage quality appears lower than actual corpus quality.
- Fix:
  - Expand term finder to include all-caps and mixed tokens (`EBITDA`, `U.S.` variants), then exact-match against definitions table.

## 2) Current Health Snapshot

- Test status: `82 passed` (`pytest -q tests` run on 2026-02-22).
- Compile status: all Python modules compile (`py_compile` pass).
- Plan coherence status: improved; staged ingestion and Phase B+ deferrals are now aligned in:
  - `plans/final_target_vision.md`
  - `plans/mvp_phase_a.md`

## 3) Final Vision Review (What Looks Right)

The final target plan is now directionally strong:
- staged gating (`500 -> 5,000 -> 30,000`) is explicit and practical;
- deferred tools (`llm_judge.py`, `template_classifier.py`, `structural_mapper.py`) are cleanly marked Phase B+;
- build order now separates MVP vs post-MVP concerns;
- schema version checks are standardized in tool entrypoints via `CorpusIndex` / `ensure_schema_version`.

Primary remaining risk is not planning coherence; it is implementation closure on the two high-severity gaps above.

## 4) Elegant 14-Tool Architecture (Opus 4.6-Ready)

Design principle: fewer primitives, stronger contracts, deterministic outputs.

1. `corpus_sync` (MVP)
- S3 staged sync with manifest and reproducibility fingerprint.
- Sources: Agent + VP corpus iteration patterns.

2. `index_builder` (MVP)
- Normalize -> sections -> clauses -> definitions -> metadata -> DuckDB snapshot.
- Sources: VP L0 + TI section extraction.

3. `section_locator` (MVP)
- Heading/keyword/DNA retrieval with confidence ladders.
- Sources: VP `section_locator`, `textmatch`.

4. `heading_variant_discoverer` (MVP)
- Discover heading aliases and canonicalize.
- Sources: TI round7/round8 concept registries.

5. `dna_discoverer` (MVP)
- TF-IDF + log-odds phrase mining with validation gates.
- Sources: VP L1 + TI DNA encoding add-ons.

6. `definition_resolver` (MVP)
- Definition lookup + cross-ref aware unrolling.
- Sources: TI definition engines + Neutron smart-quote handling.

7. `child_clause_locator` (MVP, after schema fix)
- Clause-level matching with depth, labels, and clause text.
- Sources: VP clause tree.

8. `pattern_tester` (MVP)
- Hit/miss diagnostics, nearest misses, confidence buckets.
- Sources: VP/TI evaluator patterns.

9. `coverage_reporter` (MVP)
- Coverage by template/group/cohort with blind-spot flags.
- Sources: existing Agent coverage tool + TI cohort diagnostics.

10. `evidence_bundle_collector` (MVP)
- Positive + NOT_FOUND records with provenance and near-miss context.
- Sources: Neutron provenance/evidence bundle concepts.

11. `strategy_compiler_writer` (MVP+)
- Merge bootstrap + discovered evidence + regression gate.
- Sources: VP strategy compiler + Agent strategy writer.

12. `template_classifier` (Phase B+)
- MinHash shingles + structural fingerprints + human labeling loop.
- Sources: TI round12 + round11.

13. `quality_judge` (Phase B+)
- LLM precision judge + human override integration.
- Sources: Agent vision + Neutron confidence envelope ideas.

14. `swarm_control_plane` (Phase B+/C)
- launch/start/send/status/dispatch/checkpoint/restart-safe loop.
- Sources: Neutron swarm + auto orchestrator reliability patterns.

## 5) 10-Subagent Framework (Prompt + Output Contract)

### Recommended 10-agent coverage map

1. TI core parsing/extraction
2. TI advanced semantics (modality/scope/gates)
3. TI registries/template clustering
4. VP infra + L0 parsing
5. VP L1/L2 discovery and scoring
6. VP metadata/bootstrap/lineage
7. Neutron swarm ops/prompts
8. Neutron backend confidence/provenance/failure signals
9. TermIntel domain setup/context scaffolding
10. auto reliability/orchestration primitives

### Subagent prompt contract (strict)

Every subagent must return:
- `repo_focus`: 2-4 bullets.
- `top_candidates`: table with:
  - `file_path`
  - `current_role`
  - `transferable_asset`
  - `proposed_agent_tool_mapping`
  - `port_mode` (`verbatim|adapt|inspiration|data`)
  - `priority` (`P0|P1|P2`)
  - `effort` (`S|M|L`)
  - `risk`
- `crown_jewels`: registries/constants/pattern libraries.
- `mvp_quick_wins`: max 5 items.
- `phase_b_plus`: max 5 items.

### Quality rubric for each candidate (scored during aggregation)

- Leverage (0-5): impact on precision/coverage/reliability.
- Portability (0-5): adaptation effort and dependency risk.
- Determinism (0-5): reproducible behavior without LLM dependency.
- Operational fit (0-5): fits CLI batch/swarm workflows.
- Total score = weighted rank for shortlist.

## 6) Practical Next Steps

1. Fix `child_locator` text-source contract first (schema + tool update + tests).
2. Harden `strategy_writer` regression gate to fail on empty/invalid evaluation.
3. Promote a stable 12-tool MVP baseline from the 14-tool architecture above.
4. Run a second source audit pass focused only on top-scoring candidates (score >= 16/20) and produce a final import/port queue.

## 7) Cross-Repo Crown-Jewel Shortlist (from 10-agent crawl)

### TermIntelligence
- `scripts/section_level_parser.py`
- `scripts/structure_extraction.py`
- `scripts/build_symbol_tables.py`
- `scripts/round8_registry_expansion.py`
- `scripts/round12_boilerplate_shingles.py`
- `scripts/round11_structural_fingerprint.py`
- `scripts/round9_boolean_parity.py`
- `scripts/round9_epistemic_gates.py`

### vantage_platform
- `src/vantage_platform/infra/textmatch.py`
- `src/vantage_platform/infra/html.py`
- `src/vantage_platform/l0/_enumerator.py`
- `src/vantage_platform/l0/_clause_tree.py`
- `src/vantage_platform/l1/discovery/section_locator.py`
- `src/vantage_platform/l1/discovery/section_analyzer.py`
- `src/vantage_platform/l1/discovery/strategy_compiler.py`
- `src/vantage_platform/l0/_metadata_impl.py`

### Neutron
- `tools/swarm/launch-swarm.sh`
- `tools/swarm-phase0/start-agent.sh`
- `tools/swarm-phase0/dispatch-wave.sh`
- `apps/backend/src/modules/flow-tracking/services/flow-event-emitter.service.ts`
- `apps/backend/src/modules/flow-tracking/services/trace-context.service.ts`
- `apps/backend/src/modules/confidence/services/unified-confidence.service.ts`
- `apps/backend/src/modules/agent/services/extraction/evidence-bundle-assembler.service.ts`

### TermIntel
- `taxonomy/build_taxonomy.py`
- `chunking/ca_chunker.py`
- `vectorstore/indexer.py`
- `config.py`

### auto
- `src/orchestrator/core.py`
- `src/command_center/services/state_manager.py`
- `src/backlog/schemas.py`
