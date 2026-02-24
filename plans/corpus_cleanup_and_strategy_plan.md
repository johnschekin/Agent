# Corpus Cleanup & Strategy Foundation Plan

**Created:** 2026-02-23
**Status:** In Progress
**Last Updated:** 2026-02-23 (Block 5 added — domain expert verification & golden set)

---

## Maintenance Instructions

- Update the `Last Updated` date and `Status` after each work session
- Mark items `[x]` when complete, add date in parentheses and add a nested bullet(s) as to relevant findings and implementation notes.
- If a task is blocked, mark `[~]` and note the blocker
- Sub-findings discovered during a task get appended as indented bullets
- When all items in a block are complete, mark the block header as `[x]`

---

## Block 1 — Parsing Quality: Edge Cases & Extraction Gaps

### 1.1 Section Numbers
- [x] Investigate the 95 zero-section documents — sample 10–15, identify formatting patterns (2026-02-23)
  - Downloaded 19 of 95 docs from S3 (`edgar-pipeline-documents-216213517387`). Created `scripts/diagnose_zero_sections.py` diagnostic tool.
  - **Key finding:** ALL 95 docs are large credit agreements (30K–175K words, avg 89K). Zero short/non-CA docs — completely different from initial hypothesis.
  - Dominant failure mode: articles detected (via `_SECTION_TOPLEVEL_RE` or `_ARTICLE_RE`) but zero `Section X.YY` sub-headings found.
- [x] Categorize failure modes (non-standard headings, HTML artifacts, flat-text, OCR noise) (2026-02-23)
  - Failure modes on 19-doc sample: 15 "articles exist, no sub-sections" (79%), 2 TOC over-rejection (11%), 1 aggressive filtering (5%), 1 PDF mega-line doc (5%)
  - No short docs, no non-CA docs, no OCR noise in the zero-section population
- [x] Expand `DocOutline` regex patterns to cover identified gaps (2026-02-23)
  - **Fix A:** Part/Chapter/Clause article patterns (`_PART_ARTICLE_RE`, `_CHAPTER_ARTICLE_RE`, `_CLAUSE_TOPLEVEL_RE`) — new fallback chain in `_detect_articles()`
  - **Fix B:** Flat numbered section pattern (`_SECTION_FLAT_RE`, "1. Definitions" style) — last-resort in `_detect_sections()`, guarded by ≥5 matches + no articles + no X.YY sections
  - **Fix C:** TOC over-rejection recovery — added `min_signals` parameter to `_is_toc_entry()`, retry with `min_signals=2` when all matches rejected
  - **Fix D:** Ghost section pattern widened for quoted defined terms (`"` and `\u201c`)
  - **Fix E:** Plausibility threshold relaxed from `major > 40` to `major > 60` for flat (no-article) docs
  - **Fix F** (not in original plan, discovered from live data): Section-from-article synthesis — `_synthesize_sections_from_articles()` creates one section per article when articles exist but sections don't. This was the dominant recovery mechanism.
- [x] Re-run section extraction on failed docs to validate fixes (2026-02-23)
  - **Recovery rate: 17/19 docs recovered (89%)**. Fix F recovered 15 docs, Fix C recovered 2 docs, 1 doc recovered by other fixes.
  - Projected full-corpus impact: 95 → ~10 irreducible (89% reduction)
  - 2 unrecovered: `42ca1c7fa85add9c` (PDF mega-line, 174K words, avg 2,821 chars/line — needs fundamentally different approach) and `43b11fee6dcb08bc` (153 raw section matches all rejected by filtering)
  - All 356 tests pass (25 new + 331 existing), pyright 0 errors, ruff clean on new files
- [x] Update dashboard edge-case reporting with new failure categories (2026-02-23)
  - Enriched `detail` field in `/api/edge-cases` endpoint with dynamic CASE WHEN (short doc, non-CA, parser gap)
  - Added `section_parser_mode` and `section_fallback_used` columns to DuckDB `documents` schema
  - **Files modified:** `src/agent/doc_parser.py`, `scripts/build_corpus_index.py`, `dashboard/api/server.py`
  - **Files created:** `scripts/diagnose_zero_sections.py`, `tests/test_zero_section_recovery.py`

### 1.2 Clause Numbers — Nesting Accuracy
> **Note:** This is NOT just about extraction rate (99.17%). The primary issue is nesting level accuracy.

**Known issues from visual inspection (doc 405bacce509c03b1):**
- Roman numerals (i)–(viii) under (a) misclassified as `Type: alpha` instead of `Type: roman`
- Cross-references parsed as structural clauses (e.g., `(x) and (y) above`, `(b), (c) and (d) of Section 4.01`)
- Inline enumerations within sentences treated as top-level clauses
- Ghost/empty clause bodies (e.g., `(b) .`)
- Spurious labels (e.g., `(s)` appearing where `(ii)` should be)
- Depth errors — items that should be children (depth 2) showing as depth 1

**Cross-project analysis:** Clause parsing implementations exist in TermIntelligence, Vantage Platform, Neutron, ClauseChunk, ClauseTree, and TermIntel. All 6 codebases analyzed by subagents. (ClauseChunk was data-only, no parsing code.)

#### Cross-Project Clause Parser Comparison (2026-02-23)

