# Edge-Case CA Parsing Failures: Cross-Track Synthesis

**Date:** 2026-02-27
**Tracks analyzed:** 5 independent tracethroughs by parallel agents
**Scope:** `clause_parser.py`, `doc_parser.py`, `document_processor.py`, `enumerator.py`, `server.py`

---

## 1. System-Level View: How the 5 Defect Classes Interact

```
                      ┌─────────────────────────────────────┐
                      │     DOCUMENT PROCESSING PIPELINE     │
                      └─────────────────────────────────────┘
                                       │
                  ┌────────────────────┼────────────────────┐
                  ▼                    ▼                    ▼
           ┌─────────────┐   ┌──────────────┐   ┌──────────────┐
           │ doc_parser   │   │ clause_parser │   │  confidence  │
           │ (sections)   │   │ (_build_tree) │   │  (_compute)  │
           └──────┬──────┘   └──────┬───────┘   └──────┬───────┘
                  │                  │                   │
           ┌──────┴──────┐   ┌──────┴───────┐   ┌──────┴───────┐
           │ Track 2:     │   │ Track 1: xy  │   │ Track 4:     │
           │ missing_     │   │ parent_drop  │   │ xref scoring │
           │ sections     │   │              │   │ contradiction│
           │              │   │ Track 5:     │   │              │
           │              │   │ depth_reset  │   │ Track 3:     │
           │              │   │              │   │ dup_cascade  │
           └──────────────┘   └──────────────┘   └──────────────┘
                  │                  │                   │
                  │            OVERLAPS:                 │
                  │         Track 1 ↔ Track 5            │
                  │         (x/y/z shared range)         │
                  │         Track 3 → Track 4            │
                  │         (dup carve-out + xref)       │
                  └──────────────────┴───────────────────┘
```

### Dependency/Interaction Map

| Track | Depends on | Blocks | Shares code with |
|-------|-----------|--------|-----------------|
| T1 (parent-drop) | None | T5 partial | T5 (stack-pop @ 575-577) |
| T2 (section failures) | None | None | Independent pipeline stage |
| T3 (dup cascade) | None | None | T4 (confidence carve-out @ 839) |
| T4 (xref ambiguity) | None | None | T3 (scoring loop @ 753) |
| T5 (depth reset) | T1 partial | None | T1 (high-letter guard @ 528) |

---

## 2. Per-Track Summary

### Track 1: Parent-Drop (xy_parent_loss)
**Root cause:** `clause_parser.py:575-577` — stack-pop destroys ancestry chain for `(x)` at depth 1.
**Why existing repair fails:** The `allow_punctuation` paradox — the MORE root ordinals exist (making continuation likely), the LESS likely the punctuation-based repair fires (line 549: `sparse_root_alpha_context = len(root_alpha_ordinals) <= 5`).
**Fix:** Ordinal gap detection. `max_root_ordinal = max(root_alpha_ordinals_seen)`. If `gap = chosen.ordinal - max_root_ordinal > 1`, force nesting. Escape hatch: `anchored_long_body > 500 chars`.
**Impact:** 294 docs, 378 structural rows.
**Risk:** Low-Medium. Gap=1 (contiguous list) stays root. Gap>1 nests. False positives only in lists with reserved/skipped ordinals.

### Track 2: Section Parsing Failures (missing_sections)
**Root cause:** Regex coverage gaps — two document formats completely invisible to all section regexes.
- **Doc 1 (NeoGenomics):** Sequential 3-digit numbering (`245. REVOLVING CREDIT...`). `_SECTION_FLAT_RE` only allows `\d{1,2}`.
- **Doc 2 (Skyland Grain):** Roman-numeral articles (`I. DEFINITIONS`) + Roman-prefix sections (`VI.1 Indebtedness`). No regex supports bare Roman-dot sections.
**Fix:** P0: Add `_SECTION_BARE_ROMAN_RE` + `_ARTICLE_ROMAN_ONLY_RE`. P1: Expand `_SECTION_FLAT_RE` to `\d{1,3}`.
**Impact:** 2 docs (0.06% of corpus). But these represent real format families that likely appear in other CAs.
**Risk:** Low (Roman) to Medium (3-digit flat). TOC filtering is a natural guardrail.

