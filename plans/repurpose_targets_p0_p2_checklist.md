# Repurpose Targets Checklist (P0/P1/P2)

## Goal

Turn the 12 high-leverage repurpose targets into an execution-ready plan with:
- strict priority order (`P0`, `P1`, `P2`)
- exact `Strategy` schema additions
- acceptance tests for each delivery

This plan is a companion to `plans/execution_backlog_p0_p2.md` and is scoped to
the cross-repo repurpose audit.

---

## Priority Summary

### P0 (Immediate precision gains)
1. Definition Type Classifier (`round5_def_type_classifier.py`)
2. Boolean Parity Scope Engine (`round9_boolean_parity.py`)
3. Preemption DAG (`round9_preemption_dag.py`)
4. Unified Confidence Runtime (Neutron `unified-confidence.service.ts` pattern)

### P1 (Template robustness + analytics)
1. Module-level Boilerplate Shingles (`round12_boilerplate_shingles.py`)
2. Structural Fingerprint Matrix (`round11_structural_fingerprint.py`)
3. Section Analyzer Orchestration (VP `l1/discovery/section_analyzer.py`)
4. Definition Dependency Graph (`round5_def_dependency.py`)
5. ClauseTree API parity wrapper (VP `_clause_tree.py`)

### P2 (Ontology-scale generalization)
1. Canonical Registry Expansion (`round8_registry_expansion.py`)
2. Corpus Super-Graph + Ghost/Reserved analysis (`round7_super_graph.py`)
3. VP `_doc_parser.py` parity maintenance only (already strong)

---

## Exact `Strategy` Field Additions (`src/agent/strategy.py`)

Add these fields to `Strategy` dataclass exactly as listed:

```python
# Canonical heading + functional-area normalization
canonical_heading_labels: tuple[str, ...] = ()
functional_area_hints: tuple[str, ...] = ()

# Definition-shape controls
definition_type_allowlist: tuple[str, ...] = ()
definition_type_blocklist: tuple[str, ...] = ()
min_definition_dependency_overlap: float = 0.0

# Scope/parity controls
scope_parity_allow: tuple[str, ...] = ()  # e.g. ("BROAD", "NARROW")
scope_parity_block: tuple[str, ...] = ()
boolean_operator_requirements: dict[str, Any] = field(default_factory=dict)

# Preemption/override controls
preemption_requirements: dict[str, Any] = field(default_factory=dict)
max_preemption_depth: int | None = None

# Template/structure controls
template_module_constraints: dict[str, Any] = field(default_factory=dict)
structural_fingerprint_allowlist: tuple[str, ...] = ()
structural_fingerprint_blocklist: tuple[str, ...] = ()

# Confidence controls (runtime + evaluation parity)
confidence_policy: dict[str, Any] = field(default_factory=dict)
confidence_components_min: dict[str, float] = field(default_factory=dict)
did_not_find_policy: dict[str, Any] = field(default_factory=dict)
```

Notes:
- Keep defaults permissive to preserve backward compatibility.
- `strategy_from_dict()` already ignores unknown keys and handles missing keys via dataclass defaults.
- Add tests to confirm old strategy JSON loads unchanged.

---

## P0 Checklist

### P0.1 Definition Type Classifier

Source:
- `/Users/johnchtchekine/Projects/TermIntelligence/scripts/round5_def_type_classifier.py`

Current Agent gap:
- `NONE` (Agent extracts terms but does not classify definition structure types).

Deliverables:
- New module: `src/agent/definition_types.py`
- Extend `src/agent/definitions.py` to expose typed definition records.
- Add CLI output in `scripts/definition_finder.py` with type + confidence.
- Add optional strategy filtering in `scripts/pattern_tester.py`.

Strategy fields used:
- `definition_type_allowlist`
- `definition_type_blocklist`

Acceptance tests:
1. `pytest -q tests/test_definition_types.py` with fixtures covering direct, formulaic, incorporation, enumerative, hybrid.
2. `python3 scripts/definition_finder.py --db <db> --doc-id <id> --term EBITDA` returns `definition_type`.
3. `pattern_tester.py` run with allowlist should reduce matches on known false-positive fixture set.

---

### P0.2 Boolean Parity Scope Engine

Source:
- `/Users/johnchtchekine/Projects/TermIntelligence/scripts/round9_boolean_parity.py`

Current Agent gap:
- `NONE` (no operator sign/depth parity model).

