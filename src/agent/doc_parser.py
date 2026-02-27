"""Full-document outline: articles, sections, definitions, and xref resolution.

DocOutline is the authoritative structural index for a credit agreement.
It provides O(1) lookups by section number, article number, and defined term,
plus cross-reference resolution that returns Result[XrefSpan, XrefResolutionError]
instead of silently dropping failures.

Construction: 3-phase scan (articles → sections → definitions).
Xref parsing: Lark EBNF grammar for deterministic CFG parsing.

Ported from vantage_platform l0/_doc_parser.py — full version.
Only adaptations:
  - Import paths: agent.enumerator / agent.parsing_types (not vantage_platform)
  - ClauseTree resolution: uses agent.clause_parser (parse_clauses + resolve_path)

Usage::

    outline = DocOutline.from_text(text, filename="MyCA.htm")
    sec = outline.section("2.14")
    xref = outline.resolve_xref("Section 2.14(d)")
    defn = outline.definition_span("Incremental Amount")
"""

from __future__ import annotations

import importlib
import re
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast

# ---------------------------------------------------------------------------
# Dynamic Lark import — same pattern as infra/arrow.py for pyarrow.
# importlib returns ModuleType (known), getattr returns Any (not Unknown).
# ---------------------------------------------------------------------------
_lark_mod = importlib.import_module("lark")
_lark_exc = importlib.import_module("lark.exceptions")

_LarkClass: Any = _lark_mod.Lark
_TransformerBase: Any = _lark_mod.Transformer
_v_args_decorator: Any = _lark_mod.v_args
_UnexpectedInput: type[Exception] = _lark_exc.UnexpectedInput

from agent.enumerator import (
    LEVEL_ALPHA,
    LEVEL_CAPS,
    LEVEL_NUMERIC,
    LEVEL_ROMAN,
    int_to_roman,
    ordinal_for,
)
from agent.preemption import PreemptionEdge, PreemptionSummary, extract_preemption_edges, summarize_preemption
from agent.parsing_types import (
    Err,
    Ok,
    OutlineArticle,
    OutlineSection,
    ParsedXref,
    XrefResolutionError,
    XrefSpan,
)

# ---------------------------------------------------------------------------
# Roman numeral utilities
# ---------------------------------------------------------------------------

_ROMAN_MAP: dict[str, int] = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
    "XXI": 21, "XXII": 22, "XXIII": 23, "XXIV": 24, "XXV": 25,
}

_ROMAN_INV: dict[int, str] = {v: k for k, v in _ROMAN_MAP.items()}


def _roman_to_int(s: str) -> int | None:
    """Convert Roman numeral string to int, or None if invalid."""
    return _ROMAN_MAP.get(s.upper())


def _int_to_roman(n: int) -> str | None:
    """Convert int to Roman numeral string, or None if out of range."""
    return _ROMAN_INV.get(n)


# R6-fix F13: map for spelled-out article numbers
_WORD_NUM_MAP: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}


def _word_to_int(s: str) -> int | None:
    """Convert spelled-out number to int, or None if not recognized."""
    return _WORD_NUM_MAP.get(s.lower())


# ---------------------------------------------------------------------------
# Regex patterns — proven across 1,198 EDGAR CAs
# ---------------------------------------------------------------------------

# Article heading: "ARTICLE VII" or "Article 7"
# R6-fix F8: tolerate leading digits (page numbers) before ARTICLE keyword,
# e.g., "38 ARTICLE VII" from scanned PDFs where page numbers are embedded.
# R6-fix F13: extended to match spelled-out numbers ("ARTICLE ONE", "ARTICLE TWO").
_ARTICLE_RE = re.compile(
    r"(?:^|\n)\s*\d{0,3}\s*(?:ARTICLE|Article)\s+([IVX]+|\d+|[A-Za-z]+)\b",
)

# Top-level SECTION heading: "SECTION 1" / "SECTION 14" / "SECTION I" / "SECTION IV"
# (used instead of ARTICLE in some CAs, especially from certain law firms).
# Distinguished from section-level headings by having a bare integer or Roman numeral
# (no decimal), and by appearing in ALL CAPS.
# Heading capture is optional; some documents have the title on the next line.
# R5-fix: added [IVX]+ to match Roman numerals (e.g., "SECTION I", "SECTION IV").
_SECTION_TOPLEVEL_RE = re.compile(
    r"(?:^|\n)\s*SECTION\s+(\d+|[IVX]+)\.?\s+([A-Z][A-Z\s,&\-]+)?",
)

# Section heading (strict): "Section 2.14 Some Heading" or "SECTION 2.14: Heading"
# Heading capture stops at newline ([^\n]*) to prevent cross-paragraph matches.
# Post-processing in _detect_sections() truncates to 120 chars and strips punctuation.
# R2-fix: [^\S\n]* instead of \s* to prevent cross-line heading capture.
# R2-fix: heading is now optional (?: ... )? to recover sections with no heading text.
# R2-fix: (?:^|\n)\s* anchor prevents matching mid-sentence cross-references
# like "pursuant to Section 6.01 demonstrating compliance" (R2.A4.N01).
# R6-fix F5: added § symbol as a section keyword (used in some CAs instead of "Section").
# R6-fix F6: extended number capture to match Roman-dot-number format (e.g., "Section II.1").
# R6-fix F9: tolerate optional whitespace in section number (e.g., "Section 1. 01" from OCR).
# R6-fix F15: allow optional letter suffix on section numbers (e.g., "Section 2.01a").
# Block-2 Imp 22: added Sec\. and Sec\b as section keyword alternatives
# (occurs in older EDGAR filings).
_SECTION_STRICT_RE = re.compile(
    r"(?:^|\n)\s*(?:Section|SECTION|Sec\.|Sec\b|§)\s+(\d+\.\s?\d+[a-z]?|[IVX]+\.\s?\d+[a-z]?)[^\S\n]*[.:\s][^\S\n]*([A-Z][A-Za-z][^\n]*)?",
)

# Bare-number section pattern: many CAs (particularly BofA-style) use "X.XX Heading"
# without a "Section" keyword. Allows 1-2 digit minor numbers to capture both
# "2.01 Heading" (zero-padded) and "2.1 Heading" (single-digit) formats, while
# also tolerating longer minors and optional letter suffixes ("2.201a").
# Requires [A-Z][A-Za-z] heading text to avoid matching monetary amounts or ratios.
# Only used as a fallback when _SECTION_STRICT_RE finds insufficient sections.
_SECTION_BARE_RE = re.compile(
    r"(?:^|\n)\s*(\d+\.\d{1,3}[a-z]?)\.?\s+([A-Z][A-Za-z][^\n]*)",
)

# R6-fix F11: match letter-spaced "A R T I C L E" (HTML artifact from some EDGAR filings)
_ARTICLE_SPACED_RE = re.compile(
    r"(?:^|\n)\s*A\s+R\s+T\s+I\s+C\s+L\s+E\s+([IVX]+|\d+)\b",
)

# R7-fix: split-line article pattern — number on one line, ALL-CAPS title on next.
# Ported from TermIntelligence/recover_article_structure.py ARTICLE_SPLIT_RE.
# Captures CAs where EDGAR HTML formatting puts the article number and title on
# separate lines: "ARTICLE I\n  DEFINITIONS AND ACCOUNTING TERMS"
_ARTICLE_SPLIT_RE = re.compile(
    r"(?:^|\n)\s*(?:ARTICLE|Article)\s+([IVXLC]+|\d+)\s*\n+"
    r"\s*([A-Z][A-Z\s,;/&\-()]{2,80})"
    r"(?:\s*\n|$)",
    re.MULTILINE,
)

# Block-1.1 Fix A: alternative top-level heading patterns for non-standard CAs.
# "PART I", "Part II", "Part One" — UK-style and some US syndicated agreements.
_PART_ARTICLE_RE = re.compile(
    r"(?:^|\n)\s*(?:PART|Part)\s+([IVX]+|\d+|[A-Za-z]+)\b",
)

# "CHAPTER 1", "Chapter IV" — rare but seen in certain foreign-law governed CAs.
_CHAPTER_ARTICLE_RE = re.compile(
    r"(?:^|\n)\s*(?:CHAPTER|Chapter)\s+([IVX]+|\d+)\b",
)

# "CLAUSE 1", "Clause 14" — top-level divisions (not sub-clause enumeration).
# Only matches bare "Clause N" (no dot-separated minor numbers), distinguishing
# from "Clause 1.01" which is a section-level pattern.
_CLAUSE_TOPLEVEL_RE = re.compile(
    r"(?:^|\n)\s*(?:CLAUSE|Clause)\s+(\d+)\b(?!\.\d)",
)

# Block-1.1 Fix B: flat numbered section pattern for documents using
# "1. Definitions\n2. The Commitment\n..." instead of "Section X.YY".
# Only used as last-resort fallback when no articles AND no X.YY sections found.
# Guard: requires >= 5 matches after TOC filtering to avoid false positives
# from numbered body-text lists.
_SECTION_FLAT_RE = re.compile(
    r"(?:^|\n)\s*(\d{1,2})\.\s+([A-Z][A-Za-z][^\n]{0,120})",
)

# Block-2 Imp 7: standalone section number pattern — section number alone on a
# line with heading on the NEXT non-empty line. Common in some EDGAR filings
# where HTML formatting places number and title on separate lines.
# Validated with major <= 20 guard to avoid matching pricing grid values like "50.00".
# Ported from Neutron build_section_index.py:60-62 and TI section_level_parser.py:801-940.
_SECTION_STANDALONE_RE = re.compile(
    r"(?:^|\n)\s*([IVX]+\.\d{1,3}[a-z]?|\d{1,2}\.\d{1,3}[a-z]?)\s*\.?\s*$",
    re.MULTILINE,
)

# Block-2 Imp 8: reserved section detection — [RESERVED], [Reserved],
# [Intentionally Omitted] patterns returned as heading.
# Ported from TI section_level_parser.py:393-395.
_RESERVED_RE = re.compile(
    r"\[(?:RESERVED|Reserved|Intentionally Omitted|Intentionally omitted)\]",
)

# R7-fix: boilerplate phrases that indicate a false-positive title extraction.
# Ported from TermIntelligence/recover_article_structure.py _BOILERPLATE_MARKERS.
# If ANY of these appear in a candidate title, it's body text, not a heading.
# Note: only include words that are NEVER part of valid article headings.
# Removed "APPLICABLE" (appears in "APPLICABLE MARGIN"), "CLAUSE" (appears
# in "MOST FAVORED NATION CLAUSE"), "PROVISION" (appears in "GENERAL PROVISIONS").
_BOILERPLATE_MARKERS = frozenset({
    "HEREIN", "THEREOF", "THEREIN", "PROVIDED", "SHALL", "PURSUANT",
    "HEREUNDER", "NOTWITHSTANDING", "FOREGOING", "EXPRESSLY", "CONSUMMATION",
    "VOIDABLE", "RATABLY", "REGARDLESS", "ELSEWHERE",
})

# R6-fix F14: detect exhibit/schedule/signature boundaries that follow the
# last article. The last article/section should NOT extend into these regions.
_EXHIBIT_BOUNDARY_RE = re.compile(
    r"(?:^|\n)\s*(?:EXHIBIT|Exhibit|SCHEDULE|Schedule)\s+[A-Z0-9]",
)
_SIGNATURE_BOUNDARY_RE = re.compile(
    r"(?:^|\n)\s*(?:IN WITNESS WHEREOF|SIGNATURE PAGE|EXECUTION PAGE)",
    re.IGNORECASE,
)

# Definition: "Term" means or \u201cTerm\u201d means (smart-quote agnostic)
# Handles HTML whitespace artifacts: spaces/newlines between/around quotes.
# Terms can start with uppercase OR digit (e.g., "1 Stop", "2022 Refinancing").
# EDGAR CAs often have: \u201c SPACE term SPACE \u201d NEWLINE means
# R2-fix: added :, ; and start-of-string as valid preceding context (not just \n or .)
# R4-fix: added colon-style definitions ("Term": definition text) used by some
# law firms (Simpson Thacher, Cahill Gordon, SVB-style agreements).
_DEF_RE = re.compile(
    r'(?:^|\n|[.:;]\s*)\s*["\u201c]\s*([A-Z0-9][A-Za-z0-9\s\-/,()\'\.]+?)\s*["\u201d]'
    r"\s*(?:means|shall\s+mean|has\s+the\s+meaning|(?:is|are)\s+defined\s+in|:)",
    re.IGNORECASE | re.DOTALL,
)

# R6-fix F10 / R7-fix: unquoted definitions fallback.
# Ported from TermIntelligence RE_DEFINITION_UNQUOTED with improvements:
# - Title Case terms (each significant word capitalised)
# - 0-7 additional words (supports multi-word terms like "Consolidated Adjusted EBITDA")
# - Followed by period + definition-starting word or "means/shall mean" keyword
# - False-positive exclusion set for common sentence starters
# Only activated when unquoted_count >= 20 and > 2x quoted count (see _build_definition_index).
_DEF_UNQUOTED_RE = re.compile(
    r"(?:^|(?<=\. )|(?<=\n))"
    r"([A-Z][a-zA-Z]+(?:\s+(?:[A-Z][a-zA-Z]+|of|the|and|or|for|in|to|a|an|on|by|as|with|at|de|du|per|non|sub|pre|co|re|un))+)"
    r"\s*\.\s+"
    r"(?:The |An? |Each |Any |All |With respect|For (?:any|the|purposes)|[Mm]eans? |[Ss]hall (?:mean|have)|[Hh]as the meaning)",
)