### Track 3: Duplicate-Collision Cascades (clause_dup_id_burst)
**Root cause:** Three compounding defects:
1. `clause_parser.py:726` — `re.search(r"_dup\d+$", n.id)` uses end-of-string anchor, missing `a_dup2.i` descendants
2. `clause_parser.py:839-840` — permissive carve-out lets strong children survive under non-structural dup parents
3. `clause_parser.py:823-852` — single-pass consistency, no recursive propagation
**Fix:** Replace regex with `"_dup" in n.id`. Add `"_dup" not in parent` guard to carve-out. Add `duplicate_lineage_descendant` demotion reason.
**Impact:** 3,091 docs with `structural_child_of_nonstruct_parent`. Expected 60-80% reduction.
**Risk:** Near-zero false positives (`_dup` is a synthetic token that never appears in legitimate labels).

### Track 4: Xref-vs-Structural Ambiguity
**Root cause:** Compensating bug pattern:
- **Bug 1** (`clause_parser.py:520`): `if is_inline_list: xref = True` force-sets ALL inline enums as xref
- **Bug 2** (`clause_parser.py:753`): `not_xref = not n.is_xref or n.is_inline_list` compensates by restoring credit for inline nodes, but creates a loophole for genuine xref inline lists
**Secondary bug:** Chained xref miss — `_XREF_CONTEXT_RE` can't handle `Section 10.1(a)(i)` because `(a)` breaks the lookback pattern.
**Structural weakness:** `_WEIGHT_NOT_XREF = 0.15` is too low to prevent structural classification alone; even correctly applied, unanchored xref with run of 2 gets conf 0.50.
**Fix:** Remove both bugs simultaneously (line 520 + line 753). Add chained xref regex `(?:\s*\([a-zA-Z0-9]+\))*`. Add hard negative for unanchored section-context xrefs.
**Impact:** Inline xref false positives (e.g., "Sections 4.01(a), 4.02(b) and 4.03(c)" wrongly structural).
**Risk:** Medium. Must fix both bugs together; removing only one causes regression.

### Track 5: Depth-Reset Cascades (clause_depth_reset_after_deep)
**Root cause:** Same stack-pop as Track 1 (`clause_parser.py:575-577`), but for mid-alphabet labels (m-w, ordinals 13-23) that fall below the `ordinal >= 24` guard threshold.
**Three categories:**
- A (x/y/z): Overlaps Track 1, partially guarded. ~30-50% of resets.
- B (m-w): Fully independent, ZERO guard coverage. ~50-70% of resets.
- C (a-l): Almost always legitimate. Not a problem.
**Fix:** New depth-reset guard for ordinals 13+ when stack top is depth 3+. Primary signal: ordinal-continuity (if root sequence is unbroken, allow; if gap, force nesting).
**Impact:** 8 docs, 19 resets (baseline). Category B resets (~10-13) would be fixed.
**Risk:** Low. Unbroken ordinal sequences (legitimate lists) pass through unchanged.

---

## 3. The Shared Root Cause: `clause_parser.py:575-577`

Three of five tracks (T1, T5, and partially T3) trace back to the same 3-line stack-pop:

```python
while stack and stack[-1][0] >= depth:
    stack.pop()
```

This unconditional pop is the single most impactful code path in the parser. When an alpha token (depth=1) arrives, it ALWAYS empties the stack, regardless of:
- Whether the ordinal sequence is contiguous (legitimate) or gapped (suspicious)
- Whether the previous node was at depth 4 (drastic context loss) or depth 1 (normal sibling)
- Whether the token is a continuation or a true new root item

