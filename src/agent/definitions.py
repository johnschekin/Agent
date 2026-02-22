"""5-engine defined term extractor for credit agreement text.

Extracts defined terms from credit agreement text (typically Section 1.01)
using 5 parallel regex engines:

1. Quoted pattern:        "Term" means...           (confidence 0.95)
2. Smart-quote pattern:   \u201cTerm\u201d means...           (confidence 0.93)
3. Parenthetical pattern: (the "Term")              (confidence 0.85)
4. Colon pattern:         Term: definition...        (confidence 0.70)
5. Unquoted pattern:      Term means...              (confidence 0.50)

Results are deduplicated by term name (case-insensitive, keeping highest
confidence) and returned sorted by char_start.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DefinedTerm:
    """A defined term extracted from the text."""

    term: str                # The defined term itself: "Indebtedness"
    definition_text: str     # The full definition text (up to 2000 chars)
    char_start: int          # Char offset of the term in source text
    char_end: int            # Char offset end of term
    def_start: int           # Char offset start of definition text
    def_end: int             # Char offset end of definition text
    pattern_engine: str      # Which engine found it
    confidence: float        # 0.0-1.0


# ---------------------------------------------------------------------------
# Engine priority (used for tie-breaking during deduplication)
# ---------------------------------------------------------------------------

_ENGINE_PRIORITY: dict[str, int] = {
    "quoted": 5,
    "smart_quote": 4,
    "parenthetical": 3,
    "colon": 2,
    "unquoted": 1,
}

# ---------------------------------------------------------------------------
# False-positive guard
# ---------------------------------------------------------------------------

_FALSE_POSITIVE_STARTERS: tuple[str, ...] = (
    "Section",
    "Article",
    "Exhibit",
    "Schedule",
    "Part",
    "Annex",
)

_FALSE_POSITIVE_PHRASES: tuple[str, ...] = (
    "provided that",
    "for the avoidance",
    "notwithstanding",
)


def _is_false_positive(term: str) -> bool:
    """Return True if *term* should be rejected as a false positive."""
    # Starts with structural headings
    for starter in _FALSE_POSITIVE_STARTERS:
        if term.startswith(starter):
            return True

    # All-caps single word under 4 chars (likely a stray acronym)
    if " " not in term and term.isupper() and len(term) < 4:
        return True

    # Contains disqualifying phrases (case-insensitive)
    term_lower = term.lower()
    for phrase in _FALSE_POSITIVE_PHRASES:
        if phrase in term_lower:
            return True

    # Over 80 chars
    if len(term) > 80:
        return True

    return False


# ---------------------------------------------------------------------------
# Definition-text extraction helper
# ---------------------------------------------------------------------------

# Matches the transition words that introduce a definition body.
_DEF_INTRO_RE = re.compile(
    r"\s*(?:means?|shall\s+mean|is\s+defined\s+as|has\s+the\s+meaning)\s*",
    re.IGNORECASE,
)

_MAX_DEF_LEN = 2000


def _extract_definition_text(
    text: str,
    after_pos: int,
) -> tuple[str, int, int]:
    """Extract the definition body starting at *after_pos*.

    Skips over the introductory verb phrase (e.g. "means ") and then captures
    text until one of:
      - a period followed by a blank line (paragraph break)
      - the start of another quoted/smart-quoted defined term pattern
      - 2000 characters

    Returns (definition_text, def_start, def_end) with offsets relative to
    the original *text*.
    """
    # Try to skip past the intro phrase ("means", "shall mean", etc.)
    intro_match = _DEF_INTRO_RE.match(text, after_pos)
    if intro_match:
        def_start = intro_match.end()
    else:
        # For colon patterns etc., just start right after the colon/space.
        def_start = after_pos

    # Determine the end of the definition text.
    remaining = text[def_start : def_start + _MAX_DEF_LEN]

    # End-sentinels: period + blank line, or next quoted defined term.
    # We look for the earliest sentinel.
    end_offset = len(remaining)

    # Sentinel 1: period followed by blank line (paragraph break)
    para_break = re.search(r"\.\s*\n\s*\n", remaining)
    if para_break:
        # Include the period itself
        end_offset = min(end_offset, para_break.start() + 1)

    # Sentinel 2: next quoted defined-term pattern (new definition starting)
    next_def = re.search(
        r'(?:^|\n)\s*["\u201c][A-Z]',
        remaining[1:],  # skip first char to avoid matching ourselves
    )
    if next_def:
        candidate = next_def.start() + 1  # +1 because we sliced at [1:]
        end_offset = min(end_offset, candidate)

    definition_text = remaining[:end_offset].rstrip()
    def_end = def_start + len(definition_text)

    return definition_text, def_start, def_end


# ---------------------------------------------------------------------------
# Engine 1: Quoted pattern  (confidence 0.95)
# ---------------------------------------------------------------------------

_QUOTED_DEF_RE = re.compile(
    r'"([A-Z][^"]{1,80}?)"\s*(?:means?|shall mean|is defined as|has the meaning)',
    re.MULTILINE,
)


def _engine_quoted(text: str, global_offset: int) -> list[DefinedTerm]:
    results: list[DefinedTerm] = []
    for m in _QUOTED_DEF_RE.finditer(text):
        term = m.group(1).strip()
        if _is_false_positive(term):
            continue

        char_start = m.start(1) + global_offset
        char_end = m.end(1) + global_offset

        definition_text, def_start, def_end = _extract_definition_text(
            text, m.end()
        )
        results.append(
            DefinedTerm(
                term=term,
                definition_text=definition_text,
                char_start=char_start,
                char_end=char_end,
                def_start=def_start + global_offset,
                def_end=def_end + global_offset,
                pattern_engine="quoted",
                confidence=0.95,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Engine 2: Smart-quote pattern  (confidence 0.93)
# ---------------------------------------------------------------------------

_SMART_QUOTE_DEF_RE = re.compile(
    r"\u201c([A-Z][^\u201d]{1,80}?)\u201d\s*(?:means?|shall mean|is defined as|has the meaning)",
    re.MULTILINE,
)


def _engine_smart_quote(text: str, global_offset: int) -> list[DefinedTerm]:
    results: list[DefinedTerm] = []
    for m in _SMART_QUOTE_DEF_RE.finditer(text):
        term = m.group(1).strip()
        if _is_false_positive(term):
            continue

        char_start = m.start(1) + global_offset
        char_end = m.end(1) + global_offset

        definition_text, def_start, def_end = _extract_definition_text(
            text, m.end()
        )
        results.append(
            DefinedTerm(
                term=term,
                definition_text=definition_text,
                char_start=char_start,
                char_end=char_end,
                def_start=def_start + global_offset,
                def_end=def_end + global_offset,
                pattern_engine="smart_quote",
                confidence=0.93,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Engine 3: Parenthetical pattern  (confidence 0.85)
# ---------------------------------------------------------------------------

_PAREN_DEF_RE = re.compile(
    r'\((?:the|each,?\s*(?:a|an)|collectively,?\s*the)\s*["\u201c]([A-Z][^"\u201d]{1,80}?)["\u201d]\)',
    re.MULTILINE,
)


def _engine_parenthetical(text: str, global_offset: int) -> list[DefinedTerm]:
    results: list[DefinedTerm] = []
    for m in _PAREN_DEF_RE.finditer(text):
        term = m.group(1).strip()
        if _is_false_positive(term):
            continue

        char_start = m.start(1) + global_offset
        char_end = m.end(1) + global_offset

        # For parenthetical definitions, the definition text is what
        # *precedes* the parenthetical (the sentence containing it).
        # We look backwards from the parenthetical to find the start of the
        # sentence, then forward to the end of the parenthetical.
        paren_start = m.start()
        # Walk backwards to find sentence start (period + space, or start of text)
        sentence_start = text.rfind(". ", 0, paren_start)
        if sentence_start == -1:
            # Try newline
            sentence_start = text.rfind("\n", 0, paren_start)
        if sentence_start == -1:
            sentence_start = 0
        else:
            sentence_start += 1  # skip the period/newline itself

        # The definition text spans from sentence_start up to and including
        # the closing parenthesis.
        def_text_raw = text[sentence_start : m.end()].strip()
        if len(def_text_raw) > _MAX_DEF_LEN:
            def_text_raw = def_text_raw[:_MAX_DEF_LEN]

        def_start = sentence_start + global_offset
        def_end = def_start + len(def_text_raw)

        results.append(
            DefinedTerm(
                term=term,
                definition_text=def_text_raw,
                char_start=char_start,
                char_end=char_end,
                def_start=def_start,
                def_end=def_end,
                pattern_engine="parenthetical",
                confidence=0.85,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Engine 4: Colon pattern  (confidence 0.70)
# ---------------------------------------------------------------------------

_COLON_DEF_RE = re.compile(
    r"(?:^|\.\s+)([A-Z][A-Za-z\s]{1,60}?):\s",
    re.MULTILINE,
)


def _engine_colon(text: str, global_offset: int) -> list[DefinedTerm]:
    results: list[DefinedTerm] = []
    for m in _COLON_DEF_RE.finditer(text):
        term = m.group(1).strip()
        if _is_false_positive(term):
            continue

        char_start = m.start(1) + global_offset
        char_end = m.end(1) + global_offset

        # Definition text starts after the ": "
        colon_end = m.end()
        definition_text, def_start, def_end = _extract_definition_text(
            text, colon_end
        )
        results.append(
            DefinedTerm(
                term=term,
                definition_text=definition_text,
                char_start=char_start,
                char_end=char_end,
                def_start=def_start + global_offset,
                def_end=def_end + global_offset,
                pattern_engine="colon",
                confidence=0.70,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Engine 5: Unquoted pattern  (confidence 0.50)
# ---------------------------------------------------------------------------

_UNQUOTED_DEF_RE = re.compile(
    r"(?:^|\n)\s*([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,5})\s+(?:means?|shall mean)",
    re.MULTILINE,
)


def _engine_unquoted(text: str, global_offset: int) -> list[DefinedTerm]:
    results: list[DefinedTerm] = []
    for m in _UNQUOTED_DEF_RE.finditer(text):
        term = m.group(1).strip()
        if _is_false_positive(term):
            continue

        char_start = m.start(1) + global_offset
        char_end = m.end(1) + global_offset

        definition_text, def_start, def_end = _extract_definition_text(
            text, m.end()
        )
        results.append(
            DefinedTerm(
                term=term,
                definition_text=definition_text,
                char_start=char_start,
                char_end=char_end,
                def_start=def_start + global_offset,
                def_end=def_end + global_offset,
                pattern_engine="unquoted",
                confidence=0.50,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate(terms: list[DefinedTerm]) -> list[DefinedTerm]:
    """Deduplicate by term name (case-insensitive).

    When multiple engines find the same term, keep the one with the highest
    confidence.  If confidence is tied, prefer the engine with higher
    priority (quoted > smart_quote > parenthetical > colon > unquoted).
    """
    best: dict[str, DefinedTerm] = {}
    for dt in terms:
        key = dt.term.lower()
        existing = best.get(key)
        if existing is None:
            best[key] = dt
        else:
            # Compare: higher confidence wins; ties broken by engine priority
            existing_priority = _ENGINE_PRIORITY.get(existing.pattern_engine, 0)
            new_priority = _ENGINE_PRIORITY.get(dt.pattern_engine, 0)
            if (dt.confidence, new_priority) > (
                existing.confidence,
                existing_priority,
            ):
                best[key] = dt
    return list(best.values())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_definitions(
    text: str,
    *,
    global_offset: int = 0,
) -> list[DefinedTerm]:
    """Extract all defined terms from text using 5 parallel engines.

    Runs all 5 engines, deduplicates by term name (keeping highest
    confidence), and returns sorted by char_start.

    Args:
        text: Normalized text (or section text).
        global_offset: Offset to add to all positions.

    Returns:
        List of DefinedTerm sorted by char_start.
    """
    all_terms: list[DefinedTerm] = []

    # Run all 5 engines
    all_terms.extend(_engine_quoted(text, global_offset))
    all_terms.extend(_engine_smart_quote(text, global_offset))
    all_terms.extend(_engine_parenthetical(text, global_offset))
    all_terms.extend(_engine_colon(text, global_offset))
    all_terms.extend(_engine_unquoted(text, global_offset))

    # Deduplicate
    deduped = _deduplicate(all_terms)

    # Sort by char_start
    deduped.sort(key=lambda dt: dt.char_start)

    return deduped


def find_term(text: str, term: str) -> DefinedTerm | None:
    """Find a specific defined term in text. Returns None if not found."""
    all_defs = extract_definitions(text)
    term_lower = term.lower()
    for dt in all_defs:
        if dt.term.lower() == term_lower:
            return dt
    return None


def extract_term_references(
    text: str,
    known_terms: list[str],
) -> list[tuple[str, int]]:
    """Find all references to known defined terms in text.

    Returns list of (term, char_offset) pairs.
    Useful for auto-unroll: finding which defined terms appear in a section.
    """
    references: list[tuple[str, int]] = []

    for term in known_terms:
        # Build a regex that matches the term as a whole word (case-sensitive,
        # since credit-agreement defined terms are always capitalised).
        pattern = re.compile(
            r"(?<![A-Za-z])"
            + re.escape(term)
            + r"(?![A-Za-z])",
        )
        for m in pattern.finditer(text):
            references.append((term, m.start()))

    # Sort by offset for deterministic output
    references.sort(key=lambda pair: pair[1])
    return references