# R7-fix: False-positive exclusions for unquoted definitions.
# Ported from TermIntelligence _UNQUOTED_FALSE_POS.
_UNQUOTED_FALSE_POS = frozenset({
    "The", "In", "If", "No", "An", "At", "As", "To", "On", "By",
    "For", "Each", "Any", "All", "Such", "Subject", "Section", "Article",
    "Notwithstanding", "Without", "Except", "Upon", "Unless", "Pursuant",
    "Including", "Provided", "Exhibit", "Schedule", "Table", "Date",
})

# R7-fix: simple "Term means ..." pattern for fallback when no quoted or
# TermIntelligence-style unquoted definitions found. Simpler than _DEF_UNQUOTED_RE
# but still useful as a last-resort fallback.
_DEF_UNQUOTED_SIMPLE_RE = re.compile(
    r"(?:^|\n)\s*((?:[A-Z][A-Za-z\-]*\s+){0,4}[A-Z][A-Za-z\-]*)"
    r"\s+(?:means|shall\s+mean|has\s+the\s+meaning)\b",
)

# TOC detection patterns
_TOC_HEADER_RE = re.compile(r"TABLE\s+OF\s+CONTENTS", re.IGNORECASE)
# R2-fix: match both dot-leader page numbers (". 38") and standalone page numbers
# at end of line ("38", " 202 "). EDGAR HTML tables use both formats.
# R5-fix: require 2+ digits for standalone page numbers (\d{2,3}) to avoid matching
# single-digit section numbers (e.g., "1" from "1.1" split across lines).
# Dot-leader page numbers (". 3") still allow 1+ digits since the dot-leader
# is a strong TOC signal that section numbers don't have.
_PAGE_NUM_RE = re.compile(r"(?:(?<!\d)\.\s*\d{1,3}\s*$|\b\d{2,3}\s*$)", re.MULTILINE)

# Xref scanner: finds "Section X.YY" references in text (for xref graph building)
_XREF_SCAN_RE = re.compile(
    r"(?:Section|Sections)\s+(\d+\.\d+)"
    r"((?:\s*\([a-zA-Z0-9ivxlc]+\))*)"  # Optional clause path
    r"((?:\s*(?:,|and|or|through)\s+"
    r"(?:(?:Section|Sections)\s+)?(?:\d+\.\d+)?"
    r"(?:\([a-zA-Z0-9ivxlc]+\))*)*)",  # Conjunctions
    re.IGNORECASE,
)

# Xref intent classification phrases
_XREF_INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("incorporation", re.compile(r"(?:as\s+set\s+forth\s+in|as\s+provided\s+in|pursuant\s+to)", re.IGNORECASE)),
    ("condition", re.compile(r"(?:subject\s+to|provided\s+that|conditioned\s+upon)", re.IGNORECASE)),
    ("definition", re.compile(r"(?:as\s+defined\s+in|has\s+the\s+meaning|the\s+meaning\s+(?:set\s+forth|assigned))", re.IGNORECASE)),
    ("exception", re.compile(r"(?:other\s+than|excluding|except\s+(?:as|for|to))", re.IGNORECASE)),
    ("amendment", re.compile(r"(?:as\s+amended\s+by|as\s+modified\s+by|as\s+supplemented\s+by)", re.IGNORECASE)),
    # Block-2 Imp 18: additional contextual reference patterns from Neutron
    ("compliance", re.compile(r"(?:in\s+accordance\s+with|in\s+compliance\s+with)", re.IGNORECASE)),
    ("reference", re.compile(r"(?:referenced\s+in|referred\s+to\s+in|specified\s+in)", re.IGNORECASE)),
    ("restriction", re.compile(r"(?:required\s+(?:by|under|pursuant\s+to)|permitted\s+(?:by|under))", re.IGNORECASE)),
]

# Keyword-to-concept mapping (from structure_extraction.py, proven across corpus)
_KEYWORD_CONCEPT_MAP: dict[str, str] = {
    "definition": "definitions",
    "accounting": "definitions",
    "credit": "credits",
    "commitment": "credits",
    "repayment": "repayment",
    "prepayment": "repayment",
    "loan": "loans_facility",
    "yield protection": "yield_protection",
    "increased cost": "yield_protection",
    "letter": "lc_facility",
    "payment": "payments_general",
    "interest rate": "interest_rates_standalone",
    "condition": "conditions",
    "reserved": "reserved",
    "representation": "reps_warranties",
    "warrant": "reps_warranties",
    "affirmative": "affirmative_covenants",
    "negative covenant": "negative_covenants",
    "restrictive covenant": "negative_covenants",
    "financial covenant": "financial_covenants",
    "event of default": "events_of_default",
    "default": "events_of_default",
    "agent": "agent_provisions",
    "administrative": "agent_provisions",
    "amendment": "amendments",
    "waiver": "amendments",
    "indemnification": "indemnification",
    "indemnity": "indemnification",
    "setoff": "setoff",
    "guaranty": "guaranty",
    "guarantee": "guaranty",
    "pledge": "pledge",
    "security": "security_collateral",
    "collateral": "security_collateral",
    "assignment": "assignments",
    "participation": "assignments",
    "governing law": "governing_law",
    "jurisdiction": "governing_law",
    "miscellaneous": "miscellaneous",
    "general provision": "miscellaneous",
    "interpretation": "definitions",  # R2-fix: UK-style definitions articles
    "bail-in": "bail_in",
    "bail in": "bail_in",
    "borrower representative": "borrower_representative",
    "incremental": "incremental",
    "indebtedness": "indebtedness",
    "lien": "liens",
    "restricted payment": "restricted_payments",
    "investment": "investments",
    "disposition": "dispositions",
    "fundamental change": "fundamental_changes",
    "restricted debt": "restricted_debt_payments",
}


def _title_to_concept(title: str) -> str | None:
    """Map article title to concept via keyword matching."""
    lower = title.lower().strip()
    for keyword, concept in _KEYWORD_CONCEPT_MAP.items():
        if keyword in lower:
            return concept
    return None


# ---------------------------------------------------------------------------
# Title normalisation and validation
# Ported from TermIntelligence/recover_article_structure.py
# ---------------------------------------------------------------------------

def _normalise_title(title: str) -> str:
    """Clean up extracted title text.

    Ported from TermIntelligence with adaptations:
    - Removes trailing punctuation
    - Collapses internal whitespace
    - Removes leading numbering artifacts
    - Fixes exploded text (D EFINITIONS → DEFINITIONS)
    """
    # Remove trailing periods, colons, whitespace
    title = re.sub(r"[\s.:;,]+$", "", title.strip())
    # Collapse internal whitespace
    title = re.sub(r"\s+", " ", title)
    # Remove leading numbering artifacts (e.g., "1. DEFINITIONS")
    title = re.sub(r"^\d+\s*[.:]\s*", "", title)
    # Fix exploded text (D EFINITIONS → DEFINITIONS, M ISCELLANEOUS → MISCELLANEOUS)
    title = re.sub(r"\b([A-Z])\s([A-Z]{3,})\b", lambda m: m.group(1) + m.group(2), title)
    return title


def _is_valid_title(title: str) -> bool:
    """Check if an extracted title looks like a real article heading.

    Ported from TermIntelligence with adaptations. Rejects boilerplate
    legal phrases, mid-sentence captures, and self-referential titles.
    """
    if not title or len(title) < 3:
        return False
    if len(title) > 120:
        return False
    if len(title.split()) > 15:
        return False
    # Contains boilerplate legal language (whole-word matching to avoid
    # false positives: "PROVISION" should not reject "GENERAL PROVISIONS")
    title_upper = title.upper()
    title_upper_words = set(title_upper.split())
    if title_upper_words & _BOILERPLATE_MARKERS:
        return False
    # Starts with conjunction or punctuation (mid-sentence capture)
    if title_upper.startswith(("OR ", "AND ", "BUT ", "; ", ", ", "(", ")")):
        return False
    # Just a Roman numeral or single letter
    if re.match(r"^[IVXLC]+$", title.strip()):
        return False
    if len(title.strip()) <= 2:
        return False
    # Self-referential (e.g., "ARTICLE X", "ARTICLE III")
    if re.match(r"^ARTICLE\s+[IVXLC\d]+$", title_upper):
        return False
    return True


# ---------------------------------------------------------------------------
# TOC detection
# ---------------------------------------------------------------------------

def heading_quality(heading: str) -> int:
    """Score heading quality on a 3-tier scale.

    Returns:
        2 — proper heading (starts with uppercase letter or bracket)
        1 — empty heading (may be on next line)
        0 — garbage heading (starts with comma, semicolon, lowercase,
            sub-clause marker, or contains sentence-like body text)

    Used by section deduplication to prefer entries with better headings
    and by TOC dedup to decide whether to inherit a heading from a TOC entry.

    Ported from Neutron build_section_index.py:194-211 and
    VP _doc_parser.py:1011-1032 heading quality scoring.
    """
    if not heading or not heading.strip():
        return 1  # empty — acceptable, heading may be on next line

    h = heading.strip()

    # Garbage indicators: starts with body-text patterns
    if h[0] in (",", ";", "("):
        return 0
    if h[0].islower():
        return 0

    # Sentence-like body text detection (from VP):
    # If > 60% of words are lowercase content words, it's likely body text
    words = h.split()
    if len(words) > 5:
        lowercase_content = sum(
            1 for w in words
            if w[0].islower() and w.lower() not in ("of", "and", "or", "the", "to", "for", "in", "by", "with", "on", "a", "an")
        )
        if lowercase_content > len(words) * 0.6:
            return 0

    # Contains parenthetical clause references (body text, not heading)
    if re.search(r"\([a-z]\)\s*\([ivx]+\)", h):
        return 0

    # Proper heading: starts with uppercase or bracket
    if h[0].isupper() or h[0] == "[":
        return 2

    return 0


# ---------------------------------------------------------------------------
# Block-2 Imp 16: Section canonical naming
# ---------------------------------------------------------------------------


def section_canonical_name(heading: str) -> str:
    """Derive a canonical section name from its heading.

    Canonical name: lowercase, stripped, punctuation-collapsed.
    Useful for fuzzy matching across documents (e.g., "Indebtedness"
    and "INDEBTEDNESS" both become "indebtedness").
    """
    h = str(heading or "").strip().lower()
    if not h:
        return ""
    # Keep alnum + semantic separators (dot/underscore), drop other punctuation.
    h = re.sub(r"[^a-z0-9._\s]+", " ", h)
    # Normalize repeated separators and whitespace.
    h = re.sub(r"\s+", " ", h)
    return h.strip().strip(".")


def section_reference_key(doc_id: str, section_number: str) -> str:
    """Build a section reference key: ``{doc_id}:{section_number}``."""
    return f"{doc_id}:{str(section_number or '').strip()}"


# ---------------------------------------------------------------------------
# Block-2 Imp 17: Content-addressed chunk IDs
# ---------------------------------------------------------------------------

import hashlib as _hashlib


def section_text_hash(text: str, start: int, end: int) -> str:
    """SHA-256 of an anchored text span (full lowercase hex digest)."""
    return _hashlib.sha256(text[start:end].encode()).hexdigest()


def compute_chunk_id(
    document_id: str,
    section_reference_key: str,
    clause_key: str,
    span_start: int,
    span_end: int,
    text_sha256: str,
) -> str:
    """Wave 3 chunk identity hash.

    Format:
    sha256(``document_id|section_reference_key|clause_key|span_start|span_end|text_sha256``)
    """
    payload = (
        f"{document_id}|{section_reference_key}|{clause_key}|"
        f"{int(span_start)}|{int(span_end)}|{text_sha256}"
    )
    return _hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Block-2 Imp 21: Section path normalization
# ---------------------------------------------------------------------------


def section_path(article_num: int, section_number: str) -> str:
    """Build a normalized section path.

    Format: ``{article_num}.{section_number}`` when article is known,
    otherwise just ``{section_number}``.

    Round-trip invariant: ``section_path(a, n)`` always produces the same
    string for the same inputs.
    """
    if article_num > 0:
        return f"{article_num}.{section_number}"
    return section_number


def parse_section_path(path: str) -> tuple[int, str]:
    """Parse a section path back to (article_num, section_number).

    Inverse of ``section_path()``.  Returns ``(0, path)`` for paths without
    an article prefix.
    """
    parts = path.split(".", 2)
    if len(parts) >= 3:
        try:
            art = int(parts[0])
            return (art, f"{parts[1]}.{parts[2]}")
        except ValueError:
            pass
    return (0, path)


# ---------------------------------------------------------------------------
# Block-2 Imp 19: Plural/range reference patterns
# ---------------------------------------------------------------------------

# "Sections 2.01 and 2.02", "Sections 2.01, 2.02, and 2.03"
SECTION_PLURAL_RE = re.compile(
    r"\bSections\s+(\d+(?:\.\d+)*)"
    r"\s*(?:,\s*(\d+(?:\.\d+)*))?"
    r"\s*(?:,?\s*and\s+(\d+(?:\.\d+)*))?",
    re.IGNORECASE,
)