| Feature | Agent (current) | VP / ClauseTree | TermIntel | Neutron |
|---|---|---|---|---|
| **Tree construction** | Stack-walk | Stack-walk | Stack-walk | Stack-walk |
| **Canonical depth order** | alpha(1)→roman(2)→caps(3)→numeric(4) | alpha(1)→roman(2)→caps(3)→numeric(4) | letter(2)→roman(3)→upper(4)→arabic(5) | alpha(1)→roman(2)→caps_alpha(3)→numeric(4) |
| **(i) disambiguation** | Regex overlap dedup only | 3-case: run tracking + (ii) lookahead (5000 chars) | 4-rule cascade: sequential-letter → active-roman → letter-has-children → default | Tag vote: roman_count vs alpha_count from regex |
| **Xref detection** | `_is_xref()` 80-char lookback | `_is_xref_context()` 80-char + Lark grammar | N/A (evaluation layer only) | `_is_cross_ref()` similar heuristic |
| **Confidence scoring** | Basic (single score) | 5-signal weighted: anchor(0.30), run_length(0.30), gap(0.20), xref(0.15), indent(0.05) | N/A | N/A |
| **Singleton demotion** | No | Hard invariant: always demoted | N/A | Partial (orphan pruning) |
| **Anchor checking** | No | Precomputed line starts + hard boundary detection | N/A | No |
| **Sibling tracking** | No | Implicit via stack | Explicit `last_siblings: dict[int, str]` with level-reset | No |

#### Agent clause_parser.py — Specific Bugs Identified

1. **Global `(h)` override (`_ALPHA_ONLY`)**: `clause_parser.py` has a `_ALPHA_ONLY` set containing `(h)`, `(v)`, `(x)`, `(c)`, `(d)`, `(i)`, `(l)`, `(m)` which are ALWAYS classified as alpha regardless of context. This means `(v)` as Roman numeral V is never recognized.
2. **`(iv)` / `(vi)` misclassification**: When `(i)` is at depth 1 and classified as alpha, subsequent `(iv)` and `(vi)` are also forced to alpha because they overlap with the `_ALPHA_ONLY` set (via `(i)` and `(v)`).
3. **No run tracking**: Agent has no concept of "if we've already seen `(i)`, `(ii)`, `(iii)`, then `(iv)` is almost certainly Roman." VP/ClauseTree track run length and use it as a strong signal.
4. **Xref lookback too short**: `_is_xref()` uses 80-char lookback. Cross-references like `clauses (a), (b), (c) and (d) of Section 4.01 of the Credit Agreement` can span 100+ chars.
5. **No anchor checking**: Agent doesn't verify whether `(a)` appears at line start vs. mid-sentence. VP precomputes line-start offsets and uses this to reject mid-sentence enumerators.
6. **No singleton demotion**: A level with only 1 item (e.g., a single `(i)` under `(a)` with no `(ii)`) is almost always a cross-reference, not a structural child. VP/ClauseTree demote these as a hard invariant.

#### Proposed Refactoring Plan — 6 Improvements (Ordered by Impact)

**Improvement 1: (i) Disambiguation — Port TermIntel's `last_siblings` + VP's (ii) Lookahead**
- Replace `_ALPHA_ONLY` global override with context-sensitive cascade
- Add `last_siblings: dict[int, str]` tracking (from TermIntel) — when `(a)` was last seen at depth 1, and next we see `(i)`, check if `(ii)` appears within 5000 chars ahead
- 4-rule cascade: (1) if sequential with prior alpha letter, classify as alpha; (2) if active Roman run exists at this depth, classify as Roman; (3) if parent has alpha children already, classify as alpha; (4) default to Roman if ambiguous
- **Files:** `src/agent/clause_parser.py` — `_classify_label()`, `_build_clause_tree()`
- **Expected impact:** Fixes the `(i)`→`(viii)` misclassification bug and the `(v)` / `(x)` suppression

**Improvement 2: Confidence Scoring — Port VP/ClauseTree 5-Signal Weighted System**
- Replace basic confidence with 5-signal weighted score per clause:
  - `anchor` (w=0.30): Is the enumerator at line start or after a hard boundary (`;`, `.`)?
  - `run_length` (w=0.30): How many consecutive siblings have we seen at this level? (1=low, 3+=high)
  - `gap` (w=0.20): Is there a gap in the sequence (e.g., `(a)`, `(c)` with no `(b)`)? Penalize.
  - `xref` (w=0.15): Inverse of `_is_xref()` score — high if definitely not a cross-reference
  - `indent` (w=0.05): Does indentation level match expected depth?
- Store per-clause `parse_confidence` using this scoring (already in DuckDB schema)
- **Files:** `src/agent/clause_parser.py` — new `_compute_confidence()`, update `ClauseNode`
- **Expected impact:** Enables downstream quality filtering and edge-case detection

**Improvement 3: Singleton Demotion — Hard Invariant**
- After tree construction, post-process: any level with exactly 1 sibling → mark `is_structural=False`
- Rationale: A lone `(i)` under `(a)` with no `(ii)` is almost always a cross-reference artifact
- VP/ClauseTree enforce this as a hard invariant and it eliminates a large class of false positives
- **Files:** `src/agent/clause_parser.py` — post-processing pass in `_build_clause_tree()`
- **Expected impact:** Removes ghost/spurious clauses at depth 2+

**Improvement 4: Enhanced Xref Detection — Wider Context + Lark Grammar**
- Increase `_is_xref()` lookback from 80 to 200 chars
- Add lookahead for xref continuations: `of Section`, `of Article`, `above`, `below`, `hereof`, `thereof`
- For complex multi-reference patterns (e.g., `(a), (b), (c) and (d) of Section 4.01`), consider VP's Lark grammar approach for structured parsing
- Add common xref templates: `clauses (x) and (y)`, `paragraphs (x) through (y)`, `sub-clauses (x)–(y)`
- **Files:** `src/agent/clause_parser.py` — `_is_xref()`, possibly new `_parse_xref_grammar()`
- **Expected impact:** Reduces false-positive clause counts, especially in heavily cross-referenced covenant sections

