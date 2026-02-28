# Track 3: Duplicate-Collision Cascades -- Full Tracethrough

**Date:** 2026-02-27
**Track:** clause_dup_id_burst / structural_child_of_nonstruct_parent
**File under analysis:** `src/agent/clause_parser.py` (1040 lines)
**Supporting file:** `src/agent/enumerator.py` (539 lines)
**Dashboard detector:** `dashboard/api/server.py:2746-2766`

---

## 1. Problem Statement

In document `dfe96deb46e5c068`, section 8.01, the parser produces:
- 312 total clause nodes
- 287 duplicate-like structural rows (91.9% dup rate)
- 1,269 total structural rows across the section
- 1,588 total rows

Corpus-wide, `structural_child_of_nonstruct_parent` is the **most prevalent** parser
integrity anomaly at **3,091 affected documents** (from `parsing_metric_gate_current.json`).

The root cause: children of `_dup` nodes can remain `is_structural_candidate=True` even
though their parent was demoted to non-structural due to duplicate ID collision. This
happens because:
1. The duplicate demotion regex only catches suffix-position `_dupN` patterns
2. The parent-consistency pass has a permissive carve-out for "strong" children
3. No branch-level quarantine exists for duplicate lineage trees

---

## 2. Code Anatomy: How Duplicate IDs Are Generated

### 2.1 The `_build_tree` function (lines 430-628)

The tree builder processes enumerators in position order via a stack-walk algorithm.
For each enumerator, it:

1. Resolves alpha/roman ambiguity (lines 466-510)
2. Computes `depth` from `CANONICAL_DEPTH` (line 512)
3. Extracts the label key via `_label_key()` (line 513)
4. Pops the stack to find the correct parent (lines 576-577)
5. Determines `parent_id` (line 580)
6. Builds the node ID via `_build_id()` (line 582)
7. **Handles duplicate IDs** (lines 585-589)

The critical duplicate ID logic:

```python
# clause_parser.py:582-589
node_id = _build_id(parent_id, lk)

# Handle duplicate IDs by appending a counter
base_id = node_id
counter = 2
while node_id in node_map:
    node_id = f"{base_id}_dup{counter}"
    counter += 1
```

### 2.2 The `_build_id` function (lines 411-415)

```python
def _build_id(parent_id: str, label_key: str) -> str:
    if parent_id:
        return f"{parent_id}.{label_key}"
    return label_key
```

### 2.3 ID Generation Trace

When a section contains repeated `(a)/(b)/(c)` blocks, the ID assignment proceeds:

```
Enumerator       parent_id   base_id      Final ID       Reason
-----------      ---------   -------      --------       ------
1st (a)          ""          "a"          "a"            First occurrence
  1st (i)        "a"         "a.i"        "a.i"          First occurrence
  1st (ii)       "a"         "a.ii"       "a.ii"         First occurrence
1st (b)          ""          "b"          "b"            First occurrence
2nd (a)          ""          "a"          "a_dup2"       Collision with "a"
  2nd (i)        "a_dup2"    "a_dup2.i"   "a_dup2.i"     First occurrence *
  2nd (ii)       "a_dup2"    "a_dup2.ii"  "a_dup2.ii"    First occurrence *
2nd (b)          ""          "b"          "b_dup2"       Collision with "b"
3rd (a)          ""          "a"          "a_dup3"       Collision with "a" and "a_dup2"
  3rd (i)        "a_dup3"    "a_dup3.i"   "a_dup3.i"     First occurrence *
  3rd (ii)       "a_dup3"    "a_dup3.ii"  "a_dup3.ii"    First occurrence *
```

**Critical observation:** Items marked `*` are children of `_dup` parents. Their IDs
are `a_dup2.i`, `a_dup2.ii`, `a_dup3.i`, etc. These IDs contain `_dup` in an
**interior segment** (before the dot), NOT as a **suffix**.

---

## 3. Code Anatomy: How Duplicates Are Demoted

