# Track 5: Depth-Reset Cascades -- Full Tracethrough

Date: 2026-02-27
Track: `clause_depth_reset_after_deep` / ordinal spike behavior
Analyst: Claude (CoT trace session)

## 1. Executive Summary

Depth-reset cascades occur when the clause parser jumps from a deep nesting level
(depth 4, e.g., `a.i.A.1`) directly back to a root-level alpha node (depth 1, e.g.,
`(m)`). The parser's stack-pop algorithm does not distinguish between a legitimate new
root-level enumeration and an artifact caused by the parser losing context after deep
nesting.

**Baseline metrics** (from `data/quality/edge_case_clause_guardrail_baseline.json`):
- 8 docs flagged
- 8 flagged sections total
- 19 total resets
- Max 4 resets per doc

**Root cause**: The stack-pop loop at `clause_parser.py:576` unconditionally pops all
stack entries with `depth >= current_depth`. For a root-level alpha node (depth=1),
this pops the entire stack, and the node lands at root with `parent_id=""`. There is no
continuity check, no ordinal-sequence validation, and no depth-delta heuristic to
flag the jump as anomalous during tree construction.

**Interaction with Track 1 (parent-drop)**: When the high-letter continuation repair
(lines 528-573) fails to activate because the label ordinal is < 24 (i.e., `m`=13 is
below the `>= 24` threshold), mid-alphabet resets are uncaught. The parent-drop repair
only covers `x/y/z` (ordinals 24-26). Depth-reset for labels `m` through `w` is an
entirely independent failure mode.

---

## 2. Code Architecture: The Stack-Pop Mechanism

### 2.1 Key data structures in `_build_tree`

**File**: `src/agent/clause_parser.py:430-628`

```
nodes: list[_MutableNode]      -- accumulator of all created nodes
node_map: dict[str, _MutableNode] -- lookup by node ID
stack: list[tuple[int, str]]   -- (depth, node_id) pairs representing the active ancestor chain
last_sibling_at_level: dict[int, str] -- last label seen at each depth level
```

The stack represents the "path from root to current node." When a new enumerator is
encountered, the parser pops the stack to find the appropriate parent.

### 2.2 The stack-pop loop (lines 575-577)

```python
# Pop stack until we find a node with depth < current depth
while stack and stack[-1][0] >= depth:
    stack.pop()
```

This is the single line responsible for depth-reset behavior. When `depth=1` (alpha),
EVERY stack entry is popped because all entries have depth >= 1.

### 2.3 Parent assignment (line 580)

```python
parent_id = forced_parent_id or (stack[-1][1] if stack else "")
```

After the stack is fully emptied, `stack` is `[]`, so `parent_id = ""` (root).

### 2.4 Depth assignment (line 512)

```python
depth = CANONICAL_DEPTH.get(chosen.level_type, 1)
```

`CANONICAL_DEPTH` is defined in `src/agent/enumerator.py:72-77`:
```python
CANONICAL_DEPTH = {
    "alpha": 1,
    "roman": 2,
    "caps":  3,
    "numeric": 4,
}
```

Alpha is always depth 1. The parser does not consider whether an alpha label might be
nested under another alpha -- it always assigns depth 1 unconditionally.

---

## 3. High-Letter Continuation Guard (lines 528-573)

This guard ONLY activates for `chosen.ordinal >= 24` -- that is, labels `(x)`, `(y)`,
`(z)`. Its purpose is to detect inline continuations and force them under an existing
root-alpha parent.

```python
if chosen.level_type == "alpha" and chosen.ordinal >= 24:   # line 528
```

**Critical gap**: Letters `(m)` through `(w)` (ordinals 13-23) are NOT covered by this
guard. When these labels appear after a deep nesting chain, they always fall through to
the default stack-pop path, which unconditionally places them at root.

The guard has two sub-paths:

**Path A** (line 566): Active subtree context
```python
if active_root_alpha is not None and stack and stack[-1][0] >= 2:
    forced_parent_id = active_root_alpha.id
```
Activates when there's a depth-2+ node on the stack -- i.e., we're currently inside a
deep subtree and seeing `(x/y/z)`. Forces nesting under the active root alpha.

