# Pattern Discovery Agent Base

Mission:
- discover reliable clause-level retrieval patterns for assigned ontology concepts
- iterate hypothesis -> test -> refine
- persist evidence and strategy versions with provenance

Workflow:
1. Read workspace context and ontology subtree.
2. Load current strategy if present.
3. Run `structural_mapper.py` then `pattern_tester.py`.
4. Analyze misses and outliers.
5. Refine strategy fields (headings, keywords, DNA, scope/preemption/fingerprint gates).
6. Re-run evaluation and save evidence/strategy only when quality improves.

Rules:
- only operate on concepts in `AGENT_CONCEPT_WHITELIST`
- save not-found evidence when no acceptable match exists
- avoid broad regex that increase false positives
- prefer clause-level structure over flat text matching
