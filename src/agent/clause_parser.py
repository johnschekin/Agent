"""Clause-level AST parser for contract provisions.

Parses enumerated clauses such as (a)/(b)/(c), (i)/(ii)/(iii), (A)/(B)/(C),
(1)/(2)/(3) into a multi-level tree. Every node is kept; low-confidence nodes
are demoted with is_structural_candidate=False.

Three-layer architecture:
  enumerator.py   — scanning, anchoring, ordinal utilities
  clause_parser.py — tree building, disambiguation, confidence, xref detection
  parsing_types.py — canonical ClauseNode type (forward-looking schema)
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from agent.enumerator import (
    CANONICAL_DEPTH,
    EnumeratorMatch,
    compute_indentation,
    compute_line_starts,
    scan_enumerators,
)
from agent.enumerator import (
    ROMAN_VALUES as ROMAN_VALUES,
)
from agent.enumerator import (
    check_anchor as check_anchor,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Confidence weights (5-signal: anchor, run, gap, not_xref, indent)
_WEIGHT_ANCHOR = 0.30
_WEIGHT_RUN = 0.30
_WEIGHT_GAP = 0.20
_WEIGHT_NOT_XREF = 0.15
_WEIGHT_INDENT = 0.05

_HEADER_MAX_LEN = 80

# Labels whose inner text is ambiguous between alpha and roman
_AMBIGUOUS_ROMAN = frozenset({"i", "v", "x", "l", "c", "d", "m"})


# ---------------------------------------------------------------------------
# Regex patterns (clause_parser's own — xref detection)
# ---------------------------------------------------------------------------

_XREF_CONTEXT_RE = re.compile(
    r"(?:"
    r"(?:Section|Sections|clause|clauses|Article|Articles|paragraph|paragraphs)"
    r"\s+\d+(?:\.\d+)*\s*\($"
    r"|(?:sub-?clauses?|paragraphs?)\s+\($"
    r")",
    re.IGNORECASE,
)

_XREF_LOOKAHEAD_RE = re.compile(
    r"\)\s*(?:"
    r"of\s+(?:this\s+|the\s+)?(?:Section|Article|Agreement)"
    r"|above|below"
    r"|here(?:of|in|under|to)|there(?:of|in|under|to)"
    r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

# Re-export EnumeratorMatch from enumerator for backward compatibility
__all__ = [
    "ClauseNode",
    "ClauseTree",
    "EnumeratorMatch",
    "ROMAN_VALUES",
    "check_anchor",
    "parse_clause_tree",
    "parse_clauses",
    "resolve_path",
    "scan_enumerators",
]


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
    indentation_score: float       # 0.0-1.0 (deeper = higher)
    xref_suspected: bool           # Pattern resembles inline cross-ref
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
    indentation_score: float
    match_end_local: int  # end of match in local (non-offset) coords


# ---------------------------------------------------------------------------
# Xref detection (Phase 2)
# ---------------------------------------------------------------------------

def _is_xref(text: str, pos: int, match_end: int) -> bool:
    """Check if an enumerator at `pos` is part of a cross-reference.

    Uses both lookback (200 chars) and lookahead to detect xref context.
    """
    # Lookback: check for "Section 2.14(" pattern preceding
    lookback_start = max(0, pos - 200)
    window = text[lookback_start:pos + 1]
    if _XREF_CONTEXT_RE.search(window):
        return True

    # Lookahead: check for "of this Section", "above", "hereof" etc.
    if match_end < len(text):
        lookahead_window = text[match_end - 1:min(match_end + 80, len(text))]
        if _XREF_LOOKAHEAD_RE.search(lookahead_window):
            return True

    return False


# ---------------------------------------------------------------------------
# Inline enumeration detection (Phase 6)
# ---------------------------------------------------------------------------

def _detect_inline_enums(
    matches: list[EnumeratorMatch],
    text: str,
    line_starts: list[int],
) -> set[int]:
    """Detect inline enumerations like "(a), (b) and (c)" on a single line.

    Groups matches by line, then looks for 3+ same-type enumerators separated
    by ", " / " and " / " or " / " through " on the same line.

    Returns set of positions that should be marked as xref.
    """
    inline_positions: set[int] = set()

    # Group matches by line number
    by_line: dict[int, list[EnumeratorMatch]] = {}
    for em in matches:
        line_idx = bisect.bisect_right(line_starts, em.position) - 1
        by_line.setdefault(line_idx, []).append(em)

    for line_matches in by_line.values():
        # Group by level_type within same line
        by_type: dict[str, list[EnumeratorMatch]] = {}
        for em in line_matches:
            by_type.setdefault(em.level_type, []).append(em)

        for same_type in by_type.values():
            if len(same_type) < 2:
                continue

            # Check inter-match text for inline separators
            same_type_sorted = sorted(same_type, key=lambda m: m.position)
            is_inline = True
            for j in range(len(same_type_sorted) - 1):
                gap_start = same_type_sorted[j].match_end
                gap_end = same_type_sorted[j + 1].position
                gap_text = text[gap_start:gap_end].strip().lower()

                # Accept: ", " / " and " / " or " / " through " / ", and " / ", or "
                if gap_text not in (
                    ",", "and", "or", "and/or", "through", ", and", ", or",
                ):
                    is_inline = False
                    break

            if is_inline:
                for em in same_type_sorted:
                    inline_positions.add(em.position)

    return inline_positions


# ---------------------------------------------------------------------------
# Inline disambiguation (Phase 1)
# ---------------------------------------------------------------------------

def _classify_ambiguous(
    label_inner: str,
    depth: int,
    last_sibling_at_level: dict[int, str],
) -> str:
    """4-rule cascade for ambiguous alpha/roman labels.

    Returns "alpha" or "roman". Ported from TermIntel ca_chunker.py.
    """
    # Rule 1: continues letter sequence at same depth?
    #   e.g., last_sibling[1] == "h" and label == "i" -> alpha
    last_at_depth = last_sibling_at_level.get(depth)
    if last_at_depth is not None and len(last_at_depth) == 1 and last_at_depth.isalpha():
        expected_next = chr(ord(last_at_depth) + 1)
        if label_inner == expected_next:
            return "alpha"

    # Rule 2: active roman run at child depth?
    child_depth = depth + 1
    if last_sibling_at_level.get(child_depth) is not None:
        return "roman"

    # Rule 3: letter siblings exist at this depth but no sequential match?
    #   -> new roman child level
    if last_at_depth is not None:
        return "roman"

    # Rule 4: no context -> default roman (matches corpus convention)
    return "roman"


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------

def _extract_header(text: str, start: int) -> str:
    """Extract header text from `start` up to 80 chars or first sentence end."""
    end = min(start + _HEADER_MAX_LEN, len(text))
    chunk = text[start:end]

    # Truncate at first period+space or semicolon
    for i, ch in enumerate(chunk):
        if ch == ";":
            return chunk[:i].strip()
        if ch == "." and i + 1 < len(chunk) and chunk[i + 1] == " ":
            return chunk[:i + 1].strip()

    return chunk.strip()


# ---------------------------------------------------------------------------
# Ghost clause filtering (Phase 4)
# ---------------------------------------------------------------------------

def _is_ghost_clause(body_text: str) -> bool:
    """Check if clause body is empty or near-empty (ghost clause).

    Conservative check — only catches truly empty/punctuation-only bodies
    to avoid false positives on short but legitimate clauses like
    "(b) Capital Expenditures;" or "(iv) ratio debt."
    """
    stripped = body_text.strip()
    if not stripped:
        return True
    # Strip all non-alphanumeric — if < 2 chars remain, it's ghost
    alpha_content = re.sub(r"[^a-zA-Z0-9]", "", stripped)
    return len(alpha_content) < 2


# ---------------------------------------------------------------------------
# Tree construction (Phase 0 + Phase 1)
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
    inner = em.raw_label.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1].strip()
    inner = inner.rstrip(".")
    return inner


def _build_tree(
    enumerators: list[EnumeratorMatch],
    text: str,
    global_offset: int,
    line_starts: list[int],
    inline_xref_positions: set[int],
) -> list[_MutableNode]:
    """Stack-walk algorithm to build the clause tree with inline disambiguation.

    Key improvements over the original:
    - Inline alpha/roman disambiguation using last_sibling_at_level (Phase 1)
    - Level-reset when entering a new parent (Phase 1/6)
    - Enhanced xref detection with lookback+lookahead (Phase 2)
    - Indentation scoring per node (Phase 3)
    """
    nodes: list[_MutableNode] = []
    node_map: dict[str, _MutableNode] = {}
    # Stack entries: (depth, node_id)
    stack: list[tuple[int, str]] = []

    # Phase 1: track last sibling at each depth for disambiguation
    last_sibling_at_level: dict[int, str] = {}

    # Group matches by position — when both alpha and roman exist at the
    # same position, we need to pick one via _classify_ambiguous()
    by_pos: dict[int, list[EnumeratorMatch]] = {}
    for em in enumerators:
        by_pos.setdefault(em.position, []).append(em)

    # Process in position order
    seen_positions: set[int] = set()
    for em in enumerators:
        if em.position in seen_positions:
            continue
        seen_positions.add(em.position)

        overlapping = by_pos[em.position]

        # Resolve alpha/roman ambiguity inline
        chosen: EnumeratorMatch
        if len(overlapping) == 1:
            chosen = overlapping[0]
        else:
            # Check for alpha/roman conflict
            types_at_pos = {o.level_type for o in overlapping}
            if "alpha" in types_at_pos and "roman" in types_at_pos:
                alpha_em = next(o for o in overlapping if o.level_type == "alpha")
                roman_em = next(o for o in overlapping if o.level_type == "roman")

                # Get the inner text for disambiguation
                lk_inner = _label_key(alpha_em).lower()

                if len(lk_inner) > 1 and lk_inner in ROMAN_VALUES:
                    # Multi-char roman (ii, iii, iv, vi, etc.) — always roman.
                    # These never represent alpha ordinals in legal text.
                    chosen = roman_em
                elif lk_inner in _AMBIGUOUS_ROMAN:
                    # Single-char ambiguous (i, v, x, l, c, d, m) — use
                    # context-sensitive 4-rule cascade
                    alpha_depth = CANONICAL_DEPTH.get("alpha", 1)
                    decision = _classify_ambiguous(
                        lk_inner, alpha_depth, last_sibling_at_level,
                    )
                    chosen = alpha_em if decision == "alpha" else roman_em
                else:
                    # Not ambiguous — keep alpha (e.g., "b", "e", "f")
                    chosen = alpha_em

            else:
                # No alpha/roman conflict — pick first by depth order
                overlapping_sorted = sorted(
                    overlapping,
                    key=lambda o: CANONICAL_DEPTH.get(o.level_type, 99),
                )
                chosen = overlapping_sorted[0]

        depth = CANONICAL_DEPTH.get(chosen.level_type, 1)
        lk = _label_key(chosen)
        xref = _is_xref(text, chosen.position, chosen.match_end)

        # Phase 6: mark inline enumerations as xref
        if chosen.position in inline_xref_positions:
            xref = True

        # Phase 3: compute indentation score
        indent_score = compute_indentation(chosen.position, text, line_starts)

        # Pop stack until we find a node with depth < current depth
        while stack and stack[-1][0] >= depth:
            stack.pop()

        # Determine parent
        parent_id = stack[-1][1] if stack else ""

        node_id = _build_id(parent_id, lk)

        # Handle duplicate IDs by appending a counter
        base_id = node_id
        counter = 2
        while node_id in node_map:
            node_id = f"{base_id}_dup{counter}"
            counter += 1

        header_start = chosen.match_end
        header = _extract_header(text, header_start)

        node = _MutableNode(
            id=node_id,
            label=chosen.raw_label,
            depth=depth,
            level_type=chosen.level_type,
            span_start=chosen.position + global_offset,
            span_end=len(text) + global_offset,  # Placeholder; fixed in post-pass
            header_text=header,
            parent_id=parent_id,
            children_ids=[],
            ordinal=chosen.ordinal,
            is_xref=xref,
            is_anchored=chosen.is_anchored,
            indentation_score=indent_score,
            match_end_local=chosen.match_end,
        )

        # Register as child of parent
        if parent_id and parent_id in node_map:
            node_map[parent_id].children_ids.append(node_id)

        node_map[node_id] = node
        nodes.append(node)
        stack.append((depth, node_id))

        # Phase 1: update last_sibling_at_level
        last_sibling_at_level[depth] = lk

        # Phase 1/6: level-reset — purge deeper levels
        for deeper in list(last_sibling_at_level):
            if deeper > depth:
                del last_sibling_at_level[deeper]

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


# ---------------------------------------------------------------------------
# Confidence scoring (Phases 3 + 4)
# ---------------------------------------------------------------------------

def _compute_confidence(
    nodes: list[_MutableNode],
    text: str,
    global_offset: int,
) -> list[tuple[_MutableNode, bool, bool, bool, bool, float, str]]:
    """Compute per-node confidence flags with 5-signal scoring.

    Returns list of (node, anchor_ok, run_length_ok, gap_ok,
                      is_structural_candidate, parse_confidence, demotion_reason)

    Improvements:
    - 5th signal: indentation_score (weighted at 0.05)
    - Singleton hard invariant: if run_length_ok is False, immediately demote
    - Threshold-based demotion: is_structural = confidence >= 0.5
    - Ghost clause filtering: empty/near-empty bodies get demoted
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

        # Singleton hard invariant: if not run_length_ok, immediately demote
        if not run_length_ok:
            confidence = (
                _WEIGHT_ANCHOR * (1.0 if anchor_ok else 0.0)
                + _WEIGHT_RUN * 0.0
                + _WEIGHT_GAP * (1.0 if gap_ok else 0.0)
                + _WEIGHT_NOT_XREF * (1.0 if not_xref else 0.0)
                + _WEIGHT_INDENT * n.indentation_score
            )
            results.append((
                n, anchor_ok, False, gap_ok, False,
                round(confidence, 4), "singleton",
            ))
            continue

        # Full 5-signal scoring
        confidence = (
            _WEIGHT_ANCHOR * (1.0 if anchor_ok else 0.0)
            + _WEIGHT_RUN * (1.0 if run_length_ok else 0.0)
            + _WEIGHT_GAP * (1.0 if gap_ok else 0.0)
            + _WEIGHT_NOT_XREF * (1.0 if not_xref else 0.0)
            + _WEIGHT_INDENT * n.indentation_score
        )

        # Threshold-based demotion
        is_structural = confidence >= 0.5

        # Phase 4: Ghost clause filtering
        demotion_reason = ""
        if is_structural:
            # Check body text for ghost clause
            body_start_local = n.match_end_local
            body_end_local = n.span_end - global_offset
            if 0 <= body_start_local <= body_end_local <= len(text):
                body_text = text[body_start_local:body_end_local]
                if _is_ghost_clause(body_text):
                    is_structural = False
                    demotion_reason = "ghost_body"

        if not is_structural and not demotion_reason:
            reasons: list[str] = []
            if not anchor_ok:
                reasons.append("not_anchored")
            if not gap_ok:
                reasons.append("ordinal_gap")
            if n.is_xref:
                reasons.append("cross_reference")
            if reasons:
                demotion_reason = "; ".join(reasons)

        results.append((
            n, anchor_ok, run_length_ok, gap_ok,
            is_structural, round(confidence, 4), demotion_reason,
        ))

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_clauses(text: str, *, global_offset: int = 0) -> list[ClauseNode]:
    """Parse enumerated clauses in text into a flat list of ClauseNode.

    Algorithm:
    1. Scan text with 4 regex patterns (alpha, roman, caps, numeric)
       — both alpha and roman returned at ambiguous positions
    2. Detect inline enumerations (3+ same-type on one line with separators)
    3. Stack-walk: build tree with inline alpha/roman disambiguation
       using last_sibling_at_level context
    4. Compute span boundaries
    5. 5-signal confidence scoring with singleton hard invariant,
       threshold demotion, and ghost clause filtering

    Args:
        text: Section text to parse.
        global_offset: Offset to add to all positions (for global coordinates).

    Returns:
        Flat list of ClauseNode (tree structure via parent_id/children_ids).
    """
    if not text:
        return []

    # Pre-compute line starts for anchor checking and indentation
    line_starts = compute_line_starts(text)

    # Step 1: Scan for all enumerators (both alpha and roman at same position)
    raw_matches = scan_enumerators(
        text, line_starts, deduplicate_alpha_roman=False,
    )
    if not raw_matches:
        return []

    # Step 2: Detect inline enumerations
    inline_positions = _detect_inline_enums(raw_matches, text, line_starts)

    # Step 3: Build tree via stack-walk with inline disambiguation
    mutable_nodes = _build_tree(
        raw_matches, text, global_offset, line_starts, inline_positions,
    )
    if not mutable_nodes:
        return []

    # Step 4: Compute span boundaries
    _compute_spans(mutable_nodes, len(text), global_offset)

    # Step 5: Confidence scoring with ghost clause filtering
    scored = _compute_confidence(mutable_nodes, text, global_offset)

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
            indentation_score=round(node.indentation_score, 4),
            xref_suspected=node.is_xref,
            is_structural_candidate=is_structural,
            parse_confidence=confidence,
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
    candidates = [
        n for n in nodes
        if n.parent_id == "" and _normalize_label(n.label) == target_label
    ]

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