**Path B** (line 568-573): Inline continuation context
```python
elif (
    primary_root_alpha is not None
    and looks_inline
    and not anchored_long_body
):
    forced_parent_id = active_root_alpha.id if active_root_alpha is not None else primary_root_alpha.id
```
Activates when text lookback suggests inline continuation (connectors like "and",
"or", "provided that", punctuation).

---

## 4. Concrete Scenario Trace: Gold Fixture `depth_reset_anomaly.txt`

### 4.1 Input text

```
(a) Parent one.
(i) child one.
(A) subchild one.
(1) deep one.
(m) reset one.
(b) Parent two.
(i) child two.
(A) subchild two.
(1) deep two.
(p) reset two.
```

File: `tests/fixtures/clause_gold/depth_reset_anomaly.txt`

### 4.2 Step-by-step stack trace

**Step 1: Process `(a)` at position 0**
- `chosen.level_type = "alpha"`, `chosen.ordinal = 1`
- `depth = CANONICAL_DEPTH["alpha"] = 1`
- High-letter guard: ordinal 1 < 24, SKIP
- Stack-pop: stack is `[]`, nothing to pop
- `parent_id = ""` (root)
- `node_id = "a"`
- Stack after: `[(1, "a")]`
- `last_sibling_at_level = {1: "a"}`

```
Stack: [(1, "a")]
```

**Step 2: Process `(i)` at position ~17**
- Ambiguity resolution: `(i)` matches both alpha (ordinal 9) and roman (ordinal 1).
  - `_classify_ambiguous_with_lookahead("i", 1, {1: "a"}, ...)`:
    - Rule 1 check: `last_at_depth=last_sibling_at_level[1]="a"`, which is not `"h"`,
      so expected_next="b" != "i". Rule 1 fails.
    - Rule 2 check: `last_sibling_at_level.get(2)` = None. No child depth active.
    - Rule 3 check: `last_at_depth="a"` is not None -> return "roman".
  - `chosen = roman_em`, depth = 2
- Stack-pop: pop entries with depth >= 2. Stack is `[(1, "a")]`.
  Stack[-1] = (1, "a"), 1 < 2, so NO pop.
- `parent_id = "a"` (from stack top)
- `node_id = "a.i"`
- Stack after: `[(1, "a"), (2, "a.i")]`
- `last_sibling_at_level = {1: "a", 2: "i"}`

```
Stack: [(1, "a"), (2, "a.i")]
```

**Step 3: Process `(A)` at position ~34**
- `chosen.level_type = "caps"`, `chosen.ordinal = 1`
- `depth = CANONICAL_DEPTH["caps"] = 3`
- Stack-pop: pop entries with depth >= 3. Stack[-1] = (2, "a.i"), 2 < 3. NO pop.
- `parent_id = "a.i"` (from stack top)
- `node_id = "a.i.A"`
- Stack after: `[(1, "a"), (2, "a.i"), (3, "a.i.A")]`
- `last_sibling_at_level = {1: "a", 2: "i", 3: "A"}`

```
Stack: [(1, "a"), (2, "a.i"), (3, "a.i.A")]
```

**Step 4: Process `(1)` at position ~51**
- `chosen.level_type = "numeric"`, `chosen.ordinal = 1`
- `depth = CANONICAL_DEPTH["numeric"] = 4`
- Stack-pop: pop entries with depth >= 4. None on stack. NO pop.
- `parent_id = "a.i.A"` (from stack top)
- `node_id = "a.i.A.1"`
- Stack after: `[(1, "a"), (2, "a.i"), (3, "a.i.A"), (4, "a.i.A.1")]`
- `last_sibling_at_level = {1: "a", 2: "i", 3: "A", 4: "1"}`

```
Stack: [(1, "a"), (2, "a.i"), (3, "a.i.A"), (4, "a.i.A.1")]
Tree depth: 4 (maximum)
```

**Step 5: Process `(m)` at position ~64 -- THE DEPTH RESET**

