# Corpus Cleanup & Strategy Foundation Plan

**Created:** 2026-02-23
**Status:** In Progress
**Last Updated:** 2026-02-24 (Block 3 expanded — workspace analysis, discovery pipeline, finalization criteria)

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
> **Root cause identified:** `build_corpus_index.py:569` uses `.get("aggregate")` but `extract_facility_sizes()` returns `"facility_size_mm"` as the key. This is why 0/3,000 docs have facility size data.

- [x] Fix key mismatch in `build_corpus_index.py` — change `.get("aggregate")` to `.get("facility_size_mm")` (2026-02-23)
  - Fixed in `build_corpus_index.py:573`. Also added `facility_confidence` column to schema and doc_record.
- [ ] Verify `extract_facility_sizes()` works on sample docs (unit test with real corpus text)
- [ ] Port TermIntelligence Wave 3 logic (Section 2.01 commitment table parsing) if needed
- [ ] Rebuild corpus index and verify facility size population rate
- [ ] Add facility size distribution to dashboard overview KPIs

### 1.5 Borrower
> **Focus:** Documents where borrower extraction returned None/empty — not accuracy of existing extractions.

- [ ] Query corpus index for docs with empty/null borrower field
- [ ] Quantify: how many of 3,000 docs have no borrower?
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
- [ ] Quantify: how many of 3,000 docs have no admin_agent?
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

**Cross-project analysis:** Section header and numbering format implementations surveyed across TermIntelligence, Vantage Platform, and Neutron (2026-02-23). All three sibling projects parse the same EDGAR credit agreement corpus and have independently evolved solutions for edge cases Agent doesn't yet handle.

### Cross-Project Feature Matrix (2026-02-23)

| Feature | Agent | TermIntel | VP | Neutron |
|---|:---:|:---:|:---:|:---:|
| **Article: Roman** (ARTICLE VII) | ✅ | ✅ | ✅ | ✅ |
| **Article: Arabic** (Article 7) | ✅ | ✅ | ✅ | ✅ |
| **Article: Spelled-out** (ARTICLE ONE) | ✅ | ✅ | ✅ | ❌ |
| **Article: Spaced** (A R T I C L E) | ✅ | ❌ | ✅ | ❌ |
| **Article: Split-line** (title on next line) | ✅ | ✅ | ✅ | ❌ |
| **Article: PART/CHAPTER** | ✅ | ❌ | ❌ | ❌ |
| **Article: Leading page numbers** (OCR) | ✅ | ✅ | ✅ | ❌ |
| **Section: Standard** (Section 2.14) | ✅ | ✅ | ✅ | ✅ |
| **Section: § symbol** | ✅ | ✅ | ✅ | ❌ |
| **Section: Bare number** (2.01 Heading) | ✅ | ✅ | ✅ | ✅ |
| **Section: OCR space** (1. 01) | ✅ | ✅ | ✅ | ✅ |
| **Section: Letter suffix** (2.01a) | ✅ | ❌ | ✅ | ❌ |
| **Section: Roman prefix** (II.1) | ✅ | ✅ | ✅ | ❌ |
| **Section: Flat numbered** (1. Definitions) | ✅ | ❌ | ❌ | ❌ |
| **Section: Standalone number** (10.3 alone, heading next line) | ❌ | ✅ | ❌ | ✅ |
| **Section: No-space** (1.01Defined Terms) | ❌ | ❌ | ❌ | ✅ |
| **Section: Abbreviation** (Sec. / Sec) | ❌ | ❌ | ❌ | ✅ |
| **TOC deduplication** | ❌ | partial | partial | ✅ |
| **Multi-signal TOC detection** | basic | ✅ | ✅ (5 signals) | partial |
| **Heading quality scoring** | ❌ | ✅ | ✅ | ✅ (3-tier) |
| **Multi-line heading continuation** | ❌ | ✅ | ✅ (3 lines) | partial |
| **Section number plausibility** | ❌ | ✅ | ✅ | partial |
| **Gap detection / monotonic enforcement** | ❌ | ✅ | ❌ | ❌ |
| **Ghost section rejection** | ❌ | ❌ | ✅ | ❌ |
| **Numbering format taxonomy** | ❌ | ✅ | ❌ | ❌ |
| **Synthetic article scaffolding** | ❌ | ❌ | ✅ | ❌ |
| **Exhibit/signature boundary hardening** | basic | ❌ | ✅ (500-char margin) | ❌ |
| **Section canonical naming** | ❌ | ❌ | ✅ | ❌ |
| **Content-addressed chunk IDs** | ❌ | ❌ | ✅ | ❌ |
| **Contextual reference patterns** | ❌ | ❌ | ❌ | ✅ |
| **Plural/range reference patterns** | ❌ | ❌ | ❌ | ✅ |
| **Straight→smart quote normalization** | ❌ | ❌ | ❌ | ✅ |
| **Zero-width character stripping** | ❌ | ❌ | ❌ | ✅ |
| **Reserved section detection** | ❌ | ✅ | ❌ | ❌ |
| **Boilerplate removal** (timestamps, SEC URLs) | ❌ | ❌ | ❌ | ✅ |
| **Concept-level location strategies (HHI)** | ❌ | ✅ | ❌ | ❌ |

### Where Each Project Excels

| Project | Primary Strength | Best Ideas to Port |
|---|---|---|
| **TermIntelligence** | Corpus-wide format census & DOM-aware extraction | Numbering taxonomy, gap detection, concept-location stability scoring, reserved section detection |
| **Vantage Platform** | Multi-signal quality gates & recovery mechanisms | TOC detection (5 signals), heading continuation, ghost rejection, synthetic articles, canonical naming |
| **Neutron** | Reference resolution & hierarchical structure model | TOC dedup (keep body + inherit heading), reference patterns, section path normalization, quote normalization |

### Key Source Files

**TermIntelligence:**
- `scripts/round11_numbering_census.py` — Comprehensive format taxonomy (ROMAN/ARABIC/HYBRID, zero-pad, 2/3-level)
- `scripts/section_level_parser.py` — 3-style section extraction (Style A/B/C), gap detection (lines 470-491), monotonic enforcement (lines 1087-1110)
- `scripts/round11_article_boundary.py` — DOM-aware article extraction with explicit TOC zone detection (lines 81-223)
- `scripts/compile_section_map.py` — Per-concept location strategies with HHI stability scoring

**Vantage Platform:**
- `src/vantage_platform/l0/_doc_parser.py` — 5-signal TOC detection (lines 383-455), section plausibility (lines 1517-1536), ghost rejection (lines 1423-1435), heading continuation (lines 1228-1322), synthetic articles (lines 1538-1571), canonical naming (`l0/outline.py:117-124`)

**Neutron:**
- `tools/swarm-bsl-golden/scripts/build_section_index.py` — TOC dedup with heading inheritance (lines 214-241), heading quality scoring (lines 194-211), standalone section look-ahead (lines 60-62)
- `tools/swarm-bsl-golden/scripts/convert_html_to_clean.py` — Straight→smart quote normalization (lines 267-302), zero-width char stripping
- `apps/backend/src/common/patterns/reference-patterns.ts` — Contextual/plural/range reference patterns (lines 431-474)

---

### 22 Improvements — Implementation Plan

