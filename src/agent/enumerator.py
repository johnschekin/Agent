"""Enumerator registry and validity constraints for clause parsing.

Provides regex patterns, ordinal sequencing, roman numeral utilities,
and anchor/validity constraint checking for the ClauseTree parser.

Enumerator types:
  alpha   — (a), (b), ..., (z), (aa), (bb), ...
  roman   — (i), (ii), ..., (xx)
  caps    — (A), (B), ..., (Z)
  numeric — (1), (2), ..., (50)

Each type can appear in parenthesized form ``(x)`` or period-delimited ``x.``.
The registry pattern allows future variants (bullets, hybrid) without modifying
the parser core.

Nesting depth convention:
  depth 1 = alpha      (a), (b), ...
  depth 2 = roman      (i), (ii), ...
  depth 3 = caps       (A), (B), ...
  depth 4 = numeric    (1), (2), ...

This order matches ~95% of leveraged finance CAs. Alternative orderings
are handled by the parser's stack disambiguation logic.

Ported from vantage_platform l0/_enumerator.py — full version.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Roman numeral utilities
# ---------------------------------------------------------------------------

ROMAN_VALUES: dict[str, int] = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
    "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
    "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
    "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20,
    "xxi": 21, "xxii": 22, "xxiii": 23, "xxiv": 24, "xxv": 25,
}


def roman_to_int(s: str) -> int | None:
    """Convert lowercase roman numeral to int, or None if invalid."""
    return ROMAN_VALUES.get(s.lower().strip())


def int_to_roman(n: int) -> str | None:
    """Convert int (1-25) to lowercase roman numeral, or None if out of range."""
    for k, v in ROMAN_VALUES.items():
        if v == n:
            return k
    return None


# ---------------------------------------------------------------------------
# Enumerator type definitions
# ---------------------------------------------------------------------------

# Type names (used in ClauseNode.level_type)
LEVEL_ALPHA = "alpha"
LEVEL_ROMAN = "roman"
LEVEL_CAPS = "caps"
LEVEL_NUMERIC = "numeric"
LEVEL_ROOT = "root"

# Canonical depth ordering
CANONICAL_DEPTH: dict[str, int] = {
    LEVEL_ALPHA: 1,
    LEVEL_ROMAN: 2,
    LEVEL_CAPS: 3,
    LEVEL_NUMERIC: 4,
}


@dataclass(frozen=True, slots=True)
class EnumeratorMatch:
    """A single enumerator match found in text."""
    raw_label: str      # The raw text: "(a)", "(iv)", "(A)", "(1)"
    ordinal: int        # Sequential ordinal: a=1, b=2, ..., z=26, aa=27
    level_type: str     # "alpha" | "roman" | "caps" | "numeric"
    position: int       # Char offset in the text
    match_end: int      # Char offset of end of match
    is_anchored: bool   # True if at line start or after hard boundary


# ---------------------------------------------------------------------------
# Regex patterns — the 4 canonical enumerator types
# ---------------------------------------------------------------------------

# Parenthesized forms (primary in leveraged finance)
_ALPHA_PAREN_RE = re.compile(r"\(\s*([a-z]{1,2})\s*\)")
_ROMAN_PAREN_RE = re.compile(
    r"\(\s*((?:x{0,3})(?:ix|iv|v?i{0,3}))\s*\)",
)
_CAPS_PAREN_RE = re.compile(r"\(\s*([A-Z]{1,2})\s*\)")
_NUMERIC_PAREN_RE = re.compile(r"\(\s*(\d{1,2})\s*\)")

# Period-delimited forms (secondary — ~5% of leveraged finance CAs)
# These REQUIRE line-start anchoring (multiline ^) to avoid false positives.
# Supports start-of-text and indented lines.
_ALPHA_PERIOD_RE = re.compile(r"(?m)^(\s*([a-z]{1,2}))\.\s+")
_ROMAN_PERIOD_RE = re.compile(r"(?mi)^(\s*([ivxlc]+))\.\s+")
_CAPS_PERIOD_RE = re.compile(r"(?m)^(\s*([A-Z]{1,2}))\.\s+")
_NUMERIC_PERIOD_RE = re.compile(r"(?m)^(\s*(\d{1,2}))\.\s+")


# ---------------------------------------------------------------------------
# Ordinal computation
# ---------------------------------------------------------------------------

def _alpha_ordinal(label: str) -> int:
    """Convert alpha label to ordinal: a=1, b=2, ..., z=26, aa=27, bb=28."""
    label = label.lower()
    if len(label) == 1:
        return ord(label) - ord("a") + 1
    elif len(label) == 2 and label[0] == label[1]:
        # aa=27, bb=28, ..., zz=52
        return 26 + ord(label[0]) - ord("a") + 1
    return -1  # Invalid


def _caps_ordinal(label: str) -> int:
    """Convert uppercase alpha label to ordinal: A=1, B=2, ..., Z=26."""
    label = label.upper()
    if len(label) == 1:
        return ord(label) - ord("A") + 1
    elif len(label) == 2 and label[0] == label[1]:
        return 26 + ord(label[0]) - ord("A") + 1
    return -1


def _numeric_ordinal(label: str) -> int:
    """Convert numeric label to ordinal."""
    try:
        return int(label)
    except ValueError:
        return -1


def ordinal_for(level_type: str, label: str) -> int:
    """Compute the ordinal for a label of the given level type."""
    if level_type == LEVEL_ALPHA:
        return _alpha_ordinal(label)
    elif level_type == LEVEL_ROMAN:
        val = roman_to_int(label)
        return val if val is not None else -1
    elif level_type == LEVEL_CAPS:
        return _caps_ordinal(label)
    elif level_type == LEVEL_NUMERIC:
        return _numeric_ordinal(label)
    return -1


def next_ordinal_label(level_type: str, current_ordinal: int) -> str | None:
    """Return the label for the next ordinal in the given level type."""
    next_ord = current_ordinal + 1
    if level_type == LEVEL_ALPHA:
        if next_ord <= 26:
            return chr(ord("a") + next_ord - 1)
        elif next_ord <= 52:
            c = chr(ord("a") + next_ord - 27)
            return c + c
        return None
    elif level_type == LEVEL_ROMAN:
        return int_to_roman(next_ord)
    elif level_type == LEVEL_CAPS:
        if next_ord <= 26:
            return chr(ord("A") + next_ord - 1)
        return None
    elif level_type == LEVEL_NUMERIC:
        return str(next_ord)
    return None


# ---------------------------------------------------------------------------
# Line position pre-computation
# ---------------------------------------------------------------------------

def compute_line_starts(text: str) -> list[int]:
    """Pre-compute char offsets of every line start (after each ``\\n``).

    Position 0 is always a line start. This enables O(log N) anchor checks
    via binary search instead of scanning backwards for newlines.
    """
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def is_at_line_start(position: int, line_starts: list[int], text: str) -> bool:
    """Check if position is at a line start (possibly after whitespace).

    True if the position is the first non-whitespace on a line.
    """
    idx = bisect.bisect_right(line_starts, position) - 1
    if idx < 0:
        return position == 0
    line_start = line_starts[idx]
    # Check that everything between line_start and position is whitespace
    between = text[line_start:position]
    return between.strip() == ""


# ---------------------------------------------------------------------------
# Anchor constraint — hard boundary detection
# ---------------------------------------------------------------------------

# Hard boundary patterns: positions where enumerators are structurally valid
# These appear BEFORE the enumerator position
_HARD_BOUNDARY_RE = re.compile(
    r"(?:"
    r"[;:]\s*\n"       # semicolon/colon + newline
    r"|[;:]\s+"         # semicolon/colon + whitespace
    r"|\.\s*\n"        # period + newline (sentence end)
    r")"
)


def check_anchor(
    position: int,
    text: str,
    line_starts: list[int],
    lookback: int = 20,
) -> bool:
    """Check if an enumerator at `position` satisfies the anchor constraint.

    True if:
    - Position is at the start of the text (position == 0)
    - Position is the first non-whitespace on a line
    - A hard boundary (``;\\n``, ``:\\n``, ``.\\n``) precedes within lookback chars
    """
    if position == 0:
        return True

    # Check line-start anchor (most common case)
    if is_at_line_start(position, line_starts, text):
        return True

    # Check hard boundary within lookback
    search_start = max(0, position - lookback)
    preceding = text[search_start:position]
    return bool(_HARD_BOUNDARY_RE.search(preceding))


# ---------------------------------------------------------------------------
# Scan all enumerator patterns
# ---------------------------------------------------------------------------

def scan_enumerators(
    text: str,
    line_starts: list[int] | None = None,
    *,
    deduplicate_alpha_roman: bool = True,
) -> list[EnumeratorMatch]:
    """Scan text for all enumerator patterns simultaneously.

    Returns all matches sorted by position, with anchor status computed.
    Does NOT apply run-length or gap constraints — that's the parser's job.

    Args:
        text: Text to scan for enumerator patterns.
        line_starts: Pre-computed line starts (optional, computed if None).
        deduplicate_alpha_roman: If True (default), when both alpha and roman
            match at the same position, keep only roman. Set False when
            the caller will handle disambiguation inline (e.g. clause_parser).
    """
    if line_starts is None:
        line_starts = compute_line_starts(text)

    matches: list[EnumeratorMatch] = []

    # Alpha: (a), (b), ..., (z), (aa)
    for m in _ALPHA_PAREN_RE.finditer(text):
        label = m.group(1).lower()
        ordinal = _alpha_ordinal(label)
        if ordinal > 0:
            matches.append(EnumeratorMatch(
                raw_label=m.group(0),
                ordinal=ordinal,
                level_type=LEVEL_ALPHA,
                position=m.start(),
                match_end=m.end(),
                is_anchored=check_anchor(m.start(), text, line_starts),
            ))

    # Roman: (i), (ii), ..., (xx)
    for m in _ROMAN_PAREN_RE.finditer(text):
        label = m.group(1).lower().strip()
        val = roman_to_int(label)
        if val is not None:
            matches.append(EnumeratorMatch(
                raw_label=m.group(0),
                ordinal=val,
                level_type=LEVEL_ROMAN,
                position=m.start(),
                match_end=m.end(),
                is_anchored=check_anchor(m.start(), text, line_starts),
            ))

    # Caps: (A), (B), ..., (Z)
    for m in _CAPS_PAREN_RE.finditer(text):
        label = m.group(1).upper()
        ordinal = _caps_ordinal(label)
        if ordinal > 0:
            matches.append(EnumeratorMatch(
                raw_label=m.group(0),
                ordinal=ordinal,
                level_type=LEVEL_CAPS,
                position=m.start(),
                match_end=m.end(),
                is_anchored=check_anchor(m.start(), text, line_starts),
            ))

    # Numeric: (1), (2), ..., (50)
    for m in _NUMERIC_PAREN_RE.finditer(text):
        num = int(m.group(1))
        if 1 <= num <= 50:
            matches.append(EnumeratorMatch(
                raw_label=m.group(0),
                ordinal=num,
                level_type=LEVEL_NUMERIC,
                position=m.start(),
                match_end=m.end(),
                is_anchored=check_anchor(m.start(), text, line_starts),
            ))

    # Period-delimited forms (secondary — only at line start)
    # These are inherently anchored (regex requires \n prefix), so
    # is_anchored is always True. We use the position of the label
    # character, not the leading whitespace.
    for m in _ALPHA_PERIOD_RE.finditer(text):
        label = m.group(2).lower()
        ordinal = _alpha_ordinal(label)
        if ordinal > 0:
            label_pos = m.start(2)
            matches.append(EnumeratorMatch(
                raw_label=f"{m.group(2)}.",
                ordinal=ordinal,
                level_type=LEVEL_ALPHA,
                position=label_pos,
                match_end=m.end(),
                is_anchored=True,
            ))

    for m in _ROMAN_PERIOD_RE.finditer(text):
        label = m.group(2).lower()
        val = roman_to_int(label)
        if val is not None:
            label_pos = m.start(2)
            matches.append(EnumeratorMatch(
                raw_label=f"{m.group(2)}.",
                ordinal=val,
                level_type=LEVEL_ROMAN,
                position=label_pos,
                match_end=m.end(),
                is_anchored=True,
            ))

    for m in _CAPS_PERIOD_RE.finditer(text):
        label = m.group(2).upper()
        ordinal = _caps_ordinal(label)
        if ordinal > 0:
            label_pos = m.start(2)
            matches.append(EnumeratorMatch(
                raw_label=f"{m.group(2)}.",
                ordinal=ordinal,
                level_type=LEVEL_CAPS,
                position=label_pos,
                match_end=m.end(),
                is_anchored=True,
            ))

    for m in _NUMERIC_PERIOD_RE.finditer(text):
        label = m.group(2)
        num = int(label)
        if 1 <= num <= 50:
            label_pos = m.start(2)
            matches.append(EnumeratorMatch(
                raw_label=f"{label}.",
                ordinal=num,
                level_type=LEVEL_NUMERIC,
                position=label_pos,
                match_end=m.end(),
                is_anchored=True,
            ))

    if deduplicate_alpha_roman:
        # Deduplicate: if both alpha and roman match at the same position,
        # keep only the roman match. Labels like (i), (ii), (v), (x) are valid
        # roman numerals and should be treated as roman by default.
        # disambiguate_i() may later convert roman (i) back to alpha (i)
        # based on context.
        roman_positions: set[int] = {
            m.position for m in matches if m.level_type == LEVEL_ROMAN
        }
        matches = [
            m for m in matches
            if not (m.level_type == LEVEL_ALPHA and m.position in roman_positions)
        ]

    # Sort by position, then by canonical depth (alpha < roman < caps < numeric)
    matches.sort(key=lambda m: (m.position, CANONICAL_DEPTH.get(m.level_type, 99)))
    return matches


# ---------------------------------------------------------------------------
# (i) disambiguation
# ---------------------------------------------------------------------------

def disambiguate_i(
    matches: list[EnumeratorMatch],
    lookahead_chars: int = 5000,
) -> list[EnumeratorMatch]:
    """Disambiguate ``(i)`` — is it alpha (ninth letter) or roman (first numeral)?

    Strategy (corpus-driven):
    1. If an alpha run is active and the last alpha ordinal < 9 (before 'h'),
       ``(i)`` cannot be the alpha continuation → treat as roman.
    2. If last alpha ordinal == 8 ('h'), check if ``(ii)`` follows within
       ``lookahead_chars``. If yes → roman; if no → alpha 'i'.
    3. If no alpha context, check if ``(ii)`` follows. If yes → roman.
       If no → skip (ambiguous).

    This function modifies the level_type of ambiguous matches in-place
    and returns the updated list.
    """
    result: list[EnumeratorMatch] = []

    # Find positions of all (ii) markers for quick lookup
    ii_positions: set[int] = set()
    for m in matches:
        if m.level_type == LEVEL_ROMAN and m.ordinal == 2:
            ii_positions.add(m.position)

    # Track the last alpha ordinal we've seen
    last_alpha_ordinal = 0

    for m in matches:
        if m.level_type == LEVEL_ALPHA:
            last_alpha_ordinal = m.ordinal

        # Only disambiguate when we have a match that could be either alpha (i) or roman (i)
        # Alpha (i) has ordinal 9, roman (i) has ordinal 1
        # The regex scanner may produce BOTH an alpha match and a roman match at the same position
        if m.level_type == LEVEL_ROMAN and m.ordinal == 1:
            # Check if there's a corresponding alpha match at this position
            # (i) matches both _ALPHA_PAREN_RE (label="i", ordinal=9) and
            # _ROMAN_PAREN_RE (label="i", ordinal=1)

            # Check if (ii) follows within lookahead
            has_ii_nearby = any(
                p > m.position and p - m.position <= lookahead_chars
                for p in ii_positions
            )

            if last_alpha_ordinal == 8:
                # Ambiguous: last alpha was (h)
                if has_ii_nearby:
                    # (ii) follows → roman
                    result.append(m)
                else:
                    # No (ii) → alpha (i)
                    result.append(EnumeratorMatch(
                        raw_label=m.raw_label,
                        ordinal=9,  # alpha ordinal for 'i'
                        level_type=LEVEL_ALPHA,
                        position=m.position,
                        match_end=m.match_end,
                        is_anchored=m.is_anchored,
                    ))
                    last_alpha_ordinal = 9
            elif 0 < last_alpha_ordinal < 8:
                # Alpha run active but before (h) → can't be alpha (i)
                result.append(m)  # Keep as roman
            else:
                # No alpha context
                if has_ii_nearby:
                    result.append(m)  # Roman
                else:
                    # Ambiguous with no context — keep as roman but mark unanchored
                    # so it gets demoted downstream
                    result.append(m)
        elif m.level_type == LEVEL_ALPHA and m.ordinal == 9:
            # This is the alpha interpretation of (i)
            # Check if we should skip it (roman interpretation was kept)
            # If roman (i) at the same position was already added, skip the alpha duplicate
            already_has_roman = any(
                r.position == m.position and r.level_type == LEVEL_ROMAN
                for r in result
            )
            if already_has_roman:
                continue  # Skip — roman interpretation was preferred
            result.append(m)
        else:
            result.append(m)

    return result


# ---------------------------------------------------------------------------
# Indentation scoring
# ---------------------------------------------------------------------------

def compute_indentation(position: int, text: str, line_starts: list[int]) -> float:
    """Compute indentation depth score (0.0-1.0) for an enumerator at `position`.

    Deeper indentation = higher score = more likely to be a nested child.
    Score is normalized: 0 spaces = 0.0, 20+ spaces = 1.0.
    """
    idx = bisect.bisect_right(line_starts, position) - 1
    if idx < 0:
        return 0.0
    line_start = line_starts[idx]
    leading = text[line_start:position]
    # Count leading whitespace (spaces and tabs, with tab = 4 spaces)
    indent = 0
    for ch in leading:
        if ch == " ":
            indent += 1
        elif ch == "\t":
            indent += 4
        else:
            break
    # Normalize: 0 spaces = 0.0, 20+ spaces = 1.0
    return min(indent / 20.0, 1.0)


# ---------------------------------------------------------------------------
# Module version
# ---------------------------------------------------------------------------
__version__ = "0.1.0"