- `chosen.level_type = "alpha"`, `chosen.ordinal = 13`
- `depth = CANONICAL_DEPTH["alpha"] = 1`
- High-letter guard check (line 528): `ordinal 13 >= 24`? **NO (13 < 24)**. SKIP.
- Stack-pop (line 576): pop entries with depth >= 1:
  - Pop `(4, "a.i.A.1")` -- depth 4 >= 1
  - Pop `(3, "a.i.A")` -- depth 3 >= 1
  - Pop `(2, "a.i")` -- depth 2 >= 1
  - Pop `(1, "a")` -- depth 1 >= 1
  - Stack is now EMPTY
- `parent_id = forced_parent_id="" or (stack[-1][1] if stack else "")` = `""`
- `node_id = "m"` (ROOT)
- Stack after: `[(1, "m")]`
- `last_sibling_at_level = {1: "m"}` (deeper levels purged at line 624-626)

```
Stack: [(1, "m")]          <-- ENTIRE PREVIOUS CONTEXT LOST
Tree: a -> a.i -> a.i.A -> a.i.A.1 -> m (root, sibling of a)
DEPTH JUMP: 4 -> 1
```

This is the depth-reset event. The parser has jumped from depth 4 to depth 1,
destroying the entire ancestor chain.

**Step 6: Process `(b)` at position ~80**
- `chosen.level_type = "alpha"`, `chosen.ordinal = 2`
- `depth = 1`
- Stack-pop: pop `(1, "m")`. Stack empty.
- `parent_id = ""` (root)
- `node_id = "b"`
- Stack after: `[(1, "b")]`

```
Stack: [(1, "b")]
```

**Steps 7-9: Process `(i)`, `(A)`, `(1)` under `(b)` -- repeat of steps 2-4.**

```
Stack: [(1, "b"), (2, "b.i"), (3, "b.i.A"), (4, "b.i.A.1")]
```

**Step 10: Process `(p)` at position ~145 -- SECOND DEPTH RESET**
- `chosen.level_type = "alpha"`, `chosen.ordinal = 16`
- `depth = 1`
- High-letter guard: ordinal 16 < 24. SKIP.
- Stack-pop: pops ALL 4 entries.
- `parent_id = ""`
- `node_id = "p"` (ROOT)

```
SECOND DEPTH JUMP: 4 -> 1
Final tree:
  a (root)
    a.i
      a.i.A
        a.i.A.1
  m (root)           <-- depth reset #1
  b (root)
    b.i
      b.i.A
        b.i.A.1
  p (root)           <-- depth reset #2
```

### 4.3 Expected behavior per gold fixture

The gold fixture at `tests/fixtures/clause_gold/expected.json:117-229` confirms that
the CURRENT expected behavior IS for `(m)` and `(p)` to be root nodes. The gold
fixture treats this as a known parser output, not a corrected one.

---

## 5. The Guardrail Detection Logic

### 5.1 SQL detector in `edge_case_clause_guardrail.py:152-196`

The detector query identifies depth resets by looking for consecutive structural
clauses where:
1. `prev_tree_level >= 4` (previous clause was at tree level 4+)
2. `tree_level = 1` (current clause is at tree level 1, i.e., root)
3. `label_inner BETWEEN 'm' AND 'z'` (label is a late-alphabet letter)
4. Single-char label (excludes `aa`, `bb`, etc.)
5. At least 2 such resets per section (`HAVING COUNT(*) >= 2`)

### 5.2 Why "m" through "z"?

The range `m..z` was chosen because:
- Labels `(a)` through `(l)` (ordinals 1-12) are common legitimate root-level
  enumerators. A jump from depth 4 to `(a)` at root is nearly always legitimate --
  it's a new top-level clause.
- Labels `(m)` through `(z)` (ordinals 13-26) are less common as root starts. When
  they appear immediately after a depth-4 node, it is suspicious.

### 5.3 Thresholds

- `_DEEP_RESET_PREV_LEVEL = 4` (only counts resets from depth 4+)
- `_DEEP_RESET_MIN_PER_SECTION = 2` (section must have at least 2 resets to be flagged)

The section-level threshold of 2 means a single depth reset is tolerated. Only
sections with repeated resets are flagged.

### 5.4 Dashboard query (server.py:2935-2966)

The dashboard drill-down shows all reset-point clauses for a given doc_id. It uses
the same logic but returns the actual clause rows instead of aggregates.

---

## 6. Interaction with Track 1 (Parent-Drop / xy_parent_loss)

### 6.1 Overlap surface