**Improvement 5: Anchor Checking — Line-Start Detection**
- Precompute line-start offsets for the section text before parsing
- For each candidate enumerator, check: is it at column 0 or immediately after a hard boundary (`;`, `.`, newline)?
- Mid-sentence `(a)` that isn't at a boundary → downweight or skip
- VP calls these "hard boundaries" and uses them as a primary structural signal
- **Files:** `src/agent/clause_parser.py` — new `_precompute_anchors()`, update match loop
- **Expected impact:** Eliminates inline enumeration false positives (e.g., `items (x) and (y) in the agreement`)

**Improvement 6: Sibling Level-Reset — Clear Deeper Levels on Shallower Marker**
- When the parser encounters a marker at depth N, clear all tracked siblings at depths > N
- This prevents stale sibling state from a previous subtree from contaminating the current one
- TermIntel implements this explicitly; VP does it implicitly via stack pop
- **Files:** `src/agent/clause_parser.py` — `_build_clause_tree()` stack management
- **Expected impact:** Fixes depth errors where items that should be children show as depth 1

#### Codebase-Specific Findings

**Vantage Platform (VP):**
- `vp_parser/clause_tree.py` — production-grade clause parser with anchor checking, confidence scoring, singleton demotion
- `_is_xref_context()` uses both heuristic lookback and Lark grammar for complex references
- 5-signal confidence model is well-tested and tuned for leveraged finance agreements
- Code is clean and modular; individual functions can be ported independently

**ClauseTree:**
- Nearly identical to VP (shared heritage). Same 5-signal confidence, same singleton invariant
- `clause_tree/parser.py` — uses `lark` library for grammar-based xref parsing
- Adds `_detect_inline_enum()` helper that checks for patterns like `(x), (y) and (z)` within a single sentence

