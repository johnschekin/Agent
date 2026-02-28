# Track 2: Section Parsing Failures -- Full Tracethrough

## Executive Summary

Two documents in the corpus end up with `section_count=0` and `section_parser_mode='none'`:

| doc_id | filename | text_length | defs | root cause |
|--------|----------|-------------|------|------------|
| `bd06a605c6f896c2` | exhibit10-1xcreditagre.htm | 459,101 | 11 | Sequential-number headings (245+ definitions, then sections 245-255); body uses `a. / b. / c.` sub-sections, not `X.YY` |
| `ea267cacf6d42cd0` | arcreditagreement-skylandg.htm | 572,619 | 4 | Roman-numeral article headings (`I.`, `II.`...`XII.`) with Roman-prefix sub-sections (`I.1`, `VI.1`, `VII.1`) |

Both are large, legitimate credit agreements (450K-570K chars) with dozens of sections. The parser's regex coverage has blind spots for two non-standard but real heading formats.

---

## 1. Code Path Trace: Raw HTML to section_count=0

### Entry Point

`document_processor.py:process_document_text()` (line 265-623)

```
Step 1-5: HTML normalization, doc_id, classification, CIK/accession
Step 6:   outline = DocOutline.from_text(normalized_text, filename=filename)   [line 369]
          all_sections = outline.sections                                       [line 370]
```

If `all_sections` is empty (line 383):

```python
if not all_sections:                                              # line 383
    from agent.section_parser import find_sections
    regex_sections = find_sections(normalized_text)               # line 386
    ...
    if regex_sections:                                            # line 389
        section_parser_mode = "regex_fallback"                    # line 390
    else:
        section_parser_mode = "none"                              # line 395
        section_parse_trace["reason"] = "outline_and_regex_sections_zero"  # line 397
```

Both docs land on line 395-397: `mode="none"`, `reason="outline_and_regex_sections_zero"`.

### DocOutline.from_text() -- Primary Path

`doc_parser.py:2723`:
```python
@classmethod
def from_text(cls, text: str, filename: str = "") -> DocOutline:
    return cls(text, filename)
```

This calls `__init__` (line 1067) which calls `_build()` (line 1094):

```python
def _build(self) -> None:
    raw_articles = self._detect_articles()           # Phase 1
    raw_sections = self._detect_sections(raw_articles)  # Phase 2
    if raw_sections:
        ...  # article synthesis, alignment
    elif raw_articles:
        raw_sections = self._synthesize_sections_from_articles(raw_articles)  # line 1119
    self._build_articles(raw_articles, raw_sections)  # line 1120
```

For both failing docs: `raw_articles = []` and `raw_sections = []`.

### Phase 1: _detect_articles() -- Why Zero Articles

`doc_parser.py:1344-1452`

The article detection chain:
1. `_find_article_matches()` (line 1351) -- uses `_ARTICLE_RE`: requires `ARTICLE` or `Article` keyword
2. If zero: `_find_section_toplevel_matches()` (line 1355) -- uses `_SECTION_TOPLEVEL_RE`: requires `SECTION N` (bare integer or Roman, ALL CAPS)
3. If zero: `_find_part_chapter_matches()` (line 1359) -- tries `PART N`, `CHAPTER N`, `CLAUSE N`

**Doc 1 (NeoGenomics):** Body uses `1. CERTAIN DEFINITIONS`, `245. REVOLVING CREDIT...` -- no `ARTICLE` keyword, no `SECTION N` top-level, no `PART/CHAPTER/CLAUSE`. Zero articles detected.

**Doc 2 (Skyland Grain):** Body uses `I. CERTAIN DEFINITIONS`, `II. INCREASED COSTS...` -- Roman-dot headings WITHOUT `ARTICLE` keyword. The `_ARTICLE_RE` pattern requires the literal word `ARTICLE`:

```python
# doc_parser.py:111
_ARTICLE_RE = re.compile(
    r"(?:^|\n)\s*\d{0,3}\s*(?:ARTICLE|Article)\s+([IVX]+|\d+|[A-Za-z]+)\b",
)
```

The pattern `I. CERTAIN DEFINITIONS` does NOT contain `ARTICLE` or `Article`. Zero articles detected.

### Phase 2: _detect_sections() -- Why Zero Sections

`doc_parser.py:1693-2026`

The section detection chain with `articles=[]`:

**Step A: Keyword matches (`_SECTION_STRICT_RE`)**

```python
# doc_parser.py:138-140
_SECTION_STRICT_RE = re.compile(
    r"(?:^|\n)\s*(?:Section|SECTION|Sec\.|Sec\b|§)\s+"
    r"(\d+\.\s?\d+[a-z]?|[IVX]+\.\s?\d+[a-z]?)"
    r"[^\S\n]*[.:\s][^\S\n]*"
    r"([A-Z][A-Za-z][^\n]*)?",
)
```

Number capture group: `\d+\.\s?\d+[a-z]?` or `[IVX]+\.\s?\d+[a-z]?`

- **Doc 1:** Body has NO `Section` keyword headings. All sub-sections use `a.`, `b.`, `c.` letters. Result: 0 matches.
- **Doc 2:** Body has NO `Section` keyword headings. Sub-sections use bare `I.1`, `VI.1`. One match at pos 305441 (`Section 11.8`) which is a cross-reference, not a heading. `surviving_keyword = 0`.

**Step B: Bare-number fallback (`_SECTION_BARE_RE`)**

```python
# doc_parser.py:148-150
_SECTION_BARE_RE = re.compile(
    r"(?:^|\n)\s*(\d+\.\d{1,3}[a-z]?)\.?\s+([A-Z][A-Za-z][^\n]*)",
)
```

Since `surviving_keyword < 10`, `use_bare = True` (line 1730).

- **Doc 1:** 79 bare matches -- ALL in the TOC (positions 922-11636). Body uses letter-based `a.` sub-sections, not `X.Y`. Body section headings are `245. REVOLVING CREDIT...` which match `_SECTION_BARE_RE` as `245. REVOLVING` -- WAIT. Let me re-check.

Actually no: `_SECTION_BARE_RE` captures `(\d+\.\d{1,3}[a-z]?)` which requires a DOT in the number. `245. REVOLVING` would capture number=`245.` -- but the regex expects `\d+\.\d{1,3}` which requires digits AFTER the dot too. `245.` alone (with space after) does not match because there's no `\d{1,3}` after the dot. So `245. REVOLVING` does NOT match `_SECTION_BARE_RE`.

79 TOC matches -> all rejected by `_is_toc_entry()` -> 0 surviving.

- **Doc 2:** 152 bare matches -- ALL in the TOC (positions 798-6859). The TOC uses digit-based numbering (`1.1`, `2.1`, `10.1`) while body uses Roman-prefix (`I.1`, `II.1`, `X.1`). Since `_SECTION_BARE_RE` requires `\d+\.` (digit before dot), it cannot match Roman-prefix body headings.

152 TOC matches -> all rejected by `_is_toc_entry()` -> 0 surviving.

**Step C: Standalone fallback (`_SECTION_STANDALONE_RE`)**

```python
# doc_parser.py:200-203
_SECTION_STANDALONE_RE = re.compile(
    r"(?:^|\n)\s*([IVX]+\.\d{1,3}[a-z]?|\d{1,2}\.\d{1,3}[a-z]?)\s*\.?\s*$",
    re.MULTILINE,
)
```

This COULD match `I.1`, `II.3`, `VI.1` etc. BUT it requires the number to be alone on its line (`$` anchor). In both docs, the heading text is on the SAME line as the number (`I.1 Certain Definitions`), so standalone finds 0 matches.

**Step D: TOC over-rejection recovery (line 1923)**

