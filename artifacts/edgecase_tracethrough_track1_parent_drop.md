# Track 1: Parent-Drop / xy_parent_loss / high_letter_continuation

## Live Tracethrough and Chain-of-Thought Analysis

**Date:** 2026-02-27
**File under analysis:** `src/agent/clause_parser.py`
**Supporting file:** `src/agent/enumerator.py`

---

## Table of Contents

1. [Failure Mode Summary](#1-failure-mode-summary)
2. [Architecture: How _build_tree Works](#2-architecture-how-_build_tree-works)
3. [High-Letter Continuation Repair Block: Line-by-Line](#3-high-letter-continuation-repair-block)
4. [Tracethrough Case A: Continuation After (a)...(w)](#4-case-a-continuation)
5. [Tracethrough Case B: True Root High Letter](#5-case-b-true-root)
6. [The Decision Divergence Point](#6-decision-divergence)
7. [Confidence-Phase Penalties (Second Line of Defense)](#7-confidence-penalties)
8. [Analysis of Proposed First-Introduced Tracking Algorithm](#8-first-introduced-tracking)
9. [Implementation Sketch](#9-implementation-sketch)
10. [Risk Assessment](#10-risk-assessment)

---

## 1. Failure Mode Summary

**Core bug:** `(x)` / `(y)` tokens are emitted as depth-1 root nodes with `parent_id=''` when they should be nested under a prior alpha parent like `(a)`.

**Concrete failing examples:**
- `d8764d9f5d8da445`, section 2.05: clause `(x)`, `parent_id=''`, text starts "(x) the borrower..." -- continuation-like
- `70c2899aecf31a92`, section 1.01: clause `(x)`, `parent_id=''`, text starts "(x) the remaining weighted average life..."
- `1dfdf70a55a00a9b`, section 2.11: previous deep node `x_dup3.y.ii.A` then root `(m)` -- suggests over-nesting too

**Counter-example (true root):**
- `0584375e25907ea0`, section 6.05: `(x)` and `(y)` as legitimate top-level permitted-item branches in a long enumerated list `(a)...(z)`.

---

## 2. Architecture: How _build_tree Works

### 2.1 Stack-Walk Algorithm Overview

`_build_tree()` (line 430-628) implements a stack-walk algorithm that processes enumerator tokens in position order and builds a tree using a depth-tracking stack.

**Key data structures:**
```
nodes: list[_MutableNode]           # All nodes in creation order
node_map: dict[str, _MutableNode]   # ID -> node lookup
stack: list[tuple[int, str]]        # (depth, node_id) -- ancestry path
last_sibling_at_level: dict[int, str]  # depth -> last label key at that depth
```

**Core loop (lines 461-627):**
For each enumerator token in position order:
1. **Resolve ambiguity** (lines 466-510): If both alpha and roman match at the same position, choose one via `_classify_ambiguous_with_lookahead()`.
2. **Compute depth** (line 512): `depth = CANONICAL_DEPTH.get(chosen.level_type, 1)` -- alpha=1, roman=2, caps=3, numeric=4.
3. **Check xref** (line 514): Is this a cross-reference?
4. **High-letter continuation repair** (lines 528-573): Special handling for `ordinal >= 24` (x=24, y=25, z=26).
5. **Stack pop** (lines 575-577): Pop all stack entries with `depth >= current depth`.
6. **Determine parent** (line 580): `parent_id = forced_parent_id or (stack[-1][1] if stack else "")`.
7. **Build node** (lines 582-618): Create `_MutableNode`, register in maps, push to stack.

### 2.2 The Depth Model

From `enumerator.py` lines 72-77:
```python
CANONICAL_DEPTH: dict[str, int] = {
    LEVEL_ALPHA: 1,    # (a), (b), ..., (z)
    LEVEL_ROMAN: 2,    # (i), (ii), ...
    LEVEL_CAPS: 3,     # (A), (B), ...
    LEVEL_NUMERIC: 4,  # (1), (2), ...
}
```

All alpha-type tokens (`(x)`, `(y)` included) get `depth=1`. This is the fundamental issue: there is no depth distinction between `(a)` and `(x)` -- they are all `alpha` depth 1.

### 2.3 Stack Pop Mechanics

The critical stack-pop at lines 575-577:
```python
# clause_parser.py:575-577
while stack and stack[-1][0] >= depth:
    stack.pop()
```

When `(x)` arrives with `depth=1`, this pops ALL stack entries with depth >= 1, which means ALL entries. After the pop, `stack` is empty, so:

```python
# clause_parser.py:580
parent_id = forced_parent_id or (stack[-1][1] if stack else "")
```

...resolves to `""` (root) unless `forced_parent_id` was set by the high-letter repair block.

---

## 3. High-Letter Continuation Repair Block

This is the existing mitigation for parent-drop, at lines 528-573. Let me trace through it line by line.

### 3.1 Entry Gate (line 528)

```python
# clause_parser.py:528
if chosen.level_type == "alpha" and chosen.ordinal >= 24:
```

**Ordinals:** `x=24`, `y=25`, `z=26` (from `_alpha_ordinal()` in enumerator.py:116-124).

This block ONLY fires for letters x, y, z. Letters like `(w)` (ordinal 23) or earlier are NOT handled.

> **CoT note:** This means if we have (a)...(w) as a continuation list that reaches (w), the repair block does not fire for (w). Only when the list extends past (w) to (x), (y), (z) does the repair engage. This is a design choice -- (w) is considered "normal enough" to not need special handling.

### 3.2 Find Primary Root Alpha (lines 529-535)

```python
# clause_parser.py:529-535
primary_root_alpha: _MutableNode | None = next(
    (
        n for n in nodes
        if n.level_type == "alpha" and n.depth == 1 and n.parent_id == ""
    ),
    None,
)
```

This finds the FIRST root-level alpha node ever created in this section. In a typical section with `(a) ... (b) ... (c) ...`, this would be node `(a)`.

### 3.3 Find Active Root Alpha on Stack (lines 536-543)

```python
# clause_parser.py:536-543
active_root_alpha: _MutableNode | None = None
for stack_depth, stack_node_id in reversed(stack):
    if stack_depth != 1:
        continue
    candidate = node_map.get(stack_node_id)
    if candidate and candidate.level_type == "alpha" and candidate.parent_id == "":
        active_root_alpha = candidate
        break
```

This walks the stack BACKWARDS looking for the most recent depth-1 alpha root. This is crucial -- it tells us which root alpha is "currently active" (i.e., whose body we are inside).

> **CoT critical insight:** The stack at the time `(x)` is processed tells us the ancestry context. If the stack has entries like `[(1, "a"), (2, "a.iii"), (3, "a.iii.B")]`, then `active_root_alpha` = node `a`. But if the stack has already been modified by intervening tokens, or if the stack was popped before this check... wait, no -- the stack pop happens AFTER the repair block (line 575). So the stack still reflects the state from the PREVIOUS token when the repair block runs. This is important.

Actually wait -- let me re-read the code flow. The repair block (lines 528-573) runs BEFORE the stack pop (lines 575-577). So when `(x)` enters:
1. Stack still has entries from previous tokens
2. Repair block reads the stack to find `active_root_alpha`
3. Repair block may set `forced_parent_id`
4. THEN stack pop happens
5. THEN parent is determined from `forced_parent_id` or stack

### 3.4 Root Alpha Ordinal Set and Sparseness Check (lines 544-549)

```python
# clause_parser.py:544-549
root_alpha_ordinals = {
    n.ordinal
    for n in nodes
    if n.level_type == "alpha" and n.depth == 1 and n.parent_id == ""
}
sparse_root_alpha_context = len(root_alpha_ordinals) <= 5
```

This counts how many distinct root-level alpha ordinals exist so far. If <= 5, the context is "sparse" (only a few root branches like (a), (b), (c)).

> **CoT:** In the failure case `d8764d9f5d8da445` section 2.05, if the section has (a) through (w) as root branches, `len(root_alpha_ordinals)` would be 23. So `sparse_root_alpha_context = False`. This is relevant because `_looks_like_inline_high_letter_continuation()` uses it for the `allow_punctuation` flag.

### 3.5 Inline Continuation Heuristic (lines 551-557)

```python
# clause_parser.py:551-557
looks_inline = _looks_like_inline_high_letter_continuation(
    text,
    chosen.position,
    is_anchored=chosen.is_anchored,
    primary_root_anchored=bool(primary_root_alpha and primary_root_alpha.is_anchored),
    allow_punctuation=sparse_root_alpha_context,
)
```

This calls the heuristic function defined at lines 330-366. Let me trace through that function.

#### 3.5.1 _looks_like_inline_high_letter_continuation() (lines 330-366)

```python
def _looks_like_inline_high_letter_continuation(
    text: str,
    pos: int,
    *,
    is_anchored: bool,
    primary_root_anchored: bool,
    allow_punctuation: bool = False,
) -> bool:
```

**Step 1:** Look back 160 chars from position, normalize whitespace.
```python
lookback = text[max(0, pos - 160):pos]
normalized = re.sub(r"\s+", " ", lookback.lower()).rstrip()
```

**Step 2:** Check for recent high-letter marker in lookback:
```python
has_recent_high_letter_marker = bool(
    re.search(r"\(([wxyz])\)\s*[^()]{0,160}$", normalized),
)
```
This detects if there's a prior `(w)`, `(x)`, `(y)`, or `(z)` within 160 chars.

**Step 3:** Check for word connector ("and", "or", "and/or", "provided that", "subject to"):
```python
has_word_connector = bool(_HIGH_LETTER_CONNECTOR_RE.search(normalized))
```
Pattern: `(?:\band\b|\bor\b|\band/or\b|provided\s+that|subject\s+to)\s*$`

**Step 4:** Check for punctuation tail (`,` or `;`):
```python
has_punctuation_tail = bool(_HIGH_LETTER_PUNCT_RE.search(normalized))
has_punctuation_connector = (
    allow_punctuation
    and has_punctuation_tail
    and (has_recent_high_letter_marker or len(lookback_line) >= 60)
)
```

**Step 5:** Gate: must have word connector OR punctuation connector:
```python
if not (has_word_connector or has_punctuation_connector):
    return False
```

**Step 6:** Anchoring checks:
```python
if not is_anchored:
    return True      # Unanchored + connector = inline continuation

if not primary_root_anchored:
    return True      # Root isn't anchored either = inline

# Both anchored: trust word connectors and punctuation connectors
return has_word_connector or has_punctuation_connector
```

### 3.6 Body Length Check (lines 558-564)

```python
# clause_parser.py:558-564
next_pos = len(text)
for future in enumerators:
    if future.position > chosen.position:
        next_pos = future.position
        break
body_len = max(0, next_pos - chosen.match_end)
anchored_long_body = chosen.is_anchored and body_len > 500
```

If the token is anchored (at line start) AND has more than 500 chars before the next enumerator, it's considered a substantive standalone clause.

### 3.7 The Two Repair Branches (lines 566-573)

**THIS IS THE CRITICAL DECISION POINT.**

```python
# clause_parser.py:566-573
if active_root_alpha is not None and stack and stack[-1][0] >= 2:
    forced_parent_id = active_root_alpha.id
elif (
    primary_root_alpha is not None
    and looks_inline
    and not anchored_long_body
):
    forced_parent_id = active_root_alpha.id if active_root_alpha is not None else primary_root_alpha.id
```

**Branch 1 (line 566):** If there's an active root alpha on the stack AND the top of the stack has depth >= 2, force nesting. This catches the case where we're deep inside a clause tree (e.g., inside `(a)(iii)(B)`) and a `(x)` appears.

**Branch 2 (lines 568-573):** If there's a primary root alpha, the token LOOKS inline (per the heuristic), and it does NOT have an anchored long body, force nesting.

**If NEITHER branch fires:** `forced_parent_id` remains `""`, and after stack pop, `(x)` becomes root.

---

## 4. Tracethrough Case A: Continuation After (a)...(w) -- SHOULD BE NESTED

### Scenario: `d8764d9f5d8da445`, section 2.05

Imagine a section like:
```
(a) The Borrower shall...
  (i) first sub-clause;
  (ii) second sub-clause;
(b) The Agent may...
...
(w) final enumerated item; and
(x) the borrower shall notify the Administrative Agent...
```

**Token: `(x)` at line start**

1. **Entry gate (line 528):** `level_type="alpha"`, `ordinal=24` >= 24. **FIRES.**

2. **primary_root_alpha (line 529-535):** Finds `(a)` node. **EXISTS.**

3. **active_root_alpha (lines 536-543):** The stack at this point -- what is on it?
   - After processing `(w)`, stack was pushed with `(1, "w")`.
   - So stack = `[(1, "w")]` (or maybe the stack has been modified by intervening children of `(w)`).
   - Walking backwards: `stack[-1] = (1, "w")`. Depth is 1. Check: `candidate.level_type == "alpha" and candidate.parent_id == ""`. Node `w` is root alpha. So `active_root_alpha = node_w`.
   - Wait -- node `w` has `parent_id == ""` (it's a root node). So yes, `active_root_alpha = w`.

4. **root_alpha_ordinals (line 544):** Contains ordinals 1 through 23 (a through w). `len = 23`. `sparse_root_alpha_context = False`.

5. **looks_inline (line 551):**
   - Lookback 160 chars: includes text from end of `(w)` clause
   - `has_recent_high_letter_marker`: yes, `(w)` is in the lookback (ordinal 23, but regex checks for `[wxyz]` -- `w` matches)
   - `has_word_connector`: checks for "and", "or", etc. at end of lookback. If `(w)` ends with "; and" then yes. If it ends with just ";" then no word connector.
   - `allow_punctuation = False` (since `sparse_root_alpha_context = False`, len=23 > 5)
   - `has_punctuation_connector = False` (allow_punctuation is False)

   **Sub-case A1: (w) ends with "; and":**
   - `has_word_connector = True`
   - `is_anchored`: `(x)` is at line start, so `True`
   - `primary_root_anchored`: `(a)` is at line start, so `True`
   - Both anchored: returns `has_word_connector or has_punctuation_connector` = `True`
   - **`looks_inline = True`**

   **Sub-case A2: (w) ends with ";" only (no word connector):**
   - `has_word_connector = False`
   - `has_punctuation_connector = False` (allow_punctuation is False)
   - **Returns `False`. `looks_inline = False`.**

6. **anchored_long_body (line 564):** `(x)` is anchored at line start. Body length depends on text between `(x)` match end and next enumerator. If body > 500 chars, `anchored_long_body = True`.

7. **Branch evaluation (lines 566-573):**

   **Branch 1 check:** `active_root_alpha is not None` (yes, = node_w) AND `stack` (yes, has entries) AND `stack[-1][0] >= 2`.

   BUT: `stack[-1] = (1, "w")`. `stack[-1][0] = 1`. **1 >= 2 is FALSE.** Branch 1 does NOT fire.

   > **CoT critical finding:** Branch 1 requires the stack top to have depth >= 2, meaning we must be inside a roman/caps/numeric child. If the last token was a root-level alpha like `(w)`, the stack top is depth 1, so Branch 1 fails.

   **Branch 2 check:** `primary_root_alpha is not None` (yes) AND `looks_inline` AND `not anchored_long_body`.

   - In Sub-case A1 ("; and" connector): `looks_inline = True`. If body < 500: `not anchored_long_body = True`. **Branch 2 FIRES.** `forced_parent_id = active_root_alpha.id = "w"`.
   - In Sub-case A2 (";" only): `looks_inline = False`. **Branch 2 does NOT fire.**
   - If body > 500 chars: `anchored_long_body = True`. **Branch 2 does NOT fire.**

### Case A Verdict

The existing repair ONLY catches continuations that have a word connector ("and", "or", etc.) in the 160-char lookback before `(x)`. If the prior clause `(w)` ends with just a semicolon (very common in legal enumerated lists: `(w) item w;`), the repair does NOT fire, and `(x)` becomes root.

**Root cause of parent-drop in Case A:** The heuristic `_looks_like_inline_high_letter_continuation()` requires word connectors but the typical legal pattern `(w) item; (x) continuation` uses only semicolons with no word connector. And `allow_punctuation=False` because there are > 5 root alpha ordinals (the section has `(a)` through `(w)`, so 23 ordinals).

**The allow_punctuation flag is gated on `sparse_root_alpha_context` (<=5 root ordinals).** A section with a long enumerated list has MANY root ordinals, so `allow_punctuation` is always False, and semicolons alone cannot trigger the continuation repair. This is exactly the paradox: the more ordinals a section has (making `(x)` more likely to be a continuation), the LESS likely the repair is to fire.

---

## 5. Tracethrough Case B: True Root High Letter -- SHOULD STAY ROOT

### Scenario: `0584375e25907ea0`, section 6.05 (Permitted Items)

```
(a) first permitted item;
(b) second permitted item;
...
(w) twenty-third permitted item;
(x) twenty-fourth permitted item;
(y) twenty-fifth permitted item;
```

Each item is a standalone branch at root level. `(x)` and `(y)` are legitimate roots.

1. **Entry gate (line 528):** Fires (ordinal >= 24).

2. **primary_root_alpha:** Exists (node `a`).

3. **active_root_alpha:** Stack top is `(1, "w")` -- node `w` is root alpha. So `active_root_alpha = w`.

4. **root_alpha_ordinals:** Ordinals 1-23. `sparse_root_alpha_context = False`.

5. **looks_inline:**
   - Lookback includes end of `(w)` clause.
   - Each item typically ends with ";" -- no word connector.
   - `allow_punctuation = False` (23 ordinals > 5).
   - **`looks_inline = False`**.

6. **Branch 1 (line 566):** `stack[-1][0] = 1`, not >= 2. **Does not fire.**

7. **Branch 2 (line 568-573):** `looks_inline = False`. **Does not fire.**

8. **Result:** `forced_parent_id = ""`. After stack pop, `parent_id = ""`. **(x) stays root. CORRECT.**

### Case B Verdict

The current code correctly leaves `(x)` as root when it's a true member of a long enumerated list. The repair does not fire because there's no word connector and `allow_punctuation` is False.

---

## 6. The Decision Divergence Point

### The Paradox

Case A (should nest) and Case B (should stay root) are nearly identical from the parser's perspective:
- Both have many root alpha ordinals
- Both have `(x)` at line start (anchored)
- Both have `(w)` as the preceding token
- Both have `sparse_root_alpha_context = False`

The ONLY difference the current code can detect is:
- **Word connector before (x):** If "(w) ... and (x)", the repair fires. If "(w) ...; (x)", it does not.

But in real documents:
- Continuation case: `(w) twenty-third condition;` then newline `(x) the borrower shall...` -- no word connector
- True root case: `(w) twenty-third permitted item;` then newline `(x) twenty-fourth permitted item;` -- also no word connector

These are **structurally indistinguishable** by the current heuristic. Both fail the `looks_inline` check identically.

### Where the decision SHOULD diverge (but does not)

The key insight is: **in the continuation case, `(a)` through `(w)` were already emitted as root-level peers INCORRECTLY because the section only has ONE real enumerated list, and `(x)` is part of that same list.** Both cases look the same from the stack perspective.

Wait -- actually, re-reading the failure examples more carefully:

- `d8764d9f5d8da445`, section 2.05, clause `(x)`, text "(x) the borrower..." -- this is a continuation-like clause

The distinction might be:
1. In a true root case like 6.05 Permitted Items, EVERY letter from (a) to (z) is present as a root-level item
2. In a continuation/parent-drop case, `(x)` appears AFTER a deep nesting context (e.g., `(a)(i)(A)(1)...`) and there are fewer root-level letters -- the high letters are actually sub-items that the parser promotes to root because of stack mechanics

Let me re-examine the `1dfdf70a55a00a9b` example: section 2.11, previous deep node `x_dup3.y.ii.A` then root `(m)`. This tells us:
- There were DEEP nestings involving `x` and `y` as sub-labels
- Then suddenly `(m)` appears as root
- The `x` in `x_dup3` is being used as a sub-clause label AND (potentially) as a root label -- duplicate collision

### The Real Divergence Signal: Continuity of the Alpha Run

In true root case (6.05):
- We see (a), (b), (c), ..., (w), (x), (y) -- a CONTINUOUS sequence with no gaps
- All are at the same structural level

In continuation/parent-drop case (2.05):
- We might see (a) with deep children, then (b) with children, etc.
- The letters x, y appear inline within clauses or as deep children
- When they get promoted to root, there's an ordinal GAP (e.g., jump from (e) to (x))

**THIS is the signal the "first-introduced tracking" algorithm should capture.**

---

## 7. Confidence-Phase Penalties (Second Line of Defense)

Even when the tree-building phase emits `(x)` as root, the confidence scoring phase (lines 675-854) applies penalties:

### 7.1 Root High-Letter Penalty (lines 774-780)

```python
# clause_parser.py:774-780
if (
    n.level_type == "alpha"
    and n.parent_id == ""
    and n.ordinal >= 24
    and not anchor_ok
):
    confidence *= _ROOT_HIGH_LETTER_PENALTY  # 0.60
```

This penalty ONLY applies when the token is NOT anchored. If `(x)` is at line start (anchored), this penalty does NOT fire. In many of our failure cases, `(x)` IS at line start.

### 7.2 Root High-Letter with Low Reset (lines 730-744, 781-782)

```python
# clause_parser.py:730-744
root_high_letter_with_low_reset_ids: set[str] = set()
root_alphas_by_pos = sorted(
    [n for n in nodes if n.level_type == "alpha" and n.parent_id == "" and n.ordinal > 0],
    key=lambda n: n.span_start,
)
for idx, node in enumerate(root_alphas_by_pos):
    if node.ordinal < 24:
        continue
    for follower in root_alphas_by_pos[idx + 1: idx + 9]:
        if follower.ordinal <= 5:
            root_high_letter_with_low_reset_ids.add(node.id)
            break
```

This detects the pattern: root `(x)` followed by root `(a)` or `(b)` nearby. If a low-ordinal root alpha follows a high-ordinal one, the high one gets an additional 0.55 multiplier (line 782). This catches cases where `(x)` appears as root, then `(a)` resets (indicating `(x)` was probably inline in the previous clause).

### 7.3 Confidence Threshold

```python
# clause_parser.py:785
is_structural = confidence >= 0.5
```

After all penalties, if confidence drops below 0.5, the node is demoted. But an anchored `(x)` with a sibling run starts at confidence:
- `_WEIGHT_ANCHOR * 1.0 = 0.30`
- `_WEIGHT_RUN * 1.0 = 0.30` (if `(y)` follows)
- `_WEIGHT_GAP * 1.0 = 0.20` (if no ordinal gap > 5... but gap from (w)=23 to (x)=24 is just 1)
- `_WEIGHT_NOT_XREF * 1.0 = 0.15`
- `_WEIGHT_INDENT * indent_score`
- Total: ~0.95+ before penalties

Even with `_ROOT_HIGH_LETTER_PENALTY` (0.60x), that gives 0.57, which is ABOVE 0.50. So it stays structural.

And if it IS anchored, the 0.60 penalty doesn't even fire.

**Verdict: The confidence phase is NOT a reliable safety net for this failure mode.**

---

## 8. Analysis of Proposed First-Introduced Tracking Algorithm

### 8.1 Core Concept

Track which alpha letter is introduced first within a section. If `(a)` is introduced first at root level and has children, then `(x)` appearing later should be nested under the most recent root alpha, not promoted to root itself.

### 8.2 What "First Introduced" Means

In a true root case like 6.05 Permitted Items:
```
(a) first item;
(b) second item;
...
(x) twenty-fourth item;
```
Here, `(a)` is introduced first AND `(x)` is introduced as a continuation of the SAME enumerated list. The alpha run is CONTINUOUS: ordinals 1, 2, 3, ..., 23, 24 with no gaps.

In a continuation/parent-drop case like 2.05:
```
(a) Main clause:
  (i) sub-clause;
    (A) sub-sub;
      (1) detail;
...
(b) Another main clause:
  (i) sub-clause;
...
(x) the borrower shall...  <-- should be nested
```
Here, `(a)` is introduced first, but `(x)` appears after a DISCONTINUOUS jump. Between the last root alpha ordinal and `x=24`, there are missing ordinals.

### 8.3 The Real Signal: Ordinal Continuity

The most reliable signal is NOT "first introduced" per se, but **ordinal continuity of the root-level alpha run**.

A "first-introduced" tracker should actually be an "ordinal-gap detector":
- If the root alpha sequence is `{1, 2, 3, ..., n}` and `(x)` has ordinal 24, check whether ordinals `n+1` through `23` have been seen as root
- If the sequence is CONTINUOUS up to 23 and `(x)` is 24, it's a legitimate continuation -> stay root
- If the sequence jumps (e.g., last root alpha is ordinal 5 and `(x)` is ordinal 24), it's suspicious -> nest

### 8.4 Concrete Data Structure

```python
# In _build_tree(), add at initialization:
root_alpha_max_contiguous: int = 0  # highest ordinal in a contiguous run from (a)
root_alpha_ordinals_seen: set[int] = set()  # all root-alpha ordinals seen so far
```

Update after each root alpha node is created:
```python
if node.level_type == "alpha" and node.depth == 1 and node.parent_id == "":
    root_alpha_ordinals_seen.add(node.ordinal)
    # Recompute contiguous max
    while root_alpha_max_contiguous + 1 in root_alpha_ordinals_seen:
        root_alpha_max_contiguous += 1
```

### 8.5 Decision Logic

When `(x)` (ordinal 24) arrives:
```python
# Instead of the current sparse_root_alpha_context check:
ordinal_gap = chosen.ordinal - root_alpha_max_contiguous
if ordinal_gap > 1:
    # Large gap: (x) is NOT a continuation of a contiguous list
    # It's likely an inline continuation or sub-clause -> nest under parent
    forced_parent_id = active_root_alpha.id if active_root_alpha else primary_root_alpha.id
elif ordinal_gap == 1:
    # (x) = 24 and max_contiguous = 23 (i.e., (w) was last)
    # This IS a continuation -> stay root
    pass  # no forced_parent_id
```

### 8.6 How It Handles True Root Without False Positives

**True root case (6.05):**
- Root alphas: (a)=1, (b)=2, ..., (w)=23
- `root_alpha_max_contiguous = 23`
- `(x)` ordinal = 24. Gap = 24 - 23 = 1.
- Decision: gap == 1, so STAY ROOT. **CORRECT.**

**Continuation case (2.05) with sparse roots:**
- Root alphas: (a)=1, (b)=2, (c)=3 -- only 3 roots
- `root_alpha_max_contiguous = 3`
- `(x)` ordinal = 24. Gap = 24 - 3 = 21.
- Decision: gap > 1, so NEST. **CORRECT.**

**Continuation case with moderately many roots:**
- Root alphas: (a)=1, (b)=2, ..., (h)=8 -- 8 roots
- `root_alpha_max_contiguous = 8`
- `(x)` ordinal = 24. Gap = 24 - 8 = 16.
- Decision: gap > 1, so NEST. **CORRECT.**

### 8.7 Edge Cases of the Fix Itself

**Edge Case 1: Non-contiguous legitimate list**

Some credit agreements have gaps in enumerated lists (reserved items):
```
(a) first item;
(b) second item;
(c) [reserved];
(d) fourth item;
...
(x) twenty-fourth item;
```

If `(c)` is marked as reserved and excluded by ghost-clause filtering, `root_alpha_ordinals_seen` would have `{1, 2, 4, 5, ...}` -- but `root_alpha_max_contiguous` would stop at 2 because ordinal 3 is missing. Gap from 2 to 24 = 22. The fix would INCORRECTLY nest `(x)`.

**Mitigation:** Use a relaxed contiguity check. Instead of strict contiguity, allow gaps up to 2 (for reserved items): `while root_alpha_max_contiguous + 1 in root_alpha_ordinals_seen or root_alpha_max_contiguous + 2 in root_alpha_ordinals_seen: ...`

Or use the MAX ordinal in root_alpha_ordinals_seen, not the max contiguous:
```python
max_root_ordinal = max(root_alpha_ordinals_seen) if root_alpha_ordinals_seen else 0
ordinal_gap = chosen.ordinal - max_root_ordinal
```

This is simpler and handles gaps. If we've seen ordinals up to 23, the gap is 1 regardless of internal gaps.

**Edge Case 2: Re-entrant alpha at same level**

Some sections have MULTIPLE enumerated lists at root level:
```
The Borrower shall comply with:
(a) first group item;
(b) second group item;

In addition:
(a) first additional item;
(b) second additional item;
```

The parser creates `a_dup2`, `b_dup2` etc. for the second list. `root_alpha_ordinals_seen` would see ordinal 1 twice. This doesn't break the gap calculation because we're using a set.

**Edge Case 3: Mixed level_type roots**

If a section has roman numerals at root level too (e.g., `(i)` classified as roman at depth 2 but emitted at root because stack was empty), the tracker only counts `level_type == "alpha"` roots. This is correct -- we only care about the alpha sequence.

**Edge Case 4: (x) as roman numeral 10**

`(x)` can also be interpreted as roman numeral 10 (= `x`). The disambiguation at lines 486-499 checks if `(x)` should be alpha or roman. If classified as roman, `depth = 2`, and the high-letter repair block doesn't fire (`chosen.level_type != "alpha"`). This is handled correctly -- the repair block only processes alpha-classified tokens.

**Edge Case 5: Double-letter extensions**

After `(z)` = ordinal 26, some lists continue with `(aa)` = ordinal 27, `(bb)` = 28, etc. The repair block checks `ordinal >= 24`, so `(aa)` = 27 would also trigger. The gap check would work: if max_root_ordinal = 26 (z was root), gap = 1, stay root.

**Edge Case 6: (x) appears before (a)**

In some unusual documents, high letters might appear before low letters. With the tracking approach:
- `root_alpha_ordinals_seen = {}`, `max_root_ordinal = 0`
- `(x)` ordinal 24, gap = 24. Would nest -- but under whom? There's no `active_root_alpha` or `primary_root_alpha` yet.
- Falls through both branches since `primary_root_alpha is None`. Stays root. **CORRECT.**

---

## 9. Implementation Sketch

### 9.1 Initialization (add near line 451)

```python
# After line 451 in _build_tree():
# Track 1 fix: ordinal gap detection for high-letter parent-drop
root_alpha_ordinals_seen: set[int] = set()
```

### 9.2 Update After Node Creation (add near line 621)

```python
# After line 621 (after last_sibling_at_level[depth] = lk):
# Track 1 fix: update root alpha ordinal tracker
if node.level_type == "alpha" and node.depth == 1 and node.parent_id == "":
    root_alpha_ordinals_seen.add(node.ordinal)
```

### 9.3 Modified Repair Block (replace lines 566-573)

```python
# Compute ordinal gap from existing root alpha run
max_root_ordinal = max(root_alpha_ordinals_seen) if root_alpha_ordinals_seen else 0
ordinal_gap = chosen.ordinal - max_root_ordinal

# Branch 1: Currently deep in a sub-tree -> always nest
if active_root_alpha is not None and stack and stack[-1][0] >= 2:
    forced_parent_id = active_root_alpha.id

# Branch 2 (NEW): Large ordinal gap -> nest unless overridden
elif ordinal_gap > 1 and primary_root_alpha is not None:
    # (x) is NOT the next expected ordinal in a contiguous list.
    # This strongly suggests it's an inline continuation, not a true root.
    # But still respect anchored long body as an escape hatch.
    if not anchored_long_body:
        forced_parent_id = (
            active_root_alpha.id
            if active_root_alpha is not None
            else primary_root_alpha.id
        )

# Branch 3 (existing): Inline heuristic for gap==1 cases
elif (
    primary_root_alpha is not None
    and looks_inline
    and not anchored_long_body
):
    forced_parent_id = (
        active_root_alpha.id
        if active_root_alpha is not None
        else primary_root_alpha.id
    )
```

### 9.4 Pseudocode Summary

```
FUNCTION _build_tree(enumerators, text, ...):
    ...existing init...
    root_alpha_ordinals_seen = {}  # NEW

    FOR each enumerator token:
        ...existing disambiguation...

        IF token is alpha AND ordinal >= 24:
            ...find primary_root_alpha, active_root_alpha...
            ...compute looks_inline, anchored_long_body...

            max_root = MAX(root_alpha_ordinals_seen) or 0  # NEW
            gap = token.ordinal - max_root                  # NEW

            IF active_root on stack AND stack top depth >= 2:
                forced_parent = active_root  # deep context
            ELIF gap > 1 AND primary_root EXISTS AND NOT anchored_long_body:  # NEW
                forced_parent = active_root or primary_root  # gap = nest
            ELIF primary_root EXISTS AND looks_inline AND NOT anchored_long_body:
                forced_parent = active_root or primary_root  # inline heuristic

        ...stack pop...
        parent = forced_parent or stack top or ""
        ...build node...

        IF node is root alpha:                              # NEW
            root_alpha_ordinals_seen.ADD(node.ordinal)      # NEW
```

---

## 10. Risk Assessment

### 10.1 Regression Risk: LOW-MEDIUM

The fix adds a NEW nesting branch (ordinal gap > 1) that only fires for `ordinal >= 24` tokens. Existing behavior for:
- True root long lists (gap == 1): **UNCHANGED** -- falls through to existing Branch 3
- Non-high-letter tokens: **UNCHANGED** -- repair block doesn't fire
- Tokens with `anchored_long_body`: **UNCHANGED** -- escape hatch preserved

### 10.2 False Positive Risk: LOW

The main false positive scenario is a legitimate root list with a gap (e.g., `(a)` through `(e)`, then reserved items, then `(x)` as a legitimate root). This is VERY rare in practice. And even if it fires incorrectly, the `anchored_long_body` escape hatch (body > 500 chars) would catch most substantive standalone clauses.

### 10.3 False Negative Risk: MEDIUM

The fix still misses cases where:
- The gap is exactly 1 (max root ordinal = 23 = (w), and (x) = 24 is a continuation)
- This happens when the section has a FULL (a)...(w) root list AND (x) is a continuation

These gap-1 cases fall through to the existing Branch 3 (inline heuristic), which requires word connectors. This is the SAME limitation as the current code for this specific sub-case.

### 10.4 Testing Strategy

1. **Unit test for gap detection:** Section with (a), (b), (c) then (x) -- should nest
2. **Unit test for contiguous list:** Section with (a) through (x) -- should stay root
3. **Unit test for gap with anchored long body:** Section with (a), (b) then (x) with 600-char body -- should stay root
4. **Regression test against existing gold fixtures:** Run the guardrail script `edge_case_clause_parent_guardrail.py`
5. **Shadow run on corpus:** Re-parse and compare parent_id distributions

### 10.5 Interaction with Confidence Phase

The confidence phase penalties (Section 7) remain as a second line of defense. The `root_high_letter_with_low_reset_ids` check (lines 730-744) still catches cases where a high-letter root is followed by a low-ordinal reset. These two mechanisms are complementary and do not conflict.

### 10.6 Alternative Approaches Considered

1. **Always nest (x) under nearest root alpha:** Too aggressive. Breaks true root lists.
2. **Use indentation as signal:** HTML/text indentation is unreliable in EDGAR filings.
3. **Look at clause body content:** Too expensive and fragile for the parser core.
4. **Use the `allow_punctuation` flag more liberally:** Would cause false positives in true root lists where semicolons separate items.
5. **Machine learning classifier:** Overkill for the parser core; better suited for post-processing.

### 10.7 Recommended Approach

The ordinal gap check (Section 9.3) is the cleanest fix with the best precision/recall tradeoff. It:
- Uses structural information already available in the builder
- Has a clear mathematical definition (gap > 1)
- Handles the true-root case correctly (gap == 1)
- Has a safe escape hatch (anchored long body)
- Adds minimal complexity to the existing code
- Is easy to test with synthetic inputs

---

## Appendix A: Key Line References

| Line(s) | File | Description |
|---------|------|-------------|
| 49 | clause_parser.py | `_ROOT_HIGH_LETTER_PENALTY = 0.60` |
| 52 | clause_parser.py | `_AMBIGUOUS_ROMAN` frozenset (includes "x") |
| 72-77 | enumerator.py | `CANONICAL_DEPTH` (alpha=1, roman=2, caps=3, numeric=4) |
| 116-124 | enumerator.py | `_alpha_ordinal()` (x=24, y=25, z=26) |
| 330-366 | clause_parser.py | `_looks_like_inline_high_letter_continuation()` |
| 430-628 | clause_parser.py | `_build_tree()` main function |
| 512 | clause_parser.py | `depth = CANONICAL_DEPTH.get(chosen.level_type, 1)` |
| 515 | clause_parser.py | `forced_parent_id = ""` initialization |
| 528 | clause_parser.py | High-letter repair entry gate: `ordinal >= 24` |
| 529-535 | clause_parser.py | Find `primary_root_alpha` (first root alpha ever) |
| 536-543 | clause_parser.py | Find `active_root_alpha` (most recent root alpha on stack) |
| 544-549 | clause_parser.py | `root_alpha_ordinals` set, `sparse_root_alpha_context` |
| 551-557 | clause_parser.py | `looks_inline` heuristic call |
| 558-564 | clause_parser.py | `anchored_long_body` check (>500 chars) |
| 566-567 | clause_parser.py | Branch 1: deep stack context -> nest |
| 568-573 | clause_parser.py | Branch 2: inline heuristic + not long body -> nest |
| 575-577 | clause_parser.py | Stack pop: `while stack[-1][0] >= depth` |
| 580 | clause_parser.py | Parent resolution: `forced_parent_id or stack[-1][1]` |
| 730-744 | clause_parser.py | Confidence: `root_high_letter_with_low_reset_ids` |
| 774-780 | clause_parser.py | Confidence: `_ROOT_HIGH_LETTER_PENALTY` (unanchored only) |
| 785 | clause_parser.py | Structural threshold: `confidence >= 0.5` |

## Appendix B: Existing Test Coverage

| Test | File | Line | Covers |
|------|------|------|--------|
| `test_x_as_alpha_via_lookahead_y` | test_clause_parser.py | 241 | (u)(x)(y) alpha run continuity |
| `test_x_midline_after_and_gets_nested` | test_clause_parser.py | 274 | Inline (x) after "and" -> nested |
| `test_x_at_line_start_with_long_body_stays_root` | test_clause_parser.py | 285 | Anchored (x) with long body -> root |
| `test_semicolon_only_boundary_does_not_force_nesting` | test_clause_parser.py | 298 | (a)(b)(c)(x)(y) with ";" -> root |
| `test_parent_guardrail_fails_on_xy_parent_loss_regression` | test_edge_case_clause_parent_guardrail.py | 74 | Guardrail detects xy parent-loss |

## Appendix C: The `allow_punctuation` Paradox

The `sparse_root_alpha_context` variable (line 549) controls `allow_punctuation` in the inline heuristic. The paradox:

- **When `(x)` is most likely to be a continuation** (few root alphas, e.g., only `(a)` and `(b)` as roots), `sparse_root_alpha_context = True`, so `allow_punctuation = True`. The heuristic CAN fire on semicolons.
- **When `(x)` is also likely to be a continuation** (moderate root alphas, e.g., `(a)` through `(h)`), `sparse_root_alpha_context = False` (8 > 5), so `allow_punctuation = False`. The heuristic CANNOT fire on semicolons.

The threshold of 5 is too low. But raising it risks breaking true root lists. The ordinal gap approach (Section 9) sidesteps this issue entirely by using a different signal.