# "Sections 2.01 through 2.05", "Section 2.01 to 2.10"
SECTION_RANGE_RE = re.compile(
    r"\bSections?\s+(\d+(?:\.\d+)*)\s*(?:through|to|-)\s*(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

# "Articles I through V", "Articles I-V"
ARTICLE_RANGE_RE = re.compile(
    r"\bArticles?\s+([IVXLCDM]+|\d+)\s*(?:through|to|-)\s*([IVXLCDM]+|\d+)",
    re.IGNORECASE,
)


def extract_plural_sections(text: str) -> list[str]:
    """Extract all section numbers from plural references in text.

    Handles "Sections 2.01 and 2.02" and "Sections 2.01, 2.02, and 2.03".
    Returns a flat list of section number strings.
    """
    results: list[str] = []
    for m in SECTION_PLURAL_RE.finditer(text):
        for g in m.groups():
            if g:
                results.append(g)
    return results


def extract_section_range(text: str) -> list[tuple[str, str]]:
    """Extract section ranges from text.

    Returns list of (start, end) tuples from "Sections X through Y".
    """
    return [(m.group(1), m.group(2)) for m in SECTION_RANGE_RE.finditer(text)]


def _is_toc_entry(
    text: str,
    match_start: int,
    match_end: int,
    *,
    min_signals: int = 1,
) -> bool:
    """Detect if a heading match is a Table of Contents entry.

    Proven heuristic across 1,198 EDGAR CAs. Uses content-based signals
    rather than a fixed position threshold (which fails for large CAs
    where the TOC can extend beyond 8% of the document).

    Key insight: TOC entries have page numbers and section listings in
    dense, table-like formatting. Body headings are followed by prose text.

    Block-1.1 Fix C: added ``min_signals`` parameter. Default 1 preserves
    legacy behaviour (any single signal rejects). TOC recovery path uses
    ``min_signals=2`` so that a heading needs 2+ independent signals to be
    classified as TOC — reducing over-rejection in borderline cases.
    """
    signal_count = 0

    # Signal 1: "TABLE OF CONTENTS" header is close (within 3K chars).
    # We search up to 15K back to find the header, but only fire if the
    # actual distance from the end of the header to this match is < 3K chars.
    # Beyond 3K from the TOC header, rely on Signals 3-5 for detection.
    # This prevents false positives on body Article I which typically appears
    # 5K-200K chars after the TOC header.
    doc_prefix = text[max(0, match_start - 15000):match_start]
    toc_match = _TOC_HEADER_RE.search(doc_prefix)
    if toc_match:
        distance_from_toc = len(doc_prefix) - toc_match.end()
        if distance_from_toc < 3000:
            signal_count += 1
            if signal_count >= min_signals:
                return True

    # Signal 2: Dense section number clustering in ±200 chars.
    # Requires "Section" prefix to avoid matching financial ratios like "5.00 to 1.00".
    # R2-fix: lowered threshold from >8 to >6 (HTML whitespace dilutes density).
    # Additional density check: in real TOC, refs are closely packed (median gap <80
    # chars); in body text near article boundaries, refs are spread across prose.
    ctx_start = max(0, match_start - 200)
    ctx_end = min(len(text), match_end + 200)
    context = text[ctx_start:ctx_end]
    section_ref_matches = list(
        re.finditer(r"Section\s+\d+\.\d+", context, re.IGNORECASE)
    )
    if len(section_ref_matches) > 6:
        # High count (7+): verify refs are densely packed (TOC-like), not
        # scattered across prose paragraphs near article boundaries.
        gaps: list[int] = []
        for i in range(1, len(section_ref_matches)):
            gaps.append(
                section_ref_matches[i].start() - section_ref_matches[i - 1].end()
            )
        median_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0
        if median_gap < 80:
            signal_count += 1
            if signal_count >= min_signals:
                return True

    # Signal 3: Page number patterns (dot-leader or standalone numbers at line end)
    page_nums = _PAGE_NUM_RE.findall(context)
    if len(page_nums) >= 2:
        signal_count += 1
        if signal_count >= min_signals:
            return True

    # Signal 4: Pipe-separated page numbers (EDGAR HTML table formatting)
    # TOC lines look like: "Defined Terms | 1 |" or "Section 2.14 | 38 |"
    pipe_page_nums = re.findall(r"\|\s*\d{1,3}\s*\|", context)
    if len(pipe_page_nums) >= 2:
        signal_count += 1
        if signal_count >= min_signals:
            return True

    # Signal 5: Very short lines clustered together (TOC layout)
    # Check the next 500 chars for line length pattern.
    # Threshold: lines < 50 chars (not 80) — in HTML-converted CAs, prose paragraphs
    # are single long lines (200+ chars), while TOC entries are typically 20-45 chars.
    # R6-fix F12: raised threshold from 6→7 short lines AND require no lines > 100 chars
    # in the window. Body ARTICLE headings followed by section headings look short-lined,
    # but unlike real TOC, they are eventually followed by long prose paragraphs.
    after_text = text[match_end:match_end + 500]
    lines = after_text.split("\n")
    non_empty = [line for line in lines[:10] if line.strip()]
    short_lines = sum(1 for line in non_empty if len(line.strip()) < 50)
    has_long_line = any(len(line.strip()) > 100 for line in non_empty)
    if short_lines >= 7 and len(non_empty) >= 8 and not has_long_line:
        signal_count += 1
        if signal_count >= min_signals:
            return True

    return False


# ---------------------------------------------------------------------------
# Lark grammar for cross-reference parsing
# ---------------------------------------------------------------------------

# Formal EBNF grammar for contract cross-references.
# Handles: single refs, conjunctions, ranges, clause-only refs, conditionals.
XREF_GRAMMAR = r"""
    start: ref_list
    ref_list: ref (CONJ ref)*
    ref: section_ref clause_path?       -> section_first_ref
       | SECTION_NUM clause_path?       -> bare_num_ref
       | clause_path OF section_ref     -> clause_first_ref
       | clause_path                    -> bare_clause_ref
    section_ref: SECTION_KW SECTION_NUM
    clause_path: clause_label+
    clause_label: "(" ENUM_TOKEN ")"
    OF: "of"i
    SECTION_KW: /Sections?/i
    SECTION_NUM: /\d+\.\d+/
    ENUM_TOKEN: /[a-z]+/i | /\d+/
    CONJ: /(?:,\s*)?and/i | /(?:,\s*)?or/i | "," | /through/i
    %ignore /\s+/
"""

# S3+M2: Lazy-initialized parser. Prefer LALR for speed; fall back to Earley
# if a grammar/library change introduces conflicts on a specific runtime.
_xref_parser: Any = None


def _get_xref_parser() -> Any:
    """Return the singleton Lark parser, creating it on first call."""
    global _xref_parser
    if _xref_parser is None:
        try:
            _xref_parser = _LarkClass(XREF_GRAMMAR, parser="lalr")
        except Exception:
            _xref_parser = _LarkClass(XREF_GRAMMAR, parser="earley", ambiguity="resolve")
    return _xref_parser


def _expand_clause_range(start_ref: ParsedXref, end_ref: ParsedXref) -> list[ParsedXref]:
    """Expand a range like '(d) through (g)' into [(d), (e), (f), (g)].

    Handles alpha, roman, caps, and numeric ranges. If the range endpoints
    are incompatible or expansion fails, returns just the two endpoints.
    """
    # Use the section_num from whichever ref has one (or prefer start_ref)
    section_num = start_ref.section_num or end_ref.section_num

    # Get the varying clause labels (the last one in the path differs)
    start_path = start_ref.clause_path
    end_path = end_ref.clause_path

    # Common case: same-depth paths like (d)→(g) or (a)(i)→(a)(iv)
    # The shared prefix stays the same; the last element varies
    if not start_path or not end_path:
        # Section-level range (e.g., "7.01 through 7.05") — can't expand
        # without knowing which sections exist, so return both endpoints
        return [
            ParsedXref(section_num=start_ref.section_num, clause_path=start_path, ref_type="range"),
            ParsedXref(section_num=end_ref.section_num, clause_path=end_path, ref_type="range"),
        ]

    # Extract the varying part: last clause label
    # If paths differ in length, use the shorter common prefix
    if len(start_path) != len(end_path):
        return [
            ParsedXref(section_num=section_num, clause_path=start_path, ref_type="range"),
            ParsedXref(section_num=section_num, clause_path=end_path, ref_type="range"),
        ]

    # Find the position where the paths diverge
    prefix: list[str] = []
    for s, e in zip(start_path, end_path):
        if s == e:
            prefix.append(s)
        else:
            break

    # The varying labels are from divergence point onward
    start_suffix = start_path[len(prefix):]
    end_suffix = end_path[len(prefix):]

    # We can only expand single-label suffixes: (d)→(g), not (d)(i)→(g)(iii)
    if len(start_suffix) != 1 or len(end_suffix) != 1:
        return [
            ParsedXref(section_num=section_num, clause_path=start_path, ref_type="range"),
            ParsedXref(section_num=section_num, clause_path=end_path, ref_type="range"),
        ]

    # Parse the labels to determine type and ordinals
    start_label = start_suffix[0].strip("()")
    end_label = end_suffix[0].strip("()")

    # Try each type to find a match
    for level_type in [LEVEL_ALPHA, LEVEL_ROMAN, LEVEL_CAPS, LEVEL_NUMERIC]:
        start_ord = ordinal_for(level_type, start_label)
        end_ord = ordinal_for(level_type, end_label)
        if start_ord > 0 and end_ord > 0 and end_ord > start_ord:
            # Generate intermediate labels
            expanded: list[ParsedXref] = []
            for ord_val in range(start_ord, end_ord + 1):
                if level_type == LEVEL_ALPHA:
                    lbl = chr(ord("a") + ord_val - 1) if ord_val <= 26 else None
                elif level_type == LEVEL_ROMAN:
                    lbl = int_to_roman(ord_val)
                elif level_type == LEVEL_CAPS:
                    lbl = chr(ord("A") + ord_val - 1) if ord_val <= 26 else None
                elif level_type == LEVEL_NUMERIC:
                    lbl = str(ord_val)
                else:
                    lbl = None
                if lbl is None:
                    break
                path = tuple(prefix) + (f"({lbl})",)
                expanded.append(ParsedXref(
                    section_num=section_num,
                    clause_path=path,
                    ref_type="range",
                ))
            if expanded:
                return expanded

    # Fallback: return both endpoints
    return [
        ParsedXref(section_num=section_num, clause_path=start_path, ref_type="range"),
        ParsedXref(section_num=section_num, clause_path=end_path, ref_type="range"),
    ]


@_v_args_decorator(inline=True)
class XrefTransformer(_TransformerBase):
    """Transform Lark parse tree into list[ParsedXref]."""

    def start(self, ref_list: list[ParsedXref]) -> list[ParsedXref]:
        return ref_list

    def ref_list(self, *args: Any) -> list[ParsedXref]:
        """Collect refs, expanding 'through' ranges into intermediate refs."""
        # Separate refs and conjunctions in order
        items: list[ParsedXref | str] = []
        for arg in args:
            if isinstance(arg, (list, tuple)) and not isinstance(arg, ParsedXref):
                for item in cast(list[Any], arg):
                    if isinstance(item, (ParsedXref, str)):
                        items.append(item)
            elif isinstance(arg, (ParsedXref, str)):
                items.append(arg)

        # Walk items: when we see "through" between two refs, expand the range
        refs: list[ParsedXref] = []
        i = 0
        while i < len(items):
            item = items[i]
            if isinstance(item, str) and item == "through":
                # "through" connector: expand range between previous ref and next ref
                next_item = items[i + 1] if i + 1 < len(items) else None
                if refs and isinstance(next_item, ParsedXref):
                    prev_ref = refs.pop()
                    refs.extend(_expand_clause_range(prev_ref, next_item))
                    i += 2
                    continue
            elif isinstance(item, ParsedXref):
                refs.append(item)
            i += 1
        return refs

    def section_first_ref(self, *args: Any) -> ParsedXref | list[ParsedXref]:
        section_num = ""
        clause_labels: tuple[str, ...] = ()
        for arg in args:
            if isinstance(arg, str) and "." in arg:
                section_num = arg
            elif isinstance(arg, tuple):
                clause_labels = tuple(str(x) for x in cast(tuple[Any, ...], arg))
        return ParsedXref(
            section_num=section_num,
            clause_path=tuple(f"({c})" for c in clause_labels),
            ref_type="single",
        )

    def bare_num_ref(self, *args: Any) -> ParsedXref:
        """Handle bare section numbers in conjunctions (e.g., '7.11' in 'Sections 2.14 and 7.11')."""
        section_num = ""
        clause_labels: tuple[str, ...] = ()
        for arg in args:
            if isinstance(arg, str) and "." in arg:
                section_num = arg
            elif isinstance(arg, tuple):
                clause_labels = tuple(str(x) for x in cast(tuple[Any, ...], arg))
        return ParsedXref(
            section_num=section_num,
            clause_path=tuple(f"({c})" for c in clause_labels),
            ref_type="single",
        )

    def clause_first_ref(self, *args: Any) -> ParsedXref:
        section_num = ""
        clause_labels: tuple[str, ...] = ()
        for arg in args:
            if isinstance(arg, str) and "." in arg:
                section_num = arg
            elif isinstance(arg, tuple):
                clause_labels = tuple(str(x) for x in cast(tuple[Any, ...], arg))
        return ParsedXref(
            section_num=section_num,
            clause_path=tuple(f"({c})" for c in clause_labels),
            ref_type="single",
        )

    def bare_clause_ref(self, *args: Any) -> ParsedXref:
        """Handle bare clause paths like '(g)' in 'Section 2.14(d) through (g)'.

        Section number is empty — the range expander inherits it from context.
        """
        clause_labels: tuple[str, ...] = ()
        for arg in args:
            if isinstance(arg, tuple):
                clause_labels = tuple(str(x) for x in cast(tuple[Any, ...], arg))
        return ParsedXref(
            section_num="",
            clause_path=tuple(f"({c})" for c in clause_labels),
            ref_type="single",
        )

    def section_ref(self, *args: Any) -> str:
        for arg in args:
            if isinstance(arg, str) and "." in arg:
                return arg
        return ""

    def clause_path(self, *args: str) -> tuple[str, ...]:
        return args

    def clause_label(self, token: str) -> str:
        return str(token)

    def SECTION_NUM(self, token: Any) -> str:
        return str(token)

    def ENUM_TOKEN(self, token: Any) -> str:
        return str(token)

    def SECTION_KW(self, _token: Any) -> None:
        return None

    def OF(self, _token: Any) -> None:
        return None

    def CONJ(self, token: Any) -> str:
        return str(token).strip().strip(",").strip().lower()


_xref_transformer = XrefTransformer()


def parse_xref(text: str) -> list[ParsedXref]:
    """Parse cross-reference text into structured ParsedXref objects.

    Handles single refs, conjunctions, ranges, and clause-only refs.
    Falls back to regex for patterns the grammar can't handle.

    Args:
        text: Cross-reference string like "Section 2.14(d)(iv)" or
              "Sections 2.14, 7.11 and 7.12".

    Returns:
        List of ParsedXref objects. Empty list if unparseable.
    """
    # Normalize whitespace
    cleaned = " ".join(text.split())

    # Try Lark grammar first (M2: lazy init, M9: specific exception)
    try:
        tree: Any = _get_xref_parser().parse(cleaned)
        result: Any = _xref_transformer.transform(tree)
        if isinstance(result, list):
            typed: list[ParsedXref] = [
                r for r in cast(list[Any], result) if isinstance(r, ParsedXref)
            ]
            return typed
        if isinstance(result, ParsedXref):
            return [result]
    except _UnexpectedInput:
        pass  # Grammar can't parse this pattern — fall through to regex

    # Fallback: regex extraction for simpler patterns
    m = re.match(
        r"(?:Sections?)\s+(\d+\.\d+)"
        r"((?:\s*\([a-zA-Z0-9ivxlc]+\))*)",
        cleaned,
        re.IGNORECASE,
    )
    if m:
        section_num = m.group(1)
        clause_str = m.group(2).strip()
        raw_path: list[str] = []
        if clause_str:
            raw_path = re.findall(r"\([a-zA-Z0-9ivxlc]+\)", clause_str)
        return [ParsedXref(
            section_num=section_num,
            clause_path=tuple(raw_path),
            ref_type="single",
        )]

    return []


# ---------------------------------------------------------------------------
# DefinitionEntry — internal index entry
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _DefinitionEntry:
    """Internal: a defined term with its char span."""
    term_name: str
    char_start: int
    char_end: int


# ---------------------------------------------------------------------------
# DocOutline — the main class
# ---------------------------------------------------------------------------

class DocOutline:
    """Full-document structural index for a credit agreement.

    Provides O(1) lookups by section number, article number, and defined term,
    plus cross-reference resolution.

    Construction: 3-phase scan (articles → sections → definitions).
    All char offsets are GLOBAL (position in full text), never section-relative.
    """
    __slots__ = (
        "_text", "_filename",
        "_articles", "_sections", "_definitions",
        "_synthetic_article_nums",
        "_article_by_num", "_section_by_num", "_def_by_name",
        "_sorted_section_starts", "_sorted_section_nums",
        "_sorted_article_starts", "_sorted_article_nums",
    )

    def __init__(self, text: str, filename: str = "") -> None:
        self._text = text
        self._filename = filename

        # Phase 1: detect articles
        self._articles: list[OutlineArticle] = []
        self._article_by_num: dict[int, OutlineArticle] = {}

        # Phase 2: detect sections
        self._sections: list[OutlineSection] = []
        self._section_by_num: dict[str, OutlineSection] = {}

        # Phase 3: definition index
        self._definitions: list[_DefinitionEntry] = []
        self._def_by_name: dict[str, _DefinitionEntry] = {}
        self._synthetic_article_nums: set[int] = set()

        # Sorted arrays for positional lookups
        self._sorted_section_starts: list[int] = []
        self._sorted_section_nums: list[str] = []
        self._sorted_article_starts: list[int] = []
        self._sorted_article_nums: list[int] = []

        self._build()

    # ── Construction ──────────────────────────────────────────

    def _build(self) -> None:
        """3-phase construction: articles → sections → definitions."""
        raw_articles = self._detect_articles()
        raw_sections = self._detect_sections(raw_articles)
        if raw_sections:
            all_unmapped = all(s.get("article_num", 0) == 0 for s in raw_sections)
            if not raw_articles or all_unmapped:
                raw_articles = self._synthesize_articles_from_sections(raw_sections)
            elif any(s.get("article_num", 0) == 0 for s in raw_sections):
                # If article detection is partial, align orphan sections by major number.
                known_article_nums = {a["num"] for a in raw_articles}
                for sec in raw_sections:
                    if sec.get("article_num", 0) != 0:
                        continue
                    m = re.match(r"^(\d+)\.", sec.get("number", ""))
                    if not m:
                        continue
                    major = int(m.group(1))
                    if major in known_article_nums:
                        sec["article_num"] = major
        elif raw_articles:
            # Block-1.1 Fix F: synthesize one section per article when articles
            # are detected but no sub-sections found. Common in SECTION_TOPLEVEL
            # documents (promissory notes, simple CAs) and in cases where the
            # Section X.YY sub-headings are all TOC-rejected or mid-line.
            raw_sections = self._synthesize_sections_from_articles(raw_articles)
        self._build_articles(raw_articles, raw_sections)
        self._build_definition_index()
        self._build_positional_indices()

    def _find_article_matches(self) -> list[dict[str, Any]]:
        """Find ARTICLE headings via _ARTICLE_RE with filtering."""
        matches: list[dict[str, Any]] = []
        for m in _ARTICLE_RE.finditer(self._text):
            if _is_toc_entry(self._text, m.start(), m.end()):
                continue
            label = m.group(1).strip()
            num = _roman_to_int(label.upper())
            if num is None:
                # R6-fix F13: try spelled-out number ("ONE" → 1)
                num = _word_to_int(label)
            if num is None:
                try:
                    num = int(label)
                except ValueError:
                    continue

            # R2-fix: reject implausibly high article numbers (EU Directive refs)
            if num > 25:
                continue

            # R2-fix: reject article if followed by " of Directive" / " of Regulation"
            after = self._text[m.end():m.end() + 30]
            if re.match(r"\s+of\s+(?:Directive|Regulation|the\s+EU)", after, re.IGNORECASE):
                continue

            title = self._extract_article_title(m.end())

            # R6-fix F2: truncate titles at section references instead of rejecting.
            # Many titles are "DEFINITIONS Section 1.01. Defined Terms" — truncating
            # at the Section reference recovers "DEFINITIONS" rather than discarding.
            if title:
                sec_ref = re.search(r"Section\s+\d+\.\d+", title, re.IGNORECASE)
                if sec_ref:
                    title = title[: sec_ref.start()].strip().rstrip(".,;:\u2013\u2014-")
                    # After truncation, re-validate: reject if nothing meaningful left
                    if len(title) < 3 or title.isdigit():
                        title = ""

            matches.append({
                "num": num,
                "label": label,
                "title": title,
                "char_start": m.start(),
            })

        # R7-fix: supplementary pass for split-line "ARTICLE I\nTITLE" headings.
        # Fires after primary regex and adds articles whose titles are on the next
        # line (common in EDGAR HTML formatting). Skip positions already matched.
        seen_starts = {a["char_start"] for a in matches}
        for m in _ARTICLE_SPLIT_RE.finditer(self._text):
            if m.start() in seen_starts:
                continue
            if _is_toc_entry(self._text, m.start(), m.end()):
                continue
            label = m.group(1).strip()
            num = _roman_to_int(label.upper())
            if num is None:
                num = _word_to_int(label)
            if num is None:
                try:
                    num = int(label)
                except ValueError:
                    continue
            if num > 25:
                continue
            title = _normalise_title(m.group(2).strip())
            if not _is_valid_title(title):
                title = ""
            matches.append({
                "num": num, "label": label, "title": title,
                "char_start": m.start(),
            })

        # R6-fix F11: secondary pass for letter-spaced "A R T I C L E" headings.
        # Only fires when the primary + split-line regex found zero matches.
        if not matches:
            for m in _ARTICLE_SPACED_RE.finditer(self._text):
                if _is_toc_entry(self._text, m.start(), m.end()):
                    continue
                label = m.group(1).strip()
                num = _roman_to_int(label.upper())
                if num is None:
                    try:
                        num = int(label)
                    except ValueError:
                        continue
                if num > 25:
                    continue
                if m.start() in seen_starts:
                    continue
                seen_starts.add(m.start())
                title = self._extract_article_title(m.end())
                matches.append({
                    "num": num, "label": label, "title": title,
                    "char_start": m.start(),
                })

        # Block-1.1 Fix C: TOC over-rejection recovery.
        # When ALL raw regex matches were rejected by _is_toc_entry(), retry
        # with stricter min_signals=2 (require 2+ TOC signals instead of 1).
        if not matches:
            raw_count = sum(
                1 for _ in _ARTICLE_RE.finditer(self._text)
            ) + sum(
                1 for _ in _ARTICLE_SPLIT_RE.finditer(self._text)
            )
            if raw_count > 0:
                # Retry primary regex with stricter TOC rejection
                for m in _ARTICLE_RE.finditer(self._text):
                    if _is_toc_entry(self._text, m.start(), m.end(), min_signals=2):
                        continue
                    label = m.group(1).strip()
                    num = _roman_to_int(label.upper())
                    if num is None:
                        num = _word_to_int(label)
                    if num is None:
                        try:
                            num = int(label)
                        except ValueError:
                            continue
                    if num > 25:
                        continue
                    after = self._text[m.end():m.end() + 30]
                    if re.match(r"\s+of\s+(?:Directive|Regulation|the\s+EU)", after, re.IGNORECASE):
                        continue
                    title = self._extract_article_title(m.end())
                    if title:
                        sec_ref = re.search(r"Section\s+\d+\.\d+", title, re.IGNORECASE)
                        if sec_ref:
                            title = title[: sec_ref.start()].strip().rstrip(".,;:\u2013\u2014-")
                            if len(title) < 3 or title.isdigit():
                                title = ""
                    matches.append({
                        "num": num, "label": label, "title": title,
                        "char_start": m.start(),
                    })

        return matches

    def _find_section_toplevel_matches(self) -> list[dict[str, Any]]:
        """Find top-level SECTION N headings (used instead of ARTICLE in some CAs).

        Only called when _find_article_matches() returns zero results.
        Matches patterns like "SECTION 1" / "SECTION 14" / "SECTION I" / "SECTION IV"
        with optional heading.
        """
        matches: list[dict[str, Any]] = []
        for m in _SECTION_TOPLEVEL_RE.finditer(self._text):
            if _is_toc_entry(self._text, m.start(), m.end()):
                continue
            label = m.group(1).strip()
            # R5-fix: support both Arabic digits and Roman numerals
            num = _roman_to_int(label.upper())
            if num is None:
                try:
                    num = int(label)
                except ValueError:
                    continue
            if num > 50:
                continue

            title = (m.group(2) or "").strip().rstrip(".")
            # If no inline title, try the article title extraction (next-line scan)
            if not title:
                title = self._extract_article_title(m.end())
            # Clean up ALL-CAPS title
            if title:
                title = self._clean_title_text(title)

            matches.append({
                "num": num,
                "label": label,
                "title": title,
                "char_start": m.start(),
            })
        return matches

    def _find_part_chapter_matches(self) -> list[dict[str, Any]]:
        """Block-1.1 Fix A: find Part/Chapter/Clause top-level headings.

        Last-resort fallback for non-standard CAs that use "Part I",
        "Chapter 1", or "Clause 1" instead of "Article I". Only called
        when ALL other article detection methods return zero matches.
        """
        matches: list[dict[str, Any]] = []

        for pattern in (_PART_ARTICLE_RE, _CHAPTER_ARTICLE_RE, _CLAUSE_TOPLEVEL_RE):
            for m in pattern.finditer(self._text):
                if _is_toc_entry(self._text, m.start(), m.end()):
                    continue
                label = m.group(1).strip()
                num = _roman_to_int(label.upper())
                if num is None:
                    num = _word_to_int(label)
                if num is None:
                    try:
                        num = int(label)
                    except ValueError:
                        continue
                if num > 25:
                    continue

                title = self._extract_article_title(m.end())
                if title:
                    title = self._clean_title_text(title)

                matches.append({
                    "num": num,
                    "label": label,
                    "title": title,
                    "char_start": m.start(),
                })

            # If any pattern produced matches, use it (don't mix Part + Chapter)
            if matches:
                break

        return matches

    def _detect_articles(self) -> list[dict[str, Any]]:
        """Phase 1: Find all ARTICLE headings, compute spans.

        Tries _ARTICLE_RE first. If zero matches, falls back to
        _SECTION_TOPLEVEL_RE for CAs that use "SECTION 1" / "SECTION 2"
        as top-level divisions instead of "ARTICLE I" / "ARTICLE II".
        """
        matches = self._find_article_matches()

        # R4-fix: Fallback to "SECTION N" top-level headings when no ARTICLE found
        if not matches:
            matches = self._find_section_toplevel_matches()

        # Block-1.1 Fix A: Fallback to Part/Chapter/Clause headings
        if not matches:
            matches = self._find_part_chapter_matches()

        # Compute provisional char_end for dedup span comparison.
        # We need spans BEFORE dedup to compare first vs. later occurrences.
        for i, a in enumerate(matches):
            next_start = matches[i + 1]["char_start"] if i + 1 < len(matches) else len(self._text)
            a["_provisional_end"] = next_start

        def _article_heading_quality(title: str) -> int:
            """Score article heading quality: 2=proper, 1=has title, 0=none/body.

            R5-fix: detects body-text "headings" captured from cross-references.
            Real headings are ALL CAPS ("NEGATIVE COVENANTS") or Title Case
            ("Events of Default"). Body text has many lowercase content words,
            parentheses, or sentence fragments.
            """
            if not title:
                return 0
            words = title.split()
            if len(words) > 8:
                return 0  # Too long for a heading — likely body text
            # Count lowercase content words (not articles/prepositions)
            _small_words = {"of", "and", "or", "the", "to", "for", "in", "by",
                            "with", "on", "a", "an", "as", "at", "not"}
            lc_content = sum(1 for w in words if w[0].islower() and w.lower() not in _small_words)
            if lc_content >= 2:
                return 0  # Sentence-like body text
            if "(" in title and ")" in title:
                return 0  # Parenthetical clause — body text
            return 2  # Proper heading

        # Deduplicate: prefer articles with proper headings, then by quality.
        # R5-fix: uses heading quality scoring to reject phantom articles from
        # body cross-references (e.g., "Article IV is not then satisfied...").
        # Phantom articles get sentence-like headings and artificially large spans,
        # so we no longer blindly prefer larger spans.
        best: dict[int, dict[str, Any]] = {}
        for a in matches:
            if a["num"] not in best:
                best[a["num"]] = a
            else:
                cur: dict[str, Any] = best[a["num"]]
                cur_q = _article_heading_quality(cur["title"])
                new_q = _article_heading_quality(a["title"])
                # Prefer: (1) higher heading quality, (2) earlier in document
                # (earlier is more likely to be the real article heading)
                if new_q > cur_q:
                    best[a["num"]] = a
        deduped: list[dict[str, Any]] = sorted(best.values(), key=lambda a: a["char_start"])
        # Filter out near-zero-span articles (formatting artifacts where
        # consecutive ARTICLE headings produce 28-38 char empty spans).
        deduped = [a for a in deduped
                   if a["_provisional_end"] - a["char_start"] >= 45]
        for a in deduped:
            a.pop("_provisional_end", None)

        # Compute char_end: next article's start or end of document
        for i, a in enumerate(deduped):
            if i + 1 < len(deduped):
                a["char_end"] = deduped[i + 1]["char_start"]
            else:
                a["char_end"] = len(self._text)

        # R4-fix: second-pass filter on final spans. The first filter uses
        # provisional spans (calculated from all pre-dedup matches), which may
        # differ from actual spans after dedup removes intermediate articles.
        # Articles with < 45 char final spans are formatting artifacts.
        deduped = [a for a in deduped if a["char_end"] - a["char_start"] >= 45]
        # Recompute char_end after filtering (in case we removed intermediate articles)
        for i, a in enumerate(deduped):
            if i + 1 < len(deduped):
                a["char_end"] = deduped[i + 1]["char_start"]
            else:
                a["char_end"] = len(self._text)

        # R6-fix F14: truncate the last article at exhibit/schedule/signature
        # boundaries. Without this, the last article absorbs all trailing
        # exhibits and signature pages, creating mega-sections.
        if deduped:
            last: dict[str, Any] = deduped[-1]
            search_start: int = last["char_start"]
            boundary_pos = len(self._text)
            for pattern in (_EXHIBIT_BOUNDARY_RE, _SIGNATURE_BOUNDARY_RE):
                m = pattern.search(self._text, search_start)
                if m and m.start() < boundary_pos:
                    boundary_pos = m.start()
            if boundary_pos < last["char_end"]:
                # Only truncate if the boundary is at least 500 chars into the
                # article (avoid false positives from "Exhibit A" cross-references
                # near the article heading).
                if boundary_pos - last["char_start"] > 500:
                    last["char_end"] = boundary_pos

        return deduped

    @staticmethod
    def _clean_title_text(raw: str) -> str:
        """Clean article/section title: strip table formatting artifacts."""
        # Remove pipe-separated table cell boundaries
        cleaned = re.sub(r"\s*\|\s*", " ", raw)
        # Remove page numbers at end (e.g., " 38 " or " 1 ")
        cleaned = re.sub(r"\s+\d{1,3}\s*$", "", cleaned)
        # R2-fix: collapse letter-spaced HTML artifacts ("D EFINITIONS" → "DEFINITIONS")
        # Detect: single uppercase letter followed by space then uppercase letter(s)
        # Only apply to ALL-CAPS words to avoid collapsing normal "A Random Title"
        # R5-fix: strip leading whitespace before checking regex anchor — raw HTML text
        # often has leading spaces that cause ^[A-Z] to fail.
        stripped = cleaned.strip()
        if re.match(r"^[A-Z]\s+[A-Z]", stripped):
            cleaned = re.sub(r"(?<=\b[A-Z])\s+(?=[A-Z])", "", stripped)
        # Collapse whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".;,")
        # R6-fix F1: strip leading punctuation from titles (period, dash, en-dash,
        # em-dash, semicolon, colon, comma).  HTML table artifacts often leave these
        # prefixed to article titles (e.g., ".DEFINITIONS", "- COVENANTS").
        cleaned = re.sub(r"^[.\-\u2013\u2014;,:]+\s*", "", cleaned)
        return cleaned

    def _extract_article_title(self, after_pos: int) -> str:
        """Extract article title from text following 'ARTICLE N' match.

        Handles both clean text ('ARTICLE I DEFINITIONS AND ACCOUNTING TERMS')
        and HTML table artifacts ('Article|I | | | | DEFINITIONS AND ACCOUNTING TERMS').
        Scans up to 5 lines after the match for a title-like string.
        """
        # Grab the next 500 chars for title scanning
        scan_end = min(after_pos + 500, len(self._text))
        scan_text = self._text[after_pos:scan_end]

        # R2-fix: stopwords that indicate body text, not titles
        _title_stopwords = {"article", "the", "and", "or", "agreement", "section", "a", "an"}

        # Connector words that indicate a truncated title needing continuation
        _connectors = {"of", "and", "or", "the", "to", "for", "in", "by", "with"}

        def _is_title_candidate(s: str) -> bool:
            # R7-fix: add boilerplate marker check for false-positive rejection
            if not s or len(s) < 3 or not s[0].isupper() or s.isdigit():
                return False
            if len(s) > 120 or len(s.split()) > 15:
                return False
            if s.lower() in _title_stopwords:
                return False
            if _ARTICLE_RE.match(s):
                return False
            # R7-fix: reject titles containing boilerplate legal phrases.
            # Use WHOLE-WORD matching to avoid false positives: "PROVISION"
            # should not reject "GENERAL PROVISIONS" (a common valid title).
            s_upper_words = set(s.upper().split())
            if s_upper_words & _BOILERPLATE_MARKERS:
                return False
            return True

        def _looks_truncated(title: str) -> bool:
            """Check if title appears truncated (ends with connector or comma).

            R5-fix: also treats 1-2 word titles as truncated since HTML frequently
            splits headings like "NEGATIVE\\nCOVENANTS".
            """
            last_word = title.rstrip(",").rsplit(None, 1)[-1].lower()
            return (
                title.endswith(",")
                or last_word in _connectors
                or len(title.split()) <= 2
            )

        def _is_body_text_continuation(title: str) -> bool:
            """Detect when a title has captured body text (sentence fragment)."""
            # Stop at period followed by space and content (sentence boundary)
            period_pos = title.find(". ")
            if period_pos > 0 and period_pos < len(title) - 3:
                return True
            return False

        # Strategy 1: Title on same line (most common)
        first_nl = scan_text.find("\n")
        if first_nl == -1:
            first_nl = len(scan_text)
        same_line = self._clean_title_text(scan_text[:first_nl])
        # R5-fix: truncate at sentence boundary to remove body-text capture
        if same_line and _is_body_text_continuation(same_line):
            period_pos = same_line.find(". ")
            same_line = same_line[:period_pos].strip()
        # R5-fix: strip trailing single alphabetic characters (body-text artifact)
        if same_line and len(same_line) > 2 and same_line[-2] == " " and same_line[-1].isalpha():
            same_line = same_line[:-1].strip()
        if _is_title_candidate(same_line):
            return same_line

        # Strategy 2: Title on next few lines (HTML table formatting)
        # M10: scan 10 lines (was 5) — EDGAR HTML table artifacts can push
        # the title further from the ARTICLE heading than expected.
        lines = scan_text.split("\n")
        for idx, line in enumerate(lines[1:11], start=1):
            cleaned = self._clean_title_text(line)
            # R5-fix: apply same body-text and trailing-char cleanup as Strategy 1
            if cleaned and _is_body_text_continuation(cleaned):
                pp = cleaned.find(". ")
                cleaned = cleaned[:pp].strip()
            if cleaned and len(cleaned) > 2 and cleaned[-2] == " " and cleaned[-1].isalpha():
                cleaned = cleaned[:-1].strip()
            if _is_title_candidate(cleaned):
                # Try to extend truncated titles with continuation lines
                result = cleaned
                for cont_line in lines[idx + 1:idx + 4]:
                    if not _looks_truncated(result):
                        break
                    cont = self._clean_title_text(cont_line)
                    if cont and cont[0].isupper() and len(cont) < 40:
                        result = result.rstrip(",") + " " + cont
                    else:
                        break
                # Final cleanup: sentence boundary and trailing char
                if _is_body_text_continuation(result):
                    pp = result.find(". ")
                    result = result[:pp].strip()
                if result and len(result) > 2 and result[-2] == " " and result[-1].isalpha():
                    result = result[:-1].strip()
                return result

        return ""

    # Connector words that indicate a truncated heading needing continuation
    _heading_connectors = {"of", "and", "or", "the", "to", "for", "in", "by", "with", "on"}

    def _extend_section_heading(self, heading: str, match_end: int) -> str:
        """Extend a section heading that may have been truncated at a newline.

        When HTML formatting splits headings across lines (e.g.,
        "Classification of Loans and\\nBorrowings"), the regex captures
        only the first line. This method:
        1. Applies sentence-break truncation and validation
        2. Checks if the heading looks truncated (ends with connector word or comma)
        3. If truncated, joins continuation lines from the source text

        Also handles the case where the heading is empty (heading text is
        entirely on the next line after "Section X.YY.").
        """
        # Block-2 Imp 8: check for [Reserved] / [Intentionally Omitted] pattern
        # in the heading or immediately following text. These sections have no
        # substantive content but should still be tracked in the outline.
        if heading:
            reserved_m = _RESERVED_RE.search(heading)
            if reserved_m:
                return reserved_m.group(0)
        if not heading:
            after_text = self._text[match_end:match_end + 200]
            reserved_m = _RESERVED_RE.search(after_text)
            if reserved_m:
                return reserved_m.group(0)

        # If heading is empty, try to get it from the next line
        if not heading:
            next_text = self._text[match_end:match_end + 200]
            # Skip whitespace and period after section number
            next_text = next_text.lstrip(" .\t")
            if next_text.startswith("\n"):
                next_text = next_text[1:].lstrip()
            first_nl = next_text.find("\n")
            if first_nl == -1:
                first_nl = len(next_text)
            candidate = next_text[:first_nl].strip()
            if candidate and candidate[0].isupper() and len(candidate) >= 3:
                heading = candidate

        if not heading:
            return ""

        # Apply sentence-break truncation (abbreviation-aware)
        search_start = 0
        while True:
            period_pos = heading.find(". ", search_start)
            if period_pos == -1:
                break
            if period_pos > 0 and heading[period_pos - 1].isupper():
                if period_pos < 2 or not heading[period_pos - 2].isalpha():
                    search_start = period_pos + 2
                    continue
            heading = heading[:period_pos].strip()
            break
        heading = heading.rstrip(".")
        if len(heading) > 120:
            heading = heading[:120].strip()
        # R2-fix: reject headings that are body text (>15 words)
        if len(heading.split()) > 15:
            return ""

        # R4-fix: multi-line heading continuation.
        # Check if the heading looks truncated (ends with connector or comma).
        # R5-fix: also extend when heading is very short (1-2 words), since HTML
        # formatting commonly splits headings like "Defined\nTerms" or
        # "Negative\nCovenants" where the first word is not a connector.
        word_count = len(heading.split()) if heading else 0
        last_word = heading.rstrip(",").rsplit(None, 1)[-1].lower() if heading else ""
        looks_truncated = (
            heading.endswith(",")
            or last_word in self._heading_connectors
            or word_count <= 2
        )
        if looks_truncated:
            # Look at continuation lines after the match
            # Find the actual position after the first-line heading in source text
            first_nl_pos = self._text.find("\n", match_end)
            if first_nl_pos != -1 and first_nl_pos < match_end + 300:
                cont_text = self._text[first_nl_pos + 1:first_nl_pos + 300]
                for cont_line in cont_text.split("\n")[:3]:
                    cont_word = cont_line.strip()
                    if not cont_word:
                        continue
                    # R5-fix: reject continuation lines that are section/article
                    # headers themselves (e.g., "Section 2.14. Incremental ...")
                    if _SECTION_STRICT_RE.match("\n" + cont_word) or _ARTICLE_RE.match("\n" + cont_word):
                        break
                    if cont_word[0].isupper() and len(cont_word) < 60:
                        # Looks like heading continuation
                        heading = heading.rstrip(",") + " " + cont_word
                        # Check if still truncated
                        lw = heading.rstrip(",").rsplit(None, 1)[-1].lower()
                        if not (heading.endswith(",") or lw in self._heading_connectors):
                            break
                    else:
                        break
            # Re-apply length and word limits
            heading = heading.rstrip(".")
            if len(heading) > 120:
                heading = heading[:120].strip()
            if len(heading.split()) > 15:
                return ""

        # Strip trailing punctuation (semicolons, commas)
        heading = heading.rstrip(";,")

        return heading

    def _detect_sections(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Phase 2: Find all Section headings within articles."""
        # M7: precompute sorted starts for O(log N) article lookup
        article_starts = [a["char_start"] for a in articles]

        sections: list[dict[str, Any]] = []
        # Try keyword-based regex first; fall back to bare-number if insufficient.
        # "Insufficient" means: (a) zero raw matches, (b) all matches rejected as
        # ghosts/TOC, or (c) very few matches for a large document (suggesting the
        # keyword regex only caught cross-references, not real headings).
        keyword_matches = list(_SECTION_STRICT_RE.finditer(self._text))

        # Pre-filter: count how many keyword matches survive TOC + ghost rejection
        # to decide whether bare-number fallback should fire.
        surviving_keyword = 0
        for m in keyword_matches:
            prefix_len = len("Section ")
            header_end = m.start() + prefix_len + len(m.group(1))
            if _is_toc_entry(self._text, m.start(), header_end):
                continue
            raw_heading = m.group(2)
            heading = ""
            if raw_heading:
                heading = raw_heading.strip()
            if not heading:
                after_match = self._text[m.end():m.end() + 40].lstrip()
                if after_match and not re.match(
                    r'^[.:]|^\([a-z]{1,4}\)|^\([ivx]+\)|^\(\d{1,2}\)|^[A-Z]|^["\u201c]',
                    after_match,
                ):
                    continue
            surviving_keyword += 1

        # Threshold: use bare-number fallback if keyword matches are insufficient.
        # R6-fix F7: relaxed from "(< 10 AND > 200K chars)" to just "< 10".
        # The downstream merge/replace logic (bare > keyword * 3 for merge,
        # bare > keyword * 2 for replace) prevents false positives in small docs.
        use_bare = surviving_keyword < 10

        bare_sections: list[re.Match[str]] = []
        standalone_sections: list[tuple[str, str, int]] = []  # (number, heading, char_start)
        if use_bare:
            bare_sections = list(_SECTION_BARE_RE.finditer(self._text))
            # Block-2 Imp 7: standalone section number fallback.
            # Match "10.3" alone on a line, then look ahead for heading.
            for sm in _SECTION_STANDALONE_RE.finditer(self._text):
                number = sm.group(1)
                # Reject major > 20 (pricing grid values like "50.00 bps")
                major_token = number.split(".")[0]
                major = _roman_to_int(major_token) if not major_token.isdigit() else int(major_token)
                if major is None:
                    continue
                if major > 20:
                    continue
                # Look-ahead: scan next 2 non-empty lines for heading
                after = self._text[sm.end():sm.end() + 200]
                heading = ""
                for line in after.split("\n")[:3]:
                    candidate = line.strip()
                    if not candidate:
                        continue
                    # Reject if the next non-empty line is itself a structural header.
                    if _SECTION_STRICT_RE.match("\n" + candidate) or _ARTICLE_RE.match("\n" + candidate):
                        break
                    # Reserve markers should be tracked as headings.
                    reserved = _RESERVED_RE.search(candidate)
                    if reserved:
                        heading = reserved.group(0)
                        break
                    # Standard heading continuation.
                    if candidate[0].isupper() and len(candidate) < 60:
                        heading = candidate
                        break
                    # Headingless sections are still valid when body starts with
                    # a quoted term or clause marker.
                    if re.match(r'^["\u201c]|^\([a-z]{1,4}\)|^\([ivx]+\)|^\(\d{1,2}\)|^[.:]', candidate):
                        heading = ""
                    break
                # Keep the section if either a heading was found or the body-start
                # shape looks section-like (e.g., a quoted defined term list).
                if heading or re.match(
                    r'^["\u201c]|^\([a-z]{1,4}\)|^\([ivx]+\)|^\(\d{1,2}\)|^[.:]',
                    (after.lstrip().split("\n", 1)[0].strip() if after.lstrip() else ""),
                ):
                    normalized_number = number.replace(" ", "")
                    if normalized_number and not normalized_number[0].isdigit():
                        parts = normalized_number.split(".", 1)
                        roman_int = _roman_to_int(parts[0])
                        if roman_int is not None:
                            normalized_number = f"{roman_int}.{parts[1]}"
                    standalone_sections.append((normalized_number, heading, sm.start()))
        # R6-fix F7: when bare matches outnumber keyword by 3x+, merge both sets
        # instead of replacing keyword with bare.  This handles CAs that mix
        # "Section X.YY" headings with bare "X.YY Heading" lines.  Below 3x we
        # still prefer keyword-only (more precise ghost rejection).
        match_items: list[tuple[re.Match[str], bool]]
        if bare_sections and len(bare_sections) > surviving_keyword * 3:
            # Merge: keyword matches first, then bare matches not already covered
            keyword_positions = {m.start() for m in keyword_matches}
            merged: list[tuple[re.Match[str], bool]] = (
                [(m, True) for m in keyword_matches]
                + [(bm, False) for bm in bare_sections if bm.start() not in keyword_positions]
            )
            merged.sort(key=lambda item: item[0].start())
            match_items = merged
        elif bare_sections and len(bare_sections) > surviving_keyword * 2:
            match_items = [(bm, False) for bm in bare_sections]
        else:
            match_items = [(m, True) for m in keyword_matches]

        for m, is_keyword_match in match_items:
            # Use tight boundary for TOC check: just "Section X.YY" (not the
            # full heading line which includes body text, inflating context)
            prefix_len = len("Section ") if is_keyword_match else 0
            header_end = m.start() + prefix_len + len(m.group(1))
            if _is_toc_entry(self._text, m.start(), header_end):
                continue
            number = m.group(1).replace(" ", "")  # R6-fix F9: strip OCR space
            # R6-fix F6: normalize Roman-prefix section numbers (e.g., "II.1" → "2.1")
            if number and not number[0].isdigit():
                parts = number.split(".", 1)
                roman_int = _roman_to_int(parts[0])
                if roman_int is not None:
                    number = f"{roman_int}.{parts[1]}"
            raw_heading = (m.group(2) or "").strip()
            # R4-fix: extend heading with multi-line continuation, sentence-break
            # truncation, abbreviation handling, and trailing-punctuation cleanup.
            heading = self._extend_section_heading(raw_heading, m.end())

            # Additional bare-number guardrails: bare matches are high recall but
            # vulnerable to numeric table rows and page artifacts.
            if not is_keyword_match:
                if not heading:
                    continue
                if len(heading.split()) > 12:
                    continue
                if re.search(r"\b\d{3,}\b", heading):
                    continue
                if heading.lower().startswith(("page ", "table ", "note ")):
                    continue

            # Section-number plausibility guardrail. Outlier numbering is kept
            # only when corroborated by keyword anchors + heading signal.
            if not self._is_plausible_section_number(
                number, is_keyword=is_keyword_match, heading=heading,
                has_articles=bool(articles),
            ):
                continue

            # Ghost section rejection: sections without headings that start
            # with body-text patterns are cross-references, not real sections.
            # Real headingless sections start with period, colon, or clause
            # markers like "(a)", "(i)", "(1)". Ghost xrefs start with comma,
            # lowercase, preposition, or parenthetical asides like "(but not",
            # "(other than", "(or, in the case of".
            # Block-1.1 Fix D: also accept lines starting with quoted defined
            # terms (straight or smart quotes) — e.g., '"Borrower" means...'.
            if not heading:
                after_match = self._text[m.end():m.end() + 40].lstrip()
                if after_match and not re.match(
                    r'^[.:]|^\([a-z]{1,4}\)|^\([ivx]+\)|^\(\d{1,2}\)|^[A-Z]|^["\u201c]',
                    after_match,
                ):
                    continue

            # Find which article this section belongs to (M7: O(log N))
            article_num = self._find_article_num(m.start(), articles, article_starts)

            sections.append({
                "number": number,
                "heading": heading,
                "char_start": m.start(),
                "article_num": article_num,
            })

        # Block-2 Imp 7: merge standalone section matches (number alone on line,
        # heading on next line). Only add if the section number isn't already found.
        existing_numbers = {s["number"] for s in sections}
        for number, heading, char_start in standalone_sections:
            if number not in existing_numbers:
                article_num = self._find_article_num(char_start, articles, article_starts)
                sections.append({
                    "number": number,
                    "heading": heading,
                    "char_start": char_start,
                    "article_num": article_num,
                })

        # Deduplicate: use heading quality scoring and heading inheritance.
        # When the same section number appears multiple times (e.g., in TOC
        # and body), prefer the body occurrence (later, in-article) but
        # inherit the heading from an earlier entry if the body entry lacks one.
        # Ported from Neutron build_section_index.py:214-241.
        best: dict[str, dict[str, Any]] = {}
        # Track best heading seen for each section number, regardless of
        # which entry we ultimately keep. This enables heading inheritance.
        best_heading: dict[str, str] = {}
        for s in sections:
            key: str = s["number"]
            h: str = s["heading"]
            # Track highest-quality heading seen for this section number
            if key not in best_heading or heading_quality(h) > heading_quality(best_heading[key]):
                best_heading[key] = h
            if key not in best:
                best[key] = s
            else:
                cur: dict[str, Any] = best[key]
                cur_quality = heading_quality(cur["heading"])
                new_quality = heading_quality(h)
                cur_in_article: bool = cur["article_num"] > 0
                new_in_article = s["article_num"] > 0
                # Prefer: (1) higher heading quality, (2) inside a detected article
                if (new_quality > cur_quality) or (
                    new_quality == cur_quality
                    and new_in_article
                    and not cur_in_article
                ):
                    best[key] = s
        # Heading inheritance: if the best entry has an empty/garbage heading
        # but we saw a proper heading for the same section number (e.g., from
        # TOC), inherit it. This recovers headings for body sections that
        # appear as bare "Section 2.14" without inline heading text.
        for key, s in best.items():
            if heading_quality(s["heading"]) < 2 and heading_quality(best_heading.get(key, "")) == 2:
                s["heading"] = best_heading[key]
        deduped: list[dict[str, Any]] = list(best.values())

        # Block-1.1 Fix C: section-level TOC over-rejection recovery.
        # When dedup produces zero sections but raw keyword matches existed,
        # retry with stricter min_signals=2 for TOC rejection.
        if not deduped and keyword_matches:
            for m in keyword_matches:
                prefix_len = len("Section ")
                header_end = m.start() + prefix_len + len(m.group(1))
                if _is_toc_entry(self._text, m.start(), header_end, min_signals=2):
                    continue
                number = m.group(1).replace(" ", "")
                if number and not number[0].isdigit():
                    parts = number.split(".", 1)
                    roman_int = _roman_to_int(parts[0])
                    if roman_int is not None:
                        number = f"{roman_int}.{parts[1]}"
                raw_heading = (m.group(2) or "").strip()
                heading = self._extend_section_heading(raw_heading, m.end())
                if not self._is_plausible_section_number(
                    number, is_keyword=True, heading=heading,
                    has_articles=bool(articles),
                ):
                    continue
                if not heading:
                    after_match = self._text[m.end():m.end() + 40].lstrip()
                    if after_match and not re.match(
                        r'^[.:]|^\([a-z]{1,4}\)|^\([ivx]+\)|^\(\d{1,2}\)|^[A-Z]|^["\u201c]',
                        after_match,
                    ):
                        continue
                article_num = self._find_article_num(m.start(), articles, article_starts)
                key = number
                if key not in best:
                    best[key] = {
                        "number": number,
                        "heading": heading,
                        "char_start": m.start(),
                        "article_num": article_num,
                    }
            deduped = list(best.values())

        # Sort by char_start
        deduped.sort(key=lambda s: s["char_start"])

        # Compute char_end and word_count
        for i, s in enumerate(deduped):
            if i + 1 < len(deduped):
                # Check if next section is in same article
                if deduped[i + 1]["article_num"] == s["article_num"]:
                    s["char_end"] = deduped[i + 1]["char_start"]
                else:
                    # Find article boundary
                    art = self._find_article_dict(s["article_num"], articles)
                    s["char_end"] = art["char_end"] if art else deduped[i + 1]["char_start"]
            else:
                # Last section: extends to end of its article (or document)
                art = self._find_article_dict(s["article_num"], articles)
                s["char_end"] = art["char_end"] if art else len(self._text)

            section_text = self._text[s["char_start"]:s["char_end"]]
            s["word_count"] = len(section_text.split())

        # Block-1.1 Fix B: flat numbered section fallback.
        # When no articles detected AND no X.YY sections found, try "N. Heading"
        # pattern as a last resort. Requires >= 5 matches to avoid false positives
        # from numbered body-text lists.
        if not deduped and not articles:
            flat_matches: list[dict[str, Any]] = []
            for m in _SECTION_FLAT_RE.finditer(self._text):
                if _is_toc_entry(self._text, m.start(), m.end()):
                    continue
                num_str = m.group(1)
                heading = m.group(2).strip()
                heading = self._extend_section_heading(heading, m.end())
                if not heading:
                    continue
                # Use "0.N" format so section_number is always X.YY
                number = f"0.{num_str.zfill(2)}"
                flat_matches.append({
                    "number": number,
                    "heading": heading,
                    "char_start": m.start(),
                    "article_num": 0,
                })
            if len(flat_matches) >= 5:
                # Deduplicate by number
                flat_best: dict[str, dict[str, Any]] = {}
                for fm in flat_matches:
                    key = fm["number"]
                    if key not in flat_best:
                        flat_best[key] = fm
                deduped = sorted(flat_best.values(), key=lambda s: s["char_start"])
                # Compute char_end and word_count
                for i, s in enumerate(deduped):
                    if i + 1 < len(deduped):
                        s["char_end"] = deduped[i + 1]["char_start"]
                    else:
                        s["char_end"] = len(self._text)
                    sec_text = self._text[s["char_start"]:s["char_end"]]
                    s["word_count"] = len(sec_text.split())

        # Block-2 Imp 10: enforce monotonic section ordering within each article.
        # Sections whose numeric minor part does not strictly increase (in document
        # order) are dropped.  This catches stale cross-reference echoes that
        # survived earlier dedup.  Also detects numbering gaps for diagnostics.
        deduped = self._enforce_monotonic_sections(deduped)

        return deduped

    @staticmethod
    def _parse_section_minor(number: str) -> int | None:
        """Extract the minor (after-dot) part of a section number as int.

        "7.02" → 2, "7.2" → 2, "0.05" → 5, "IV.3" → None (roman article).
        """
        parts = number.split(".")
        if len(parts) != 2:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    def _enforce_monotonic_sections(
        self, sections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Enforce strictly increasing section numbers within each article.

        Within a single article, sections must have strictly increasing minor
        numbers (the part after the dot).  A section whose minor number is ≤
        the previously kept section's minor number is dropped (unless it has
        a better heading than the previous entry with the same number, in
        which case it replaces it).

        Returns: the filtered section list, sorted by char_start.
        """
        # Group by article_num.  When article_num is 0 (no article context),
        # use the major number (part before the dot) as a proxy so that
        # sections 1.01, 1.02, 2.01, 2.02 are validated independently.
        by_article: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for s in sections:
            art = s["article_num"]
            if art == 0:
                parts = s["number"].split(".")
                try:
                    art = int(parts[0])
                except ValueError:
                    pass
            by_article[art].append(s)

        validated: list[dict[str, Any]] = []
        for _art_num in sorted(by_article):
            art_secs = sorted(by_article[_art_num], key=lambda s: s["char_start"])

            if len(art_secs) <= 1:
                validated.extend(art_secs)
                continue

            kept: list[dict[str, Any]] = [art_secs[0]]
            for s in art_secs[1:]:
                cur_minor = self._parse_section_minor(s["number"])
                prev_minor = self._parse_section_minor(kept[-1]["number"])

                if cur_minor is None or prev_minor is None:
                    # Unparseable — keep (graceful degradation)
                    kept.append(s)
                    continue

                if cur_minor > prev_minor:
                    kept.append(s)
                elif cur_minor == prev_minor:
                    # Duplicate minor: prefer entry with heading
                    if s["heading"] and not kept[-1]["heading"]:
                        kept[-1] = s
                # else: cur_minor < prev_minor → drop (non-monotonic)

            validated.extend(kept)

        validated.sort(key=lambda s: s["char_start"])
        return validated

    def _find_article_num(
        self, char_pos: int, articles: list[dict[str, Any]], starts: list[int],
    ) -> int:
        """Find which article number contains a char position.

        M7: O(log N) via bisect_right on precomputed starts array,
        replacing the previous O(N) reversed linear scan.
        """
        if not articles:
            return 0
        idx = bisect_right(starts, char_pos) - 1
        if idx >= 0 and articles[idx]["char_start"] <= char_pos < articles[idx]["char_end"]:
            return articles[idx]["num"]
        return 0

    def _find_article_dict(self, num: int, articles: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Find article dict by number."""
        for a in articles:
            if a["num"] == num:
                return a
        return None

    @staticmethod
    def _is_plausible_section_number(
        number: str,
        *,
        is_keyword: bool,
        heading: str,
        has_articles: bool = True,
    ) -> bool:
        """Validate section-number plausibility to reduce numeric ghost sections.

        Outlier numbers are allowed only when corroborated by a keyword-based
        match with heading signal (to avoid suppressing valid but unusual docs).

        Block-1.1 Fix E: when ``has_articles`` is False (flat document with no
        article structure), the major-number threshold is relaxed from 40 to 60.
        Large UK-style agreements can exceed 40 top-level sections.
        """
        m = re.match(r"^(\d+)\.(\d+)[a-z]?$", number, re.IGNORECASE)
        if not m:
            return False
        major = int(m.group(1))
        minor = int(m.group(2))

        # Block-1.1 Fix E: use relaxed threshold for flat docs
        major_limit = 40 if has_articles else 60
        outlier = major > major_limit or minor > 120
        if not outlier:
            return True

        # Corroboration path for unusual-but-real numbering.
        return is_keyword and bool(heading) and heading[0].isupper()

    def _synthesize_articles_from_sections(
        self, raw_sections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Recover article scaffolding from section majors when articles are missing."""
        groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for sec in raw_sections:
            m = re.match(r"^(\d+)\.", sec.get("number", ""))
            if not m:
                continue
            groups[int(m.group(1))].append(sec)

        if not groups:
            return []

        items = sorted(groups.items(), key=lambda kv: min(s["char_start"] for s in kv[1]))
        synthetic: list[dict[str, Any]] = []
        for idx, (major, secs) in enumerate(items):
            start = min(s["char_start"] for s in secs)
            if idx + 1 < len(items):
                next_start = min(s["char_start"] for s in items[idx + 1][1])
                end = next_start
            else:
                end = len(self._text)
            for sec in secs:
                sec["article_num"] = major
            synthetic.append({
                "num": major,
                "label": _int_to_roman(major) or str(major),
                "title": "",
                "char_start": start,
                "char_end": end,
                "is_synthetic": True,
            })
        return synthetic

    def _synthesize_sections_from_articles(
        self,
        raw_articles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Block-1.1 Fix F: create one section per article when no sub-sections found.

        Common in SECTION_TOPLEVEL documents (promissory notes, simple CAs) where
        the top-level headings ARE the sections, and in cases where Section X.YY
        sub-headings exist in the body but are all rejected by TOC/ghost filters.

        Section number format: "{article_num}.01" (one section per article).
        """
        sections: list[dict[str, Any]] = []
        for a in raw_articles:
            num = a["num"]
            number = f"{num}.01"
            sec_text = self._text[a["char_start"]:a["char_end"]]
            sections.append({
                "number": number,
                "heading": a.get("title", ""),
                "char_start": a["char_start"],
                "char_end": a["char_end"],
                "article_num": num,
                "word_count": len(sec_text.split()),
            })
        return sections

    @staticmethod
    def _apply_definition_guardrails(
        entries: list[_DefinitionEntry],
    ) -> list[_DefinitionEntry]:
        """Filter fragmented/duplicate definition entries from fallback passes."""
        if not entries:
            return []

        filtered: list[_DefinitionEntry] = []
        seen: set[tuple[str, int]] = set()
        for entry in sorted(entries, key=lambda d: d.char_start):
            key = (entry.term_name.lower(), entry.char_start)
            if key in seen:
                continue
            seen.add(key)
            term_len = len(entry.term_name.strip())
            span_len = max(0, entry.char_end - entry.char_start)
            if term_len < 2 or term_len > 140:
                continue
            if span_len < 10:
                continue
            filtered.append(entry)

        if not filtered:
            return []

        # Over-fragmentation guardrail: if the majority of matches are tiny
        # snippets, keep only substantive spans.
        tiny = [d for d in filtered if (d.char_end - d.char_start) < 35]
        if len(filtered) >= 30 and (len(tiny) / len(filtered)) > 0.65:
            substantial = [d for d in filtered if (d.char_end - d.char_start) >= 35]
            if substantial:
                filtered = substantial

        return filtered

    def _build_articles(self, raw_articles: list[dict[str, Any]], raw_sections: list[dict[str, Any]]) -> None:
        """Build OutlineArticle and OutlineSection objects."""
        self._synthetic_article_nums = set()

        # Group sections by article
        sections_by_article: dict[int, list[OutlineSection]] = {}
        for s in raw_sections:
            sec = OutlineSection(
                number=s["number"],
                heading=s["heading"],
                char_start=s["char_start"],
                char_end=s["char_end"],
                article_num=s["article_num"],
                word_count=s["word_count"],
            )
            self._sections.append(sec)
            self._section_by_num[sec.number] = sec
            sections_by_article.setdefault(s["article_num"], []).append(sec)

        for a in raw_articles:
            art_sections = tuple(sections_by_article.get(a["num"], ()))
            concept = _title_to_concept(a["title"])
            article = OutlineArticle(
                num=a["num"],
                label=a["label"],
                title=a["title"],
                concept=concept,
                char_start=a["char_start"],
                char_end=a["char_end"],
                sections=art_sections,
                is_synthetic=bool(a.get("is_synthetic", False)),
            )
            self._articles.append(article)
            self._article_by_num[article.num] = article
            if article.is_synthetic:
                self._synthetic_article_nums.add(article.num)

    @staticmethod
    def _count_def_patterns(span_text: str) -> int:
        """Count definition-like patterns in a text span (quoted + unquoted).

        R6-fix F10 / R7-fix: counts both quoted ("Term" means) and unquoted
        (Term means / Term. Means) patterns. Used to validate whether a span
        actually contains definitions.
        """
        # Primary: quoted definitions
        quoted = len(re.findall(
            r'["\u201d]\s*(?:means\b|shall\s+mean\b|has\s+the\s+meaning\b|:)',
            span_text, re.IGNORECASE,
        ))
        if quoted >= 2:
            return quoted
        # Secondary: TermIntelligence-style unquoted (Title Case + period)
        unquoted_ti = len(_DEF_UNQUOTED_RE.findall(span_text))
        if quoted + unquoted_ti >= 2:
            return quoted + unquoted_ti
        # Tertiary: simple unquoted "Term means" fallback
        unquoted_simple = len(_DEF_UNQUOTED_SIMPLE_RE.findall(span_text))
        return quoted + unquoted_ti + unquoted_simple

    def _build_definition_index(self) -> None:
        """Phase 3: Scan definitions article for defined terms.

        R2-fix: Falls back to scanning sections with definitions-like headings
        when no definitions article is found, and to full-text scan as last resort.
        """
        # Find the definitions article
        def_article = None
        for art in self._articles:
            if art.concept == "definitions":
                def_article = art
                break

        # R6-fix F4: validate that the concept-matched definitions article actually
        # contains definitions.  Some CAs have an "ARTICLE I – DEFINITIONS" that is
        # just a one-line pointer ("Terms used herein have the meanings given in
        # Section 1.01") with the real definitions in a section.  Without validation
        # we'd return 0 definitions.  Use a low threshold (>=2) since the article
        # was already concept-matched — we just need to confirm it's not a pointer.
        if def_article:
            _val_text = self._text[def_article.char_start:def_article.char_end]
            if self._count_def_patterns(_val_text) < 2:
                def_article = None  # fall through to fallbacks

        # Fallback 1: try sections with definitions-like headings
        # R5-fix: validate that the candidate span actually contains definitions
        # (at least 5 "means" or colon-style patterns). This prevents "interpretation"
        # sections that don't contain definitions from being used as the def span.
        if not def_article:
            for sec in self._sections:
                lower_heading = sec.heading.lower()
                if any(kw in lower_heading for kw in (
                    "defined terms", "definitions", "interpretation",
                )):
                    # Prefer the parent article if available
                    art = self._article_by_num.get(sec.article_num)
                    if art and (art.char_end - art.char_start) > 5000:
                        span_text = self._text[art.char_start:art.char_end]
                        if self._count_def_patterns(span_text) >= 5:
                            def_article = art
                            break
                    # No article detected: use the section's own span directly
                    if (sec.char_end - sec.char_start) > 5000:
                        span_text = self._text[sec.char_start:sec.char_end]
                        if self._count_def_patterns(span_text) >= 5:
                            def_article = OutlineArticle(
                                num=0, label="0",
                                title="(inferred from section)",
                                concept="definitions",
                                char_start=sec.char_start,
                                char_end=sec.char_end,
                                sections=(),
                            )
                            break

        # Fallback 2: use the first article if it looks like definitions
        # (contains many "means" or colon-style definition phrases in its span)
        if not def_article and self._articles:
            first = self._articles[0]
            first_text = self._text[first.char_start:first.char_end]
            if self._count_def_patterns(first_text) >= 5:
                def_article = first

        # Fallback 3: scan the first portion of the document directly
        # (handles CAs where Article 1 was missed entirely)
        if not def_article:
            scan_end = min(len(self._text), 200_000)
            probe = self._text[:scan_end]
            if self._count_def_patterns(probe) >= 10:
                # Create a virtual definitions span covering the probe area
                def_article = OutlineArticle(
                    num=0, label="0", title="(inferred definitions)",
                    concept="definitions",
                    char_start=0, char_end=scan_end,
                    sections=(),
                )

        if not def_article:
            return

        text_slice = self._text[def_article.char_start:def_article.char_end]

        for m in _DEF_RE.finditer(text_slice):
            # Clean term name: collapse whitespace from HTML artifacts
            term_name = re.sub(r"\s+", " ", m.group(1)).strip()
            # Compute global offsets
            global_start = def_article.char_start + m.start()
            # M11: Find end boundary using multiple signals for robustness.
            # Primary: next definition start. Secondary: section boundary
            # within the definitions article (indicates we've left definitions).
            # Fallback: end of definitions article.
            next_def = _DEF_RE.search(text_slice, m.end())
            section_break = re.search(
                r"\n\s*(?:Section|SECTION)\s+\d+\.\d+",
                text_slice[m.end():],
            )
            boundary_candidates: list[int] = []
            if next_def:
                boundary_candidates.append(def_article.char_start + next_def.start())
            if section_break:
                boundary_candidates.append(
                    def_article.char_start + m.end() + section_break.start()
                )
            global_end = min(boundary_candidates) if boundary_candidates else def_article.char_end

            entry = _DefinitionEntry(
                term_name=term_name,
                char_start=global_start,
                char_end=global_end,
            )
            self._definitions.append(entry)
            # Normalize: strip smart quotes, lowercase for lookup key
            normalized = term_name.replace("\u201c", "").replace("\u201d", "")
            self._def_by_name[normalized.lower()] = entry

        # R6-fix F10 / R7-fix: unquoted definitions fallback.
        # Strategy: try TermIntelligence-style unquoted (Title Case + period) first,
        # then fall back to simple "Term means" pattern.
        # Only fires when the primary regex found 0 definitions.
        if not self._definitions and def_article:
            # Try TermIntelligence-style unquoted definitions first
            unquoted_matches: list[tuple[str, re.Match[str]]] = []
            for m in _DEF_UNQUOTED_RE.finditer(text_slice):
                term_name = re.sub(r"\s+", " ", m.group(1)).strip()
                # R7-fix: false-positive exclusion — check first word
                first_word = term_name.split()[0] if term_name else ""
                if first_word in _UNQUOTED_FALSE_POS:
                    continue
                if len(term_name) <= 3:
                    continue
                unquoted_matches.append((term_name, m))

            # Fall back to simple pattern if TermIntelligence pattern found nothing
            if not unquoted_matches:
                for m in _DEF_UNQUOTED_SIMPLE_RE.finditer(text_slice):
                    term_name = re.sub(r"\s+", " ", m.group(1)).strip()
                    if len(term_name) < 2 or term_name.lower() in (
                        "the", "this", "that", "each", "any", "all", "no",
                    ):
                        continue
                    first_word = term_name.split()[0] if term_name else ""
                    if first_word in _UNQUOTED_FALSE_POS:
                        continue
                    unquoted_matches.append((term_name, m))

            # Build entries from whichever pattern matched
            active_regex = _DEF_UNQUOTED_RE if unquoted_matches else _DEF_UNQUOTED_SIMPLE_RE
            for term_name, m in unquoted_matches:
                global_start = def_article.char_start + m.start()
                next_def = active_regex.search(text_slice, m.end())
                section_break = re.search(
                    r"\n\s*(?:Section|SECTION)\s+\d+\.\d+",
                    text_slice[m.end():],
                )
                boundary_candidates: list[int] = []
                if next_def:
                    boundary_candidates.append(def_article.char_start + next_def.start())
                if section_break:
                    boundary_candidates.append(
                        def_article.char_start + m.end() + section_break.start()
                    )
                global_end = min(boundary_candidates) if boundary_candidates else def_article.char_end
                entry = _DefinitionEntry(
                    term_name=term_name,
                    char_start=global_start,
                    char_end=global_end,
                )
                self._definitions.append(entry)
                self._def_by_name[term_name.lower()] = entry

        # Final guardrails: remove tiny/duplicate fragments and rebuild lookup map.
        self._definitions = self._apply_definition_guardrails(self._definitions)
        self._def_by_name = {}
        for entry in self._definitions:
            normalized = entry.term_name.replace("\u201c", "").replace("\u201d", "").lower()
            if normalized not in self._def_by_name:
                self._def_by_name[normalized] = entry

    def _build_positional_indices(self) -> None:
        """Build sorted arrays for O(log N) positional lookups."""
        sorted_sections = sorted(self._sections, key=lambda s: s.char_start)
        self._sorted_section_starts = [s.char_start for s in sorted_sections]
        self._sorted_section_nums = [s.number for s in sorted_sections]

        sorted_articles = sorted(self._articles, key=lambda a: a.char_start)
        self._sorted_article_starts = [a.char_start for a in sorted_articles]
        self._sorted_article_nums = [a.num for a in sorted_articles]

    # ── Public API: section/article lookups ────────────────────

    def section(self, num: str) -> OutlineSection | None:
        """Lookup section by number (e.g., '2.14')."""
        return self._section_by_num.get(num)

    def section_text(self, num: str) -> str:
        """Get the full text of a section. Empty string if not found."""
        sec = self._section_by_num.get(num)
        if sec is None:
            return ""
        return self._text[sec.char_start:sec.char_end]

    def section_preemption_summary(self, num: str) -> PreemptionSummary:
        """Summarize override/yield markers for a section."""
        section_text = self.section_text(num)
        return summarize_preemption(section_text)

    def section_preemption_edges(self, num: str) -> list[PreemptionEdge]:
        """Return extracted override/yield edges for a section."""
        section_text = self.section_text(num)
        return extract_preemption_edges(section_text)

    def article(self, num: int) -> OutlineArticle | None:
        """Lookup article by number (e.g., 7)."""
        return self._article_by_num.get(num)

    @property
    def articles(self) -> list[OutlineArticle]:
        """All detected articles in document order."""
        return list(self._articles)

    @property
    def sections(self) -> list[OutlineSection]:
        """All detected sections in document order."""
        return list(self._sections)

    @property
    def synthetic_article_nums(self) -> list[int]:
        """Article numbers synthesized from section-major fallback."""
        return sorted(self._synthetic_article_nums)

    @property
    def text(self) -> str:
        """The full document text this outline indexes."""
        return self._text

    @property
    def filename(self) -> str:
        """Source filename."""
        return self._filename

    # ── Public API: positional lookups ─────────────────────────

    def containing_article(self, char_pos: int) -> OutlineArticle | None:
        """Find the article containing a char position."""
        if not self._sorted_article_starts:
            return None
        idx = bisect_right(self._sorted_article_starts, char_pos) - 1
        if idx < 0:
            return None
        art_num = self._sorted_article_nums[idx]
        art = self._article_by_num.get(art_num)
        if art and art.char_start <= char_pos < art.char_end:
            return art
        return None

    def containing_section(self, char_pos: int) -> OutlineSection | None:
        """Find the section containing a char position."""
        if not self._sorted_section_starts:
            return None
        idx = bisect_right(self._sorted_section_starts, char_pos) - 1
        if idx < 0:
            return None
        sec_num = self._sorted_section_nums[idx]
        sec = self._section_by_num.get(sec_num)
        if sec and sec.char_start <= char_pos < sec.char_end:
            return sec
        return None

    # ── Public API: definition resolution ──────────────────────

    def _resolve_def_entry(self, term_name: str) -> _DefinitionEntry | None:
        """Lookup a defined term entry with plural/singular fallback."""
        normalized = term_name.replace("\u201c", "").replace("\u201d", "").lower()
        entry = self._def_by_name.get(normalized)
        if entry is not None:
            return entry
        # Plural/singular fallback: try adding/removing trailing 's'
        if normalized.endswith("s"):
            entry = self._def_by_name.get(normalized[:-1])
        else:
            entry = self._def_by_name.get(normalized + "s")
        return entry

    def definition(self, term_name: str) -> str | None:
        """Lookup defined term text. Handles smart quotes. Returns text or None."""
        entry = self._resolve_def_entry(term_name)
        if entry is None:
            return None
        return self._text[entry.char_start:entry.char_end]

    def definition_span(self, term_name: str) -> XrefSpan | None:
        """Definition as an XrefSpan with precise char offsets."""
        entry = self._resolve_def_entry(term_name)
        if entry is None:
            return None
        return XrefSpan(
            section_num="1.01",  # Definitions are typically in Section 1.01
            clause_path=(),
            char_start=entry.char_start,
            char_end=entry.char_end,
            resolution_method="definition",
        )

    @property
    def defined_terms(self) -> list[str]:
        """All defined term names found in the definitions article."""
        return [d.term_name for d in self._definitions]

    # ── Public API: cross-reference resolution ─────────────────

    def resolve_xref(self, ref: str) -> Ok[XrefSpan] | Err[XrefResolutionError]:
        """Resolve a cross-reference string to a precise document span.

        Handles "Section 2.14", "Section 2.14(d)", "Section 2.14(d)(iv)".
        Returns Result, not None — failure reason is a first-class signal.
        """
        parsed = parse_xref(ref)
        if not parsed:
            return Err(XrefResolutionError(
                reason="parse_failed",
                raw_ref=ref,
                attempted_path="",
            ))

        # Use first parsed xref (most xref strings have a single ref)
        first = parsed[0]
        sec = self._section_by_num.get(first.section_num)
        if sec is None:
            return Err(XrefResolutionError(
                reason="target_not_found",
                raw_ref=ref,
                attempted_path=first.section_num,
            ))

        # Section-only reference: return the whole section span.
        if not first.clause_path:
            return Ok(XrefSpan(
                section_num=first.section_num,
                clause_path=(),
                char_start=sec.char_start,
                char_end=sec.char_end,
                resolution_method="section_only",
            ))

        # Clause-path reference: resolve against clause tree of the target section.
        from agent.clause_parser import parse_clauses, resolve_path

        section_text = self._text[sec.char_start:sec.char_end]
        nodes = parse_clauses(section_text, global_offset=sec.char_start)
        # Convert tuple clause_path to list for resolve_path
        node = resolve_path(nodes, list(first.clause_path))
        if node is None:
            attempted = first.section_num + "".join(first.clause_path)
            return Err(XrefResolutionError(
                reason="path_invalid",
                raw_ref=ref,
                attempted_path=attempted,
            ))

        return Ok(XrefSpan(
            section_num=first.section_num,
            clause_path=first.clause_path,
            char_start=node.span_start,
            char_end=node.span_end,
            resolution_method="section+clause_path",
        ))

    # ── Public API: xref intent classification ─────────────────

    def classify_xref_intent(self, context: str) -> str:
        """Classify xref intent from surrounding text context.

        Returns one of: "incorporation", "condition", "definition",
        "exception", "amendment", "other".
        """
        for intent, pattern in _XREF_INTENT_PATTERNS:
            if pattern.search(context):
                return intent
        return "other"

    # ── Public API: scan all xrefs in a section ────────────────

    def scan_xrefs_in_range(self, char_start: int, char_end: int) -> list[tuple[ParsedXref, str, int]]:
        """Scan a text range for all cross-references.

        Returns list of (parsed_xref, intent, match_start_global).
        """
        text_slice = self._text[char_start:char_end]
        results: list[tuple[ParsedXref, str, int]] = []

        for m in _XREF_SCAN_RE.finditer(text_slice):
            full_match = m.group(0)
            parsed = parse_xref(full_match)
            if not parsed:
                continue

            # Get context for intent classification (±100 chars)
            ctx_start = max(0, m.start() - 100)
            ctx_end = min(len(text_slice), m.end() + 100)
            context = text_slice[ctx_start:ctx_end]
            intent = self.classify_xref_intent(context)

            global_pos = char_start + m.start()
            for p in parsed:
                results.append((p, intent, global_pos))

        return results

    # ── Alternative constructors ───────────────────────────────

    @classmethod
    def from_text(cls, text: str, filename: str = "") -> DocOutline:
        """Build outline by scanning text directly."""
        return cls(text, filename)

    @classmethod
    def _from_prebuilt(
        cls,
        text: str,
        filename: str,
        articles: list[OutlineArticle],
        sections: list[OutlineSection],
        definitions: list[_DefinitionEntry] | None = None,
    ) -> DocOutline:
        """Internal: construct from pre-built components without text scanning.

        Used by from_structure_map (structure map → articles/sections,
        text scan → definitions) and by ArtifactStore.load_outline
        (all components from stored artifacts).
        """
        outline = cls.__new__(cls)
        outline._text = text
        outline._filename = filename
        outline._articles = list(articles)
        outline._synthetic_article_nums = {
            article.num for article in articles if article.is_synthetic
        }
        outline._article_by_num = {a.num: a for a in articles}
        outline._sections = list(sections)
        outline._section_by_num = {s.number: s for s in sections}
        outline._definitions = []
        outline._def_by_name = {}
        outline._sorted_section_starts = []
        outline._sorted_section_nums = []
        outline._sorted_article_starts = []
        outline._sorted_article_nums = []

        if definitions is not None:
            outline._definitions = list(definitions)
            for d in definitions:
                normalized = d.term_name.replace("\u201c", "").replace("\u201d", "").lower()
                outline._def_by_name[normalized] = d
        else:
            # Scan definitions from text (structure map doesn't include them)
            outline._build_definition_index()

        outline._build_positional_indices()
        return outline

    @classmethod
    def from_structure_map(cls, text: str, entry: dict[str, Any]) -> DocOutline:
        """Build outline from a corpus_structure_map.json entry.

        S5: Uses pre-computed article and section data from the structure
        map to avoid regex scanning. Definitions are always scanned from
        text (the structure map doesn't capture them). Falls back to full
        text scanning if the entry has no article data.

        Expected entry format (from analysis/corpus_structure_map.json per_ca)::

            {
                "filename": "...",
                "articles": [
                    {"num": 1, "label": "I", "title": "...", "concept": "...",
                     "char_start": N, "char_end": N|null,
                     "sections": [
                        {"number": "1.01", "heading": "...",
                         "char_start": N, "char_end": N, "word_count": N}
                     ]}
                ]
            }
        """
        entry_articles = entry.get("articles", [])
        if not entry_articles:
            return cls.from_text(text, filename=entry.get("filename", ""))

        # Sort articles by char_start for boundary computation
        sorted_entries = sorted(entry_articles, key=lambda a: a.get("char_start", 0))

        # First pass: compute missing char_end boundaries
        for i, a in enumerate(sorted_entries):
            if a.get("char_end") is None:
                if i + 1 < len(sorted_entries):
                    a["char_end"] = sorted_entries[i + 1]["char_start"]
                else:
                    a["char_end"] = len(text)

        # Build OutlineArticle and OutlineSection objects
        articles: list[OutlineArticle] = []
        sections: list[OutlineSection] = []

        for a in sorted_entries:
            art_sections: list[OutlineSection] = []
            for s in a.get("sections", []):
                sec = OutlineSection(
                    number=s["number"],
                    heading=s.get("heading", ""),
                    char_start=s["char_start"],
                    char_end=s.get("char_end", a["char_end"]),
                    article_num=a["num"],
                    word_count=s.get("word_count", 0),
                )
                art_sections.append(sec)
                sections.append(sec)

            article = OutlineArticle(
                num=a["num"],
                label=a.get("label", str(a["num"])),
                title=a.get("title", ""),
                concept=a.get("concept"),
                char_start=a["char_start"],
                char_end=a["char_end"],
                sections=tuple(art_sections),
                is_synthetic=bool(a.get("is_synthetic", False)),
            )
            articles.append(article)

        # Definitions are always scanned from text (pass definitions=None)
        return cls._from_prebuilt(
            text, filename=entry.get("filename", ""),
            articles=articles, sections=sections, definitions=None,
        )

    # ── Summary / repr ─────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Return a summary dict for diagnostics."""
        return {
            "filename": self._filename,
            "article_count": len(self._articles),
            "synthetic_article_count": len(self._synthetic_article_nums),
            "synthetic_article_nums": sorted(self._synthetic_article_nums),
            "section_count": len(self._sections),
            "definition_count": len(self._definitions),
            "text_length": len(self._text),
        }

    def __repr__(self) -> str:
        return (
            f"DocOutline({self._filename!r}, "
            f"articles={len(self._articles)}, "
            f"sections={len(self._sections)}, "
            f"definitions={len(self._definitions)})"
        )