Track 1 detects `(x)` and `(y)` at root when `(a)` exists in the same section
with text mentioning `(x)` or `(y)`. This is a SUBSET of the depth-reset problem:

- Track 1 covers: `x` (ordinal 24), `y` (ordinal 25) -- sometimes `z` (26)
- Track 5 covers: `m` (13) through `z` (26)
- Overlap: `x`, `y`, `z` labels that reset after depth 4

### 6.2 How parent-drop causes depth resets

When the parser drops `(x)` or `(y)` as root nodes (parent-drop), subsequent
sub-nodes that SHOULD be children of `(x)` or `(y)` instead become orphaned. This
can create a cascade where:

1. `(x)` should be `a.x` but lands as root `x` (parent-drop)
2. `(x)`'s children `(i)`, `(A)`, `(1)` build under `x` at depths 2-4
3. The next label `(y)` should be `a.y` but lands as root `y` (another parent-drop + depth reset)

In this scenario, fixing the parent-drop (making `(x)` into `a.x`) would
automatically fix the depth-reset metric too, because the tree level of `(x)` would be
2 (under `a`), not 1. The `tree_level = 1` check in the detector would no longer fire.

### 6.3 Independence analysis

**Cases where fixing Track 1 fixes Track 5**: Any depth reset involving labels `x`, `y`, `z`
that the high-letter guard (ordinal >= 24) should catch but currently misses due to:
- No active root alpha on stack
- Anchored long body preventing forced nesting
- Connector lookback not matching

**Cases where Track 5 is independent**: Any depth reset involving labels `m` through `w`
(ordinals 13-23). These are NEVER caught by the high-letter guard because they fail the
`ordinal >= 24` threshold.

### 6.4 Quantitative estimate

From the baseline:
- Track 1: 294 docs, 378 structural rows (all `x`/`y`)
- Track 5: 8 docs, 19 total resets (labels `m`..`z`)

The Track 5 detector requires `prev_tree_level >= 4`, which is much stricter than
Track 1's check. Track 5's 8 docs are likely a mix:
- Some overlap with Track 1 where `x`/`y` follows depth 4 specifically
- Some independent where `m`..`w` follows depth 4

A rough estimate: fixing Track 1 would resolve approximately 30-50% of the 19 depth
resets (those involving `x`/`y`/`z`), leaving 10-13 resets from `m`..`w` as independent
Track 5 issues.

---

## 7. Root Cause Classification

### 7.1 Legitimate depth resets (true positives of the parser's behavior)

A depth reset is LEGITIMATE when:
- The document genuinely has a new top-level enumeration after a deep subsection.
- Example: Section with clauses `(a)` through `(l)`, each with deep children, then
  `(m)` starts a new top-level item.
- Signal: `(m)` is anchored, starts a new paragraph, and the ordinal sequence
  `a..l..m` is unbroken.

### 7.2 Illegitimate depth resets (parser errors)

A depth reset is ILLEGITIMATE when:
- The label should be nested deeper but the parser has lost context.
- Example: `(a)` has children down to depth 4, then `(m)` appears but is actually
  a cross-reference or inline continuation, not a new top-level item.
- Example: The document uses a non-standard nesting order (e.g., `a -> m -> i`
  instead of `a -> i -> A -> 1`), and the parser's fixed CANONICAL_DEPTH forces `(m)`
  to depth 1.

### 7.3 Ambiguous cases

Some resets are ambiguous even to human readers:
- Long sections with 20+ top-level items where the deep subtree is a one-off
  elaboration.
- Cases where `(m)` has minimal text and could be either a stub root item or a
  continuation.

---

## 8. Signal Analysis: Distinguishing Legitimate vs. Illegitimate

### 8.1 Signals indicating a LEGITIMATE new root item

1. **Unbroken ordinal sequence**: Previous root-level items form a continuous
   sequence (`a`, `b`, `c`, ..., `l`, `m`). The jump to `(m)` simply continues the
   existing run.

2. **Anchoring**: The new node is line-start anchored (`is_anchored=True`) AND the
   previous root nodes are also anchored.

3. **Paragraph boundary**: There is a clear paragraph break (empty line or
   semicolon+newline) before the new node.

