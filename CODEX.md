# CODEX.md

## Scope
This is Codex-specific working context for this repository, focused on:
1. Ontology links workflow execution (domain/family/concept/sub-component scopes).
2. Helping the user create, test, and publish rules safely.

It is intentionally aligned to the relevant guidance in `CLAUDE.md`, but narrowed to operational use while coding.

## Ontology Links Workflow (Default Loop)
Use this loop for ontology-link tasks:
1. Clarify target relationship and success criteria.
2. Draft rule(s) in the linking DSL.
3. Preview results before publish (inspect hits, misses, and edge cases).
4. Iterate on filters/thresholds/operators until precision/recall is acceptable.
5. Publish only after evidence-backed validation.
6. Record version + rationale for traceability.

## Rule Creation Workflow (Assistant Behavior)
When helping create rules:
1. Start from corpus evidence, not intuition.
2. Propose a minimal first rule, then refine.
3. Show why each condition exists (what false positives/negatives it addresses).
4. Validate against representative examples and boundary cases.
5. Keep changes versioned and reversible.

## Non-Negotiable Evidence Rules
1. Do not invent domain facts or snippets.
2. Always ground outputs in real corpus evidence.
3. Preserve and report global offsets for quoted evidence.
4. Log evidence rows with `(doc_id, char_start, char_end)`.
5. Emit structured JSON to stdout when required by the workflow/tooling.

## Data + Storage Constraints
1. Treat DuckDB indexes as read-only, except dedicated index-builder paths.
2. Keep strategy versions immutable once published.
3. Prefer append/new-version patterns over in-place mutation for rules/strategies.

## Key Components to Touch for Ontology Linking
Focus edits and investigation in these areas when relevant:
1. `query_filters`
2. `embeddings` (including Voyage embedding usage where configured)
3. `link_store`
4. Bootstrap data used by linking flows
5. Expert notes/knowledge inputs consumed by link generation
6. Ontology-link API/auth surfaces and dashboard integration points

## Rule Proposal Template
Use this structure when drafting rules for the user:
1. Objective: what relationship this rule should capture.
2. Candidate rule: DSL expression.
3. Evidence: concrete matched snippets with offsets.
4. Expected impact: precision/recall tradeoff.
5. Risks: likely false positives/negatives.
6. Next iteration: one targeted change to test.

## Publish Checklist
Before publish, confirm all are true:
1. Rule behavior was previewed on realistic samples.
2. Evidence is attached with offsets and doc IDs.
3. No read-only data paths were mutated.
4. Versioning metadata is explicit.
5. Rollback path is clear.