**All three proposed fixes (T1, T5, and T3's parent-consistency) work AROUND this pop** by setting `forced_parent_id` before the pop executes or by demoting results after the fact. None of them modify the pop itself.

---

## 4. Priority Matrix

| Priority | Track | Fix | Lines changed | Corpus impact | Risk | Dependencies |
|----------|-------|-----|---------------|---------------|------|--------------|
| **P0** | T3 | Dup lineage detection | ~10 lines | 3,091 docs | Near-zero | None |
| **P1** | T1 | Ordinal gap detection | ~20 lines | 294 docs | Low-Medium | None |
| **P2** | T4 | Xref dual-bug fix | ~25 lines | Unknown (inline xref FPs) | Medium | T4a+T4b together |
| **P3** | T5 | Depth-reset guard | ~25 lines | 8 docs / 19 resets | Low | Complement to T1 |
| **P4** | T2 | Section regex expansion | ~30 lines | 2 docs | Low-Medium | None |

### Rationale

- **T3 first** because it's the highest-impact fix (3,091 docs), lowest risk (synthetic `_dup` token), simplest change (substring check), and has zero dependencies.
- **T1 second** because it addresses the second-largest population (294 docs) with a clean mathematical solution (ordinal gap).
- **T4 third** because it fixes a real scoring contradiction, but requires careful paired changes and more testing.
- **T5 fourth** because it addresses a small population (8 docs) and overlaps with T1. After T1 is fixed, T5's remaining independent population is ~5-8 docs.
- **T2 last** because it only affects 2 docs (0.06%), though the format families may appear in new corpus additions.

---

## 5. Cross-Track Interactions During Implementation

### Safe to implement in parallel
- T2 (section parser) and T3 (dup cascade): completely independent code paths
- T2 and T4: completely independent
- T3 and T5: no interaction (T3 is in scoring, T5 is in tree-building)

### Must be sequenced
- T1 before T5: T5's guard should run BEFORE T1's high-letter guard, and they share the `forced_parent_id` mechanism. Implementing T5 first would create confusion about the ordinal >= 24 overlap zone.
- T4a and T4b together: removing the `xref=True` force-set (line 520) without removing the `or n.is_inline_list` (line 753) causes regression for structural inline nodes. Must be paired.

### Potential conflicts
- T1 + T5: Both guards set `forced_parent_id` for alpha tokens. If both fire (ordinal >= 24 AND stack depth >= 3), the depth-reset guard should defer to the high-letter guard (richer textual signals). Order: T5 guard first (ordinal 13-23 range), T1 guard second (ordinal >= 24).

---

## 6. Testing Strategy

### Tier 1: Unit tests (per track)
Each track report includes specific test cases. Total new tests: ~15.

### Tier 2: Integration snapshot
Re-parse the ~20 specific doc_ids referenced across all tracks. Compare clause trees before/after.

### Tier 3: Corpus-wide regression
Full corpus rebuild (3,298 docs). Gate criteria:
- No doc loses sections (T2 safety)
- `structural_child_of_nonstruct_parent` count decreases by >= 50% (T3 target)
- `xy_parent_loss` count decreases by >= 60% (T1 target)
- No doc gains > 10 new structural clauses (false promotion guard)
- Depth-reset count decreases (T5 target)

### Tier 4: Guardrail re-baseline
After all fixes:
- Re-run `edge_case_clause_guardrail.py` and `edge_case_clause_parent_guardrail.py`
- Update `data/quality/*.json` baselines
- Verify dashboard detectors reflect improvements

---

## 7. Consolidated Line Reference Index

| Line(s) | File | Tracks | Description |
|---------|------|--------|-------------|
| 59-70 | clause_parser.py | T4 | `_XREF_CONTEXT_RE`, `_XREF_LOOKAHEAD_RE` |
| 111-113 | doc_parser.py | T2 | `_ARTICLE_RE` |
| 138-140 | doc_parser.py | T2 | `_SECTION_STRICT_RE` |
| 148-150 | doc_parser.py | T2 | `_SECTION_BARE_RE` |
| 160-180 | clause_parser.py | T4 | `_is_xref()` |
| 184-230 | clause_parser.py | T4 | `_detect_inline_enums()` |
| 191-193 | doc_parser.py | T2 | `_SECTION_FLAT_RE` |
| 200-203 | doc_parser.py | T2 | `_SECTION_STANDALONE_RE` |
| 330-366 | clause_parser.py | T1 | `_looks_like_inline_high_letter_continuation()` |
| 430-628 | clause_parser.py | T1,T3,T5 | `_build_tree()` |
| 512 | clause_parser.py | T1,T5 | `depth = CANONICAL_DEPTH[...]` |
| 518-520 | clause_parser.py | T4 | `if is_inline_list: xref = True` (Bug 1) |
| 528-573 | clause_parser.py | T1,T5 | High-letter continuation repair |
| 544-549 | clause_parser.py | T1 | `sparse_root_alpha_context` / `allow_punctuation` paradox |
| 575-577 | clause_parser.py | T1,T3,T5 | **Stack-pop loop (shared root cause)** |
| 580 | clause_parser.py | T1,T5 | Parent resolution: `forced_parent_id or stack[-1][1]` |
| 585-589 | clause_parser.py | T3 | Duplicate ID generation |
| 620-626 | clause_parser.py | T5 | `last_sibling_at_level` purge |
| 675-854 | clause_parser.py | T3,T4 | `_compute_confidence()` |
| 724-727 | clause_parser.py | T3 | **`re.search(r"_dup\d+$")` (suffix-only bug)** |
| 731-744 | clause_parser.py | T1,T5 | `root_high_letter_with_low_reset_ids` |
| 753 | clause_parser.py | T4 | **`not_xref = not n.is_xref or n.is_inline_list` (Bug 2)** |
| 774-780 | clause_parser.py | T1,T5 | `_ROOT_HIGH_LETTER_PENALTY` (unanchored, ordinal >= 24 only) |
| 799-802 | clause_parser.py | T3 | Duplicate demotion |
| 823-852 | clause_parser.py | T3 | Parent-consistency pass (single-level) |
| 839-840 | clause_parser.py | T3 | **Permissive carve-out (anchor + run + conf >= 0.75)** |
| 383-397 | document_processor.py | T2 | `outline_and_regex_sections_zero` state |
| 1094-1122 | doc_parser.py | T2 | `_build()` 3-phase construction |
| 1344-1452 | doc_parser.py | T2 | `_detect_articles()` with fallback chain |
| 1693-2026 | doc_parser.py | T2 | `_detect_sections()` with multi-strategy merge |
| 2746-2766 | server.py | T3 | `structural_child_of_nonstruct_parent` detector |

---

## 8. Key Insight: The "Allow Punctuation" Paradox (T1) Is a Microcosm

Track 1's finding about the `allow_punctuation` paradox (line 549) is the single most instructive finding across all 5 tracks:

> The MORE root alpha ordinals exist (making `(x)` more likely to be a continuation), the LESS likely the punctuation-based repair fires.

This is because `sparse_root_alpha_context = len(root_alpha_ordinals) <= 5`. A section with 23 root alphas sets this to `False`, disabling punctuation-based continuation detection — exactly when continuation is most likely.

The ordinal-gap fix sidesteps this paradox entirely by using structural rather than textual signals. This pattern (replacing fragile text heuristics with structural invariants) is the unifying principle across all 5 fixes:

| Track | Current heuristic (fragile) | Proposed signal (structural) |
|-------|----------------------------|------------------------------|
| T1 | Word connectors in 160-char lookback | Ordinal gap > 1 |
| T2 | Fixed regex patterns | Expanded regex coverage |
| T3 | End-of-string regex anchor | Substring check on synthetic token |
| T4 | Boolean OR compensation logic | Independent xref flags with hard negative |
| T5 | ordinal >= 24 threshold | Ordinal continuity check |