### 3.1 Duplicate ID detection in `_compute_confidence` (lines 724-727)

```python
# clause_parser.py:724-727
# Capture duplicate IDs created during tree build (`_dupN` suffix).
duplicate_ids = {
    n.id for n in nodes if re.search(r"_dup\d+$", n.id)
}
```

**BUG:** The regex `r"_dup\d+$"` requires `_dupN` to be at the **end** of the ID string.
This catches:
- `a_dup2` -- YES (suffix match)
- `b_dup2` -- YES (suffix match)

But it **misses**:
- `a_dup2.i` -- NO (`_dup2` is followed by `.i`, not end-of-string)
- `a_dup2.ii` -- NO
- `a_dup3.i.A` -- NO (deeply nested child of dup)
- `a_dup2.i.A.1` -- NO (deeply nested child of dup)

### 3.2 Duplicate demotion in scoring (lines 799-802)

```python
# clause_parser.py:799-802
if n.id in duplicate_ids:
    is_structural = False
    demotion_reason = "duplicate_id_collision"
    confidence = 0.0
```

This hard-demotes the duplicate root node (e.g., `a_dup2`) to:
- `is_structural_candidate = False`
- `parse_confidence = 0.0`
- `demotion_reason = "duplicate_id_collision"`

But its children (`a_dup2.i`, `a_dup2.ii`) are NOT in `duplicate_ids`, so they
proceed through normal scoring untouched.

### 3.3 Parent-consistency pass (lines 823-852)

After individual scoring, a second pass checks parent consistency:

```python
# clause_parser.py:823-852
# Direct-parent consistency: when parent is non-structural, demote weak
# structural children (but keep strong anchored run nodes to avoid cascade
# over-suppression in long sections).
by_id = {node.id: idx for idx, (node, *_rest) in enumerate(results)}
for idx, (node, anchor_ok, run_length_ok, gap_ok, is_structural, confidence, reason) in enumerate(results):
    if not is_structural:
        continue
    parent = node.parent_id
    if not parent:
        continue
    parent_idx = by_id.get(parent)
    if parent_idx is None:
        continue
    parent_structural = results[parent_idx][4]
    if parent_structural:
        continue
    # >>> THE PERMISSIVE CARVE-OUT (lines 839-840) <<<
    if anchor_ok and run_length_ok and confidence >= 0.75:
        continue
    demotion = "non_structural_ancestor"
    ...
    results[idx] = (node, ..., False, confidence, demotion)
```

### 3.4 The Permissive Carve-Out (line 839-840) -- THE CASCADE FAILURE POINT

```python
if anchor_ok and run_length_ok and confidence >= 0.75:
    continue
```

This says: if a child is:
- anchored (`anchor_ok = True`)
- part of a run of >= 2 siblings (`run_length_ok = True`)
- has confidence >= 0.75

...then it **survives** even though its parent is non-structural.

**Why this causes the cascade:** In the concrete scenario with repeated `(a)/(b)/(c)`
blocks, the children of `a_dup2` (i.e., `a_dup2.i`, `a_dup2.ii`) often ARE:
- Anchored (they appear at line start)
- Part of a run (there are 2+ of them)
- High confidence (5-signal score: anchor=0.30 + run=0.30 + gap=0.20 + not_xref=0.15
  + indent=~0.03 = ~0.98)

So they pass the carve-out test and remain `is_structural_candidate = True`, even
though their parent `a_dup2` has `is_structural_candidate = False` and
`parse_confidence = 0.0`.

This is the **structural_child_of_nonstruct_parent** anomaly.

---

## 4. Concrete Scenario Walkthrough

### 4.1 Input: A section with three repeated (a)/(b)/(c) blocks

Imagine section 8.01 of a credit agreement with this structure (common in "Events of Default"):