Fires when `not deduped and keyword_matches` (line 1923). Since `keyword_matches = []` for Doc 1 and `keyword_matches` has 1 entry for Doc 2 (the cross-reference), this recovery path is essentially a no-op.

**Step E: Flat section fallback (`_SECTION_FLAT_RE`, line 1985)**

```python
# doc_parser.py:191-193
_SECTION_FLAT_RE = re.compile(
    r"(?:^|\n)\s*(\d{1,2})\.\s+([A-Z][A-Za-z][^\n]{0,120})",
)
```

Only fires when `not deduped and not articles` (line 1985).

- **Doc 1:** 13 flat matches, but 12 are TOC-rejected, 1 survives (body `1. CERTAIN DEFINITIONS` at pos 14178). The body `245. REVOLVING CREDIT...` does NOT match because `_SECTION_FLAT_RE` captures `\d{1,2}` (max 2 digits), but `245` has 3 digits. So only 1 survives, which is below the `>= 5` threshold (line 2003). Flat fallback does NOT fire.

- **Doc 2:** 0 flat matches. The body uses Roman-numeral articles (`I.`, `II.`), not digit-dot format. Flat regex requires `\d{1,2}\.` which doesn't match Roman numerals.

### section_parser.py Fallback -- Also Zero

`document_processor.py:383-397` calls `section_parser.find_sections()` when `DocOutline` returns zero sections.

`section_parser.py:find_sections()` (line 261) calls `DocOutline.from_text(text)` AGAIN -- same result (zero). Then falls back to its own `_find_articles()` and `_find_all_sections()` which use `_ARTICLE_RE` and `_SECTION_RE` (line 118-123):

```python
# section_parser.py:118-123
_SECTION_RE = re.compile(
    r"(?:^|\n)\s*(?:Section|SECTION|§)\s+"
    r"(\d{1,2}\.\d{2})"     # Even MORE restrictive: requires exactly 2 digits after dot
    r"\s*[.\-\u2013\u2014]?\s*([^\n]{0,120})",
    re.MULTILINE,
)
```