4. **Body length**: The new node has substantial body text (> 100 chars), indicating
   it is a real clause, not a stub.

5. **Multiple root siblings**: There are already many root-level alpha nodes in the
   section (e.g., 12+).

### 8.2 Signals indicating an ILLEGITIMATE reset (parser error)

1. **Ordinal gap**: The new node's ordinal is far from the last root-level ordinal.
   E.g., last root was `(a)` (ordinal 1) and now `(m)` (ordinal 13) appears with no
   `(b)` through `(l)` in between.

2. **No anchoring**: The new node is not line-start anchored -- it appears mid-line.

3. **Inline context**: The text before the new node contains connectors ("and", "or",
   ";") suggesting continuation, not a new item.

4. **Small body**: The new node has very short body text (< 50 chars), suggesting it
   may be a cross-reference or fragment.

5. **Depth delta**: The jump is from depth 4 to depth 1 with no intervening
   intermediate-depth nodes. A legitimate sequence would typically have the previous
   depth-4 subtree "closed" by its parent returning to depth 1, but in a depth-reset
   scenario the IMMEDIATE predecessor is depth 4.

6. **Single or few root siblings**: If there are only 1-3 root-level alpha nodes in
   the section, a new root `(m)` with ordinal 13 is suspicious.

### 8.3 Composite heuristic score

A "depth-reset legitimacy score" could combine these signals:

```
score = (
    0.25 * ordinal_continuity   # 1.0 if ordinal matches expected next, 0.0 if gap > 5
  + 0.20 * is_anchored          # 1.0 if anchored, 0.0 if not
  + 0.20 * paragraph_break      # 1.0 if preceded by paragraph boundary
  + 0.15 * body_length_score    # scaled 0..1 based on body chars
  + 0.10 * root_sibling_count   # scaled by existing root count
  + 0.10 * depth_delta_normal   # 1.0 if delta <= 2, 0.0 if delta >= 4
)
```

If `score < 0.4`, the reset is likely illegitimate and should be flagged or corrected.

---

## 9. Proposed Fix: Depth-Reset Guard

### 9.1 Where to insert the guard

In `_build_tree`, after the ambiguity resolution and before the stack-pop loop
(between lines 527 and 575).

### 9.2 Pseudocode

```python
# After choosing the enumerator and computing depth, but before stack-pop:

# Depth-reset guard: detect jumps from deep nesting to root alpha
if (
    depth == 1
    and chosen.level_type == "alpha"
    and chosen.ordinal >= 13      # mid-to-late alphabet
    and stack                      # there is an existing context
    and stack[-1][0] >= 3          # current stack top is at depth 3+
):
    # Compute legitimacy signals
    root_alphas_seen = [
        n for n in nodes
        if n.level_type == "alpha" and n.depth == 1 and n.parent_id == ""
    ]
    last_root_ordinal = max(
        (n.ordinal for n in root_alphas_seen), default=0
    )
    ordinal_gap = chosen.ordinal - last_root_ordinal - 1

    # Check 1: Is the ordinal sequence unbroken?
    ordinal_continuous = (ordinal_gap == 0)

    # Check 2: How many root siblings already exist?
    has_substantial_root_run = len(root_alphas_seen) >= chosen.ordinal - 1

    # Check 3: Is the node anchored at line start?
    node_anchored = chosen.is_anchored

    # Check 4: Is there an active root alpha on the stack?
    active_root = None
    for sd, sid in reversed(stack):
        if sd == 1:
            cand = node_map.get(sid)
            if cand and cand.level_type == "alpha" and cand.parent_id == "":
                active_root = cand
                break

    # Decision: if the ordinal sequence is broken AND we have an active root,
    # force nesting under that root instead of resetting.
    if (
        not ordinal_continuous
        and not has_substantial_root_run
        and active_root is not None
    ):
        forced_parent_id = active_root.id
        # Note: depth stays 1, but parent is set, so the node becomes
        # a child of the active root alpha. This is the "continuation" interpretation.
```

### 9.3 Key design decisions

1. **Ordinal threshold at 13 (not 24)**: The current high-letter guard uses 24,
   but depth resets at `(m)` through `(w)` are equally problematic. Lowering to 13
   catches the full Track 5 range.