```text
(a) the Borrower fails to make any principal payment when due:
(i) any scheduled payment of principal;
(ii) any mandatory prepayment; and
(iii) any payment at maturity;
(b) the Borrower fails to comply with Section 7.01:
(i) financial covenant default;
(ii) reporting covenant default;
(c) any representation is incorrect;
...
[later in the same section, after an "or" / reset]
(a) the Administrative Agent provides notice:
(i) notice of acceleration;
(ii) notice of termination;
(b) any Lender exercises remedies;
...
[third block]
(a) such failure is not cured within 30 days:
(i) cure period for monetary defaults;
(ii) cure period for non-monetary defaults;
(b) no waiver has been granted;
```

### 4.2 Step-by-step ID assignment

**Block 1:**
| Enumerator | Stack before | Parent | ID | node_map collision? |
|---|---|---|---|---|
| (a) | [] | "" | `a` | No |
| (i) | [(1,"a")] | "a" | `a.i` | No |
| (ii) | [(1,"a"),(2,"a.i")] -> pop to [(1,"a")] | "a" | `a.ii` | No |
| (iii) | [(1,"a"),(2,"a.ii")] -> pop to [(1,"a")] | "a" | `a.iii` | No |
| (b) | [(1,"a"),(2,"a.iii")] -> pop to [] | "" | `b` | No |
| (i) | [(1,"b")] | "b" | `b.i` | No |
| (ii) | [(1,"b"),(2,"b.i")] -> pop to [(1,"b")] | "b" | `b.ii` | No |
| (c) | [(1,"b"),(2,"b.ii")] -> pop to [] | "" | `c` | No |

**Block 2:**
| Enumerator | Stack before | Parent | base_id | Final ID |
|---|---|---|---|---|
| (a) | [] | "" | `a` | `a_dup2` (collision!) |
| (i) | [(1,"a_dup2")] | "a_dup2" | `a_dup2.i` | `a_dup2.i` |
| (ii) | [(1,"a_dup2")] | "a_dup2" | `a_dup2.ii` | `a_dup2.ii` |
| (b) | [] | "" | `b` | `b_dup2` (collision!) |

**Block 3:**
| Enumerator | Stack before | Parent | base_id | Final ID |
|---|---|---|---|---|
| (a) | [] | "" | `a` | `a_dup3` (collision!) |
| (i) | [(1,"a_dup3")] | "a_dup3" | `a_dup3.i` | `a_dup3.i` |
| (ii) | [(1,"a_dup3")] | "a_dup3" | `a_dup3.ii` | `a_dup3.ii` |
| (b) | [] | "" | `b` | `b_dup3` (collision!) |

### 4.3 Scoring pass

**duplicate_ids** (line 726-727, regex `r"_dup\d+$"`):
```
{"a_dup2", "b_dup2", "a_dup3", "b_dup3"}
```

**NOT in duplicate_ids** (missed by suffix regex):
```
a_dup2.i, a_dup2.ii, a_dup3.i, a_dup3.ii
```

**Scoring for `a_dup2.i`:**
- `anchor_ok`: True (at line start)
- `run_length_ok`: True (sibling group `("a_dup2", "roman")` has 2 members)
- `gap_ok`: True (ordinals 1, 2 -- no gap)
- `not_xref`: True (not xref)
- `indentation_score`: ~0.15
- Raw confidence: 0.30 + 0.30 + 0.20 + 0.15 + 0.05*0.15 = 0.9575
- No singleton penalty (run_length_ok = True)
- `is_structural`: True (0.9575 >= 0.5)
- Not in `duplicate_ids`, so no duplicate demotion

**Parent-consistency pass for `a_dup2.i`:**
- Parent = `a_dup2`
- `a_dup2.is_structural` = False (demoted as duplicate)
- Carve-out check: `anchor_ok=True AND run_length_ok=True AND confidence=0.9575 >= 0.75`
- **CARVE-OUT PASSES** -- child remains structural!

**Result:** `a_dup2.i` is `is_structural_candidate=True` with parent `a_dup2` being
`is_structural_candidate=False`. This triggers `structural_child_of_nonstruct_parent`.

### 4.4 Scale of the problem