Deliverables:
- New module: `src/agent/scope_parity.py`
- Add operator taxonomy + depth parser.
- Integrate parity features into `scripts/child_locator.py` and `scripts/pattern_tester.py`.

Strategy fields used:
- `scope_parity_allow`
- `scope_parity_block`
- `boolean_operator_requirements`

Acceptance tests:
1. `pytest -q tests/test_scope_parity.py` validates nested proviso examples.
2. Fixture clauses with equivalent logic but formatting variation produce same parity label.
3. `pattern_tester.py` reports parity channel metrics in output JSON.

---

### P0.3 Preemption DAG

Source:
- `/Users/johnchtchekine/Projects/TermIntelligence/scripts/round9_preemption_dag.py`

Current Agent gap:
- `NONE` (xref exists, precedence graph absent).

Deliverables:
- New module: `src/agent/preemption.py`
- Extract override/yield edges (`notwithstanding`, `subject to`).
- Build per-section DAG + SCC detection.
- Emit edge metadata in evidence payloads.

Strategy fields used:
- `preemption_requirements`
- `max_preemption_depth`

Acceptance tests:
1. `pytest -q tests/test_preemption.py` validates edge extraction and cycle handling.
2. Known synthetic precedence chain resolves expected controlling clause.
3. `pattern_tester.py` can enforce max depth gate without crashing on no-edge docs.

---

### P0.4 Unified Confidence Runtime

Source inspiration:
- `/Users/johnchtchekine/Projects/Neutron/apps/backend/src/modules/confidence/services/unified-confidence.service.ts`

Current Agent gap:
- `PARTIAL` (strong offline scoring/outliers; no unified runtime confidence service).

Deliverables:
- New module: `src/agent/confidence.py`
- Single API for confidence components + weighted final score.
- Align `scripts/pattern_tester.py` outputs to this model.
- Wire `scripts/strategy_writer.py` to enforce confidence policy gates.

Strategy fields used:
- `confidence_policy`
- `confidence_components_min`
- `did_not_find_policy`

Acceptance tests:
1. `pytest -q tests/test_confidence.py` for weighted aggregation and threshold gates.
2. `pattern_tester.py` output includes component breakdown and final confidence.
3. `strategy_writer.py` rejects strategy when confidence policy fails.

---

## P1 Checklist

### P1.1 Module-level Boilerplate Shingles

Source:
- `/Users/johnchtchekine/Projects/TermIntelligence/scripts/round12_boilerplate_shingles.py`

Current Agent gap:
- `PARTIAL` (document-level clustering exists; module-level shingles and deviation stats absent).

Deliverables:
- Extend `scripts/template_classifier.py` with module extraction and per-module MinHash.
- Add deviation/customization stats per module.

Strategy fields used:
- `template_module_constraints`

Acceptance tests:
1. Module-level classifications output file exists with non-empty cluster assignments.
2. Same doc can belong to different module clusters as expected.
3. Coverage report can group by module cluster and template family.

---

### P1.2 Structural Fingerprint Matrix

Source:
- `/Users/johnchtchekine/Projects/TermIntelligence/scripts/round11_structural_fingerprint.py`

Current Agent gap:
- `PARTIAL` (position distributions only; no full feature matrix/PCA/hash/archetypes).

Deliverables:
- New module: `src/agent/structural_fingerprint.py`
- Generate per-doc feature vectors + fingerprint IDs.
- Export discriminative feature ranking.

Strategy fields used:
- `structural_fingerprint_allowlist`
- `structural_fingerprint_blocklist`

Acceptance tests:
1. Fingerprint build on 500 docs outputs stable IDs across rerun.
2. PCA/discrimination summary generated with top features.
3. `pattern_tester.py` can filter/evaluate by fingerprint constraints.

---

### P1.3 Section Analyzer Orchestration

Source:
- `/Users/johnchtchekine/Projects/vantage_platform/src/vantage_platform/l1/discovery/section_analyzer.py`

Current Agent gap:
- `PARTIAL` (DNA math present, full family-profile orchestration missing).

Deliverables:
- Extend `src/agent/dna.py` orchestration layer and outputs.
- Add family-profile artifact generation for heading/keyword precision and prevalence.

Strategy fields used:
- Reuse existing metrics fields: `heading_hit_rate`, `keyword_precision`, `corpus_prevalence`, `cohort_coverage`.

