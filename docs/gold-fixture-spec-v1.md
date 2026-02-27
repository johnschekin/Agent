# Gold Fixture Specification v1
Date: 2026-02-27  
Scope: clause parsing quality, no-regression gating, and ML/LLM-ready supervision assets.

## 1) Objective
Build a single fixture program that serves both:
1. Deterministic parser refactor/regression gates now.
2. Future ML/LLM training, validation, and benchmark evaluation.

This spec defines fixture schema, reason-code policy, splits, adjudication flow, and acceptance gates.

## 2) Design Principles
1. One source of truth: same fixture artifacts for parser and model evaluation.
2. Explicit uncertainty: use `review`/`abstain` labels where ambiguity is real.
3. Reproducibility: freeze source text snapshot and split manifests.
4. Leak-safe evaluation: split by document, never by clause.
5. Minimal silent drift: fixture changes require rationale and version bump.

## 3) Dataset Targets (v1.0)
1. Total fixtures: ~550.
2. Composition:
3. Synthetic exact fixtures: 120.
4. Corpus-sourced fixtures: 300.
5. Adversarial/noisy fixtures: 80.
6. Ontology-linking contract fixtures: 50.
7. Human-verified share: >= 35% overall, >= 70% for ambiguity classes.

## 4) Coverage Taxonomy
Required categories:
1. `ambiguous_alpha_roman`
2. `high_letter_continuation`
3. `xref_vs_structural`
4. `deep_nesting_chain`
5. `nonstruct_parent_chain`
6. `duplicate_collision`
7. `defined_term_boundary`
8. `formatting_noise`
9. `true_root_high_letter`
10. `linking_contract`

Each category must include:
1. Positive controls (known correct behavior).
2. Negative controls (known false-positive traps).
3. Ambiguous cases (expected `review` or `abstain`).

## 5) Artifact Layout
Canonical location:
1. `data/fixtures/gold/v1/fixtures.jsonl`
2. `data/fixtures/gold/v1/splits.v1.manifest.json`
3. `data/fixtures/gold/v1/reason_codes.v1.json`
4. `data/fixtures/gold/v1/README.md`
5. `data/fixtures/gold/v1/fixture.template.json`

Optional sidecars:
1. `data/fixtures/gold/v1/text_snapshots/*.txt`
2. `data/fixtures/gold/v1/adjudication/*.jsonl`

## 6) Fixture Schema (canonical record)
Top-level required fields:
1. `fixture_id`: stable immutable ID.
2. `schema_version`: must be `gold-fixture-v1`.
3. `category`: one of taxonomy categories.
4. `source_type`: `synthetic|corpus`.
5. `source`: object with `doc_id`, `section_number`, `snapshot_id`.
6. `text`: object with `raw_text`, `char_start`, `char_end`, `normalization`.
7. `gold_nodes`: list of expected nodes.
8. `gold_decision`: `accepted|review|abstain`.
9. `reason_codes`: list of codes from `reason_codes.v1.json`.
10. `adjudication`: object with verification metadata.
11. `split`: `train|val|test|holdout`.

Node object required fields:
1. `clause_id`
2. `label`
3. `parent_id`
4. `depth`
5. `level_type`
6. `span_start`
7. `span_end`
8. `is_structural`
9. `xref_suspected`

Optional node fields:
1. `confidence_band`: `high|medium|low`
2. `notes`

## 7) Decision Policy
Allowed `gold_decision` meanings:
1. `accepted`: deterministic target parse is defined and expected.
2. `review`: multiple plausible outcomes but one preferred with human context.
3. `abstain`: parser/model should not auto-assert structure confidently.

Rules:
1. `accepted` fixtures are valid for exact-match parser gating and supervised labels.
2. `review` fixtures are excluded from strict exact-match failure budgets.
3. `abstain` fixtures are scored by abstention correctness, not forced structure.

## 8) Reason-Code Taxonomy
Reason codes are machine-readable and must come from:
1. `data/fixtures/gold/v1/reason_codes.v1.json`

Use cases:
1. Triage queues.
2. Error analytics.
3. Model target masking for ambiguous labels.
4. Production abstain reason reporting.

## 9) Split Policy (ML-safe)
1. Split at `doc_id` granularity only.
2. No doc overlap across `train|val|test|holdout`.
3. Holdout is frozen for release comparison only.
4. Category stratification target: each major category appears in all splits.
5. Ambiguous fixtures are overrepresented in `val/test` to prevent overfitting.

## 10) Adjudication Workflow
Pipeline:
1. Candidate extraction from edge-case hotspots and control pools.
2. Auto-label pass for low-ambiguity fixtures.
3. Human adjudication for ambiguity classes `A1|A2|A3`.
4. Dual-review on contested fixtures.
5. Freeze record with adjudicator metadata.

Adjudication metadata required:
1. `human_verified`: bool.
2. `ambiguity_class`: `none|A1|A2|A3`.
3. `adjudicator_id`
4. `adjudicated_at`
5. `rationale`

## 11) Parser Gates (current)
Fixture-driven gates:
1. `gold_exact`: exact node match for `accepted`.
2. `gold_tolerant`: bounded span tolerance for noisy fixtures.
3. `abstain_gate`: abstention correctness on `abstain`.
4. `invariant_gate`: zero parser invariant violations.
5. `shadow_gate`: no unacceptable drift in shadow reparse sample.
6. `guardrail_gate`: corpus detector budgets.

## 12) ML/LLM Readiness Contract
This fixture format is immediately usable for:
1. Supervised fine-tuning (`accepted` fixtures).
2. Preference/ranking datasets (alternate parses with human rationales).
3. Prompt benchmark suites (few-shot + deterministic eval).
4. Abstain calibration (`review`/`abstain` fixtures).

Required for ML usage:
1. Keep offsets exact and stable.
2. Preserve raw source text snapshot IDs.
3. Never relabel fixtures without changelog + version bump.

## 13) Versioning and Change Control
1. Dataset semantic versioning: `vMAJOR.MINOR`.
2. Any schema change requires MAJOR bump.
3. Label or split updates require MINOR bump and changelog entry.
4. Keep previous versions immutable for reproducible backtests.

## 14) Acceptance Criteria for v1.0
1. Fixture count >= 550 with required category coverage.
2. Split manifest complete and leak-safe.
3. `accepted` fixtures >= 70% of total.
4. Ambiguity fixtures have reason codes and adjudication metadata.
5. Parser gate wired into CI with version-pinned fixture paths.
6. Baseline benchmark report generated and archived.

## 15) Execution Plan (immediate)
Phase 1:
1. Finalize reason codes and templates.
2. Build extraction and validation scripts.
3. Seed first 250 fixtures.

Phase 2:
1. Human adjudicate ambiguous pool.
2. Expand to 550 fixtures.
3. Freeze `v1.0` + publish benchmark.

Phase 3:
1. Start parser refactor work gated on this fixture set.
2. Reuse the same fixtures for ML/LLM experiments when enabled.