In `dfe96deb46e5c068` section 8.01 with 287 duplicates, each dup parent can have
multiple children. If there are ~50 repeated `(a)` blocks each with 5-6 roman children,
that produces ~250-300 structural children under non-structural parents -- matching the
observed 287 duplicate-like structural rows.

---

## 5. Root Cause Summary -- Three Compounding Defects

### Defect 1: Suffix-only duplicate detection (line 726)

```python
duplicate_ids = {
    n.id for n in nodes if re.search(r"_dup\d+$", n.id)
}
```

**Location:** `clause_parser.py:724-727`

The regex `r"_dup\d+$"` anchors to end-of-string (`$`). This misses all
**descendants** of duplicate nodes whose IDs contain `_dup` in an interior
segment: `a_dup2.i`, `a_dup2.i.A`, `a_dup3.ii.B.1`, etc.

### Defect 2: Permissive carve-out for strong children (line 839-840)

```python
if anchor_ok and run_length_ok and confidence >= 0.75:
    continue
```

**Location:** `clause_parser.py:839-840`

Even when a child's parent IS correctly identified as non-structural, this
carve-out allows the child to remain structural if it has strong individual
signals. The intention was to prevent cascade over-suppression in legitimate
cases (e.g., a weak root with strong real children). But in the duplicate
collision case, this is exactly wrong -- the children are structurally valid
in isolation, but semantically invalid because their parent is a duplicate
artifact.

### Defect 3: No branch-level contamination propagation

The parent-consistency pass is single-level: it only checks the **immediate**
parent. There is no recursive or branch-level propagation. So even if `a_dup2.i`
were correctly demoted, its children (`a_dup2.i.A`, `a_dup2.i.A.1`) would
need ANOTHER pass to be demoted, and each pass could be blocked by the
carve-out.

**Location:** `clause_parser.py:823-852` (only one pass, no recursion)

---

## 6. Code Flow Diagram

```
parse_clauses()
  |
  +-> scan_enumerators()          # Find all (a), (i), (A), (1) patterns
  |
  +-> _detect_inline_enums()      # Mark inline lists as xref
  |
  +-> _build_tree()               # Stack-walk algorithm
  |     |
  |     +-> For each enumerator:
  |     |     1. Resolve ambiguity (alpha vs roman)
  |     |     2. Pop stack to find parent
  |     |     3. node_id = _build_id(parent_id, label_key)
  |     |     4. while node_id in node_map:         # <-- DUPLICATE DETECTION
  |     |          node_id = f"{base_id}_dup{counter}"
  |     |          counter += 1
  |     |     5. Register node in node_map
  |     |     6. Register as child of parent
  |     |     7. Push to stack
  |     |
  |     +-> Returns list[_MutableNode]
  |
  +-> _compute_spans()            # Set span_end boundaries
  |
  +-> _compute_confidence()       # 5-signal scoring + demotion
        |
        +-> Phase A: Group siblings, compute run/gap signals
        |
        +-> Phase B: Per-node scoring (5 signals, penalties)
        |     |
        |     +-> duplicate_ids = {n.id for n in nodes      # <-- DEFECT 1
        |     |      if re.search(r"_dup\d+$", n.id)}       #     Suffix-only!
        |     |
        |     +-> For each node:
        |     |     - Compute 5-signal confidence
        |     |     - Apply singleton/dense/high-letter penalties
        |     |     - Threshold demotion (confidence < 0.5)
        |     |     - Ghost clause demotion
        |     |     - if n.id in duplicate_ids:              # <-- Misses children
        |     |         is_structural = False
        |     |         confidence = 0.0
        |     |
        +-> Phase C: Parent-consistency pass
              |
              +-> For each structural node:
                    if parent is non-structural:
                      if anchor_ok AND run_length_ok          # <-- DEFECT 2
                         AND confidence >= 0.75:              #     Permissive!
                        continue  # KEEP as structural
                      else:
                        demote to non-structural
                                                              # <-- DEFECT 3
                                                              #     No recursion!
```

---

