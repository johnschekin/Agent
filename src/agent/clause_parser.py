"""Clause-level AST parser for contract provisions.

Parses enumerated clauses such as (a)/(b)/(c), (i)/(ii)/(iii), (A)/(B)/(C),
(1)/(2)/(3) into a multi-level tree. Every node is kept; low-confidence nodes
are demoted with is_structural_candidate=False.

Standalone module: only standard library imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROMAN_VALUES: dict[str, int] = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
    "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
    "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
    "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20,
    "xxi": 21, "xxii": 22, "xxiii": 23, "xxiv": 24, "xxv": 25,
}

_ROMAN_SET = frozenset(ROMAN_VALUES.keys())

# Depth ordering: alpha=1, roman=2, caps=3, numeric=4 (root=0)
_LEVEL_DEPTH: dict[str, int] = {
    "root": 0,
    "alpha": 1,
    "roman": 2,
    "caps": 3,
    "numeric": 4,
}

# Confidence weights
_WEIGHT_ANCHOR = 0.3
_WEIGHT_RUN = 0.3
_WEIGHT_GAP = 0.2
_WEIGHT_NOT_XREF = 0.2

_HEADER_MAX_LEN = 80

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_ALPHA_PAREN_RE = re.compile(r"\(\s*([a-z]{1,2})\s*\)")
_ROMAN_PAREN_RE = re.compile(r"\(\s*((?:x{0,3})(?:ix|iv|v?i{0,3}))\s*\)")
_CAPS_PAREN_RE = re.compile(r"\(\s*([A-Z]{1,2})\s*\)")
_NUMERIC_PAREN_RE = re.compile(r"\(\s*(\d{1,2})\s*\)")

_XREF_CONTEXT_RE = re.compile(
    r"(?:Section|Sections|clause|Article)\s+\d+\.\d+\s*\($",
    re.IGNORECASE,
)

# Hard boundary characters that can precede a structural enumerator
_HARD_BOUNDARY_CHARS = frozenset(";\n")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EnumeratorMatch:
    """A single enumerator match found in text."""

    raw_label: str      # "(a)", "(iv)", "(A)", "(1)"
    ordinal: int        # Sequential ordinal: a=1, b=2, ..., z=26
    level_type: str     # "alpha" | "roman" | "caps" | "numeric"
    position: int       # Char offset in the text
    match_end: int      # Char offset of end of match
    is_anchored: bool   # True if at line start or after hard boundary


@dataclass(frozen=True, slots=True)
class ClauseNode:
    """A node in the clause tree AST."""

    id: str              # Path-style: "a", "a.i", "a.i.A", "a.i.A.1"
    label: str           # Raw: "(a)", "(i)", "(A)", "(1)"
    depth: int           # 0=root section, 1=alpha, 2=roman, 3=caps, 4=numeric
    level_type: str      # "alpha" | "roman" | "caps" | "numeric" | "root"
    span_start: int      # char offset (inclusive) -- ALWAYS global
    span_end: int        # char offset (exclusive)
    header_text: str     # first ~80 chars after label
    parent_id: str       # "" for root children
    children_ids: tuple[str, ...]
    # Per-constraint confidence flags
    anchor_ok: bool                # Enumerator at line start or after hard boundary
    run_length_ok: bool            # Level has >=2 sequential siblings
    gap_ok: bool                   # No ordinal skip >5 at this level
    is_structural_candidate: bool  # True = high-confidence structural
    parse_confidence: float        # 0.0-1.0
    demotion_reason: str           # "" if structural, else reason


# ---------------------------------------------------------------------------
# Internal mutable builder (converted to frozen ClauseNode at the end)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _MutableNode:
    """Internal mutable node used during tree construction."""

    id: str
    label: str
    depth: int
    level_type: str
    span_start: int
    span_end: int  # set in post-pass
    header_text: str
    parent_id: str
    children_ids: list[str]
    ordinal: int
    is_xref: bool
    is_anchored: bool


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _alpha_ordinal(s: str) -> int:
    """Convert alpha string to ordinal: a=1, b=2, ..., z=26, aa=27, ..."""
    if len(s) == 1:
        return ord(s) - ord("a") + 1
    # Two-letter: aa=27, ab=28, etc.
    return 26 + (ord(s[0]) - ord("a")) * 26 + (ord(s[1]) - ord("a")) + 1


def _caps_ordinal(s: str) -> int:
    """Convert caps string to ordinal: A=1, B=2, ..., Z=26, AA=27, ..."""
    if len(s) == 1:
        return ord(s) - ord("A") + 1
    return 26 + (ord(s[0]) - ord("A")) * 26 + (ord(s[1]) - ord("A")) + 1


def _is_anchored(text: str, pos: int) -> bool:
    """Check if position is at line start or after a hard boundary."""
    if pos == 0:
        return True
    # Walk backwards past whitespace to find the preceding non-space character
    i = pos - 1
    while i >= 0 and text[i] in " \t":
        i -= 1
    if i < 0:
        return True
    return text[i] in _HARD_BOUNDARY_CHARS


def _is_xref(text: str, pos: int) -> bool:
    """Check if an enumerator at `pos` is part of a cross-reference."""
    lookback_start = max(0, pos - 80)
    window = text[lookback_start:pos + 1]
    return _XREF_CONTEXT_RE.search(window) is not None


def scan_enumerators(text: str) -> list[EnumeratorMatch]:
    """Scan text for all enumerator patterns. Returns sorted by position."""
    matches: list[EnumeratorMatch] = []

    # Alpha
    for m in _ALPHA_PAREN_RE.finditer(text):
        inner = m.group(1)
        # Skip if it is also a valid roman numeral -- handled by disambiguation later
        # We include it as alpha here; disambiguation pass may reclassify
        matches.append(EnumeratorMatch(
            raw_label=m.group(0),
            ordinal=_alpha_ordinal(inner),
            level_type="alpha",
            position=m.start(),
            match_end=m.end(),
            is_anchored=_is_anchored(text, m.start()),
        ))

    # Roman
    for m in _ROMAN_PAREN_RE.finditer(text):
        inner = m.group(1)
        if not inner:
            continue  # Empty match from the regex
        if inner not in _ROMAN_SET:
            continue
        matches.append(EnumeratorMatch(
            raw_label=m.group(0),
            ordinal=ROMAN_VALUES[inner],
            level_type="roman",
            position=m.start(),
            match_end=m.end(),
            is_anchored=_is_anchored(text, m.start()),
        ))

    # Caps
    for m in _CAPS_PAREN_RE.finditer(text):
        inner = m.group(1)
        matches.append(EnumeratorMatch(
            raw_label=m.group(0),
            ordinal=_caps_ordinal(inner),
            level_type="caps",
            position=m.start(),
            match_end=m.end(),
            is_anchored=_is_anchored(text, m.start()),
        ))

    # Numeric
    for m in _NUMERIC_PAREN_RE.finditer(text):
        inner = m.group(1)
        matches.append(EnumeratorMatch(
            raw_label=m.group(0),
            ordinal=int(inner),
            level_type="numeric",
            position=m.start(),
            match_end=m.end(),
            is_anchored=_is_anchored(text, m.start()),
        ))

    # Sort by position, then prefer the deeper (more specific) level type
    # when two matches share the same position
    matches.sort(key=lambda em: (em.position, _LEVEL_DEPTH.get(em.level_type, 99)))
    return matches


# ---------------------------------------------------------------------------
# Disambiguation
# ---------------------------------------------------------------------------

def _disambiguate(matches: list[EnumeratorMatch]) -> list[EnumeratorMatch]:
    """Resolve ambiguity between alpha and roman at the same position.

    The key challenge: (i) can be alpha (9th letter) or roman numeral 1.

    Rules:
    - If (i) is preceded by (h) at the same level -> alpha
    - If (ii) follows (i) nearby -> both are roman
    - If (i) stands alone with no (h) before and no (ii) after -> roman
    - Also handles (v) ambiguity: alpha 'v' (22nd) vs roman 'v' (5)
    """
    # Group by position to find overlapping matches
    by_pos: dict[int, list[EnumeratorMatch]] = {}
    for em in matches:
        by_pos.setdefault(em.position, []).append(em)

    # Build quick lookup: for a given level_type, what ordinals exist
    # at what positions (for context checking)
    alpha_by_ordinal: dict[int, list[int]] = {}
    roman_by_ordinal: dict[int, list[int]] = {}
    for em in matches:
        if em.level_type == "alpha":
            alpha_by_ordinal.setdefault(em.ordinal, []).append(em.position)
        elif em.level_type == "roman":
            roman_by_ordinal.setdefault(em.ordinal, []).append(em.position)

    result: list[EnumeratorMatch] = []
    seen_positions: set[tuple[int, str]] = set()

    for em in matches:
        key = (em.position, em.level_type)
        if key in seen_positions:
            continue

        overlapping = by_pos.get(em.position, [em])

        # If only one match at this position, keep it
        if len(overlapping) == 1:
            seen_positions.add(key)
            result.append(em)
            continue

        # Multiple matches at same position -- decide which to keep
        types_at_pos = {o.level_type for o in overlapping}

        if "alpha" in types_at_pos and "roman" in types_at_pos:
            alpha_em = next(o for o in overlapping if o.level_type == "alpha")
            roman_em = next(o for o in overlapping if o.level_type == "roman")

            keep = _choose_alpha_or_roman(
                alpha_em, roman_em, alpha_by_ordinal, roman_by_ordinal,
            )

            for o in overlapping:
                okey = (o.position, o.level_type)
                seen_positions.add(okey)
                if o.level_type == keep:
                    result.append(o)
                elif o.level_type not in ("alpha", "roman"):
                    # Keep non-conflicting types (caps, numeric)
                    result.append(o)
        else:
            # No alpha/roman conflict -- keep all
            for o in overlapping:
                okey = (o.position, o.level_type)
                if okey not in seen_positions:
                    seen_positions.add(okey)
                    result.append(o)

    result.sort(key=lambda em: (em.position, _LEVEL_DEPTH.get(em.level_type, 99)))
    return result


def _choose_alpha_or_roman(
    alpha_em: EnumeratorMatch,
    roman_em: EnumeratorMatch,
    alpha_by_ordinal: dict[int, list[int]],
    roman_by_ordinal: dict[int, list[int]],
) -> str:
    """Decide whether an ambiguous match is alpha or roman.

    Returns 'alpha' or 'roman'.
    """
    # The raw inner text (without parens) for this match
    # Roman ordinal 1 corresponds to (i), which is also alpha ordinal 9
    roman_ord = roman_em.ordinal
    alpha_ord = alpha_em.ordinal

    # Check: is (h) present before this position? (h) = alpha ordinal 8
    # If so, this (i) is likely alpha continuation
    if alpha_ord == 9:  # (i) as alpha
        prev_alpha_ord = alpha_ord - 1  # (h) = 8
        h_positions = alpha_by_ordinal.get(prev_alpha_ord, [])
        has_h_before = any(p < alpha_em.position for p in h_positions)
        if has_h_before:
            return "alpha"

    # Check: does (ii) follow? If so, this is roman
    if roman_ord == 1:
        ii_positions = roman_by_ordinal.get(2, [])
        has_ii_after = any(p > roman_em.position for p in ii_positions)
        if has_ii_after:
            return "roman"

    # For (v): alpha 'v' = ordinal 22, roman 'v' = ordinal 5
    # If (iv) or (vi) exists nearby, prefer roman
    if roman_ord == 5:
        iv_positions = roman_by_ordinal.get(4, [])
        vi_positions = roman_by_ordinal.get(6, [])
        has_iv_near = any(abs(p - roman_em.position) < 5000 for p in iv_positions)
        has_vi_near = any(abs(p - roman_em.position) < 5000 for p in vi_positions)
        if has_iv_near or has_vi_near:
            return "roman"
        # If (u) exists before (alpha ordinal 21), it's alpha
        u_positions = alpha_by_ordinal.get(21, [])
        has_u_before = any(p < alpha_em.position for p in u_positions)
        if has_u_before:
            return "alpha"

    # For single-letter roman numerals that are also alpha:
    # i(9), v(22), x(24), c(3), d(4), m(13), l(12)
    # Default: if the roman ordinal is small (1-3) prefer roman interpretation
    if roman_ord <= 3:
        return "roman"

    # Default: prefer alpha for larger ordinals
    return "alpha"


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------

def _extract_header(text: str, start: int) -> str:
    """Extract header text from `start` up to 80 chars or first sentence end."""
    end = min(start + _HEADER_MAX_LEN, len(text))
    chunk = text[start:end]

    # Truncate at first period+space or semicolon
    for i, ch in enumerate(chunk):
        if ch == ";" :
            return chunk[:i].strip()
        if ch == "." and i + 1 < len(chunk) and chunk[i + 1] == " ":
            return chunk[:i + 1].strip()

    return chunk.strip()


# ---------------------------------------------------------------------------
# Tree construction
# ---------------------------------------------------------------------------

def _build_id(parent_id: str, label_key: str) -> str:
    """Build a path-style ID from parent and label key."""
    if parent_id:
        return f"{parent_id}.{label_key}"
    return label_key


def _label_key(em: EnumeratorMatch) -> str:
    """Extract the inner content of a label for use in IDs.

    (a) -> 'a', (iv) -> 'iv', (A) -> 'A', (12) -> '12'
    """
    # Strip parens and whitespace
    inner = em.raw_label.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1].strip()
    return inner


def _build_tree(
    enumerators: list[EnumeratorMatch],
    text: str,
    global_offset: int,
) -> list[_MutableNode]:
    """Stack-walk algorithm to build the clause tree.

    We maintain a stack of (depth, node_id) pairs representing the current
    nesting path. For each enumerator:
    1. Determine its depth from level_type
    2. Pop stack until top has depth < new depth
    3. Parent is the top of stack (or root)
    4. Push new node onto stack
    """
    nodes: list[_MutableNode] = []
    node_map: dict[str, _MutableNode] = {}
    # Stack entries: (depth, node_id)
    stack: list[tuple[int, str]] = []

    for em in enumerators:
        depth = _LEVEL_DEPTH.get(em.level_type, 1)
        lk = _label_key(em)
        xref = _is_xref(text, em.position)

        # Pop stack until we find a node with depth < current depth
        while stack and stack[-1][0] >= depth:
            stack.pop()

        # Determine parent
        if stack:
            parent_id = stack[-1][1]
        else:
            parent_id = ""

        node_id = _build_id(parent_id, lk)

        # Handle duplicate IDs by appending a counter
        base_id = node_id
        counter = 2
        while node_id in node_map:
            node_id = f"{base_id}_{counter}"
            counter += 1

        header_start = em.match_end
        header = _extract_header(text, header_start)

        node = _MutableNode(
            id=node_id,
            label=em.raw_label,
            depth=depth,
            level_type=em.level_type,
            span_start=em.position + global_offset,
            span_end=len(text) + global_offset,  # Placeholder; fixed in post-pass
            header_text=header,
            parent_id=parent_id,
            children_ids=[],
            ordinal=em.ordinal,
            is_xref=xref,
            is_anchored=em.is_anchored,
        )

        # Register as child of parent
        if parent_id and parent_id in node_map:
            node_map[parent_id].children_ids.append(node_id)

        node_map[node_id] = node
        nodes.append(node)
        stack.append((depth, node_id))

    return nodes


# ---------------------------------------------------------------------------
# Span computation
# ---------------------------------------------------------------------------

def _compute_spans(nodes: list[_MutableNode], text_len: int, global_offset: int) -> None:
    """Set span_end for each node.

    span_end of a node = span_start of its next sibling, or parent's span_end,
    or end of text.
    """
    if not nodes:
        return

    # Build sibling groups: nodes sharing the same parent_id
    by_parent: dict[str, list[_MutableNode]] = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)

    # Sort each sibling group by span_start
    for siblings in by_parent.values():
        siblings.sort(key=lambda n: n.span_start)

    # Node lookup
    node_map = {n.id: n for n in nodes}

    # Process each sibling group
    for parent_id, siblings in by_parent.items():
        # Determine the end boundary for this group
        if parent_id and parent_id in node_map:
            group_end = node_map[parent_id].span_end
        else:
            group_end = text_len + global_offset

        for i, sib in enumerate(siblings):
            if i + 1 < len(siblings):
                sib.span_end = siblings[i + 1].span_start
            else:
                sib.span_end = group_end

    # Now propagate: a node's span_end should also be bounded by its children
    # (handled implicitly since children are within the parent's span)


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _compute_confidence(nodes: list[_MutableNode]) -> list[tuple[_MutableNode, bool, bool, bool, bool, float, str]]:
    """Compute per-node confidence flags.

    Returns list of (node, anchor_ok, run_length_ok, gap_ok,
                      is_structural_candidate, parse_confidence, demotion_reason)
    """
    # Group siblings by (parent_id, level_type)
    sibling_groups: dict[tuple[str, str], list[_MutableNode]] = {}
    for n in nodes:
        key = (n.parent_id, n.level_type)
        sibling_groups.setdefault(key, []).append(n)

    # Sort each group by ordinal
    for group in sibling_groups.values():
        group.sort(key=lambda n: n.ordinal)

    # Pre-compute group properties
    group_run_ok: dict[tuple[str, str], bool] = {}
    group_gap_ok: dict[tuple[str, str], bool] = {}

    for key, group in sibling_groups.items():
        # Run length: >= 2 siblings means the level is substantiated
        group_run_ok[key] = len(group) >= 2

        # Gap: check for ordinal skips > 5
        has_gap = False
        for i in range(1, len(group)):
            if group[i].ordinal - group[i - 1].ordinal > 5:
                has_gap = True
                break
        group_gap_ok[key] = not has_gap

    results: list[tuple[_MutableNode, bool, bool, bool, bool, float, str]] = []

    for n in nodes:
        key = (n.parent_id, n.level_type)
        anchor_ok = n.is_anchored
        run_length_ok = group_run_ok.get(key, False)
        gap_ok = group_gap_ok.get(key, True)
        not_xref = not n.is_xref

        is_structural = anchor_ok and run_length_ok and gap_ok and not_xref

        confidence = (
            _WEIGHT_ANCHOR * (1.0 if anchor_ok else 0.0)
            + _WEIGHT_RUN * (1.0 if run_length_ok else 0.0)
            + _WEIGHT_GAP * (1.0 if gap_ok else 0.0)
            + _WEIGHT_NOT_XREF * (1.0 if not_xref else 0.0)
        )

        demotion_reason = ""
        if not is_structural:
            reasons: list[str] = []
            if not anchor_ok:
                reasons.append("not_anchored")
            if not run_length_ok:
                reasons.append("singleton_level")
            if not gap_ok:
                reasons.append("ordinal_gap")
            if n.is_xref:
                reasons.append("cross_reference")
            demotion_reason = "; ".join(reasons)

        results.append((n, anchor_ok, run_length_ok, gap_ok, is_structural, confidence, demotion_reason))

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_clauses(text: str, *, global_offset: int = 0) -> list[ClauseNode]:
    """Parse enumerated clauses in text into a flat list of ClauseNode.

    Algorithm:
    1. Scan text with 4 regex patterns (alpha, roman, caps, numeric)
    2. Filter by anchor constraint (line-start or after hard boundary like ';')
    3. Disambiguate (i) -- alpha 'i' vs roman numeral 'i' based on context
    4. Stack-walk: build tree with parent-child relationships
    5. Post-pass: apply run-length and gap constraints
    6. Compute span boundaries (span_end = next sibling's span_start or parent end)
    7. Compute per-node confidence scores

    Args:
        text: Section text to parse.
        global_offset: Offset to add to all positions (for global coordinates).

    Returns:
        Flat list of ClauseNode (tree structure via parent_id/children_ids).
    """
    if not text:
        return []

    # Step 1: Scan for all enumerators
    raw_matches = scan_enumerators(text)
    if not raw_matches:
        return []

    # Step 2: Filter -- keep only anchored matches for structural consideration
    # (but we still keep non-anchored ones; they get demoted in confidence)
    # We keep all matches and let confidence scoring handle demotion.

    # Step 3: Disambiguate alpha vs roman
    matches = _disambiguate(raw_matches)
    if not matches:
        return []

    # Step 4: Build tree via stack-walk
    mutable_nodes = _build_tree(matches, text, global_offset)
    if not mutable_nodes:
        return []

    # Step 6: Compute span boundaries
    _compute_spans(mutable_nodes, len(text), global_offset)

    # Step 5 & 7: Confidence scoring
    scored = _compute_confidence(mutable_nodes)

    # Convert to frozen ClauseNode
    result: list[ClauseNode] = []
    for node, anchor_ok, run_length_ok, gap_ok, is_structural, confidence, demotion in scored:
        clause = ClauseNode(
            id=node.id,
            label=node.label,
            depth=node.depth,
            level_type=node.level_type,
            span_start=node.span_start,
            span_end=node.span_end,
            header_text=node.header_text,
            parent_id=node.parent_id,
            children_ids=tuple(node.children_ids),
            anchor_ok=anchor_ok,
            run_length_ok=run_length_ok,
            gap_ok=gap_ok,
            is_structural_candidate=is_structural,
            parse_confidence=round(confidence, 4),
            demotion_reason=demotion,
        )
        result.append(clause)

    return result


def resolve_path(nodes: list[ClauseNode], path: list[str]) -> ClauseNode | None:
    """Resolve a clause path like ['(d)', '(iv)', '(A)'] to a node.

    The path elements are raw labels including parentheses.
    Walks the tree level by level, matching labels to children.

    Args:
        nodes: Flat list of ClauseNode (as returned by parse_clauses).
        path: List of raw labels, e.g. ['(d)', '(iv)', '(A)'].

    Returns:
        The matching ClauseNode, or None if not found.
    """
    if not path or not nodes:
        return None

    node_map = {n.id: n for n in nodes}

    # Normalize labels for comparison (strip internal whitespace)
    def _normalize_label(label: str) -> str:
        return re.sub(r"\s+", "", label)

    # Start: find root-level nodes matching the first path element
    target_label = _normalize_label(path[0])
    candidates = [n for n in nodes if n.parent_id == "" and _normalize_label(n.label) == target_label]

    if not candidates:
        return None

    current = candidates[0]

    for step_label in path[1:]:
        target = _normalize_label(step_label)
        found = False
        for child_id in current.children_ids:
            child = node_map.get(child_id)
            if child and _normalize_label(child.label) == target:
                current = child
                found = True
                break
        if not found:
            return None

    return current