> **Prerequisite:** Improvements 1-2 (TOC handling) should be implemented first, as TOC contamination would corrupt any corpus-wide heading survey. Improvements are grouped into 4 phases by dependency and impact.

#### Phase A — TOC Handling & Section Validation (gate for corpus survey)

**Improvement 1: TOC deduplication — keep body occurrence, inherit heading from TOC**
- **Source:** Neutron `build_section_index.py:214-241`
- **What:** When the same section number appears in both TOC and body, keep the LAST occurrence (body). If the body entry has an empty heading but the TOC entry has a good one, inherit the heading from the TOC entry.
- **Files:** `src/agent/doc_parser.py` — add `_dedup_sections()` post-processing pass after `_detect_sections()`
- **Complexity:** Low
- **Tests:** New test cases with synthetic TOC + body duplicate sections
- [ ] Implement `_dedup_sections()` — keep last occurrence per section number, with heading inheritance
- [ ] Add heading quality scoring helper: quality 0 (garbage: starts with `,`, lowercase, `(`), quality 1 (empty), quality 2 (proper: starts with `[A-Z]`)
- [ ] Add tests with TOC-contaminated documents

**Improvement 2: Multi-signal TOC detection (5 signals)**
- **Source:** VP `_doc_parser.py:383-455`
- **What:** Replace basic "TABLE OF CONTENTS" header detection with 5-signal heuristic: (1) distance from TOC header within 3K chars, (2) dense section clustering (>6 refs in ±200 chars, median gap <80), (3) page number patterns (dot-leader or standalone 2+ digits), (4) pipe-separated page numbers (EDGAR HTML table format), (5) short-line clustering (<50 chars, 7+ lines, no lines >100 chars).
- **Files:** `src/agent/doc_parser.py` — enhance `_is_toc_entry()` with additional signals
- **Complexity:** Medium
- **Tests:** Add signal-specific test cases for each of the 5 TOC indicators
- [ ] Add dense section clustering signal (#2) — count section refs in ±200 char window, check median gap
- [ ] Add pipe-separated page number signal (#4)
- [ ] Add short-line clustering signal (#5)
- [ ] Integrate min_signals parameter for adjustable sensitivity
- [ ] Add tests for each signal in isolation and combined

**Improvement 3: Section number plausibility validation**
- **Source:** VP `_doc_parser.py:1517-1536`
- **What:** Validate parsed section numbers by rejecting outliers (major >40, minor >120). Outliers only allowed if keyword-matched (has "Section" prefix) AND heading present.
- **Files:** `src/agent/doc_parser.py` — add `_is_plausible_section_number()` called during section detection
- **Complexity:** Low
- **Tests:** Test with monetary amounts ("50.00"), ratios, and valid edge cases (Section 40.01)
- [ ] Implement `_is_plausible_section_number(major, minor, has_keyword, has_heading)` → bool
- [ ] Wire into `_detect_sections()` as a filter after regex matching
- [ ] Add tests for outlier rejection and valid edge cases

**Improvement 4: Heading quality scoring**
- **Source:** VP `_doc_parser.py:1011-1032`, Neutron `build_section_index.py:194-211`
- **What:** Score heading quality on a 3-tier scale: 0 = garbage (starts with `,`, `;`, lowercase, sub-clause marker), 1 = empty (may be on next line), 2 = proper (starts with `[A-Z]`). Use quality score in section dedup and article dedup to prefer entries with better headings.
- **Files:** `src/agent/doc_parser.py` — add `_heading_quality()` helper, use in dedup logic
- **Complexity:** Low
- [ ] Implement `_heading_quality(heading: str) -> int` (0/1/2)
- [ ] Use in `_dedup_sections()` (Improvement 1) and article dedup
- [ ] Add sentence-like body text detection from VP (parenthetical clauses, lowercase content words)

---

#### Phase B — Heading Extraction & Recovery (improves extraction before survey)

**Improvement 5: Multi-line heading continuation**
- **Source:** VP `_doc_parser.py:1228-1322`, TI `section_level_parser.py:870-922`
- **What:** When heading extraction yields an empty or truncated result, look up to 3 continuation lines. Check for: (a) title ends with connector word (of, and, or, the, to, for, in, by, with), (b) title ends with comma, (c) title is very short (1-2 words). Continuation lines must start with uppercase, be <60 chars, and not be another section/article header. Abbreviation-aware sentence breaks (don't truncate at "U.S." or "Inc.").
- **Files:** `src/agent/doc_parser.py` — enhance `_extract_article_title()` and section heading extraction
- **Complexity:** Medium
- [ ] Add abbreviation-aware sentence break detection (U.S., Inc., Co., Ltd., Corp., N.A., L.P.)
- [ ] Add heading truncation detection (connector words, comma, short length)
- [ ] Add continuation line scanner (up to 3 lines, validate each)
- [ ] Increase heading word limit from 12 to 15 (matching VP)
- [ ] Add tests with split headings from real EDGAR HTML

**Improvement 6: Ghost section rejection with context checks**
- **Source:** VP `_doc_parser.py:1423-1435`
- **What:** After section detection, reject sections without headings that start with body-text patterns. Real headingless sections start with: `.`, `:`, `(a)`, `(i)`, `(1)`, uppercase. Ghost xrefs start with: `,`, lowercase, prepositions ("pursuant", "as defined"), parenthetical asides.
- **Files:** `src/agent/doc_parser.py` — add `_is_ghost_section()` post-filter
- **Complexity:** Low
- [ ] Implement `_is_ghost_section(section_text_start: str, has_heading: bool) -> bool`
- [ ] Apply as post-filter in `_detect_sections()` (only for headingless sections)
- [ ] Add tests with body-text cross-references vs. real headingless sections

**Improvement 7: Standalone section number with look-ahead**
- **Source:** Neutron `build_section_index.py:60-62`, TI `section_level_parser.py:801-940`
- **What:** Handle section numbers that appear alone on a line (e.g., "10.3" with no heading), with heading on the NEXT non-empty line. Validate: reject article numbers >20 (pricing grid values like "50.00 bps"), require 2-line look-ahead for uppercase-starting text.
- **Files:** `src/agent/doc_parser.py` — add `_SECTION_STANDALONE_RE` pattern and look-ahead logic
- **Complexity:** Low
- [ ] Add `_SECTION_STANDALONE_RE = re.compile(r"(?:^|\n)\s*(\d{1,2}\.\d{1,2})\s*\.?\s*$")`
- [ ] Add look-ahead: scan next 2 lines for uppercase-starting text <60 chars
- [ ] Add validation: reject major >20 for standalone matches
- [ ] Wire in as fallback after `_SECTION_BARE_RE`
- [ ] Add tests with standalone section numbers + pricing grid false positives

**Improvement 8: Reserved section detection**
- **Source:** TI `section_level_parser.py:393-395`
- **What:** Detect `[RESERVED]`, `[Reserved]`, `[Intentionally Omitted]` patterns in section text and return as heading.
- **Files:** `src/agent/doc_parser.py` — add `_RESERVED_RE` pattern check in heading extraction
- **Complexity:** Low
- [ ] Add `_RESERVED_RE = re.compile(r"\[(?:RESERVED|Reserved|Intentionally Omitted)\]")`
- [ ] Check in `_extract_heading()` and `_extract_article_title()` — if found, return "[Reserved]"
- [ ] Add tests

---

#### Phase C — Numbering Taxonomy & Corpus Survey (the Block 2 core deliverables)

**Improvement 9: Numbering format taxonomy (corpus-wide census)**
- **Source:** TI `round11_numbering_census.py`
- **What:** Classify every document's numbering format: article format (ROMAN/ARABIC/SECTION_ONLY/HYBRID with 80% dominance rule), section depth (2-level/3-level), zero-padding (padded/unpadded/mixed), and detect anomalies (mid-document format switches, padding convention shifts).
- **Files:** New `scripts/numbering_census.py`; add `article_format`, `section_depth`, `zero_padded` columns to DuckDB `documents` table
- **Complexity:** Medium
- [ ] Build `scripts/numbering_census.py` — classify article format per document
- [ ] Classify section depth (2-level X.Y vs 3-level X.Y.Z) per document
- [ ] Classify zero-padding (padded "6.01" vs unpadded "6.1") per document
- [ ] Detect mid-document format anomalies (ROMAN→ARABIC switches)
- [ ] Add `article_format`, `section_depth`, `zero_padded` to DuckDB schema
- [ ] Output corpus-wide format distribution report (JSON to stdout)

**Improvement 10: Section gap detection & monotonic enforcement**
- **Source:** TI `section_level_parser.py:470-491, 1087-1110`
- **What:** After section extraction, detect gaps in section numbering within each article (e.g., 7.01→7.03 without 7.02). Remove out-of-sequence sections. Merge duplicates (keep the one with a valid heading).
- **Files:** `src/agent/doc_parser.py` — add `_detect_numbering_gaps()` and `_enforce_monotonic()` post-processing
- **Complexity:** Low
- [ ] Implement `_detect_numbering_gaps(sections, article_num)` → list of gap tuples
- [ ] Implement `_enforce_monotonic(sections)` → reordered sections with out-of-sequence removed
- [ ] Store gap metadata for edge-case reporting
- [ ] Add tests with gapped and out-of-sequence section numbers

**Improvement 11: Synthetic article scaffolding**
- **Source:** VP `_doc_parser.py:1538-1571`
- **What:** When sections are found but no articles are detected, group sections by major component (all "2.xx" → Article 2) and create synthetic articles. Mark as `is_synthetic: True`.
- **Files:** `src/agent/doc_parser.py` — add `_synthesize_articles_from_sections()`, similar to existing `_synthesize_sections_from_articles()` (Fix F from Block 1.1)
- **Complexity:** Low
- [ ] Implement `_synthesize_articles_from_sections(sections)` → list of articles
- [ ] Add `is_synthetic` flag to article data (or use a naming convention like "Article 7 [synthetic]")
- [ ] Wire into fallback chain: if no articles AND sections exist, synthesize
- [ ] Add tests

**Improvement 12: Exhibit/signature boundary hardening**
- **Source:** VP `_doc_parser.py:1078-1094`
- **What:** Harden existing `_EXHIBIT_BOUNDARY_RE` and `_SIGNATURE_BOUNDARY_RE` with a 500-char margin requirement to avoid false positives from cross-references like "as set forth in Exhibit A".
- **Files:** `src/agent/doc_parser.py` — add margin check in boundary truncation logic
- **Complexity:** Low
- [ ] Add 500-char margin check: boundary must be >500 chars from last section start
- [ ] Add tests with cross-reference false positives near document end

### 2.1 Section Headers — Broad Range Survey

> **Blocked on:** Phase A + B improvements (TOC handling, heading quality, ghost rejection, multi-line continuation). Without these, the survey would be contaminated by TOC duplicates, ghost sections, and truncated headings.

- [ ] Query the corpus index for all distinct section headings across 12,583 docs (post-rebuild)
- [ ] Group by frequency and identify the long tail of rare/unusual headings
- [ ] Categorize heading formats: standard, non-standard, truncated, HTML artifacts, [Reserved]
- [ ] Identify headings that the parser is truncating (>120 chars) or rejecting (>15 words)
- [ ] Build a heading taxonomy for use in strategy development
- [ ] Identify per-template heading patterns (if template families are assigned)

### 2.2 Article & Section Numbering Formats

> **Blocked on:** Improvement 9 (numbering format taxonomy). The census script will produce the quantified distribution.

- [ ] Survey numbering schemes: Roman (ARTICLE VII), Arabic (Article 7), spelled-out (ARTICLE ONE), HYBRID
- [ ] Survey section numbering: dotted (2.14), bare (Section 2.14), letter-suffixed (2.01a), 3-level (X.Y.Z)
- [ ] Survey zero-padding distribution: padded (6.01) vs unpadded (6.1)
- [ ] Identify non-standard formats the parser doesn't handle
- [ ] Check OCR tolerance patterns (e.g., "Section 1. 01" with extra space, no-space "1.01Defined Terms")
- [ ] Quantify format distribution across the corpus
- [ ] Identify mid-document format anomalies

---

#### Phase D — Enrichment & Normalization (future enhancement layer)

**Improvement 13: Straight→smart quote normalization**
- **Source:** Neutron `convert_html_to_clean.py:267-302`
- **What:** Normalize straight double quotes to smart quotes (U+201C/U+201D) in normalized text, handling paragraph-spanning definitions.
- **Files:** `src/agent/html_utils.py` — add `_normalize_defined_term_quotes()` pass
- **Complexity:** Low
- [ ] Implement `_normalize_defined_term_quotes(text)` with paragraph-boundary awareness
- [ ] Call after main normalization in `normalize_html()`
- [ ] Verify definition extraction improvement on sample docs with straight quotes

**Improvement 14: Zero-width character stripping**
- **Source:** Neutron `convert_html_to_clean.py`
- **What:** Strip U+200C (ZWNJ), U+200B (ZWSP), U+FEFF (BOM) characters from normalized text.
- **Files:** `src/agent/html_utils.py`
- **Complexity:** Low
- [ ] Add zero-width character stripping after HTML entity normalization
- [ ] Add test with embedded zero-width chars in section headings

**Improvement 15: Boilerplate removal (timestamps, SEC URLs, page markers)**
- **Source:** Neutron `strip_boilerplate.py:116-128`
- **What:** Strip common EDGAR boilerplate patterns before parsing: timestamps ("1/16/26, 1:44 PM"), SEC archive URLs, page markers ("Page 1 of 252"), exhibit headers ("EX-10.1 2 exh101-...").
- **Files:** `src/agent/html_utils.py` — add `_strip_boilerplate()` pass
- **Complexity:** Low
- [ ] Implement boilerplate pattern removal (4 patterns: timestamp, SEC URL, page marker, exhibit header)
- [ ] Call before section parsing
- [ ] Add tests with real boilerplate from EDGAR filings

**Improvement 16: Section canonical naming**
- **Source:** VP `outline.py:117-124`
- **What:** Add `section_canonical_name` (heading normalized) and `section_reference_key` (`{document_id}:{canonical_name}`) to section/link anchor data.
- **Files:** `src/agent/doc_parser.py` or `src/agent/corpus.py` — add to `OutlineSection` or DuckDB `sections` table
- **Complexity:** Low
- [x] Add canonical naming helper in parser utilities (`section_canonical_name`)
- [x] Add `section_reference_key` helper
- [ ] (Optional) Materialize in DuckDB `sections` table schema (deferred; runtime anchor contract now uses computed fields)

**Improvement 17: Content-addressed chunk IDs**
- **Source:** VP `outline.py:43-54`
- **What:** Compute Wave3 chunk ID from `(document_id, section_reference_key, clause_key, span_start, span_end, text_sha256)`.
- **Files:** `src/agent/doc_parser.py` — add `_compute_chunk_id()`, store in section data
- **Complexity:** Low
- [x] Implement canonical chunk-id helper (`compute_chunk_id`) with full SHA-256 contract
- [ ] Add `chunk_id` to DuckDB `sections` table (deferred; currently emitted in linker/evidence path)
- [x] Add stability tests (same anchor tuple => same chunk_id)

**Improvement 18: Contextual reference patterns**
- **Source:** Neutron `reference-patterns.ts:431-474`
- **What:** Recognize legal preamble patterns: "pursuant to Section X.XX", "as set forth in Section X.XX", "subject to Section X.XX", "in accordance with Section X.XX", "defined in Section X.XX", "referenced in Section X.XX", "specified in Section X.XX". These improve xref detection by providing intent classification.
- **Files:** `src/agent/doc_parser.py` — extend `_XREF_INTENT_PATTERNS`
- **Complexity:** Medium
- [ ] Add 7+ legal preamble patterns to `_XREF_INTENT_PATTERNS`
- [ ] Add tests for each preamble pattern

**Improvement 19: Plural/range reference patterns**
- **Source:** Neutron `reference-patterns.ts`
- **What:** Handle "Sections 7.01 and 7.02", "Sections 7.01, 7.02, and 7.03", "Sections 7.01 through 7.05", "Sections 7.01-7.10".
- **Files:** `src/agent/doc_parser.py` — extend `_XREF_SCAN_RE` or add companion patterns
- **Complexity:** Medium
- [ ] Add plural section reference pattern (comma/and separated)
- [ ] Add range reference pattern (through/dash)
- [ ] Add expansion logic (range → enumerate intermediate section numbers)
- [ ] Add tests

**Improvement 20: Concept-level location strategies with HHI stability scoring**
- **Source:** TI `compile_section_map.py`
- **What:** For each ontology concept, compute a prevalence matrix across the corpus (which section numbers it most commonly appears in), rank by frequency, and compute Herfindahl-Hirschman Index (HHI) for stability scoring. High HHI = concept always in same section; low HHI = scattered across many sections.
- **Files:** New `scripts/compile_section_map.py`
- **Complexity:** High
- [ ] Build per-concept section prevalence matrix from strategy matches
- [ ] Compute top_raw_titles per concept (canonical section titles)
- [ ] Compute HHI stability score per concept
- [ ] Output per-concept location strategy with confidence indicators
- [ ] Integrate with strategy seeding (Block 3.5)

**Improvement 21: Section path normalization with round-trip invariant**
- **Source:** Neutron `section-path.utils.ts:23-166`
- **What:** Define a canonical section path format (`ARTICLE VII > Section 7.06 > (a)`) with separator ` > `. Ensure round-trip invariant: `array → string → array` produces identical result. Support legacy separators on read, normalize on write.
- **Files:** New utility in `src/agent/` or extend `doc_parser.py`
- **Complexity:** Medium
- [ ] Define canonical section path format and separator
- [ ] Implement `split_section_path(path)` and `join_section_path(parts)`
- [ ] Add round-trip invariant tests
- [ ] Add legacy separator support on read

**Improvement 22: Section abbreviation patterns (Sec. / Sec)**
- **Source:** Neutron `reference-patterns.ts`
- **What:** Add `Sec.` and `Sec` as section keyword alternatives in `_SECTION_STRICT_RE` (rare but occurs in some older filings).
- **Files:** `src/agent/doc_parser.py` — extend section detection regex
- **Complexity:** Low
- [ ] Add `Sec\.?` to `_SECTION_STRICT_RE` keyword alternatives
- [ ] Add tests with "Sec. 2.14" and "Sec 2.14" patterns

---

## Block 3 — Strategy Cleanup & Family-Level Focus

> **Philosophy change:** Focus exclusively on the 49 top-level families. Finalize family-level strategies before touching any children. Child/grandchild strategies will derive from the sections linked by the family strategy.

### Current State Analysis (2026-02-23)

**Workspace ↔ Family mapping:**
- 41 workspace directories exist under `workspaces/`
- 49 ontology families exist (level-1 nodes across 6 domains)
- Mapping is **not 1:1**: the `incremental` workspace covers 10 ontology sub-families (`free_clear`, `ratio`, `builders`, `mfn`, `ied`, `stacking_reclass`, `acquisition_debt`, `contribution_debt`, `subordinated_debt`, `structural_controls`) — but 3 of those (`mfn`, `stacking_reclass`, `structural_controls`) also have their own dedicated workspaces. The `governance` workspace aggregates 5 sub-families (`affiliate_txns`, `amendments_voting`, `assignments`, `reporting`, `reps_conditions`) that also each have their own workspace.
- 1 ontology family (`cash_flow.carve_outs`, 6 concepts) has **no workspace at all**
- Net: 41 workspaces, 49 families, with overlap and one gap

**Strategy files:**
- 440 total strategy JSON files across all `strategies/` directories
- ALL are `_v001.json` — zero iteration has occurred
- ALL are bootstrap quality (`validation_status: "bootstrap"`)
- Estimated split: ~13 `family_core` (profile_type), ~427 `concept_standard` (children)
- All originated from `data/bootstrap/bootstrap_all.json` (332 entries) via `setup_workspace.py`

**Format state:**
- All workspace strategies are in **flat format** (individual top-level fields, not nested `search_strategy` wrapper). `setup_workspace.py` already flattens on write.
- All are `acceptance_policy_version: "v1"` — no v2 policy fields populated (no `outlier_policy`, `did_not_find_policy`, `template_stability_policy`)
- The `bootstrap_all.json` source file uses the legacy **nested format** (`search_strategy` sub-object) but workspace copies were already flattened

**Checkpoint state:**
- 22 of 41 workspaces have `checkpoint.json`
- All at `iteration_count: 0` — wave 2 was bootstrap/evidence-only
- Status: all either `"completed"` or `"running"` (set by `wave_promote_status.py`)
- No workspace has gone through the iterative refinement loop

**Contamination (14 files across 8 workspaces):**

| Workspace | Contaminating Strategy | Root Cause |
|-----------|----------------------|------------|
| `collateral` | `cash_flow.dispositions.disp_non_collateral` | "collateral" in concept name |
| `collateral` | `debt_capacity.liens.cash_collateral_liens` | "collateral" in concept name |
| `collateral` | `debt_capacity.liens.non_collateral_liens` | "collateral" in concept name |
| `cross_covenant` | `cash_flow.available_amount.aa_cross_covenant_allocation` | "cross_covenant" in concept ID |
| `cross_covenant` | `cash_flow.dispositions.disp_cross_covenant_links` | "cross_covenant" in concept ID |
| `ebitda` | `debt_capacity.incremental.free_clear.ebitda_correlation` | "ebitda" in concept name |
| `fees` | `deal_econ.pricing.lc_fees` | "fees" in concept name |
| `incremental` | `debt_capacity.indebtedness.incremental_equivalent` | "incremental" in concept name |
| `inv` | `cash_flow.available_amount.aa_investment_returns` | "inv" substring of "investment" |
| `inv` | `cash_flow.dispositions.disp_reinvestment_period` | "inv" substring of "reinvestment" |
| `inv` | `cash_flow.rp.investment_return` | "inv" substring of "investment" |
| `inv` | `credit_protection.events_of_default.invalidity` | "inv" substring of "invalidity" |
| `leverage` | `debt_capacity.incremental.ratio.leverage_metric` | "leverage" in concept name |
| `mfn` | `deal_econ.pricing.mfn_protection` | "mfn" in concept name |

**Root cause:** `setup_workspace.py:extract_bootstrap_strategies()` does **substring matching** (`family_lower in val.lower()`) on concept fields. The 3-letter `inv` family is worst affected — "inv" is a substring of "investment", "reinvestment", and "invalidity".

**Bootstrap gap families (no entries in `bootstrap_all.json`):**
- `deal_econ.term_loan` (73 concepts)
- `deal_econ.revolver` (59 concepts)
- `deal_econ.second_lien` (46 concepts)
- `credit_protection.corporate_structure` (62 concepts)
- `credit_protection.lme_protections` (116 concepts)
- `governance.pre_closing` (40 concepts)
- `governance.other_advisory_roles` (2 concepts)
- `debt_capacity.side_by_side_revolvers` (5 concepts)
- `cash_flow.simultaneous_incurrence_netting` (5 concepts)

---

### 3.1 Fix Workspace Setup Root Cause & Reconcile Mapping

> The cross-family contamination and workspace-family mapping issues stem from `setup_workspace.py`'s substring matching. Fix the root cause before any cleanup.

**Improvement 1: Exact family matching in `setup_workspace.py`**
- **What:** Replace `family_lower in val.lower()` substring matching with exact ontology-path matching. A concept belongs to family `F` if and only if its `concept_id` starts with the family's ontology path (e.g., `"cash_flow.inv."` for the `inv` family, `"cash_flow.inv"` for the family node itself). This prevents "inv" from matching "investment" or "invalidity".
- **Files:** `scripts/setup_workspace.py` — `extract_bootstrap_strategies()` function
- **Complexity:** Low
- [ ] Replace substring matching with exact ontology-path prefix matching in `extract_bootstrap_strategies()`
- [ ] Add `--family-id` parameter (full dotted ontology path, e.g., `cash_flow.inv`) distinct from `--family` (short name)
- [ ] Add validation: reject concepts whose `family_id` prefix doesn't match the workspace family
- [ ] Add tests for false-positive rejection (e.g., "inv" must NOT match "invalidity")

**Improvement 2: Workspace ↔ family mapping reconciliation**
- **What:** Establish a canonical 1:1 mapping between workspaces and ontology families. Resolve the incremental/governance overlap. Decide whether to split `incremental` into 10 sub-workspaces or keep it as a super-workspace. Create workspace for `cash_flow.carve_outs`.
- [ ] Create `data/workspace_family_map.json` — canonical mapping of `{ workspace_name: family_id }`
- [ ] Resolve `incremental` overlap: decide whether `mfn`, `stacking_reclass`, `structural_controls` use their own workspace or the shared `incremental` workspace (recommend: dedicated workspaces, since each has its own ontology family)
- [ ] Resolve `governance` overlap: the `governance` workspace aggregates 5 sub-families that also have their own workspaces — deduplicate (recommend: remove the aggregated `governance` workspace, keep 5 individual workspaces)
- [ ] Create missing workspace for `cash_flow.carve_outs`
- [ ] Update `generate_swarm_conf.py` to use `workspace_family_map.json` for canonical assignments
- [ ] Validate: every ontology family has exactly one workspace; every workspace maps to exactly one family

### 3.2 Clean Up Cross-Family Contamination

> 14 contaminated files across 8 workspaces identified (see table above). Must be cleaned after root cause fix (3.1) to prevent re-contamination on re-setup.

- [ ] For each of the 14 contaminated files: verify the concept doesn't belong to this workspace's family by checking its ontology path
- [ ] Move contaminated files to `workspaces/{family}/quarantine/` (not delete — some may be useful reference)
- [ ] For the `inv` workspace: remove all 4 false-positive strategies (`aa_investment_returns`, `disp_reinvestment_period`, `investment_return`, `invalidity`)
- [ ] For the `collateral` workspace: remove 3 files (`disp_non_collateral`, `cash_collateral_liens`, `non_collateral_liens`) — these belong to `dispositions` and `liens` respectively
- [ ] Log all removals to `plans/contamination_cleanup_log.json` with `{workspace, file, concept_id, correct_family, reason}`
- [ ] Re-run `setup_workspace.py` with fixed matching (from 3.1) on affected workspaces to verify no re-contamination
- [ ] Verify final file counts per workspace match expected concept counts from ontology

### 3.3 Remove Child/Grandchild Strategies

> Of ~440 total strategies: ~13 `family_core`, ~427 `concept_standard` (children). All are bootstrap v001. Per the philosophy change, only family-level strategies should remain active.

**Approach:** Archive child strategies rather than delete — they contain bootstrap heading_patterns and keyword_anchors that may be useful reference during discovery seeding (3.5).

- [ ] Scan all workspaces and classify each strategy by `profile_type` (or infer from concept_id depth if field is absent)
- [ ] For each workspace, identify the family-level strategy (shortest concept_id, or `profile_type: "family_core"`)
- [ ] Create `workspaces/{family}/archive/` directory in each workspace
- [ ] Move all `concept_standard` (child) strategies to `archive/`
- [ ] Update `current.json` symlinks to point to the family strategy (if they currently point to a child)
- [ ] Reset `checkpoint.json` in each workspace (`iteration_count: 0`, `status: "pending"`, clear evidence fields)
- [ ] Build summary: per-workspace count of archived vs. retained strategies
- [ ] Verify dashboard `/strategies` page shows only ~49 family-level strategies (one per family)

### 3.4 Normalize Family Strategies to v2 Policy Format

> All workspace strategies are already in flat format (setup_workspace.py flattens on write), but all are `acceptance_policy_version: "v1"`. Need to upgrade to v2 with policy fields.

**Migration pipeline:**
1. Run `migrate_strategy_v1_to_v2.py` on each family strategy
2. Fill starter policy values (configurable defaults)
3. Validate loaded strategy against `Strategy` dataclass

**Default starter policy values (tuned for family-level discovery phase):**

| Policy | Field | Starter Value | Rationale |
|--------|-------|---------------|-----------|
| `outlier_policy` | `max_outlier_rate` | `0.15` | Relaxed for bootstrap (tighten during refinement) |
| | `max_high_risk_rate` | `0.08` | |
| | `max_review_rate` | `0.25` | |
| | `sample_size` | `200` | |
| `template_stability_policy` | `min_group_size` | `10` | |
| | `min_groups` | `2` | |
| | `min_group_hit_rate` | `0.50` | Relaxed for bootstrap |
| | `max_group_hit_rate_gap` | `0.30` | Relaxed for bootstrap |
| `did_not_find_policy` | `min_coverage` | `0.80` | Relaxed for bootstrap |
| | `max_near_miss_rate` | `0.20` | |
| | `max_near_miss_count` | `15` | |
| `confidence_policy` | `min_final` | `0.40` | Low floor for discovery |
| | `min_margin` | `0.05` | |

**Tasks:**
- [ ] Run `migrate_strategy_v1_to_v2.py --force` on all ~49 family strategies
- [ ] Verify each migrated strategy loads via `load_strategy()` without errors
- [ ] Verify `acceptance_policy_version: "v2"` is set on all family strategies
- [ ] Verify `outlier_policy`, `template_stability_policy`, `did_not_find_policy` are non-empty dicts
- [ ] Add `profile_type: "family_core"` to any family strategy that's missing it
- [ ] Set `validation_status: "bootstrap"` explicitly (should already be set)
- [ ] Run `strategy_writer.py --dry-run` on one family to verify gate pipeline accepts the v2 format
- [ ] Build script `scripts/migrate_all_family_strategies.sh` that runs the migration across all 49 families with consistent parameters

### 3.5 Fill Strategy Gaps for Missing Families

> 9 families have zero entries in `bootstrap_all.json`. These need hand-crafted bootstrap strategies seeded from ontology definitions and domain knowledge.

**Per-family bootstrap strategy design:**

| Family | Likely Article(s) | Seed Heading Patterns | Seed Keywords |
|--------|-------------------|----------------------|---------------|
| `deal_econ.term_loan` | I–II | `Term Loan`, `Term Facility`, `Term Loan Commitments` | `term loan`, `term facility`, `maturity date`, `amortization`, `scheduled repayment` |
| `deal_econ.revolver` | I–II | `Revolving Credit`, `Revolving Facility`, `Revolving Loan` | `revolving`, `revolving commitment`, `availability`, `swingline`, `letter of credit` |
| `deal_econ.second_lien` | I–II | `Second Lien`, `Second Lien Term Loan` | `second lien`, `junior lien`, `subordinated`, `intercreditor` |
| `credit_protection.corporate_structure` | V–VI | `Merger`, `Consolidation`, `Fundamental Changes` | `merger`, `consolidate`, `fundamental change`, `successor`, `all or substantially all` |
| `credit_protection.lme_protections` | various | `Liability Management`, `J. Crew`, `Serta`, `Uptier` | `uptier`, `liability management`, `non-pro-rata`, `open market purchase`, `Dutch auction` |
| `governance.pre_closing` | IV, conditions | `Conditions Precedent`, `Conditions to Closing`, `Conditions to Effectiveness` | `conditions precedent`, `closing date`, `effective date`, `officer's certificate`, `legal opinion` |
| `governance.other_advisory_roles` | preamble | `Arranger`, `Bookrunner`, `Syndication Agent` | `arranger`, `bookrunner`, `syndication agent`, `documentation agent`, `co-agent` |
| `debt_capacity.side_by_side_revolvers` | I–II | `Side-by-Side`, `Additional Revolving` | `side-by-side`, `additional revolving`, `parallel revolving`, `co-extensive` |
| `cash_flow.simultaneous_incurrence_netting` | VII | `Simultaneous Incurrence`, `Netting` | `simultaneous`, `incurrence`, `netting`, `offset`, `deemed to satisfy` |

**Tasks:**
- [ ] Create `{family_id}_v001.json` bootstrap strategies for each of the 9 gap families using seed patterns above
- [ ] Validate each against the `Strategy` dataclass (all required fields present, types correct)
- [ ] Set `acceptance_policy_version: "v2"` with starter policy values (from 3.4)
- [ ] Run `pattern_tester.py --sample 100` on each to get a baseline hit rate
- [ ] Refine heading patterns based on initial test results (add discovered variants)
- [ ] Add bootstrap entries to `data/bootstrap/bootstrap_all.json` for future re-setup
- [ ] Create workspaces for any gap families that lack one (currently only `carve_outs` is missing)

### 3.6 Family Strategy Pre-Process — Discovery Seeding

> **Before** agents refine strategies, run automated discovery algorithms on each of the 49 families to seed richer initial strategies. This replaces bare bootstrap patterns with corpus-evidence-backed patterns and provides a strong starting point for iterative refinement.

#### Discovery Pipeline — Per-Family Orchestration

The seeding pipeline runs 6 discovery steps per family, each building on the previous. A new orchestration script (`scripts/discovery_seed_pipeline.py`) should coordinate these steps.

**Step 1: Heading Discovery** (`heading_discoverer.py`)
- Input: family's current `heading_patterns` as `--seed-headings`; optional `--article-range` from `primary_articles`
- Output: ranked heading variants with frequency, article distribution, and canonical concept mapping
- Action: expand `heading_patterns` with high-frequency discovered headings (frequency ≥ 5)
- Also populate `negative_heading_patterns` from headings that frequently co-occur in matched articles but belong to a different family (via canonical mapping)

**Step 2: DNA Discovery** (`dna_discoverer.py`)
- Input: positive sections = all sections matching Step 1 headings; background = random non-matching sections
- Output: ranked DNA phrases with TF-IDF + log-odds scores, section rates, background rates
- Action: populate `dna_tier1` (top 10 phrases, section_rate ≥ 0.30, bg_rate ≤ 0.03) and `dna_tier2` (next 15, section_rate ≥ 0.15, bg_rate ≤ 0.08)

**Step 3: Anti-DNA Discovery** (inverse of Step 2)
- Input: positive sections = sections that are near-misses (score 0.15–0.30) or false positives from other families; background = true positive sections from Step 2
- Output: phrases that discriminate false positives from true positives
- Action: populate `dna_negative_tier1` (top 10 anti-signal phrases) and `dna_negative_tier2` (next 10)

**Step 4: Structural Position Analysis** (`structural_mapper.py`)
- Input: family strategy (with enriched headings/DNA from Steps 1-2)
- Output: article distribution, section number distribution, typical position, structural fingerprint summary
- Action: populate `primary_articles`, `primary_sections`, `structural_fingerprint_allowlist`

**Step 5: Defined Term Dependencies** (`definition_finder.py` + corpus analysis)
- Input: matched sections from Step 1; extract defined terms that appear in ≥ 50% of matched sections
- Output: ranked defined terms by co-occurrence frequency
- Action: populate `defined_term_dependencies` (top 10 terms), set `min_definition_dependency_overlap` (e.g., 0.3)

**Step 6: Template Family Patterns** (`coverage_reporter.py`)
- Input: family strategy (enriched from Steps 1-5); `--group-by template_family`
- Output: per-template hit rates, structural fingerprints, template-specific heading variants
- Action: populate `template_overrides` for templates with significantly different patterns; flag templates with low hit rates (< 0.50) for investigation

#### Pipeline Orchestration

- [ ] Build `scripts/discovery_seed_pipeline.py` — orchestrates Steps 1-6 for a single family
  - Inputs: `--family-id`, `--db`, `--workspace`, `--strategy`
  - Produces intermediate files in `workspaces/{family}/discovery/` (heading_results.json, dna_results.json, anti_dna_results.json, structural_map.json, term_deps.json, template_coverage.json)
  - Produces enriched strategy JSON that merges all discovery results
  - Runs `pattern_tester.py` before and after to measure improvement
- [ ] Add `--dry-run` mode that shows what fields would change without writing
- [ ] Add regression guard: enriched strategy must not decrease hit_rate or increase outlier_rate vs. baseline

#### Per-Step Tasks

**Heading Discovery (Step 1):**
- [ ] Run `heading_discoverer.py` for each of the 49 families with current heading_patterns as seeds
- [ ] Filter results: frequency ≥ 5, canonical mapping confirms family membership
- [ ] Identify negative headings: high-frequency headings in matched articles that map to OTHER families
- [ ] Merge discovered headings into `heading_patterns` (append, deduplicate)
- [ ] Merge negative headings into `negative_heading_patterns`

**DNA Discovery (Step 2):**
- [ ] For each family, collect positive sections (sections matching enriched headings from Step 1)
- [ ] Collect background sections (random 500 non-matching sections, stratified by template)
- [ ] Run `dna_discoverer.py` with `--top-k 30 --min-section-rate 0.15 --max-bg-rate 0.08`
- [ ] Tier the results: tier 1 (section_rate ≥ 0.30, bg_rate ≤ 0.03), tier 2 (remainder)
- [ ] Merge into `dna_tier1` and `dna_tier2`

**Anti-DNA Discovery (Step 3):**
- [ ] Collect false-positive sections (sections scoring 0.15–0.30 that are NOT the target family)
- [ ] Collect true-positive sections from Step 2 as background
- [ ] Run `dna_discoverer.py` in inverted mode (false positives as positive, true positives as background)
- [ ] Merge top results into `dna_negative_tier1` and `dna_negative_tier2`

**Structural Position (Step 4):**
- [ ] Run `structural_mapper.py` for each family with enriched strategy
- [ ] Extract `typical_position.article_num` → `primary_articles`
- [ ] Extract top section numbers → `primary_sections`
- [ ] Extract top structural fingerprint tokens → `structural_fingerprint_allowlist`

**Defined Term Dependencies (Step 5):**
- [ ] For each family, collect all defined terms from matched documents
- [ ] Rank by co-occurrence frequency (fraction of matched sections containing the term)
- [ ] Select top 10 terms with co-occurrence ≥ 0.50 → `defined_term_dependencies`
- [ ] Set `min_definition_dependency_overlap` based on empirical distribution (e.g., P25 of overlap fraction)

**Template Patterns (Step 6):**
- [ ] Run `coverage_reporter.py --group-by template_family` for each family
- [ ] Identify templates with hit_rate < 0.50 (investigation needed)
- [ ] Identify templates with significantly different heading patterns (e.g., "Limitation on Indebtedness" vs. "Borrowing" across template families)
- [ ] Populate `template_overrides` for divergent templates

#### Validation & Integration

- [ ] Run `pattern_tester.py --sample 300` on each enriched family strategy
- [ ] Compare before/after metrics: `hit_rate`, `heading_hit_rate`, `corpus_prevalence`, `outlier_rate`
- [ ] Reject enrichment if hit_rate decreases by > 0.05 or outlier_rate increases by > 0.05
- [ ] Save enriched strategies as `{family_id}_v002.json` via `strategy_writer.py`
- [ ] Update `checkpoint.json` in each workspace
- [ ] Build summary report: per-family discovery stats (headings added, DNA phrases found, structural position, metric deltas)

### 3.7 Heading Super-Graph Analysis

> Run `super_graph_analyzer.py` once across the entire corpus to identify ghost candidates (high-frequency headings not in any strategy's heading registry) and heading co-occurrence patterns.

- [ ] Run `super_graph_analyzer.py --db corpus_index/main.duckdb --top-n 200 --ghost-min-frequency 5`
- [ ] Review ghost candidates — these are common section headings that no current strategy claims
- [ ] For each ghost candidate, determine: (a) does it belong to an existing family? → add to that family's `heading_patterns`; (b) is it a new concept not in the ontology? → flag for ontology review; (c) is it boilerplate/structural? → ignore
- [ ] Use co-occurrence graph to identify heading clusters (headings that always appear together in the same article) — these clusters suggest which families co-locate
- [ ] Feed co-occurrence data into Block 5 strategy back-propagation (which strategies overlap in the same articles)

### 3.8 Begin Family-Level Strategy Finalization

> The iterative corpus-testing loop: run each family strategy against the corpus, measure metrics, refine patterns, repeat until stable. This begins AFTER discovery seeding (3.6) has enriched all strategies.

#### Finalization Criteria

A family strategy is "finalized" (`validation_status: "corpus_validated"`) when ALL of the following are met:

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| `heading_hit_rate` | ≥ 0.70 | At least 70% of hits come from heading matches (not just keyword/DNA) |
| `hit_rate` (overall) | ≥ 0.75 | Strategy finds the concept in at least 75% of corpus documents |
| `outlier_rate` | ≤ 0.10 | No more than 10% of hits are outliers |
| `high_risk_rate` | ≤ 0.05 | No more than 5% are high-risk outliers |
| `did_not_find coverage` | ≥ 0.85 | At most 15% of documents have no match |
| `near_miss_rate` | ≤ 0.15 | Near-misses (score 0.24–0.30) are rare |
| `template_stability` | group_hit_rate_gap ≤ 0.25 | Hit rate doesn't vary wildly across template families |
| `confidence_distribution` | ≥ 60% "high" | Majority of hits have high confidence |
| iterations | ≥ 3 | At least 3 refinement iterations completed |

Strategies that fail finalization after 5 iterations get flagged for domain expert review (Block 5 golden set).

#### Family Prioritization

> Order the 49 families by a composite score of: (1) concept count (larger families = more downstream children), (2) corpus prevalence (how often the concept appears), (3) interconnectedness (how many other families reference this one). Families with bootstrap gap (3.5) are lowest priority since they start from scratch.

**Tier 1 — Anchor families (refine first, highest downstream impact):**
1. `debt_capacity.indebtedness` (480 concepts, universal in credit agreements)
2. `debt_capacity.liens` (255 concepts, universal)
3. `cash_flow.rp` (213 concepts, restricted payments — core negative covenant)
4. `cash_flow.inv` (178 concepts, investments — core negative covenant)
5. `cash_flow.dispositions` (136 concepts, asset sales)
6. `cash_flow.mandatory_prepayment` (135 concepts)
7. `credit_protection.lme_protections` (116 concepts, high market relevance)
8. `cash_flow.available_amount` (102 concepts, builder basket)

**Tier 2 — Core families (refine second):**
9. `fin_framework.financial_covenant` (96 concepts)
10. `fin_framework.ebitda` (88 concepts)
11. `deal_econ.pricing` (100 concepts)
12. `deal_econ.ddtl` (87 concepts)
13. `credit_protection.events_of_default` (81 concepts)
14. `governance.amendments_voting` (80 concepts)
15. `governance.reps_conditions` (74 concepts)
16. `cash_flow.restricted_debt_payments` (72 concepts)
17. `governance.assignments` (66 concepts)
18. `deal_econ.term_loan` (73 concepts, bootstrap gap)
19. `credit_protection.corporate_structure` (62 concepts, bootstrap gap)
20. `deal_econ.revolver` (59 concepts, bootstrap gap)

**Tier 3 — Supporting families (refine third):**
21-35. Remaining families with 30–60 concepts each: `fin_framework.leverage`, `fin_framework.equity_cure`, `governance.affiliate_txns`, `deal_econ.fees`, `deal_econ.second_lien`, `credit_protection.collateral`, `governance.reporting`, `fin_framework.lct`, `credit_protection.change_of_control`, `credit_protection.guarantees`, `governance.pre_closing`, `deal_econ.governance`, `fin_framework.accounting`, `cash_flow.dividend_blockers`, `cash_flow.cross_covenant`

**Tier 4 — Small/niche families (refine last):**
36-49. Families with < 30 concepts each: incremental sub-families (`free_clear`, `ratio`, `builders`, `mfn`, `ied`, `stacking_reclass`, `acquisition_debt`, `contribution_debt`, `subordinated_debt`, `structural_controls`), `side_by_side_revolvers`, `simultaneous_incurrence_netting`, `carve_outs`, `other_advisory_roles`

#### Iteration Protocol

For each family (in priority order):

**Iteration N (N = 1, 2, 3, ...):**
1. Run `pattern_tester.py --db <corpus> --strategy <current> --sample 300 --verbose`
2. Analyze output:
   - `hit_summary`: heading_hit_rate, avg_score, confidence_distribution
   - `miss_summary`: top headings in misses (→ add to heading_patterns?), nearest_misses (→ lower threshold or add keywords?), structural_deviation (→ expand primary_articles?)
   - `outlier_summary`: top_outliers with flags (→ add to negative_heading_patterns or negative_keyword_patterns?)
   - `did_not_find_summary`: coverage, near_miss_rate (→ relax or tighten policies?)
3. Refine strategy based on analysis:
   - Add discovered heading variants to `heading_patterns`
   - Add false-positive headings to `negative_heading_patterns`
   - Adjust `keyword_anchors` based on keyword_precision
   - Adjust DNA phrases based on outlier flags
   - Tighten/relax policy thresholds
4. Save via `strategy_writer.py --db <corpus>` (runs full gate pipeline)
5. Collect evidence via `evidence_collector.py --matches <results> --workspace <ws>`
6. Check finalization criteria — if all met, promote to `corpus_validated`

**Tasks:**
- [ ] Define finalization criteria in a shared config file (`data/finalization_criteria.json`)
- [ ] Build `scripts/finalization_check.py` — reads pattern_tester output and checks all criteria, returns pass/fail with per-metric detail
- [ ] Prioritize the 49 families per the tier ranking above
- [ ] For Tier 1 families (top 8): complete ≥ 3 iterations each, targeting `corpus_validated`
- [ ] For Tier 2 families (9-20): complete ≥ 2 iterations each, targeting `corpus_validated`
- [ ] For Tier 3 families (21-35): complete ≥ 1 iteration, targeting improved bootstrap
- [ ] For Tier 4 families (36-49): run initial pattern_tester baseline, defer full refinement
- [ ] Track progress in dashboard Strategy Manager: per-family iteration count, current metrics, validation_status
- [ ] Flag families failing after 5 iterations for domain expert review via Block 5 golden set

### 3.9 Golden Set Integration for Strategy Evaluation

> Connect Block 3 strategy work with Block 5 golden annotations. Golden-linked sections (from domain expert ontology linking) become the ground truth for strategy evaluation.

- [ ] Add `--golden` flag to `pattern_tester.py` — when provided, also reports against golden-linked sections:
  - "Of N golden-linked sections for this concept, how many did the strategy find?"
  - "Of M strategy hits, how many are golden-confirmed vs. golden-flagged-false-positive?"
- [ ] Add golden set recall/precision to finalization criteria (once golden set reaches ≥ 20 annotations per family)
- [ ] Add `--golden-required` flag to `strategy_writer.py` — reject strategy if golden recall drops below threshold
- [ ] Build golden set coverage dashboard: per-family golden annotation count, golden recall of current strategy, golden false positive count

---

## Block 4 — Pipeline Rebuild & Optimization

> Given 3,000 documents and multiple parsing refinements expected today, the rebuild process must be optimized for rapid iteration. Ray-based parallel builders exist (`build_corpus_ray.py`, `build_corpus_ray_v2.py`) and need evaluation.

### 4.1 Rebuild Optimization

**Agent analysis findings (2026-02-23):**
- Current `build_corpus_index.py` is **single-threaded** and re-reads + normalizes every HTML file on each run
- **HTML normalization is the bottleneck**: `normalize_html()` using `html2text` is ~60% of per-doc processing time. Switching to `lxml` + custom stripping could 3-5x this step.
- **Ray builders**: `build_corpus_ray.py` (v1) uses Ray actors but has stale schema (missing new columns). `build_corpus_ray_v2.py` fixes schema but has untested error handling. Neither is production-ready without fixes.
- **Incremental rebuild is feasible**: DuckDB supports `DELETE FROM table WHERE doc_id IN (...)` + re-insert. Need a manifest of changed doc_ids (based on file mtime or content hash).
- **Table-specific rebuild**: The `_process_file()` function returns `{"doc": ..., "sections": ..., "clauses": ..., "definitions": ..., "section_texts": ...}`. Could skip sub-parsers and only recompute one table's data.
- **Estimated times** (3,000 docs):
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
- [ ] Run full corpus rebuild (3,000 docs) using optimized pipeline
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
| 2. Header & Numbering (Phases A–D + surveys) | 73 | 0 | 73 |
| 3. Strategy Cleanup & Seeding (3.1–3.9) | 93 | 0 | 93 |
| 4. Pipeline Rebuild & Optimization | 16 | 0 | 16 |
| 5. Domain Expert Verification & Golden Set (5.1–5.7) | 47 | 0 | 47 |
| **Total** | **289** | **11** | **278** |

> **Note:** Item count increased from 97 → 111 after cross-project analysis surfaced specific implementation tasks for clause parser refactor (6 improvements), admin agent improvements, edge case taxonomy expansion (25 categories), and rebuild optimization steps.
> Block 1.1 completed 2026-02-23: 5 new items checked off (zero-section investigation, categorization, regex expansion, validation, dashboard enrichment). Recovery rate 89% on 19-doc sample (17/19 recovered).
> Block 5 added 2026-02-23: 47 new items for domain expert verification features (golden set storage, section verification, clause depth correction, ontology linking, strategy back-propagation, golden set dashboard, feedback integration).
> Block 2 expanded 2026-02-23: Cross-project analysis of TermIntelligence, Vantage Platform, and Neutron identified 22 improvements across 4 phases (A: TOC/validation, B: heading extraction, C: taxonomy/survey, D: enrichment). Item count 10 → 73 (22 improvements with 63 sub-tasks + 13 survey items).
> Block 3 expanded 2026-02-24: Deep analysis of workspace structure (41 workspaces, 440 strategy files), contamination root cause (substring matching, 14 files in 8 workspaces), ontology family mapping (49 families, 3,538 total nodes). Added: setup fix (3.1), contamination cleanup (3.2), v2 migration with starter policies (3.4), bootstrap gap strategies with seed patterns for 9 families (3.5), 6-step discovery pipeline with orchestration script (3.6), super-graph analysis (3.7), finalization criteria + 4-tier family prioritization + iteration protocol (3.8), golden set integration (3.9). Item count 25 → 93.