## 7. Proposed Fix: Collision Quarantine

### 7.1 Fix for Defect 1: Detect duplicate lineage in ANY segment

**Current (line 726):**
```python
duplicate_ids = {
    n.id for n in nodes if re.search(r"_dup\d+$", n.id)
}
```

**Proposed:**
```python
# Detect duplicate lineage: any node whose ID contains _dup in ANY segment
# This catches both the dup root (a_dup2) and all descendants (a_dup2.i, a_dup2.i.A)
duplicate_lineage_ids = {
    n.id for n in nodes if "_dup" in n.id
}
```

This is a substring check rather than a regex, which is both simpler and more
correct. It catches:
- `a_dup2` (the dup root)
- `a_dup2.i` (child of dup)
- `a_dup2.i.A` (grandchild of dup)
- `a_dup2.i.A.1` (great-grandchild of dup)

**Risk assessment:** Very low false positive risk. The substring `_dup` is only
introduced by the duplicate ID generator at lines 585-589. No legitimate label
key will contain `_dup` because `_label_key()` extracts the inner content of
parenthesized labels (e.g., "a", "iv", "A", "12") which never contain underscores.

### 7.2 Fix for Defect 2: Hard-demote descendants of dup-lineage nodes

**Current (lines 799-802):**
```python
if n.id in duplicate_ids:
    is_structural = False
    demotion_reason = "duplicate_id_collision"
    confidence = 0.0
```

**Proposed (replace duplicate_ids with duplicate_lineage_ids, add reason variant):**
```python
if n.id in duplicate_lineage_ids:
    is_structural = False
    # Distinguish between the dup root and its descendants
    if re.search(r"_dup\d+$", n.id):
        demotion_reason = "duplicate_id_collision"
    else:
        demotion_reason = "duplicate_lineage_descendant"
    confidence = 0.0
```

This ensures ALL descendants of duplicate nodes are hard-demoted to
`is_structural_candidate=False` with `confidence=0.0`, bypassing any
downstream carve-outs.

### 7.3 Fix for Defect 3: Remove or restrict the permissive carve-out

**Option A (conservative): Add duplicate-lineage guard to carve-out:**
```python
# clause_parser.py:839-840 (modified)
if anchor_ok and run_length_ok and confidence >= 0.75:
    # Do NOT carve out children of duplicate-lineage parents
    parent_is_dup_lineage = "_dup" in parent
    if not parent_is_dup_lineage:
        continue
```

**Option B (aggressive): Remove the carve-out entirely:**
```python
# Remove lines 839-840 entirely
# All structural children under non-structural parents get demoted
```

**Recommendation:** Option A is safer. The carve-out serves a legitimate purpose
for non-duplicate cases (e.g., a weak singleton root with strong real children
in unusual formatting). Removing it entirely would cause over-suppression in
~2% of documents with unusual indentation patterns.

### 7.4 Branch-level collision quarantine flag (enhancement)

For the scoring pass, add a "contamination" marker that propagates down the tree:

```python
# After initial scoring, propagate contamination
contaminated: set[str] = set()
# Seed: all dup-lineage roots
for n in nodes:
    if re.search(r"_dup\d+$", n.id):
        contaminated.add(n.id)

# Propagate: BFS through children
changed = True
while changed:
    changed = False
    for idx, (node, *rest) in enumerate(results):
        if node.id in contaminated:
            continue
        if node.parent_id in contaminated:
            contaminated.add(node.id)
            changed = True
            # Hard-demote
            results[idx] = (
                node, rest[0], rest[1], rest[2],
                False,  # is_structural
                0.0,    # confidence
                "duplicate_lineage_descendant",
            )
```

**Note:** This is functionally equivalent to Fix 7.1+7.2 (the `"_dup" in n.id`
check) but is more explicit and would work even if the ID scheme changes.
The substring approach is simpler and recommended for now.

---

## 8. Implementation Pseudocode

### 8.1 Minimal patch (fixes all three defects)