**TermIntel:**
- `termi_parse/clause_nesting.py` — unique 4-rule disambiguation cascade for (i) ambiguity
- `last_siblings: dict[int, str]` is the key innovation — simple, stateful, effective
- Offset tracking uses 1-based indexing (unlike Agent's 0-based); conversion needed if porting

**TermIntelligence:**
- `termint/parsers/clause_outline.py` — stack-walk with explicit depth tracking
- Simpler than VP but has good ghost clause filtering (min 10-char body requirement)
- `_reject_empty_clause()` helper could be ported for ghost clause fix

**Neutron:**
- `neutron/nlp/clause_tagger.py` — ML-assisted approach: regex extraction + random forest classifier for structural vs. non-structural
- Training data: 500 hand-labeled clause trees from leveraged finance agreements
- "Tag vote" system for (i) disambiguation: counts Roman-like vs. alpha-like patterns in surrounding context
- Interesting but heavy dependency (requires trained model); best ideas to port are the tag-vote heuristic and orphan pruning

**ClauseChunk:**
- Data-only package (pre-chunked clause segments for downstream consumers). No parsing code. Not useful for our purposes.

**Tasks:**
- [x] Analyze clause parsers in TermIntelligence, Vantage Platform, Neutron, ClauseChunk, ClauseTree, TermIntel (2026-02-23)
  - All 6 codebases analyzed. ClauseChunk is data-only. Comparison table and bug list compiled above.
- [ ] Audit `clause_parser.py` (i) vs alpha disambiguation logic — identify when (vi) at depth 1 gets classified as alpha
- [ ] Implement Improvement 1: (i) disambiguation — `last_siblings` dict + (ii) lookahead + 4-rule cascade
- [ ] Implement Improvement 2: 5-signal weighted confidence scoring
- [ ] Implement Improvement 3: Singleton demotion post-processing pass
- [ ] Implement Improvement 4: Enhanced xref detection — 200-char lookback + lookahead + Lark grammar
- [ ] Implement Improvement 5: Anchor checking — precompute line starts, reject mid-sentence enumerators
- [ ] Implement Improvement 6: Sibling level-reset on shallower marker
- [ ] Fix ghost clause bodies — port TermIntelligence's min 10-char body filter
- [ ] Add inline enumeration detection — port ClauseTree's `_detect_inline_enum()` helper
- [ ] Sample 20 documents across templates and score nesting accuracy manually (pre/post comparison)
- [ ] Add nesting accuracy metrics to the dashboard quality page

### 1.3 Definitions
- [ ] Investigate the bimodal distribution (median 19, P95 272) — are low-count docs genuinely sparse or extraction failures?
- [ ] Sample docs with <10 definitions and >200 definitions to validate accuracy
- [ ] Review definition boundary precision (start/end offsets)
- [ ] Check for cross-contamination between definition engines (colon engine false positives in particular)

### 1.4 Facility Size
> **Root cause identified:** `build_corpus_index.py:569` uses `.get("aggregate")` but `extract_facility_sizes()` returns `"facility_size_mm"` as the key. This is why 0/12,583 docs have facility size data.

- [x] Fix key mismatch in `build_corpus_index.py` — change `.get("aggregate")` to `.get("facility_size_mm")` (2026-02-23)
  - Fixed in `build_corpus_index.py:573`. Also added `facility_confidence` column to schema and doc_record.
- [ ] Verify `extract_facility_sizes()` works on sample docs (unit test with real corpus text)
- [ ] Port TermIntelligence Wave 3 logic (Section 2.01 commitment table parsing) if needed
- [ ] Rebuild corpus index and verify facility size population rate
- [ ] Add facility size distribution to dashboard overview KPIs

### 1.5 Borrower
> **Focus:** Documents where borrower extraction returned None/empty — not accuracy of existing extractions.

- [ ] Query corpus index for docs with empty/null borrower field
- [ ] Quantify: how many of 12,583 docs have no borrower?
- [ ] Sample 20 missing-borrower docs, manually identify what borrower patterns they use
- [ ] Expand `extract_borrower()` regex passes to cover new patterns
- [ ] Validate fixes against the sampled docs

### 1.6 Administrative Agent
> **Issue:** Multiple blank admin_agent fields observed in the dashboard. Similar to borrower — need to quantify the gap and fix extraction.

**Agent analysis findings (2026-02-23):**
- `extract_admin_agent()` in `metadata.py` uses a **single regex** searching first 10K chars for `"as Administrative Agent"` only
- Gap 1: **Search window too narrow** — some credit agreements place the admin agent identification after introductory recitals, which can exceed 10K chars in long-form agreements
- Gap 2: **Missing role variants** — the function doesn't match `"as Agent"`, `"as Collateral Agent"`, `"as Administrative Agent and Collateral Agent"`, `"as Arranger"`, `"in its capacity as agent"`, or `"acting as agent"`
- Gap 3: **No fallback patterns** — when the standard pattern fails, no secondary extraction is attempted (e.g., searching for bank names near "agent" in the signature block)
- Gap 4: **False positives possible** — the regex captures the entity name before `"as Administrative Agent"` but doesn't validate that it's actually a financial institution name
- **Estimated improvement**: Widening search to 20K chars + adding 5-6 role variant patterns should recover 60-80% of missing admin agents

**Tasks:**
- [ ] Query corpus index for docs with empty/null admin_agent field
- [ ] Quantify: how many of 12,583 docs have no admin_agent?
- [ ] Widen search window from 10K to 20K chars in `extract_admin_agent()`
- [ ] Add role variant patterns: `"as Agent"`, `"as Collateral Agent"`, `"as Administrative Agent and Collateral Agent"`, `"in its capacity as [Aa]gent"`
- [ ] Add signature block fallback: search for bank names near "agent" in last 5K chars
- [ ] Tighten false-positive filtering: validate extracted entity looks like a financial institution name
- [ ] Sample 20 missing-admin-agent docs before/after to validate improvements
- [ ] Validate fixes against the sampled docs

### 1.7 EBITDA (Closing EBITDA from Grower Baskets)
> **Logic exists** in `src/agent/metadata.py:extract_grower_baskets()` — it infers `closing_ebitda_mm` from the modal implied EBITDA across grower basket pairs (e.g., "greater of 50% of Consolidated EBITDA and $100M" → EBITDA = $200M).
>
> **Pipeline gap:** `extract_grower_baskets()` is **never called** in `build_corpus_index.py`, and there is no `closing_ebitda` column in the DuckDB schema.

- [x] Add `closing_ebitda_mm` column to DuckDB schema in `build_corpus_index.py` (2026-02-23)
  - Added to DDL, doc_record dict, and INSERT statement. Also added `facility_confidence` column.
- [x] Add `ebitda_confidence` column to DuckDB schema (2026-02-23)
  - Added alongside `closing_ebitda_mm`. Values: high/medium/low/none.
- [x] Call `extract_grower_baskets()` in the build pipeline alongside other metadata (2026-02-23)
  - Imported and called in Step j of `_process_file()`. Results stored in `closing_ebitda_mm` and `ebitda_confidence`.
- [x] Store `closing_ebitda_mm` and `ebitda_confidence` per document (2026-02-23)
  - Updated `corpus.py` DocRecord, `build_corpus_index.py` doc_record, INSERT, and dashboard server doc detail response.
- [ ] Rebuild corpus index and verify EBITDA population rate
- [ ] Add EBITDA distribution to dashboard overview (similar to facility size)
- [ ] Port `inferred_leverage = facility_size_mm / closing_ebitda_mm` as a derived metric

### 1.8 Edge Case Criteria — Refine & Expand
> Current edge case categories are narrow (5 categories) and use fixed thresholds. Need a more comprehensive taxonomy that reflects actual parsing quality dimensions.

**Current categories:** `missing_sections`, `low_definitions`, `extreme_word_count`, `zero_clauses`, `extreme_facility`

**Agent analysis findings (2026-02-23) — Proposed expansion to 25+ categories in 6 tiers:**

| Tier | Category | Condition | Severity |
|------|----------|-----------|----------|
| **Structural** | `no_sections_detected` | section_count == 0 | high |
| | `low_section_count` | section_count < 5 (credit agreements typically have 10–15 articles) | medium |
| | `section_numbering_gap` | gaps in section number sequence (e.g., 2.01 → 2.03 with no 2.02) | medium |
| | `section_numbering_duplicate` | same section number appears twice in one doc | high |
| | `heading_truncation` | heading text > 120 chars or > 12 words (parser rejects) | low |
| **Clauses** | `zero_clauses` | clause_count == 0 | high |
| | `low_clause_density` | clause_count / section_count < 2 (most sections have 3+ clauses) | medium |
| | `low_avg_clause_confidence` | mean parse_confidence across all clauses < 0.5 | high |
| | `high_singleton_ratio` | > 30% of clause levels have only 1 sibling | medium |
| | `high_xref_false_positive_ratio` | > 20% of clauses flagged as xref by `_is_xref()` | medium |
| | `deep_nesting_anomaly` | max clause depth > 5 (unusual for credit agreements) | low |
| **Definitions** | `low_definitions_absolute` | definition_count < 10 | medium |
| | `low_definitions_relative` | definition_count / (word_count / 10000) < 5 | medium |
| | `high_definitions_anomaly` | definition_count > 500 (possible extraction noise) | medium |
| | `colon_engine_contamination` | > 30% of definitions from colon engine have < 20 char bodies | low |
| **Metadata** | `missing_borrower` | borrower is empty/null | medium |
| | `missing_admin_agent` | admin_agent is empty/null | medium |
| | `missing_facility_size` | facility_size_mm is null | medium |
| | `missing_ebitda` | closing_ebitda_mm is null | low |
| | `missing_closing_date` | closing_date is null | low |
| **Document** | `extreme_word_count_low` | word_count < 5000 (too short for a credit agreement) | high |
| | `extreme_word_count_high` | word_count > 200000 (may be multi-doc filing) | medium |
| | `extreme_text_length_ratio` | text_length / word_count > 15 (HTML artifact bloat) | medium |
| | `unknown_doc_type` | doc_type_confidence == "low" or doc_type == "" | high |
| **Template** | `orphan_template` | template_family is empty after clustering | low |
| | `template_outlier` | document is > 3σ from template family centroid | medium |

**Key threshold changes from current system:**
- `low_definitions`: Change from absolute `< 20` to relative `< 5 per 10K words`
- `extreme_word_count`: Split into `_low` (< 5000) and `_high` (> 200000) with different severities
- `extreme_facility`: Replace with `missing_facility_size` (null check, not range check) + new `implausible_facility` (< $1M or > $50B)
- Add 6 new clause-quality categories enabled by the confidence scoring refactor (Improvement 2)

**Tasks:**
- [ ] Implement the 25-category taxonomy above in `_build_anomaly_rows()` in `build_corpus_index.py`
- [ ] Change `low_definitions` threshold to relative (definitions per 10K words)
- [ ] Split `extreme_word_count` into low/high with different severities
- [ ] Add clause-quality categories (requires confidence scoring refactor — blocked on 1.2 Improvement 2)
- [ ] Assign severity tiers (high/medium/low) with the rationale in the table above
- [ ] Update `/api/edge-cases` endpoint with new categories and severity filter
- [ ] Update dashboard Edge Cases page to display new categories with severity badges
- [ ] Add aggregated edge-case counts to dashboard overview KPIs

---

## Block 2 — Header & Numbering Format Audit

### 2.1 Section Headers — Broad Range Survey
- [ ] Query the corpus index for all distinct section headings across 12,583 docs
- [ ] Group by frequency and identify the long tail of rare/unusual headings
- [ ] Categorize heading formats: standard, non-standard, truncated, HTML artifacts
- [ ] Identify headings that the parser is truncating (>120 chars) or rejecting (>12 words)
- [ ] Build a heading taxonomy for use in strategy development

### 2.2 Article & Section Numbering Formats
- [ ] Survey numbering schemes: Roman (ARTICLE VII), Arabic (Article 7), spelled-out (ARTICLE ONE)
- [ ] Survey section numbering: dotted (2.14), bare (Section 2.14), letter-suffixed (2.01a)
- [ ] Identify non-standard formats the parser doesn't handle
- [ ] Check OCR tolerance patterns (e.g., "Section 1. 01" with extra space)
- [ ] Quantify format distribution across the corpus

---

## Block 3 — Strategy Cleanup & Family-Level Focus

> **Philosophy change:** Focus exclusively on the 49 top-level families. Finalize family-level strategies before touching any children. Child/grandchild strategies will derive from the sections linked by the family strategy.

### 3.1 Clean Up Cross-Family Strategy Contamination
> 17 workspaces have strategies from multiple families (e.g., `ratio` workspace has strategies from 10 different families, `governance` has strategies from 5 families).

- [ ] Audit each workspace to identify strategies that don't belong to the workspace's family
- [ ] Move or remove cross-family strategies
- [ ] Document which strategies were removed and why

### 3.2 Remove Child/Grandchild Strategies
> Of 464 total strategies: 13 are `family_core`, 451 are `concept_standard` (children). All are bootstrap v1.

- [ ] Identify all `concept_standard` (child) strategies across all workspaces
- [ ] Archive them (move to `workspaces/{family}/archive/`) before deletion
- [ ] Remove from active `strategies/` directories
- [ ] Verify dashboard shows only the 49 family-level strategies

### 3.3 Normalize Family Strategies to Flat Format
> Only the indebtedness workspace (22 strategies) uses the flat Strategy dataclass format with v2 policies. The remaining 440 use the legacy nested `search_strategy` wrapper.

- [ ] For each of the 49 families, ensure a `family_core` strategy exists in flat format
- [ ] Migrate legacy nested format to flat format using `migrate_strategy_v1_to_v2.py`
- [ ] Add `acceptance_policy_version: v2`, `outlier_policy`, and `did_not_find_policy` to each
- [ ] Verify all 49 family strategies load correctly in the dashboard

### 3.4 Fill Strategy Gaps for Missing Families
> 9 families have zero strategies: term_loan, revolver, second_lien, corporate_structure, lme_protections, pre_closing, other_advisory_roles, side_by_side_revolvers, simultaneous_incurrence_netting.

- [ ] Create bootstrap `family_core` strategies for each of the 9 missing families
- [ ] Source heading patterns and keyword anchors from ontology expert materials
- [ ] Validate against sample corpus documents

### 3.5 Family Strategy Pre-Process — Discovery Seeding
> **Before** agents refine strategies, run automated discovery algorithms on each of the 49 families to seed richer initial strategies. This gives agents a strong starting point rather than bare bootstrap patterns.

**For each of the 49 families, run:**
- [ ] **DNA Discovery** — scan corpus for family-specific DNA phrases (tier 1 and tier 2)
- [ ] **Anti-DNA Discovery** — identify negative DNA patterns (phrases that indicate the section is NOT this family)
- [ ] **Heading Discovery** — discover heading patterns from corpus evidence beyond the bootstrap set
- [ ] **Keyword Discovery** — expand keyword anchors from corpus frequency analysis
- [ ] **Structural Position Analysis** — identify primary articles/sections where each family typically appears
- [ ] **Defined Term Dependencies** — auto-detect which defined terms are relevant to each family
- [ ] **Template Family Patterns** — identify per-template variations if template families are assigned
- [ ] Merge all discovery results into the family strategy files (enriching heading_patterns, keyword_anchors, dna_tier1, dna_tier2, dna_negative_tier1, primary_articles, primary_sections, defined_term_dependencies, concept_notes)
- [ ] Validate enriched strategies don't regress baseline metrics

### 3.6 Begin Family-Level Strategy Finalization
> This is the iterative corpus-testing loop: run each family strategy against the corpus, measure hit rate / precision / prevalence / coverage, refine patterns, repeat until metrics stabilize.

- [ ] Define "finalized" criteria for family strategies (min hit rate, min precision, etc.)
- [ ] Prioritize the 49 families by importance / corpus prevalence
- [ ] For each family (in priority order):
  - [ ] Run strategy against corpus
  - [ ] Measure heading_hit_rate, keyword_precision, corpus_prevalence, cohort_coverage
  - [ ] Identify false positives and false negatives
  - [ ] Refine heading_patterns and keyword_anchors
  - [ ] Promote to `corpus_validated` when criteria met
- [ ] Track progress in dashboard Strategy Manager

---

## Block 4 — Pipeline Rebuild & Optimization

> Given 12,583 documents and multiple parsing refinements expected today, the rebuild process must be optimized for rapid iteration. Ray-based parallel builders exist (`build_corpus_ray.py`, `build_corpus_ray_v2.py`) and need evaluation.

### 4.1 Rebuild Optimization

**Agent analysis findings (2026-02-23):**
- Current `build_corpus_index.py` is **single-threaded** and re-reads + normalizes every HTML file on each run
- **HTML normalization is the bottleneck**: `normalize_html()` using `html2text` is ~60% of per-doc processing time. Switching to `lxml` + custom stripping could 3-5x this step.
- **Ray builders**: `build_corpus_ray.py` (v1) uses Ray actors but has stale schema (missing new columns). `build_corpus_ray_v2.py` fixes schema but has untested error handling. Neither is production-ready without fixes.
- **Incremental rebuild is feasible**: DuckDB supports `DELETE FROM table WHERE doc_id IN (...)` + re-insert. Need a manifest of changed doc_ids (based on file mtime or content hash).
- **Table-specific rebuild**: The `_process_file()` function returns `{"doc": ..., "sections": ..., "clauses": ..., "definitions": ..., "section_texts": ...}`. Could skip sub-parsers and only recompute one table's data.
- **Estimated times** (12,583 docs):
  - Current single-threaded: ~45–60 min (estimated)
  - With `lxml` normalization: ~15–20 min
  - With `lxml` + 8-process multiprocessing: ~3–5 min
  - Incremental (100 changed docs): ~15–30 sec

**Proposed optimization order (quick wins first):**
1. Switch `html2text` → `lxml` for HTML normalization (3-5x speedup, ~2 hours to implement)
2. Add `multiprocessing.Pool` with `_process_file` as worker (near-linear scaling, ~1 hour)
3. Add `--incremental` flag using file mtime manifest (~2 hours)
4. Add `--tables` flag for table-specific rebuild (~1 hour)
5. Fix Ray v2 builder for cluster deployments (lower priority, ~3 hours)

**Tasks:**
- [ ] Benchmark current `build_corpus_index.py` — measure wall time for full rebuild
- [ ] Switch HTML normalization from `html2text` to `lxml`-based stripping
- [ ] Add `multiprocessing.Pool` parallelism to `_process_file()` loop
- [ ] Implement `--incremental` flag using file mtime or content hash manifest
- [ ] Implement `--tables` flag for table-specific rebuild (clauses-only, definitions-only, etc.)
- [ ] Add progress reporting (docs/sec, ETA) with `tqdm` or custom stderr output
- [ ] Cache normalized text to `/tmp/corpus_normalized/` to skip re-normalization
- [ ] Fix `build_corpus_ray_v2.py` schema to match current DuckDB DDL (add new columns)
- [ ] Test optimized rebuild and confirm speedup targets met

### 4.2 Apply Fixes & Full Rebuild
- [ ] Apply all `build_corpus_index.py` fixes (facility size key, EBITDA column, admin_agent improvements)
- [ ] Run full corpus rebuild (12,583 docs) using optimized pipeline
- [ ] Verify new columns populated: `facility_size_mm`, `closing_ebitda_mm`, `ebitda_confidence`
- [ ] Verify facility size distribution is non-zero
- [ ] Verify EBITDA distribution makes sense (plausible range: $50M–$5B for leveraged finance)
- [ ] Run dashboard smoke tests to confirm no regressions
- [ ] Update dashboard overview page with new KPIs (EBITDA, leverage)

---

## Block 5 — Domain Expert Verification & Golden Set

> **Philosophy:** The domain expert is the highest-authority signal source. The dashboard must make it effortless to verify, correct, and annotate parsing results and ontology linkages while reading documents. Every confirmed action builds a golden set that feeds back into strategy evaluation, parser benchmarking, and edge-case prioritization.

### 5.1 Golden Set Storage & Schema
> **Foundation layer** — all other features in Block 5 write to this store.

A golden set is a collection of human-verified annotations at multiple granularities (section, clause, ontology link). These are ground-truth records that downstream processes treat as authoritative.

**Schema: `golden_annotations` table (new DuckDB table or JSON sidecar)**

| Field | Type | Description |
|-------|------|-------------|
| `annotation_id` | TEXT PK | UUID |
| `doc_id` | TEXT | Document being annotated |
| `annotation_type` | TEXT | One of: `section_gap`, `section_confirmed`, `clause_depth_correction`, `clause_confirmed`, `ontology_link`, `strategy_match_verified`, `strategy_false_positive` |
| `section_number` | TEXT | Section number (nullable for doc-level annotations) |
| `clause_id` | TEXT | Clause ID (nullable for section-level annotations) |
| `payload` | JSON | Type-specific data (see per-feature sections below) |
| `created_by` | TEXT | User identifier (default: `"domain_expert"`) |
| `created_at` | TIMESTAMP | When the annotation was created |
| `status` | TEXT | `pending` / `confirmed` / `superseded` |

**Tasks:**
- [ ] Design golden set storage — DuckDB table vs. JSON sidecar vs. SQLite (consider mutability requirements; DuckDB corpus is read-only by convention)
- [ ] Implement `data/golden_annotations.json` as initial store (mutable sidecar, like `feedback_backlog.json`)
- [ ] Add CRUD API endpoints: `GET/POST/PATCH/DELETE /api/golden`
- [ ] Add filtering: by doc_id, annotation_type, status, concept_id
- [ ] Add export endpoint: `GET /api/golden/export` → JSONL for pipeline consumption
- [ ] Add import endpoint: `POST /api/golden/import` ← bulk load from pre-labeled data

### 5.2 Section Outline Verification
> **Goal:** While viewing a document's section outline (SectionTOC), the domain expert can flag missing sections, confirm correct outlines, and annotate numbering anomalies.

**Interaction design:**
- **Gap detection (automatic):** Parse sequential section numbers in the TOC. When a gap is detected (e.g., 9.15 → 9.17 with no 9.16), display a visual indicator (dashed divider with warning icon) between the two sections.
- **Flag missing section:** Click the gap indicator → modal/popover: "Flag missing section between 9.15 and 9.17?" with optional notes field. Saves `annotation_type: section_gap` with payload `{ "gap_after": "9.15", "gap_before": "9.17", "notes": "..." }`.
- **Confirm section correct:** Right-click or context menu on any section → "Confirm section parsing correct." Saves `annotation_type: section_confirmed`.
- **Bulk confirm:** "Mark all sections as verified" button in the TOC header (for when the full outline looks correct).
- **Visual state:** Sections with golden confirmations show a small checkmark badge. Flagged gaps show persistently.

**Tasks:**
- [ ] Add automatic gap detection logic to `SectionTOC` component (parse section_number sequences, identify gaps)
- [ ] Add gap indicator UI element (dashed divider + warning icon between sections)
- [ ] Add "Flag missing section" interaction (click gap → popover → save annotation)
- [ ] Add "Confirm section correct" context menu action on individual sections
- [ ] Add "Mark all sections verified" bulk action in TOC header
- [ ] Add visual badges (checkmark for confirmed, warning for flagged) to TOC items
- [ ] Wire up to golden set API (POST on flag/confirm, GET on page load to show existing annotations)

### 5.3 Clause Depth Correction
> **Goal:** While viewing the clause tree (ClausePanel), the domain expert can correct nesting depth errors by indenting/unindenting clauses, and confirm correct clause parsing.

**Interaction design:**
- **Depth correction:** Each clause row in the ClausePanel gets subtle indent/unindent arrow buttons (← →) visible on hover. Clicking adjusts the visual depth and opens a confirmation popover: "Correct depth of (a)(4) from 3 → 2?" Saves `annotation_type: clause_depth_correction` with payload `{ "clause_id": "...", "original_depth": 3, "corrected_depth": 2 }`.
- **Confirm clause correct:** Click/tap a clause → context menu → "Confirm parsing correct." Saves `annotation_type: clause_confirmed`.
- **Type correction:** If a clause's `level_type` is wrong (e.g., alpha classified as roman), a dropdown lets the expert correct it. Payload includes `{ "original_type": "alpha", "corrected_type": "roman" }`.
- **Visual state:** Corrected clauses show with a colored diff indicator (original depth ghosted, corrected depth solid). Confirmed clauses show a checkmark.

**Tasks:**
- [ ] Add indent/unindent arrow buttons to ClausePanel rows (visible on hover)
- [ ] Add depth correction confirmation popover with before/after preview
- [ ] Add "Confirm clause correct" context menu action
- [ ] Add `level_type` correction dropdown (alpha ↔ roman ↔ caps ↔ numeric)
- [ ] Add visual diff indicators for corrected clauses (ghosted original, solid corrected)
- [ ] Add checkmark badges for confirmed clauses
- [ ] Wire up to golden set API
- [ ] Auto-create feedback backlog item when a depth correction is saved (for parser investigation)

### 5.4 Ontology Node Linking from Document Reader
> **Goal:** While reading a section or clause, the domain expert can link it to an ontology concept. This creates a golden record that strategy evaluation uses as ground truth — "section 7.01 in doc X **is** the indebtedness covenant."

**Interaction design:**
- **Link section to concept:** Button in the SectionViewer header bar (e.g., 🏷️ "Link to Concept"). Opens a searchable ontology picker (typeahead search of ontology nodes, filtered to families by default). On select, saves `annotation_type: ontology_link` with payload `{ "concept_id": "indebtedness", "level": "family", "section_number": "7.01" }`.
- **Link clause to concept:** Same interaction from the ClausePanel's selected-clause detail card. Payload includes `clause_id`.
- **Quick-link from strategy matches:** If strategy back-propagation (5.5) shows that a strategy already matches this section, a one-click "Confirm match" button saves a verified link.
- **Visual state:** Linked sections/clauses show concept badge(s) in the TOC and ClausePanel. Multiple concepts can be linked to the same section (e.g., a section covering both indebtedness and liens).
- **Unlink:** Remove a previously saved link if it was incorrect.

**Tasks:**
- [ ] Build searchable ontology picker component (typeahead, filtered by family/domain, shows node hierarchy)
- [ ] Add "Link to Concept" button in SectionViewer header bar
- [ ] Add "Link to Concept" action in ClausePanel selected-clause detail card
- [ ] Add concept badge display in SectionTOC for linked sections
- [ ] Add concept badge display in ClausePanel for linked clauses
- [ ] Add unlink action (remove saved ontology link)
- [ ] Support multiple concept links per section/clause
- [ ] Wire up to golden set API
- [ ] Add `GET /api/golden/links?concept_id=X` endpoint — fetch all golden-linked sections for a concept (for strategy evaluation)

### 5.5 Strategy Back-Propagation
> **Goal:** While viewing any section, see which strategies (if any) would match it. This works in two directions:
> 1. **Reverse lookup:** "Which strategies return this section?" — shows all matching strategies with their scores.
> 2. **Forward check:** "Does concept X's strategy match this section?" — targeted evaluation for a specific concept.
>
> The domain expert can then verify: "Yes, this strategy correctly matches" or "No, this is a false positive."

**Interaction design:**
- **Strategy matches panel:** A collapsible panel in the SectionViewer (or a tab alongside the clause tree) that shows: concept_id, strategy version, match score, match reason (which heading pattern / keyword / DNA phrase triggered the match).
- **Verify match:** Green checkmark button → saves `annotation_type: strategy_match_verified` with payload `{ "concept_id": "...", "strategy_version": "...", "section_number": "..." }`.
- **Flag false positive:** Red X button → saves `annotation_type: strategy_false_positive` with same payload. Auto-creates a feedback backlog item.
- **No matches indicator:** If zero strategies match, show "No strategy matches this section" with a prompt to link it to a concept (flows into 5.4).
- **Targeted check:** Dropdown to select a specific concept → runs that strategy's scoring logic against this section → shows detailed score breakdown.

**Implementation note:** This requires running the scoring pipeline (heading_matches, keyword_density, section_dna_density from `textmatch.py`) on-demand for a single section. A new API endpoint should accept `(doc_id, section_number)` and return all matching strategies with scores, or accept `(doc_id, section_number, concept_id)` and return a detailed score breakdown for one strategy.

**Tasks:**
- [ ] Add `POST /api/reader/{doc_id}/section/{section_number}/strategy-matches` endpoint — runs all active strategies against a section, returns matches with scores
- [ ] Add `POST /api/reader/{doc_id}/section/{section_number}/score?concept_id=X` endpoint — detailed score breakdown for one strategy against one section
- [ ] Build strategy matches panel component in SectionViewer (collapsible, shows concept + score + match reason)
- [ ] Add "Verify match" (✓) and "Flag false positive" (✗) buttons per strategy match
- [ ] Add "No matches" indicator with prompt to link to concept
- [ ] Add targeted concept selector dropdown for forward-check mode
- [ ] Wire verify/flag actions to golden set API
- [ ] Auto-create feedback backlog item on false positive flag

### 5.6 Golden Set Dashboard & Metrics
> **Goal:** A dedicated view showing golden set progress, coverage, and utilization.

**Tasks:**
- [ ] Add `/golden` dashboard page showing: total annotations by type, annotations per document, coverage by family
- [ ] Add golden set coverage metric to strategy evaluation — "Of N golden-linked sections for concept X, how many does strategy vY correctly return?"
- [ ] Add golden set utilization to parser benchmarking — "Of N clause depth corrections, how many match the parser's current output?" (i.e., has the parser been fixed since the correction was filed?)
- [ ] Surface golden set stats on the `/overview` page (total verified sections, total verified clauses, total ontology links)

### 5.7 Feedback Backlog Integration
> **Goal:** Corrections and flags from all Block 5 features automatically flow into the existing feedback backlog, creating actionable items for investigation.

**Auto-generated backlog items:**
- Section gap flag → feedback item: `type: bug`, `title: "Missing section {gap} in doc {doc_id}"`, `related_concept_id: null`
- Clause depth correction → feedback item: `type: bug`, `title: "Clause {label} depth error in doc {doc_id} §{section}"`, `related_concept_id: null`
- Strategy false positive → feedback item: `type: bug`, `title: "False positive: {concept_id} strategy matches §{section} in doc {doc_id}"`, `related_concept_id: concept_id`
- Level type correction → feedback item: `type: bug`, `title: "Clause {label} type misclassification in doc {doc_id}"`, `related_concept_id: null`

**Tasks:**
- [ ] Auto-create feedback backlog items from golden annotations (section gaps, clause corrections, false positives)
- [ ] Add provenance link from feedback item back to golden annotation (`annotation_id` reference)
- [ ] Add "View in Reader" deep-link from feedback items that have doc_id + section_number
- [ ] De-duplicate: don't create a second feedback item if one already exists for the same annotation

---

## Progress Summary

| Block | Items | Complete | Remaining |
|-------|-------|----------|-----------|
| 1. Parsing Quality (1.1–1.8) | 60 | 11 | 49 |
| 2. Header & Numbering | 10 | 0 | 10 |
| 3. Strategy Cleanup & Seeding (3.1–3.6) | 25 | 0 | 25 |
| 4. Pipeline Rebuild & Optimization | 16 | 0 | 16 |
| 5. Domain Expert Verification & Golden Set (5.1–5.7) | 47 | 0 | 47 |
| **Total** | **158** | **11** | **147** |

> **Note:** Item count increased from 97 → 111 after cross-project analysis surfaced specific implementation tasks for clause parser refactor (6 improvements), admin agent improvements, edge case taxonomy expansion (25 categories), and rebuild optimization steps.
> Block 1.1 completed 2026-02-23: 5 new items checked off (zero-section investigation, categorization, regex expansion, validation, dashboard enrichment). Recovery rate 89% on 19-doc sample (17/19 recovered).
> Block 5 added 2026-02-23: 47 new items for domain expert verification features (golden set storage, section verification, clause depth correction, ontology linking, strategy back-propagation, golden set dashboard, feedback integration).