@dataclass(frozen=True, slots=True)
class ClauseTree:
    """Wrapper API around flat clause nodes for parity with VP-style consumers."""

    nodes: tuple[ClauseNode, ...]

    @classmethod
    def from_text(cls, text: str, *, global_offset: int = 0) -> ClauseTree:
        return cls(nodes=tuple(parse_clauses(text, global_offset=global_offset)))

    @property
    def roots(self) -> tuple[ClauseNode, ...]:
        return tuple(n for n in self.nodes if n.parent_id == "")

    def node_by_id(self, node_id: str) -> ClauseNode | None:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def children_of(self, node_id: str) -> tuple[ClauseNode, ...]:
        return tuple(n for n in self.nodes if n.parent_id == node_id)

    def resolve(self, path: list[str]) -> ClauseNode | None:
        return resolve_path(list(self.nodes), path)

    def as_records(self) -> list[dict[str, object]]:
        return [
            {
                "id": n.id,
                "label": n.label,
                "depth": n.depth,
                "level_type": n.level_type,
                "span_start": n.span_start,
                "span_end": n.span_end,
                "header_text": n.header_text,
                "parent_id": n.parent_id,
                "children_ids": list(n.children_ids),
                "anchor_ok": n.anchor_ok,
                "run_length_ok": n.run_length_ok,
                "gap_ok": n.gap_ok,
                "indentation_score": n.indentation_score,
                "xref_suspected": n.xref_suspected,
                "is_structural_candidate": n.is_structural_candidate,
                "parse_confidence": n.parse_confidence,
                "demotion_reason": n.demotion_reason,
            }
            for n in self.nodes
        ]


def parse_clause_tree(text: str, *, global_offset: int = 0) -> ClauseTree:
    """Convenience wrapper returning a ClauseTree object."""
    return ClauseTree.from_text(text, global_offset=global_offset)