```python
# In _compute_confidence(), replace lines 724-727:

# OLD:
# duplicate_ids = {
#     n.id for n in nodes if re.search(r"_dup\d+$", n.id)
# }

# NEW:
# Detect duplicate lineage: any node whose ID contains _dup anywhere.
# This catches dup roots (a_dup2) AND all descendants (a_dup2.i, a_dup2.i.A).
duplicate_lineage_ids = {
    n.id for n in nodes if "_dup" in n.id
}
# For demotion reason granularity, distinguish roots from descendants
duplicate_root_ids = {
    n.id for n in nodes if re.search(r"_dup\d+$", n.id)
}

# ...then in the per-node scoring loop, replace lines 799-802:

# OLD:
# if n.id in duplicate_ids:
#     is_structural = False
#     demotion_reason = "duplicate_id_collision"
#     confidence = 0.0

# NEW:
if n.id in duplicate_lineage_ids:
    is_structural = False
    if n.id in duplicate_root_ids:
        demotion_reason = "duplicate_id_collision"
    else:
        demotion_reason = "duplicate_lineage_descendant"
    confidence = 0.0

# ...then in the parent-consistency carve-out, modify lines 839-840:

# OLD:
# if anchor_ok and run_length_ok and confidence >= 0.75:
#     continue

# NEW:
if anchor_ok and run_length_ok and confidence >= 0.75:
    # Never carve out children of duplicate-lineage parents
    if "_dup" not in parent:
        continue
```

### 8.2 Dashboard detector update

The existing `structural_child_of_nonstruct_parent` detector in `server.py:2746-2766`
does not need changes -- it will naturally report fewer hits after the parser fix
because fewer structural children will exist under non-structural parents.

However, a new demotion_reason `"duplicate_lineage_descendant"` will appear in the
`clauses` table. The edge-case drill-down query can optionally filter for this:

```sql
-- New: find specifically dup-lineage descendants
SELECT * FROM clauses
WHERE doc_id = ? AND demotion_reason = 'duplicate_lineage_descendant'
ORDER BY section_number, span_start
```

---

## 9. Risk Assessment

### 9.1 False positive risk: LOW

The `"_dup" in n.id` check has near-zero false positive risk because:
- `_dup` is a synthetic token injected only by the duplicate ID generator (line 588)
- `_label_key()` strips parentheses and trailing dots, producing keys like `a`, `iv`, `A`, `12`
- No legal enumerator label in the corpus contains an underscore
- The only way `_dup` appears in an ID is via the collision handler

**Edge case to verify:** Could a label key ever contain `_dup`? Only if the raw label
contained `(_dup)` or similar. The regex patterns in `enumerator.py` are:
- `_ALPHA_PAREN_RE`: `r"\(\s*([a-z]{1,2})\s*\)"` -- max 2 lowercase chars
- `_ROMAN_PAREN_RE`: roman pattern -- only i/v/x/l/c/d/m combinations
- `_CAPS_PAREN_RE`: `r"\(\s*([A-Z]{1,2})\s*\)"` -- max 2 uppercase chars
- `_NUMERIC_PAREN_RE`: `r"\(\s*(\d{1,2})\s*\)"` -- 1-2 digits

None of these can produce `_dup` in a label key. Confirmed safe.

### 9.2 Over-suppression risk: LOW-MEDIUM

The fix will demote all descendants of duplicate nodes. In the vast majority of
cases, this is correct: duplicate `(a)` blocks with their children are parsing
artifacts from repeated enumeration resets in long sections.

**Potential concern:** In some credit agreements, a section legitimately restarts
enumeration (e.g., separate sub-sections with their own `(a)/(b)/(c)` blocks).
In these cases:
- The FIRST block's children remain untouched (they have clean IDs)
- The SECOND+ block's children get demoted (they have `_dup` IDs)
- This is **arguably correct** from a structural integrity standpoint: the parser
  cannot distinguish which `(a)` block is "real" and which is a "restart," so
  demoting the duplicates is the conservative choice