2. **Stack depth threshold at 3 (not 4)**: The guardrail detector uses `prev_tree_level >= 4`,
   but a jump from depth 3 to depth 1 with a large ordinal gap is also suspicious.
   Using 3 catches more cases while maintaining high precision.

3. **Ordinal continuity as primary signal**: The strongest signal for legitimacy is
   an unbroken sequence. If `a,b,c,...,l` all exist as root nodes, then `(m)` at root
   is almost certainly legitimate. If only `(a)` exists as root and `(m)` appears,
   that is suspicious.

4. **Do NOT change depth assignment**: The fix should use `forced_parent_id` (like the
   existing high-letter guard) rather than changing the depth. This keeps the
   `CANONICAL_DEPTH` assignment clean and predictable.

### 9.4 Integration with existing high-letter guard

The proposed depth-reset guard should run BEFORE the existing high-letter guard
(lines 528-573). The existing guard handles `ordinal >= 24` with inline continuation
heuristics. The new guard handles `ordinal 13-23` with ordinal-continuity heuristics.

The two guards are complementary:
- Depth-reset guard: structural signal (ordinal gap, root sibling count)
- High-letter guard: textual signal (connector lookback, body length)

For ordinals 24+, both guards could activate. The high-letter guard should take
precedence since it uses richer textual signals.

```python
# Order of guards:
# 1. Depth-reset guard (ordinal 13+, depth delta 3+, ordinal gap check)
# 2. High-letter guard (ordinal 24+, inline continuation check)
# 3. Default stack-pop
```

---

## 10. The `last_sibling_at_level` Purge Cascade

### 10.1 The purge mechanism (lines 623-626)

```python
# Phase 1/6: level-reset -- purge deeper levels
for deeper in list(last_sibling_at_level):
    if deeper > depth:
        del last_sibling_at_level[deeper]
```

When a depth-1 node is processed, ALL deeper levels (2, 3, 4) are purged from
`last_sibling_at_level`. This means the alpha/roman disambiguation state for those
deeper levels is lost.

### 10.2 Cascade effect

After the depth reset to `(m)` at depth 1:
- `last_sibling_at_level` becomes `{1: "m"}`
- The roman disambiguation state at depth 2 is lost
- The caps state at depth 3 is lost
- The numeric state at depth 4 is lost

When the parser subsequently encounters `(b)` and its children `(i)`, `(A)`, `(1)`,
the disambiguation must restart from scratch. This is correct behavior for a
legitimate depth reset (new top-level clause), but for an illegitimate one, it
compounds the error by making the parser's context reconstruction less accurate.

---

## 11. The Confidence Scoring Path for Depth-Reset Nodes

### 11.1 How confidence is computed (lines 675-854)

For the `(m)` node in the gold fixture:
- `anchor_ok = True` (line-start anchored)
- `run_length_ok`: depends on sibling count at `(parent_id="", level_type="alpha")`.
  In the gold fixture, root alphas include `a`, `m`, `b`, `p` = 4 siblings.
  `len(group) >= 2` = True.
- `gap_ok`: ordinals are `1, 13, 2, 16`. Gap between 1 and 13 is 12 > 5. **gap_ok = False**.
  Wait -- the group is sorted by ordinal: `1, 2, 13, 16`. Gaps: 2-1=1, 13-2=11, 16-13=3.
  Max gap 11 > 5. **gap_ok = False**.
- `not_xref = True` (not an xref)
- `indentation_score = 0.0` (line start)

```
confidence = 0.30 * 1.0   # anchor
           + 0.30 * 1.0   # run_length
           + 0.20 * 0.0   # gap (FAILS)
           + 0.15 * 1.0   # not_xref
           + 0.05 * 0.0   # indentation
           = 0.30 + 0.30 + 0.0 + 0.15 + 0.0
           = 0.75
```

0.75 >= 0.50 threshold, so **is_structural = True**.

The gold fixture confirms `parse_confidence: 0.75` for the `(m)` node.

### 11.2 The root_high_letter_with_low_reset check (lines 731-743)