Acceptance tests:
1. End-to-end run emits phrase candidates + family profile tables.
2. Profile metrics are consumed by `strategy_writer.py` gate decisions.
3. Backward compatibility with existing `dna_discoverer.py` inputs.

---

### P1.4 Definition Dependency Graph

Source:
- `/Users/johnchtchekine/Projects/TermIntelligence/scripts/round5_def_dependency.py`

Current Agent gap:
- `PARTIAL` (references extracted but no graph analytics).

Deliverables:
- New module: `src/agent/definition_graph.py`
- Build term dependency graph, centrality metrics, and communities.
- Optionally expose in `scripts/definition_finder.py` / dedicated script.

Strategy fields used:
- `min_definition_dependency_overlap`

Acceptance tests:
1. Graph built from fixture docs has non-zero edges and stable node counts.
2. Centrality ranking deterministic for fixed seed/input.
3. `pattern_tester.py` can enforce minimum dependency overlap where configured.

---

### P1.5 ClauseTree API Parity Wrapper

Source:
- `/Users/johnchtchekine/Projects/vantage_platform/src/vantage_platform/l0/_clause_tree.py`

Current Agent gap:
- `PARTIAL` (core parse exists, wrapper APIs missing).

Deliverables:
- Add wrapper object/API in `src/agent/clause_parser.py` for:
  - `find_containing`
  - `children_of`
  - `flatten`
  - `summary`

Strategy fields used:
- None new.

Acceptance tests:
1. `pytest -q tests/test_clause_tree_api.py`
2. Span containment and path resolution match expected fixtures.
3. No regression in existing clause parser outputs.

---

## P2 Checklist

### P2.1 Canonical Registry Expansion

Source:
- `/Users/johnchtchekine/Projects/TermIntelligence/scripts/round8_registry_expansion.py`

Current Agent gap:
- `PARTIAL` (heading discoverer exists; dynamic registry expansion absent).

Deliverables:
- Extend `scripts/heading_discoverer.py` to produce registry candidates.
- Add reviewable alias promotion flow (candidate -> accepted registry).

Strategy fields used:
- `canonical_heading_labels`
- `functional_area_hints`

Acceptance tests:
1. Candidate heading aliases generated with support counts.
2. Accepted aliases improve holdout hit rate without precision collapse.
3. Registry versioning artifact persisted and diffable.

---

### P2.2 Corpus Super-Graph + Ghost/Reserved Analysis

Source:
- `/Users/johnchtchekine/Projects/TermIntelligence/scripts/round7_super_graph.py`

Current Agent gap:
- `PARTIAL` (no corpus-level present/ghost/reserved analytics).

Deliverables:
- New script: `scripts/super_graph_analyzer.py`
- Build union concept graph and per-doc diff states.
- Output ghost/reserved/novel metrics.

Strategy fields used:
- Reuse `outlier_policy` and `template_stability_policy` with ghost-aware criteria.

Acceptance tests:
1. Analyzer produces per-doc concept-state records.
2. Ghost state counts reproducible across reruns.
3. Outlier summaries can include ghost-driven reason codes.

---

### P2.3 VP `_doc_parser.py` parity maintenance

Source:
- `/Users/johnchtchekine/Projects/vantage_platform/src/vantage_platform/l0/_doc_parser.py`

Current Agent status:
- `STRONG` (already ported).

Deliverables:
- No net-new feature work.
- Add drift tests against upstream behavior on shared fixtures.

Strategy fields used:
- None.

Acceptance tests:
1. Snapshot comparison tests pass for article/section/xref extraction.
2. Drift alert triggers on upstream regex/parser behavior changes.

---

## Implementation Sequence (Recommended)

1. P0.1 Definition Type Classifier
2. P0.2 Boolean Parity
3. P0.3 Preemption DAG
4. P0.4 Unified Confidence Runtime
5. P1.1 Module-level Shingles
6. P1.2 Structural Fingerprint
7. P1.3 Section Analyzer Orchestration
8. P1.4 Definition Dependency Graph
9. P1.5 ClauseTree API Wrapper
10. P2.1 Registry Expansion
11. P2.2 Super-Graph Analyzer
12. P2.3 Doc Parser Parity Maintenance

---

## Definition of Done (for this checklist)

- Every item has:
  - merged code
  - passing unit/integration tests
  - one run artifact in `workspaces/indebtedness/results/` or `corpus_index/templates/`
  - one short change note in strategy `update_notes`
- `strategy.py` field additions are backward compatible with existing strategy JSON files.