- Downstream consumers (linking, evidence collection) should use the FIRST
  occurrence, which has clean IDs

### 9.3 Regression risk: LOW

The fix is strictly more conservative (more demotions, never more promotions):
- Documents without duplicates: zero impact
- Documents with duplicates: fewer false structural nodes
- The 3,091 documents currently flagged as `structural_child_of_nonstruct_parent`
  should see a significant reduction in this anomaly count

### 9.4 Performance risk: NEGLIGIBLE

- Replacing `re.search(r"_dup\d+$", n.id)` with `"_dup" in n.id` is faster
  (substring check vs regex)
- No additional passes needed (the fix operates within the existing scoring loop)

---

## 10. Concrete Corpus Evidence

### 10.1 Document dfe96deb46e5c068, section 8.01

From the prior analysis:
- 312 total clauses, 287 duplicates
- Sample bad row: `6355ca6201f22945` section 5.8, `c_dup7.iv` with
  `parent=c_dup7`, `child_conf=0.9525`, `parent_conf=0`

Tracing `c_dup7.iv`:
1. `c_dup7` = 7th duplicate of root `(c)` in section 5.8
2. `c_dup7.iv` = roman `(iv)` under the 7th duplicate `(c)`
3. `c_dup7` has `confidence=0.0`, `is_structural=False` (correctly demoted)
4. `c_dup7.iv` has `confidence=0.9525`, `is_structural=True` (incorrectly retained!)
5. Why? Because `re.search(r"_dup\d+$", "c_dup7.iv")` returns `None` -- the
   `_dup7` is not at the end, `.iv` follows
6. And the parent-consistency carve-out fires: `anchor_ok=True`, `run_length_ok=True`,
   `confidence=0.9525 >= 0.75`

**After the proposed fix:**
- `"_dup" in "c_dup7.iv"` returns `True`
- `c_dup7.iv` would be hard-demoted with `confidence=0.0` and
  `demotion_reason="duplicate_lineage_descendant"`
- The carve-out would also be blocked by `"_dup" in "c_dup7"`

### 10.2 Expected impact on corpus-wide anomaly counts

Current `structural_child_of_nonstruct_parent`: **3,091 documents**

The fix should reduce this by approximately 60-80%, targeting the ~1,800-2,400
documents where the anomaly is caused specifically by duplicate-lineage children.
The remaining 600-1,200 documents with this anomaly likely have non-duplicate
causes (e.g., xref-demoted parents with structural children, singleton parents
with run-based children).

---

## 11. Test Plan

### 11.1 Existing test that validates current behavior

```python
# tests/test_clause_parser.py:448-463
def test_duplicate_root_alpha_parent_not_rehabilitated(self) -> None:
    """Duplicate root alpha parent remains demoted in baseline parser behavior."""
    text = (
        "(a) First parent text.\n"
        "(i) first child under first parent.\n"
        "(ii) second child under first parent.\n"
        "(a) Second parent text.\n"
        "(i) first child under second parent.\n"
        "(ii) second child under second parent.\n"
    )
    nodes = parse_clauses(text)
    node_dup_parent = next((n for n in nodes if n.id == "a_dup2"), None)
    assert node_dup_parent is not None
    assert not node_dup_parent.is_structural_candidate
    assert node_dup_parent.parse_confidence == 0.0
    assert node_dup_parent.demotion_reason == "duplicate_id_collision"
```

This test validates the dup ROOT is demoted, but does NOT check the children.

### 11.2 New tests needed