This is even more restrictive than `_SECTION_STRICT_RE` (requires exactly `\d{2}` after dot, and doesn't support `Sec.` or `Sec`). Still finds nothing.

Final result: `section_parser_mode = "none"`, `section_count = 0`.

---

## 2. Regex Pattern Analysis (Character-by-Character)

### 2.1 _SECTION_STRICT_RE Number Group

Pattern: `(\d+\.\s?\d+[a-z]?|[IVX]+\.\s?\d+[a-z]?)`

This matches:
- `\d+\.\s?\d+[a-z]?` -- digit(s), dot, optional space, digit(s), optional letter
  - Matches: `7.02`, `2.1`, `10.10`, `2. 01` (OCR space)
  - Misses: `2.1.1` (second dot), `I.1` (Roman prefix)
- `[IVX]+\.\s?\d+[a-z]?` -- Roman numeral(s), dot, optional space, digit(s), optional letter
  - Matches: `I.1`, `II.3`, `VI.1`, `VII.1`
  - Misses: `2.1.1` (digit prefix)

**Critical gap:** NO support for multi-dot formats like `X.Y.Z`.

**But also:** This regex requires the `Section|SECTION|Sec.|Sec|§` keyword prefix. Both failing docs lack this keyword in their body headings.

### 2.2 _SECTION_BARE_RE Number Group

Pattern: `(\d+\.\d{1,3}[a-z]?)`

- Requires DIGIT(s) before the dot
- Requires 1-3 DIGITS after the dot
- Misses: Roman-prefix (`I.1`), multi-dot (`2.1.1`)

### 2.3 _SECTION_STANDALONE_RE Number Group

Pattern: `([IVX]+\.\d{1,3}[a-z]?|\d{1,2}\.\d{1,3}[a-z]?)`

- Supports Roman prefix (`I.1`) AND digit prefix (`7.02`)
- BUT requires the number to be alone on its line (`$` anchor)
- Misses: any format with heading on the same line

### 2.4 _SECTION_FLAT_RE Number Group

Pattern: `(\d{1,2})`

- Only 1-2 digit numbers
- Misses: 3-digit numbers like `245`
- Requires uppercase heading following the number

### 2.5 _ARTICLE_RE

Pattern: `(?:^|\n)\s*\d{0,3}\s*(?:ARTICLE|Article)\s+([IVX]+|\d+|[A-Za-z]+)\b`

- Requires literal `ARTICLE` or `Article` keyword
- Misses: Roman-only articles (`I.`, `II.`) without `ARTICLE` keyword
- Misses: digit-only articles (`1.`, `2.`) without `ARTICLE` keyword

### 2.6 Heading Formats That Fail All Patterns

| Heading format | Example | Strict | Bare | Standalone | Flat | Article |
|---|---|---|---|---|---|---|
| Roman-dot article | `I. CERTAIN DEFINITIONS` | N/A | N/A | N/A | no (Roman) | no (no ARTICLE keyword) |
| Roman-dot section | `I.1 Certain Definitions` | no (no Section keyword) | no (Roman prefix) | no (not alone on line) | N/A | N/A |
| Multi-dot section | `2.1.1 Revolving Credit Loans` | no (multi-dot) | no (multi-dot) | no (multi-dot) | N/A | N/A |
| Sequential flat (3-digit) | `245. REVOLVING CREDIT` | no (no keyword) | no (no digits after dot) | no (3-digit) | no (3-digit cap) | no (no ARTICLE keyword) |
| Letter sub-section | `a. Certain Definitions` | no | no | no | no | no |

---

## 3. Root Cause Analysis by Document

### 3.1 Doc bd06a605 (NeoGenomics Credit Agreement)

**Structure:** PNC Bank-style document using sequential numbering for ALL content items:
- Definitions numbered 1-244 as a flat list
- Top-level sections continue from 245 onwards: `245. REVOLVING CREDIT AND SWING LOAN FACILITIES`, `247. INTEREST RATES`, etc.
- Sub-sections use letter labels: `a. Revolving Credit Commitments`, `b. Construction`
- Sub-sub-sections use Roman numerals: `i. Revolving Credit Loans`

**Why it fails:**
1. No `ARTICLE` keyword anywhere -> `_detect_articles()` returns `[]`
2. No `Section` keyword in headings -> `_SECTION_STRICT_RE` finds 0 matches
3. `_SECTION_BARE_RE` matches 79 TOC entries but 0 body entries (body uses letter sub-sections, not `X.Y` format)
4. `_SECTION_FLAT_RE` finds 13 matches (12 TOC + 1 body), but only 1 survives TOC filter -> below the `>= 5` threshold
5. Body section numbers (`245`, `247`, `248`) have 3 digits -> `_SECTION_FLAT_RE` only allows `\d{1,2}` (max 2 digits)

**Key insight:** This is fundamentally a different document structure. It doesn't use the `Article N / Section X.YY` pattern at all. Instead, it numbers ALL content items sequentially (like a legal brief) and uses letter/Roman sub-enumeration.

### 3.2 Doc ea267cacf6d42cd0 (Skyland Grain Credit Agreement)

**Structure:** CoBank-style document using Roman-numeral articles and Roman-prefix sections:
- Articles: `I. CERTAIN DEFINITIONS`, `II. INCREASED COSTS...`, through `XII. GUARANTY`
- Sections: `I.1 Certain Definitions`, `I.2 Construction`, `VI.1 Indebtedness`, `VII.1 Minimum Debt Service Coverage Ratio`
- TOC uses Arabic-digit equivalents: `1.1`, `2.1`, `6.1`, `7.1`

**Why it fails:**
1. No `ARTICLE` keyword -> `_detect_articles()` returns `[]`
2. Body headings lack `Section` keyword -> `_SECTION_STRICT_RE` finds 0 body matches (1 cross-reference match)
3. `_SECTION_BARE_RE` requires `\d+\.` (digits before dot) -> cannot match Roman-prefix `I.1`, `VI.1`
4. `_SECTION_STANDALONE_RE` supports Roman prefix BUT requires number alone on line -> body has `I.1 Certain Definitions` (number + heading on same line)
5. `_SECTION_FLAT_RE` requires `\d{1,2}\.` -> cannot match Roman numerals
6. 152 bare matches in TOC are all rejected by `_is_toc_entry()`

**Key insight:** The doc's body sections would match `_SECTION_STRICT_RE`'s number group (`[IVX]+\.\s?\d+[a-z]?`) IF they had a `Section` keyword prefix. But they use bare Roman-prefix notation. A "bare Roman-dot section" regex is the missing piece.

---

## 4. _is_toc_entry() Behavior Analysis

For completeness: TOC rejection is NOT the root cause for these docs (it correctly rejects TOC entries). But it's worth noting how it handles the failing docs:

### Doc 1 (NeoGenomics)

TOC region: positions 881-11636 (TOC header at ~position 770). All 79 `_SECTION_BARE_RE` matches are within this TOC region. `_is_toc_entry()` correctly identifies them via:
- Signal 1: TOC header within 3K chars (for early matches)
- Signal 3: Page number patterns (`. 38`, `. 1` at end of lines)
- Signal 5: Short lines clustered (TOC layout: entries < 50 chars)

The body starts at ~14178. Only 1 `_SECTION_FLAT_RE` match survives into the body, but alone it's below the `>= 5` threshold.

### Doc 2 (Skyland Grain)

TOC region: positions 798-6859 (TOC header at ~position 780). All 152 `_SECTION_BARE_RE` matches are within this TOC. `_is_toc_entry()` correctly identifies them via the same signals.

Body starts at ~11273 with `I. CERTAIN DEFINITIONS`. No regex matches body headings at all.

**Conclusion:** `_is_toc_entry()` is working correctly. The problem is upstream: the regexes don't match the body heading formats.

---

## 5. Proposed Fixes

### Fix 1: Add bare Roman-dot section regex (for Doc 2 and similar)

**Problem:** `_SECTION_BARE_RE` only supports digit-prefix (`\d+\.\d{1,3}`). Roman-prefix sections (`I.1`, `VI.1`) with heading text on the same line have no matching regex.

**Proposed regex:**
```python
_SECTION_BARE_ROMAN_RE = re.compile(
    r"(?:^|\n)\s*([IVX]+\.\d{1,3}[a-z]?)\.?\s+([A-Z][A-Za-z][^\n]*)",
)
```

**Integration point:** `_detect_sections()` around line 1734 -- when `use_bare` is True, also scan `_SECTION_BARE_ROMAN_RE` and merge into `bare_sections`.

After matching, normalize Roman prefix to digits (e.g., `VI.1` -> `6.1`) using existing `_roman_to_int()`.

### Fix 2: Add Roman-only article regex (for Doc 2 and similar)

**Problem:** `_ARTICLE_RE` requires `ARTICLE` keyword. Documents using `I. TITLE`, `II. TITLE` as article headings are invisible.

**Proposed regex:**
```python
_ARTICLE_ROMAN_ONLY_RE = re.compile(
    r"(?:^|\n)\s*([IVX]+)\.\s+([A-Z][A-Z\s,&\-]{2,80})\s*(?:\n|$)",
)
```

**Integration point:** `_detect_articles()` line 1358-1359, as a new fallback after `_find_part_chapter_matches()`. Only fire when all other article detectors return zero.

**Guard:** Require >= 3 matches to avoid false positives from body Roman-numeral lists. Validate that captured Roman numerals are sequential (I, II, III or start from I).

### Fix 3: Support multi-dot section numbers (for Doc 1 and similar)

**Problem:** All section regexes only support single-dot `X.Y` format. Multi-dot `X.Y.Z` (e.g., `2.1.1`, `2.6.5`, `2.9.10`) used by PNC-style CAs is completely missed.

**Proposed regex changes:**

In `_SECTION_STRICT_RE`, extend number group:
```python
# Current:
r"(\d+\.\s?\d+[a-z]?|[IVX]+\.\s?\d+[a-z]?)"
# Proposed:
r"(\d+\.\s?\d+(?:\.\d+)*[a-z]?|[IVX]+\.\s?\d+(?:\.\d+)*[a-z]?)"
```

In `_SECTION_BARE_RE`:
```python
# Current:
r"(\d+\.\d{1,3}[a-z]?)"
# Proposed:
r"(\d+\.\d{1,3}(?:\.\d{1,3})*[a-z]?)"
```

**However:** For Doc 1 specifically, this wouldn't help because the body doesn't use `X.Y.Z` notation. The body uses `a. / b. / c.` letter sub-sections and `i. / ii.` Roman sub-sub-sections. The X.Y.Z format only appears in the TOC.

### Fix 4: Expand _SECTION_FLAT_RE to support 3-digit numbers

**Problem:** `_SECTION_FLAT_RE` only matches `\d{1,2}` (1-2 digits). NeoGenomics-style docs number sections from 245+, requiring 3 digits.

**Proposed change:**
```python
# Current:
_SECTION_FLAT_RE = re.compile(
    r"(?:^|\n)\s*(\d{1,2})\.\s+([A-Z][A-Za-z][^\n]{0,120})",
)
# Proposed:
_SECTION_FLAT_RE = re.compile(
    r"(?:^|\n)\s*(\d{1,3})\.\s+([A-Z][A-Za-z][^\n]{0,120})",
)
```

**Risk:** Higher false-positive rate from 3-digit numbers in financial tables (e.g., `100. The Administrative Agent...`). Mitigated by the `>= 5` threshold and TOC filtering.

**However:** Even with this fix, Doc 1 would still fail because only 1 body flat match survives TOC filtering (the `1. CERTAIN DEFINITIONS` at 14178). The remaining body sections are numbered 245-255, which are in fact present but the TOC entries for them (positions 881-11636) are what `_SECTION_FLAT_RE` finds -- and they're all correctly TOC-rejected.

Wait -- with 3-digit support, would the BODY `245. REVOLVING CREDIT...` be found? Let me check: the body text at position 139442 shows `245. REVOLVING CREDIT AND SWING LOAN FACILITIES`. If `_SECTION_FLAT_RE` supported `\d{1,3}`, this would match. And it's well past the TOC region, so it wouldn't be TOC-rejected. Combined with the already-surviving `1. CERTAIN DEFINITIONS` at 14178 and other body sections, we might reach the `>= 5` threshold.

Body sections (with 3-digit support): `1.` (14178), `245.` (139442), `247.` (193161), `248.` (207270), `249.` (258234), `250.` (290373), `251.` (300761), `252.` (359346), `253.` (375588), `254.` (390503), `255.` (444051) = 11 body matches. Well above the `>= 5` threshold. **This fix would resolve Doc 1.**

### Fix 5: Zero-section recovery pass with min_signals=2

**Problem:** When both outline and regex fallback produce zero sections, no recovery is attempted.

**Proposed pseudocode:**
```python
# In _detect_sections(), after all existing logic, before return:
if not deduped:
    # Recovery pass: retry ALL regex patterns with min_signals=2
    # This catches edge cases where valid body headings are
    # over-rejected by single-signal TOC detection
    for m in chain(keyword_matches, bare_sections, standalone_sections):
        if _is_toc_entry(text, m.start(), m.end(), min_signals=2):
            continue
        # ... add to deduped
```

**Assessment:** This would NOT fix either of these docs because the root cause is regex blindness (no matches at all in body text), not over-aggressive TOC rejection.

### Fix 6: Rejection reason log (diagnostic)

**Proposed:** Add a `rejection_log` field to `section_parse_trace` that records why each candidate was rejected:

```python
section_parse_trace["rejection_log"] = {
    "strict_raw": len(keyword_matches),
    "strict_toc_rejected": strict_toc_count,
    "strict_ghost_rejected": strict_ghost_count,
    "bare_raw": len(bare_sections),
    "bare_toc_rejected": bare_toc_count,
    "bare_heading_rejected": bare_heading_count,
    "standalone_raw": len(standalone_sections),
    "flat_raw": flat_raw_count,
    "flat_toc_rejected": flat_toc_count,
    "flat_threshold_failed": flat_survived < 5,
}
```

This would make future debugging much faster.

---

## 6. Priority-Ordered Fix Recommendations

### P0: Fix Doc 2 (Skyland Grain) -- Roman-prefix bare sections

**Changes required:**
1. Add `_SECTION_BARE_ROMAN_RE` regex (new) -- `doc_parser.py`
2. Add `_ARTICLE_ROMAN_ONLY_RE` regex (new) -- `doc_parser.py`
3. Integrate Roman bare sections into `_detect_sections()` merge logic -- `doc_parser.py:~1734`
4. Integrate Roman-only articles as a new fallback in `_detect_articles()` -- `doc_parser.py:~1358`
5. Ensure Roman-to-digit normalization uses existing `_roman_to_int()` -- already available

**Expected result:** 12 articles detected (`I` through `XII`), ~120+ sections detected (`I.1` through `XII.15`), full outline recovery.

**Risk:** Low. Roman-only article headings like `I. DEFINITIONS` are unambiguous in context (start-of-line, ALL CAPS heading, no `ARTICLE` keyword ambiguity). Guard with sequential-numbering validation and minimum match count (>= 3).

### P1: Fix Doc 1 (NeoGenomics) -- 3-digit flat section numbers

**Changes required:**
1. Expand `_SECTION_FLAT_RE` number group from `\d{1,2}` to `\d{1,3}` -- `doc_parser.py:191`
2. Possibly raise the `>= 5` threshold to `>= 8` to compensate for higher false-positive rate

**Expected result:** 11 body sections detected (numbers 1, 245-255), flat fallback fires.

**Risk:** Medium. 3-digit flat numbers could match pricing grid values, page artifacts, or regulation references. But the `>= 5` threshold and TOC filtering provide good guardrails.

### P2: Multi-dot section support

**Changes required:**
1. Extend `_SECTION_STRICT_RE`, `_SECTION_BARE_RE`, `_SECTION_STANDALONE_RE` number groups to support `(?:\.\d+)*` suffix
2. Update `_is_plausible_section_number()` to handle multi-dot numbers
3. Update `_parse_section_minor()` to handle multi-dot numbers
4. Update `_enforce_monotonic_sections()` for multi-level ordering

**Expected result:** Multi-dot sections like `2.1.1`, `2.6.5` would be detected.

**Risk:** Medium-High. Multi-dot numbers appear in financial ratios (`5.00 to 1.00`), IP addresses, version numbers, and other non-section contexts. Requires careful guardrails.

**Note:** This fix alone would NOT resolve Doc 1 (which doesn't use multi-dot in the body) but would help other documents in the corpus that use this format.

### P3: Diagnostic improvements

**Changes required:**
1. Add rejection reason log to `section_parse_trace` in both `_detect_sections()` and `process_document_text()`
2. Log raw match counts by regex type, TOC rejection counts, ghost rejection counts, threshold failures

**Expected result:** Future zero-section failures can be diagnosed in seconds from the trace instead of requiring manual code tracing.

**Risk:** None. Pure diagnostic addition, no behavioral change.

---

## 7. Risk Assessment

### Regression risk from proposed fixes

| Fix | Scope | Regression surface | Mitigation |
|-----|-------|--------------------|------------|
| Roman bare sections | New regex, new code path | Could over-match Roman lists in body text | Require >= 3 matches, sequential numbering, ALL CAPS heading |
| Roman-only articles | New regex, new fallback | Could match Roman-numeral lists as articles | Require >= 3, sequential, after all other article fallbacks |
| 3-digit flat sections | Regex widening | Could match 3-digit numbers in financial tables | Raise threshold from 5 to 8, existing TOC filter |
| Multi-dot sections | Regex widening + validation changes | Could match financial ratios, IP addresses | Keyword-corroboration requirement for bare matches |
| Diagnostic log | Additive | None | None |

### Corpus-wide impact estimate

- Currently: 2/3,298 docs (0.06%) have `mode=none`
- With P0+P1 fixes: both would likely recover to `mode=doc_outline` with full section coverage
- P2 (multi-dot) may recover sections in additional docs currently using `regex_fallback` mode

### Testing strategy

1. Unit tests: Add the two failing docs as gold fixtures
2. Snapshot tests: Run full corpus build before/after, compare section_count deltas
3. Regression gate: Ensure no existing doc loses sections (no decrease in section_count for any doc)
4. Manual inspection: Review the 2 recovered docs' section boundaries for correctness

---

## 8. Appendix: Exact File/Line References

| Component | File | Lines | Purpose |
|-----------|------|-------|---------|
| Entry point | `src/agent/document_processor.py` | 265-623 | `process_document_text()` |
| Zero-section branch | `src/agent/document_processor.py` | 383-397 | Sets `mode='none'` when both outline and regex fallback produce 0 sections |
| `DocOutline.from_text()` | `src/agent/doc_parser.py` | 2723-2725 | Factory method |
| `_build()` | `src/agent/doc_parser.py` | 1094-1122 | 3-phase construction |
| `_detect_articles()` | `src/agent/doc_parser.py` | 1344-1452 | Phase 1: article detection with fallback chain |
| `_find_article_matches()` | `src/agent/doc_parser.py` | 1124-1262 | Primary `ARTICLE` keyword regex |
| `_find_section_toplevel_matches()` | `src/agent/doc_parser.py` | 1264-1300 | `SECTION N` fallback |
| `_find_part_chapter_matches()` | `src/agent/doc_parser.py` | 1302-1342 | Part/Chapter/Clause fallback |
| `_detect_sections()` | `src/agent/doc_parser.py` | 1693-2026 | Phase 2: section detection with multi-strategy merge |
| `_SECTION_STRICT_RE` | `src/agent/doc_parser.py` | 138-140 | Keyword-anchored section regex |
| `_SECTION_BARE_RE` | `src/agent/doc_parser.py` | 148-150 | Bare `X.YY` section regex |
| `_SECTION_STANDALONE_RE` | `src/agent/doc_parser.py` | 200-203 | Number-alone-on-line regex |
| `_SECTION_FLAT_RE` | `src/agent/doc_parser.py` | 191-193 | Flat `N. Heading` regex |
| `_ARTICLE_RE` | `src/agent/doc_parser.py` | 111-113 | Article heading regex |
| `_is_toc_entry()` | `src/agent/doc_parser.py` | 627-722 | 5-signal TOC detection |
| `_is_plausible_section_number()` | `src/agent/doc_parser.py` | 2122-2152 | Section number validation |
| `_enforce_monotonic_sections()` | `src/agent/doc_parser.py` | 2042-2098 | Monotonic ordering filter |
| `section_parser.find_sections()` | `src/agent/section_parser.py` | 261-304 | Legacy fallback (also calls DocOutline) |
| `section_parser._SECTION_RE` | `src/agent/section_parser.py` | 118-123 | Legacy section regex (more restrictive) |
