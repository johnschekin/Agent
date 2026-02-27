# Agent Canonical IDs v1

Status: frozen for Wave 3
Effective date: 2026-02-27

## Scope
This contract defines deterministic ID generation for parser, linker, and export outputs in Agent.

## Canonical IDs

1. `document_id`
- Formula: `sha256(normalized_source_bytes)` (lowercase hex, 64 chars).
- `normalized_source_bytes`:
  - Input document bytes only (no filesystem path, mtime, run metadata).
  - Preserve byte order; do not transcode.

2. `section_reference_key`
- Formula: `{document_id}:{section_number}`.
- `section_number`:
  - Canonical section identifier emitted by parser/index (for example `7.01`).
  - Must be stable for identical source bytes and parser config.
  - No heading-derived normalization in v1.

3. `clause_key`
- Formula: `{section_reference_key}:{clause_path}`.
- `clause_path`:
  - Deterministic clause path emitted by parser (`a`, `a.1`, `a.1.i`, etc).
  - No random suffixes; path order must be traversal-stable.

4. `ontology_node_id`
- Value must be immutable release node identifier from ontology payload.
- Must validate against active ontology release before persistence.

5. `chunk_id`
- Formula:
  - `sha256("{document_id}|{section_reference_key}|{clause_key}|{span_start}|{span_end}|{text_sha256}")`
  - Lowercase hex, 64 chars.
- `text_sha256` is hash of the exact anchored evidence text span.

## Required invariants

1. Same input bytes + same parser config => same `document_id`, `section_reference_key`, `clause_key`, `chunk_id`.
2. IDs are pure functions of canonicalized content/anchor inputs and must not include timestamps.
3. All persisted/exported IDs are lowercase hex (when hash-based) and non-empty.
4. Any missing anchor component (`section_number`, `clause_path`, span bounds, `text_sha256`) makes `chunk_id` invalid and must fail fast at export boundary.

## Example

```json
{
  "document_id": "2b70f8ca4d92a8b1f1d7f4e1ea9a9967f5cbe57f482cb9f22857dcf0176fa0aa",
  "section_reference_key": "2b70f8ca4d92a8b1f1d7f4e1ea9a9967f5cbe57f482cb9f22857dcf0176fa0aa:7.02",
  "clause_key": "2b70f8ca4d92a8b1f1d7f4e1ea9a9967f5cbe57f482cb9f22857dcf0176fa0aa:7.02:a.1.i",
  "ontology_node_id": "debt_capacity.indebtedness.other_debt",
  "chunk_id": "b7f4b3e190cd54f77ea8420a0a18a572ba30f2246ba76397cb0c4bfc6cf966e4"
}
```