```python
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

This check looks for root high-letter nodes (ordinal >= 24) followed by low root
alphas (ordinal <= 5). It applies a `0.55` confidence multiplier. But again, the
`ordinal < 24` guard means `(m)` (ordinal 13) is SKIPPED.

### 11.3 The unanchored root high-letter penalty (lines 774-780)

```python
if (
    n.level_type == "alpha"
    and n.parent_id == ""
    and n.ordinal >= 24
    and not anchor_ok
):
    confidence *= _ROOT_HIGH_LETTER_PENALTY   # 0.60
```

Again, only triggers for ordinal >= 24. Labels `(m)` through `(w)` escape ALL
penalties.

### 11.4 Summary of confidence blind spots for depth-reset nodes

The confidence scoring has **no specific penalty** for depth-reset events involving
labels `(m)` through `(w)`. These nodes:
1. Pass the `is_structural` threshold (confidence 0.75)
2. Are not penalized by the high-letter guards (ordinal < 24)
3. Are not penalized by the root_high_letter_with_low_reset check (ordinal < 24)
4. Are only penalized by the gap check (gap_ok = False), which costs 0.20

This means a depth-reset node `(m)` that is anchored and has run-length peers
achieves confidence 0.75 and is marked structural -- even when the ordinal gap
is massive (e.g., from `(a)` to `(m)` with no `(b)` through `(l)`).

---

## 12. The `clause_ordinal_spike_after_deep` Related Detector

### 12.1 How it differs from depth-reset

The `clause_ordinal_spike_after_deep` detector (test at line 739 of test_edge_cases.py)
catches a related but different pattern: a root alpha with high ordinal FOLLOWED by
a root alpha with low ordinal. Example: `(a) -> (a.i) -> (y) -> (b)`.

This is the "spike" pattern: the ordinal sequence at depth 1 goes `1, 25, 2` instead
of a monotonic sequence. It specifically checks for `ordinal >= 24` in the spike
node, then `ordinal <= 5` in the follower.

### 12.2 Relationship to Track 5

The ordinal-spike detector is complementary to the depth-reset detector:
- Depth-reset: looks at depth delta (4 -> 1) with late-alphabet labels
- Ordinal-spike: looks at ordinal sequence anomalies at depth 1

Both can fire on the same node. In the gold fixture, `(m)` and `(p)` fire the
depth-reset detector. They would NOT fire the ordinal-spike detector because their
ordinals (13, 16) are below 24.

---

## 13. Risk Assessment for the Proposed Fix

### 13.1 False positive risk (breaking legitimate root sequences)

**Scenario**: A section genuinely has root items `(a)` through `(z)`, each with deep
sub-clauses. After `(l)` with children down to depth 4, `(m)` legitimately starts at
depth 1.

**Mitigation**: The ordinal-continuity check ensures that if `(a)` through `(l)` all
exist as root nodes, then `(m)` passes the check and is NOT forced under a parent.
The guard only activates when there is a GAP in the root sequence.

**Estimated false positive rate**: Very low. Legitimate sections with 13+ root
items will have an unbroken sequence `a..l..m`.

### 13.2 True positive recovery (fixing real errors)

**Scenario**: Section with root `(a)` and children down to depth 4, then `(m)` appears
as a cross-reference or continuation but gets placed at root.

**Recovery**: The guard detects the ordinal gap (1 -> 13 with no 2-12) and forces `(m)`
under `(a)`.

**Estimated recovery rate**: Most of the 8 flagged docs / 19 resets that involve
`m..w` labels would be fixed.

### 13.3 Interaction risk with Track 1 fix

If Track 1 is fixed first (making `x/y/z` nest under active root alpha more
aggressively), the depth-reset guard at ordinals 24-26 becomes redundant. However:
- It is safe to have both guards because the depth-reset guard checks ordinal
  continuity, which is a different signal than the inline-continuation check.
- They can coexist without conflict.
- If Track 1 is NOT fixed, the depth-reset guard partially compensates for labels
  24-26 that have ordinal gaps.

### 13.4 Regression risk

**Gold fixture impact**: The `depth_reset_anomaly.txt` gold fixture currently expects
`(m)` and `(p)` at root. The proposed fix would change them to be nested under `(a)`
and `(b)` respectively. The gold fixture must be updated.

**Guardrail impact**: The depth-reset metric (8 docs, 19 resets) should decrease.
The guardrail baseline must be re-snapshotted.

**Downstream link impact**: Any links that reference clause_id `m` or `p` as
root nodes would break if they become `a.m` or `b.p`. This requires a migration
strategy for persisted clause IDs.

---

## 14. Summary: The Three Categories of Depth Reset

| Category | Label Range | Current Guard | Independent? | Fix Strategy |
|----------|------------|---------------|-------------|--------------|
| **A. High-letter inline** | x, y, z (24-26) | High-letter guard (lines 528-573) | Overlaps Track 1 | Track 1 fix (improved forced_parent_id) |
| **B. Mid-alphabet orphan** | m through w (13-23) | NONE | Fully independent | New depth-reset guard (proposed above) |
| **C. Low-alphabet reset** | a through l (1-12) | N/A (not flagged) | N/A | Almost always legitimate; no fix needed |

The proposed fix targets Category B, which is the truly independent Track 5 issue.
Category A has overlap with Track 1 and is partially addressed by the existing
high-letter guard. Category C is not a problem.

---

## 15. Appendix: File References

| File | Lines | Purpose |
|------|-------|---------|
| `src/agent/clause_parser.py` | 430-628 | `_build_tree` -- stack-walk algorithm |
| `src/agent/clause_parser.py` | 512 | `depth = CANONICAL_DEPTH[...]` -- fixed depth assignment |
| `src/agent/clause_parser.py` | 528-573 | High-letter continuation guard (ordinal >= 24 only) |
| `src/agent/clause_parser.py` | 575-577 | Stack-pop loop -- the depth-reset mechanism |
| `src/agent/clause_parser.py` | 580 | Parent assignment from stack or forced_parent_id |
| `src/agent/clause_parser.py` | 620-626 | `last_sibling_at_level` update and purge |
| `src/agent/clause_parser.py` | 675-854 | `_compute_confidence` -- scoring and demotion |
| `src/agent/clause_parser.py` | 731-743 | Root high-letter reset penalty (ordinal >= 24 only) |
| `src/agent/clause_parser.py` | 774-780 | Unanchored root high-letter penalty (ordinal >= 24 only) |
| `src/agent/enumerator.py` | 72-77 | `CANONICAL_DEPTH` constants |
| `scripts/edge_case_clause_guardrail.py` | 152-196 | Depth-reset detector SQL query |
| `scripts/edge_case_clause_parent_guardrail.py` | 84-181 | Parent-loss detector SQL query |
| `dashboard/api/server.py` | 2332-2334 | Depth-reset thresholds |
| `dashboard/api/server.py` | 2935-2966 | Depth-reset category query |
| `dashboard/api/server.py` | 3417-3439 | Depth-reset drill-down query |
| `tests/fixtures/clause_gold/depth_reset_anomaly.txt` | 1-10 | Gold fixture input |
| `tests/fixtures/clause_gold/expected.json` | 117-229 | Gold fixture expected output |
| `tests/test_edge_cases.py` | 713-736 | Depth-reset unit test |
| `data/quality/edge_case_clause_guardrail_baseline.json` | 30-35 | Baseline metrics |
| `data/quality/edge_case_clause_parent_guardrail_baseline.json` | 29-37 | Parent-loss baseline |

---

## 16. Recommended Next Steps

1. **Implement depth-reset guard** in `_build_tree` for ordinals 13-23, using
   ordinal-continuity as the primary legitimacy signal.

2. **Add confidence penalty** in `_compute_confidence` for depth-reset nodes in the
   `m..w` range, analogous to the existing high-letter penalty but with a lower
   ordinal threshold.

3. **Update gold fixture** `depth_reset_anomaly.txt` expected output to reflect
   corrected parent assignment.

4. **Coordinate with Track 1**: Ensure the high-letter guard fix (ordinals 24-26)
   and the depth-reset guard (ordinals 13-23) are tested together to verify no
   interference.

5. **Re-baseline guardrails** after the fix is applied. Both
   `edge_case_clause_guardrail_baseline.json` and
   `edge_case_clause_parent_guardrail_baseline.json` should be re-snapshotted.

6. **Shadow reparse validation**: Run `clause_shadow_reparse_diff.py` on the 8
   flagged docs to confirm the fix resolves the depth-reset anomalies without
   introducing regressions.