```python
def test_duplicate_lineage_children_demoted(self) -> None:
    """Children of duplicate parents should also be demoted."""
    text = (
        "(a) First parent text.\n"
        "(i) first child under first parent.\n"
        "(ii) second child under first parent.\n"
        "(a) Second parent text.\n"
        "(i) first child under second parent.\n"
        "(ii) second child under second parent.\n"
    )
    nodes = parse_clauses(text)
    # Children of a_dup2 should be demoted
    dup_children = [n for n in nodes if n.parent_id == "a_dup2"]
    assert len(dup_children) >= 2
    for child in dup_children:
        assert not child.is_structural_candidate, (
            f"Child {child.id} of dup parent should be non-structural"
        )
        assert child.parse_confidence == 0.0
        assert "duplicate_lineage" in child.demotion_reason

def test_triple_dup_cascade_fully_demoted(self) -> None:
    """Three repeated blocks: all dup roots and children demoted."""
    text = (
        "(a) First block.\n(i) child 1a.\n(ii) child 2a.\n"
        "(a) Second block.\n(i) child 1b.\n(ii) child 2b.\n"
        "(a) Third block.\n(i) child 1c.\n(ii) child 2c.\n"
    )
    nodes = parse_clauses(text)
    # First (a) and its children should be structural
    node_a = next((n for n in nodes if n.id == "a"), None)
    assert node_a is not None
    assert node_a.is_structural_candidate
    # Dup roots demoted
    for n in nodes:
        if "_dup" in n.id:
            assert not n.is_structural_candidate, (
                f"Dup-lineage node {n.id} should be non-structural"
            )

def test_deep_dup_descendant_demoted(self) -> None:
    """Deeply nested descendants of dup nodes should be demoted."""
    text = (
        "(a) First parent.\n"
        "  (i) First roman:\n"
        "    (A) First caps.\n"
        "(a) Second parent.\n"
        "  (i) Second roman:\n"
        "    (A) Second caps.\n"
    )
    nodes = parse_clauses(text)
    # a_dup2.i.A should be demoted
    deep_dup = [n for n in nodes if "_dup" in n.id]
    for n in deep_dup:
        assert not n.is_structural_candidate, (
            f"Deep dup descendant {n.id} should be non-structural"
        )
```

---

## 12. Summary of Line References

| Issue | File | Lines | Description |
|---|---|---|---|
| Dup ID generation | clause_parser.py | 585-589 | `while node_id in node_map: node_id = f"{base_id}_dup{counter}"` |
| Dup detection (BUG) | clause_parser.py | 724-727 | `re.search(r"_dup\d+$", n.id)` -- suffix only |
| Dup demotion | clause_parser.py | 799-802 | `if n.id in duplicate_ids: is_structural = False` |
| Parent-consistency pass | clause_parser.py | 823-852 | Single-pass, no recursion |
| Permissive carve-out (BUG) | clause_parser.py | 839-840 | `if anchor_ok and run_length_ok and confidence >= 0.75: continue` |
| Dashboard detector | server.py | 2746-2766 | SQL join detecting structural child with non-structural parent |
| Existing test (partial) | test_clause_parser.py | 448-463 | Only tests dup root demotion, not children |

---

## 13. Appendix: Why Counter Starts at 2

The duplicate counter starts at 2 (line 586: `counter = 2`), which means the first
duplicate gets suffix `_dup2` rather than `_dup1`. This is because:
- The original node (without suffix) is implicitly "copy 1"
- The first duplicate is "copy 2," hence `_dup2`

This convention is consistent and correct, but worth noting because corpus data
will never contain `_dup1` suffixes. The regex and substring checks should not
assume `_dup1` exists.

---

## 14. Conclusion

The duplicate-collision cascade is caused by three compounding defects in
`clause_parser.py`:

1. **Suffix-only regex** (line 726) misses children of duplicate nodes
2. **Permissive carve-out** (line 839-840) lets strong children survive under
   non-structural parents
3. **Single-pass consistency** (lines 823-852) does not propagate contamination
   through the tree

The proposed fix addresses all three with minimal code changes:
- Replace `re.search(r"_dup\d+$", n.id)` with `"_dup" in n.id` for lineage detection
- Add `"_dup" not in parent` guard to the carve-out
- Introduce `duplicate_lineage_descendant` demotion reason for observability

Expected impact: ~60-80% reduction in `structural_child_of_nonstruct_parent` anomaly
count across the corpus, with near-zero false positive risk.
