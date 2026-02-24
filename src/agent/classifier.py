"""Pure classification logic — regex signal extraction + rule-based classification.

Absorbs 17 regex patterns from TI's ``corpus_classifier.py``:

**Absorbed (17 patterns):**
    1. RE_DEFINITION — ``"Term" means``
    2. RE_DEFINITION_COLON — ``"Term": definition``
    3. RE_DEFINITION_UNQUOTED — ``Term. Definition text``
    4. RE_ARTICLE — ``ARTICLE VII``
    5. RE_NEGCOV_HEADING — ``ARTICLE VII NEGATIVE COVENANTS``
    6. RE_BASKET_LANGUAGE — ``basket``, ``permitted``, ``exception``
    7. RE_SECTION_NUMBER — ``7.01``
    8. RE_FINANCIAL_COVENANT — ``FINANCIAL COVENANT``
    9. RE_MAINTENANCE — leverage ratio / coverage ratio tests
    10. RE_CONSOLIDATED_EBITDA — ``Consolidated EBITDA``
    11. RE_AVAILABLE_AMOUNT — ``Available Amount``
    12. RE_INCREMENTAL — ``Incremental Facility/Commitment/Loan``
    13. RE_GROWER_BASKET — ``greater of $X and Y% of Metric``
    14. RE_GROWER_BASKET_TIMES — ``greater of $X and 0.YY times Metric``
    15. RE_GROWER_BASKET_ALT — ``$X and Y% of Metric`` (no "greater of")
    16. RE_GROWER_BASKET_ALT_TIMES — ``$X and 0.YY times Metric``
    17. RE_IN_WITNESS — ``IN WITNESS WHEREOF``

**Dropped (2 HTML-specific patterns):**
    - RE_DEFINITION_U_TAG — matches ``<u>Term</u>`` in raw HTML
    - RE_DEFINITION_BOLD_ITALIC — matches CSS bold-italic formatting

    VP operates on normalized text (post-HTML-strip), so HTML tag patterns
    are redundant.  The remaining 3 definition patterns (quoted, colon,
    unquoted) capture the same terms post-normalization.  Regression
    fixtures in ``test_l0_corpus_classifier.py`` verify zero recall loss.

No file I/O, no corpus iteration — pure functions only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Classification Signals Contract ───────────────────────────────────
# Defined inline (VP imports from vantage_platform.contracts.document).
# Frozen dataclass with 15 typed fields — downstream code uses typed
# attribute access, eliminating cast()/isinstance() noise under pyright strict.


@dataclass(frozen=True, slots=True)
class ClassificationSignals:
    """15 classification signals extracted from normalized text."""

    word_count: int
    definition_count: int
    article_count: int
    has_negative_covenants: bool
    negcov_subsection_count: int
    has_financial_covenants: bool
    has_maintenance_covenants: bool
    has_consolidated_ebitda: bool
    has_available_amount: bool
    has_incremental: bool
    has_grower_baskets: bool
    grower_basket_dollar_amount: float | None
    basket_language_count: int
    has_signature_block: bool
    title_text: str


# ── Definition Patterns ─────────────────────────────────────────────────

# Pattern 1: Quoted term + "means" / "shall mean" / "has the meaning" variants
RE_DEFINITION: re.Pattern[str] = re.compile(
    r'[\"\u201c\u201d]\s*([^\"\u201c\u201d]{2,80}?)[\"\u201c\u201d]\s*'
    r'(?:means|shall\s+mean|shall\s+have\s+the\s+meaning|has\s+the\s+meaning|have\s+the\s+meaning)',
    re.IGNORECASE,
)

# Pattern 2: Quoted term + colon — e.g. "Consolidated EBITDA": means ...
# Guard: captured term must start with uppercase to avoid false positives.
RE_DEFINITION_COLON: re.Pattern[str] = re.compile(
    r'[\"\u201c\u201d]\s*([A-Z][^\"\u201c\u201d]{1,79}?)[\"\u201c\u201d]\s*:\s+[a-zA-Z(]',
)

# Pattern 3: Unquoted definitions — "Term. Definition text..."
# Title Case 1-8 words, followed by period + definition-starting word.
# Only activated in first 40% of text and only if >20 matches (dominant format).
RE_DEFINITION_UNQUOTED: re.Pattern[str] = re.compile(
    r'(?:^|(?<=\. )|(?<=\n))'
    r'([A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|of|the|and|or|for|in|to|a|an|on|by|as|with|at|de|du|per|non|sub|pre|co|re|un))+)\s*\.\s+'
    r'(?:The |An? |Each |Any |All |With respect|For (?:any|the|purposes)'
    r'|[Mm]eans? |[Ss]hall (?:mean|have)|[Hh]as the meaning)',
)

# False-positive exclusions for Pattern 3
_UNQUOTED_FALSE_POS: frozenset[str] = frozenset({
    'The', 'In', 'If', 'No', 'An', 'At', 'As', 'To', 'On', 'By',
    'For', 'Each', 'Any', 'All', 'Such', 'Subject', 'Section', 'Article',
    'Notwithstanding', 'Without', 'Except', 'Upon', 'Unless', 'Pursuant',
    'Including', 'Provided', 'Exhibit', 'Schedule', 'Table', 'Date',
})

# ── Structural Patterns ─────────────────────────────────────────────────

RE_ARTICLE: re.Pattern[str] = re.compile(
    r'ARTICLE\s+[IVXLCDM0-9]+\b',
    re.IGNORECASE,
)

RE_NEGCOV_HEADING: re.Pattern[str] = re.compile(
    r'ARTICLE\s+[IVXLCDM0-9]+[^<]{0,50}NEGATIVE\s+COVENANT',
    re.IGNORECASE,
)

RE_SECTION_NUMBER: re.Pattern[str] = re.compile(
    r'\b(\d+\.\d{2})\b',
)

# ── Feature Patterns ────────────────────────────────────────────────────

RE_FINANCIAL_COVENANT: re.Pattern[str] = re.compile(
    r'FINANCIAL\s+COVENANT',
    re.IGNORECASE,
)

RE_MAINTENANCE: re.Pattern[str] = re.compile(
    r'(?:Consolidated\s+(?:Total\s+)?(?:Net\s+)?Leverage\s+Ratio|'
    r'Consolidated\s+(?:Total\s+)?(?:Net\s+)?Debt\s+(?:to|/)\s+(?:Consolidated\s+)?EBITDA|'
    r'Total\s+Leverage\s+Ratio|'
    r'First\s+Lien\s+(?:Net\s+)?Leverage\s+Ratio|'
    r'Consolidated\s+Interest\s+Coverage\s+Ratio|'
    r'Fixed\s+Charge\s+Coverage\s+Ratio|'
    r'Consolidated\s+Senior\s+Secured\s+(?:Net\s+)?Leverage\s+Ratio)'
    r'\s+(?:shall\s+not\s+(?:exceed|be\s+(?:greater|less)\s+than)|'
    r'does\s+not\s+exceed|'
    r'is\s+(?:greater|less)\s+than\s+or\s+equal\s+to)',
    re.IGNORECASE,
)

RE_CONSOLIDATED_EBITDA: re.Pattern[str] = re.compile(
    r'Consolidated\s+(?:Adjusted\s+)?EBITDA',
    re.IGNORECASE,
)

RE_AVAILABLE_AMOUNT: re.Pattern[str] = re.compile(
    r'Available\s+Amount',
    re.IGNORECASE,
)

RE_INCREMENTAL: re.Pattern[str] = re.compile(
    r'Incremental\s+(?:Term\s+)?(?:Facility|Commitment|Loan|Amendment)',
    re.IGNORECASE,
)

RE_IN_WITNESS: re.Pattern[str] = re.compile(
    r'IN\s+WITNESS\s+WHEREOF',
    re.IGNORECASE,
)

# ── Grower Basket Patterns ──────────────────────────────────────────────

_METRIC_PATTERN = (
    r'((?:Consolidated\s+)?(?:Adjusted\s+)?'
    r'(?:EBITDA|Total\s+Assets|Consolidated\s+Total\s+Assets|LTM\s+EBITDA'
    r'|(?:Net\s+)?Tangible\s+Assets|Net\s+Worth|Shareholders?\s*[\u2019\']?\s*Equity'
    r'|Stockholders?\s*[\u2019\']?\s*Equity|Total\s+Capitalization'
    r'|Net\s+(?:Tangible\s+)?Assets|Book\s+Value))'
)

# Pattern A: "greater of $X and Y% of [metric]"
RE_GROWER_BASKET: re.Pattern[str] = re.compile(
    r'(?:the\s+)?greater\s+of\s+'
    r'(?:\((?:x|i|a|1|A)\)\s*)?'
    r'\$\s*([\d,]+(?:\.\d+)?)\s*'
    r'(?:,?000,?000|million|,000)?'
    r'\s+and\s+'
    r'(?:\((?:y|ii|b|2|B)\)\s*)?'
    r'(\d+(?:\.\d+)?)\s*%\s*of\s+'
    + _METRIC_PATTERN,
    re.IGNORECASE,
)

# Pattern B: "greater of $X and 0.YY times [metric]"
RE_GROWER_BASKET_TIMES: re.Pattern[str] = re.compile(
    r'(?:the\s+)?greater\s+of\s+'
    r'(?:\((?:x|i|a|1|A)\)\s*)?'
    r'\$\s*([\d,]+(?:\.\d+)?)\s*'
    r'(?:,?000,?000|million|,000)?'
    r'\s+and\s+'
    r'(?:\((?:y|ii|b|2|B)\)\s*)?'
    r'(\d+(?:\.\d+)?)\s*(?:times|x)\s+'
    r'(?:the\s+)?'
    + _METRIC_PATTERN,
    re.IGNORECASE,
)

# Pattern C: "$X and Y% of [metric]" (without "greater of")
RE_GROWER_BASKET_ALT: re.Pattern[str] = re.compile(
    r'\$\s*([\d,]+(?:\.\d+)?)\s*'
    r'(?:,?000,?000|million|,000)?'
    r'\s+(?:and|or)\s+'
    r'(\d+(?:\.\d+)?)\s*%\s*of\s+'
    + _METRIC_PATTERN,
    re.IGNORECASE,
)

# Pattern D: "$X and 0.YY times [metric]" (without "greater of")
RE_GROWER_BASKET_ALT_TIMES: re.Pattern[str] = re.compile(
    r'\$\s*([\d,]+(?:\.\d+)?)\s*'
    r'(?:,?000,?000|million|,000)?'
    r'\s+(?:and|or)\s+'
    r'(\d+(?:\.\d+)?)\s*(?:times|x)\s+'
    r'(?:the\s+)?'
    + _METRIC_PATTERN,
    re.IGNORECASE,
)

RE_BASKET_LANGUAGE: re.Pattern[str] = re.compile(
    r'\b(?:basket|permitted|exception)\b',
    re.IGNORECASE,
)

# ── Document Type Keyword Lists ─────────────────────────────────────────

AMENDMENT_KEYWORDS: list[str] = [
    r'\bAmendment\s+No\.\s*\d',
    r'\bFirst\s+Amendment\b',
    r'\bSecond\s+Amendment\b',
    r'\bThird\s+Amendment\b',
    r'\bFourth\s+Amendment\b',
    r'\bFifth\s+Amendment\b',
    r'\bSixth\s+Amendment\b',
    r'\bSeventh\s+Amendment\b',
    r'\bEighth\s+Amendment\b',
    r'\bNinth\s+Amendment\b',
    r'\bTenth\s+Amendment\b',
    r'\bOmnibus\s+Amendment\b',
    r'\bAmendment\s+and\s+(?:Restatement|Waiver|Extension)\b',
    r'\bAmendment\s+(?:to|of)\s+(?:the\s+)?(?:Credit|Loan)\b',
    r'\bIncremental\s+(?:Term\s+)?(?:Facility\s+)?Amendment\b',
]

WAIVER_KEYWORDS: list[str] = [
    r'\bLimited\s+Waiver\b',
    r'\bWaiver\s+(?:and|of)\b',
    r'\bConsent\s+(?:and|to)\b',
    r'\bWaiver\b(?!.*(?:Credit\s+Agreement|Loan\s+Agreement))',
]

GUARANTY_KEYWORDS: list[str] = [
    r'\bGuaranty\s+Agreement\b',
    r'\bGuarantee\s+Agreement\b',
    r'\bGuaranty\b(?!.*(?:Credit\s+Agreement|Loan\s+Agreement))',
]

INTERCREDITOR_KEYWORDS: list[str] = [
    r'\bIntercreditor\s+Agreement\b',
    r'\bSubordination\s+Agreement\b',
    r'\bInter-?creditor\b',
]

SUPPLEMENT_KEYWORDS: list[str] = [
    r'\bLender\s+Supplement\b',
    r'\bJoinder\s+Agreement\b',
    r'\bIncreasing\s+Lender\b',
    r'\bAssumption\s+Agreement\b',
    r'\bSupplement\s+(?:to|No\.)\b',
]

CA_KEYWORDS: list[str] = [
    r'\bCredit\s+(?:and\s+(?:Guaranty|Security)\s+)?Agreement\b',
    r'\bLoan\s+(?:and\s+(?:Security|Guaranty)\s+)?Agreement\b',
    r'\bCredit\s+Facility\s+Agreement\b',
    r'\bTerm\s+Loan\s+(?:Credit\s+)?Agreement\b',
    r'\bRevolving\s+Credit\s+(?:and\s+(?:Term\s+Loan|Guaranty)\s+)?Agreement\b',
    r'\bFirst\s+Lien\s+Credit\s+Agreement\b',
    r'\bSecond\s+Lien\s+Credit\s+Agreement\b',
    r'\bSenior\s+Secured\s+Credit\s+Agreement\b',
    r'\bAmended\s+and\s+Restated\s+Credit\s+Agreement\b',
    r'\bA\s*&\s*R\s+Credit\s+Agreement\b',
]

# Pattern to detect "Amendment [No. X / First / etc.] ... to ... Credit/Loan Agreement".
# The word "to" connecting the amendment reference to the CA reference is the key signal
# distinguishing "Amendment No. 3 to Amended and Restated Credit Agreement" (amendment)
# from standalone "Amended and Restated Credit Agreement" (credit agreement).
# Note: \bAmendment\b does NOT match "Amended" — no false positives on standalone A&R CAs.
RE_AMENDMENT_TO_CA: re.Pattern[str] = re.compile(
    r'\bAmendment\b'
    r'.{0,120}?'
    r'\bto\b'
    r'.{0,120}?'
    r'(?:Credit|Loan)\s+(?:and\s+\w+\s+)?(?:Facility\s+)?Agreement',
    re.IGNORECASE | re.DOTALL,
)


# ── Helper Functions ────────────────────────────────────────────────────


def _has_any_keyword(text: str, patterns: list[str]) -> bool:
    """Check if text matches any regex pattern in the list."""
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _has_any_grower_basket(text: str) -> bool:
    """Check if text contains any grower basket pattern."""
    return bool(
        RE_GROWER_BASKET.search(text)
        or RE_GROWER_BASKET_TIMES.search(text)
        or RE_GROWER_BASKET_ALT.search(text)
        or RE_GROWER_BASKET_ALT_TIMES.search(text)
    )


def _normalize_dollar_to_millions(dollar_str: str, context: str) -> float | None:
    """Convert a dollar string to millions.

    Args:
        dollar_str: The numeric part (e.g., "100,000,000" or "100").
        context: Surrounding text to check for "million", ",000,000" etc.

    Returns:
        Value in millions, or None if can't parse.
    """
    try:
        clean = dollar_str.replace(',', '')
        val = float(clean)
    except (ValueError, TypeError):
        return None

    context_lower = context.lower()
    if 'million' in context_lower:
        return val
    if val >= 1_000_000:
        return val / 1_000_000
    if val >= 1_000:
        if ',000,000' in context or '000,000' in context:
            return val / 1_000_000
        return val / 1_000
    return val


def _extract_grower_basket_info(text: str) -> tuple[float | None, str | None]:
    """Extract the first grower basket dollar amount and metric name.

    Returns:
        ``(dollar_amount_in_millions, metric_name)``.
        metric_name is e.g. ``"Consolidated EBITDA"``.
    """
    for pattern in [RE_GROWER_BASKET, RE_GROWER_BASKET_TIMES,
                    RE_GROWER_BASKET_ALT, RE_GROWER_BASKET_ALT_TIMES]:
        m = pattern.search(text)
        if m:
            dollar_str = m.group(1)
            context = m.group(0)
            metric = m.group(3).strip()
            amount = _normalize_dollar_to_millions(dollar_str, context)
            return amount, metric
    return None, None


def _is_ebitda_metric(metric: str) -> bool:
    """Check if the captured metric name references EBITDA."""
    return 'EBITDA' in metric.strip().upper()


def _count_negcov_subsections(text: str) -> int:
    """Count subsections under the Negative Covenants article."""
    m = RE_NEGCOV_HEADING.search(text)
    if not m:
        broad = re.search(r'Negative\s+Covenant', text, re.IGNORECASE)
        if not broad:
            return 0
        start_pos = broad.end()
    else:
        start_pos = m.end()

    rest = text[start_pos:]
    next_article = RE_ARTICLE.search(rest)
    negcov_section = rest[:next_article.start()] if next_article else rest[:50000]

    section_nums = RE_SECTION_NUMBER.findall(negcov_section)
    return len(set(section_nums))


def _extract_title(text: str, max_chars: int = 2000) -> str:
    """Extract document title from the first portion of normalized text.

    Unlike TI's version which inspects ``<title>`` tags in raw HTML,
    VP operates on normalized text so we take the first 500 chars of
    the document as a title proxy.
    """
    return text[:max_chars].strip()[:500]


# ── Public API ──────────────────────────────────────────────────────────


def extract_classification_signals(
    normalized_text: str,
    filename: str = "",
) -> ClassificationSignals:
    """Extract 15 classification signals from normalized text.

    Returns a frozen dataclass — NOT a dict.  All downstream code
    accesses signals via typed attribute access, eliminating
    ``cast()``/``isinstance()`` noise under pyright strict.

    Args:
        normalized_text: HTML-stripped, whitespace-collapsed CA text.
        filename: Source filename (reserved for future heuristics).

    Returns:
        Strongly-typed ``ClassificationSignals`` instance.
    """
    _ = filename  # reserved — prevents pyright "unused parameter" warning
    text = normalized_text

    # Word count
    word_count = len(text.split())

    # Title
    title_text = _extract_title(text)

    # ── Definition counting ──
    # Pattern 1: "Term" means
    means_defs: set[str] = set()
    for m in RE_DEFINITION.finditer(text):
        means_defs.add(m.group(1).strip().lower())

    # Pattern 2: "Term": definition
    colon_defs: set[str] = set()
    for m in RE_DEFINITION_COLON.finditer(text):
        term = m.group(1).strip()
        if term.lower() not in means_defs:
            colon_defs.add(term.lower())

    # Pattern 3: Unquoted — only in first 40%, activated if dominant
    unquoted_defs: set[str] = set()
    cutoff_40pct = int(len(text) * 0.40)
    defs_section = text[:cutoff_40pct]
    for m in RE_DEFINITION_UNQUOTED.finditer(defs_section):
        term = m.group(1).strip()
        if (
            term not in _UNQUOTED_FALSE_POS
            and len(term) > 3
            and term.lower() not in means_defs
            and term.lower() not in colon_defs
        ):
            unquoted_defs.add(term.lower())

    quoted_total = len(means_defs) + len(colon_defs)

    # Unquoted: only activate if dominant format (>20 matches AND >2x quoted)
    if len(unquoted_defs) >= 20 and len(unquoted_defs) > quoted_total * 2:
        definition_count = quoted_total + len(unquoted_defs)
    else:
        definition_count = quoted_total

    # Article count
    article_count = len(RE_ARTICLE.findall(text))

    # Negative covenants
    has_negative_covenants = bool(re.search(r'Negative\s+Covenant', text, re.IGNORECASE))
    negcov_subsection_count = _count_negcov_subsections(text) if has_negative_covenants else 0

    # Feature presence
    has_financial_covenants = bool(RE_FINANCIAL_COVENANT.search(text))
    has_maintenance_covenants = bool(RE_MAINTENANCE.search(text))
    has_consolidated_ebitda = bool(RE_CONSOLIDATED_EBITDA.search(text))
    has_available_amount = bool(RE_AVAILABLE_AMOUNT.search(text))
    has_incremental = bool(RE_INCREMENTAL.search(text))
    has_signature_block = bool(RE_IN_WITNESS.search(text))

    # Grower baskets
    has_grower_baskets = _has_any_grower_basket(text)
    grower_basket_dollar_amount: float | None = None
    if has_grower_baskets:
        raw_amount, metric = _extract_grower_basket_info(text)
        if metric and _is_ebitda_metric(metric):
            grower_basket_dollar_amount = raw_amount

    # Basket language count
    basket_language_count = len(RE_BASKET_LANGUAGE.findall(text))

    return ClassificationSignals(
        word_count=word_count,
        definition_count=definition_count,
        article_count=article_count,
        has_negative_covenants=has_negative_covenants,
        negcov_subsection_count=negcov_subsection_count,
        has_financial_covenants=has_financial_covenants,
        has_maintenance_covenants=has_maintenance_covenants,
        has_consolidated_ebitda=has_consolidated_ebitda,
        has_available_amount=has_available_amount,
        has_incremental=has_incremental,
        has_grower_baskets=has_grower_baskets,
        grower_basket_dollar_amount=grower_basket_dollar_amount,
        basket_language_count=basket_language_count,
        has_signature_block=has_signature_block,
        title_text=title_text,
    )


def classify_document_type(
    filename: str,
    signals: ClassificationSignals,
) -> tuple[str, str, list[str]]:
    """Classify document type from filename, title, and content signals.

    5-priority classification:
        1. A&R + CA keywords -> credit_agreement
        2. CA keyword + large -> credit_agreement
        3. Non-CA keywords without CA keywords -> amendment/waiver/etc.
        4. Structural signals (articles + defs + signature) -> credit_agreement
        5. Default -> other

    Args:
        filename: Source filename.
        signals: Typed classification signals.

    Returns:
        ``(doc_type, confidence, reasons)`` where confidence is
        ``"high"`` or ``"medium"``.
    """
    reasons: list[str] = []
    fname_spaced = filename.lower().replace('_', ' ')
    title = signals.title_text
    check_text = fname_spaced + " | " + title

    # Detect keyword presence
    has_ca_kw = _has_any_keyword(check_text, CA_KEYWORDS)
    has_amendment_kw = _has_any_keyword(check_text, AMENDMENT_KEYWORDS)
    has_waiver_kw = _has_any_keyword(check_text, WAIVER_KEYWORDS)
    has_guaranty_kw = _has_any_keyword(check_text, GUARANTY_KEYWORDS)
    has_intercreditor_kw = _has_any_keyword(check_text, INTERCREDITOR_KEYWORDS)
    has_supplement_kw = _has_any_keyword(check_text, SUPPLEMENT_KEYWORDS)

    has_ar = bool(re.search(
        r'Amended\s+and\s+Restated\s+(?:Credit|Loan|Revolving|Term\s+Loan)\s+'
        r'(?:and\s+\w+\s+)?(?:Facility\s+)?Agreement',
        check_text, re.IGNORECASE,
    ))

    has_ca_guaranty = bool(re.search(
        r'(?:Credit\s+Agreement\s+and\s+Guaranty|Credit\s+and\s+Guaranty\s+Agreement)',
        check_text, re.IGNORECASE,
    ))

    is_large = signals.word_count >= 30000 or signals.definition_count >= 100

    # --- Priority 0: Amendment to CA (must fire before CA classification) ---
    # "Amendment No. 3 to Amended and Restated Credit Agreement" is an amendment,
    # not a standalone CA — even if the full restated agreement is attached as annex.
    if has_amendment_kw and RE_AMENDMENT_TO_CA.search(check_text):
        reasons.append("Amendment to Credit Agreement")
        return "amendment", "high", reasons

    # --- Priority 1: Clear CA ---
    if has_ca_kw and has_ar:
        reasons.append("Amended and Restated Credit Agreement")
        return "credit_agreement", "high", reasons

    if has_ca_guaranty:
        reasons.append("Credit Agreement and Guaranty (full CA)")
        return "credit_agreement", "high", reasons

    if has_ca_kw and is_large:
        reasons.append(
            f"Credit agreement keyword + large document "
            f"({signals.word_count} words, {signals.definition_count} defs)"
        )
        return "credit_agreement", "high", reasons

    # --- Priority 2: Non-CA types (small/medium) ---
    if has_intercreditor_kw and not has_ca_kw:
        reasons.append("Intercreditor keyword in filename/title")
        return "intercreditor", "high", reasons

    if has_amendment_kw and not has_ca_kw and not has_ar:
        reasons.append("Amendment keyword in filename/title")
        return "amendment", "high", reasons

    if has_amendment_kw and has_ca_kw and not is_large:
        reasons.append("Amendment keyword with CA reference (small document)")
        return "amendment", "medium", reasons

    if has_waiver_kw and not has_ca_kw:
        reasons.append("Waiver keyword in filename/title")
        return "waiver", "high", reasons

    if has_guaranty_kw and not has_ca_kw and not has_ca_guaranty:
        reasons.append("Guaranty keyword in filename/title")
        return "guaranty", "high", reasons

    if has_supplement_kw and not has_ca_kw:
        if is_large:
            reasons.append(
                f"Supplement keyword but large document ({signals.word_count} words, "
                f"{signals.definition_count} defs) — treating as CA"
            )
            return "credit_agreement", "medium", reasons
        reasons.append("Supplement/joinder keyword in filename/title")
        return "supplement", "high", reasons

    # --- Priority 3: CA from keywords alone ---
    if has_ca_kw:
        reasons.append("Credit agreement keyword in filename/title")
        return "credit_agreement", "medium", reasons

    # --- Priority 4: Content-based fallback ---
    has_structure = (
        signals.article_count >= 5 and signals.definition_count >= 20
        and signals.has_signature_block
    )
    if has_structure:
        reasons.append(
            f"Structural signals: {signals.article_count} articles, "
            f"{signals.definition_count} definitions, signature block present"
        )
        return "credit_agreement", "medium", reasons

    if signals.has_negative_covenants and signals.definition_count >= 30:
        reasons.append(f"Has negative covenants + {signals.definition_count} definitions")
        return "credit_agreement", "medium", reasons

    if signals.word_count >= 30000 and signals.definition_count >= 50:
        reasons.append(
            f"Large document ({signals.word_count} words) with "
            f"{signals.definition_count} definitions"
        )
        return "credit_agreement", "medium", reasons

    if signals.word_count >= 25000 and signals.has_signature_block:
        reasons.append(f"Large document ({signals.word_count} words) with signature block")
        return "credit_agreement", "medium", reasons

    if signals.word_count >= 40000:
        reasons.append(f"Very large document ({signals.word_count} words)")
        return "credit_agreement", "medium", reasons

    # --- Priority 5: Small non-CA from content ---
    if signals.word_count < 15000:
        if re.search(r'amendment|amend', title, re.IGNORECASE):
            reasons.append("Short document with amendment language in title")
            return "amendment", "medium", reasons
        if re.search(r'waiver|consent', title, re.IGNORECASE):
            reasons.append("Short document with waiver/consent language in title")
            return "waiver", "medium", reasons
        if re.search(r'supplement|joinder', title, re.IGNORECASE):
            reasons.append("Short document with supplement/joinder language in title")
            return "supplement", "medium", reasons
        if re.search(r'intercreditor|subordination', title, re.IGNORECASE):
            reasons.append("Short document with intercreditor language in title")
            return "intercreditor", "medium", reasons

    # Moderate structure
    if signals.article_count >= 3 and signals.definition_count >= 10:
        reasons.append(
            f"Moderate structure: {signals.article_count} articles, "
            f"{signals.definition_count} definitions"
        )
        return "credit_agreement", "medium", reasons

    # Default
    reasons.append(
        f"No clear classification signals "
        f"(articles={signals.article_count}, "
        f"defs={signals.definition_count}, "
        f"words={signals.word_count})"
    )
    return "other", "low", reasons


def classify_market_segment(
    signals: ClassificationSignals,
) -> tuple[str, str, list[str]]:
    """Classify market segment for credit agreements.

    2-tier classification:
        - Leveraged: grower baskets + NegCov + definitions
        - Investment grade: no grower + no NegCov

    Args:
        signals: Typed classification signals.

    Returns:
        ``(segment, confidence, reasons)`` where segment is one of
        ``"leveraged"`` | ``"investment_grade"`` | ``"uncertain"``.
    """
    reasons: list[str] = []

    has_grower = signals.has_grower_baskets
    negcov_subs = signals.negcov_subsection_count
    def_count = signals.definition_count
    has_negcov = signals.has_negative_covenants
    has_avail = signals.has_available_amount
    has_incr = signals.has_incremental
    has_ebitda = signals.has_consolidated_ebitda
    has_maint = signals.has_maintenance_covenants

    leveraged_signals = sum([
        has_grower,
        has_avail,
        has_incr,
        has_ebitda,
        has_maint,
        negcov_subs >= 6,
        def_count >= 150,
    ])

    # ── Leveraged (high confidence) ──
    if has_grower and negcov_subs >= 6 and def_count >= 150:
        reasons.append(
            f"Grower baskets present, {negcov_subs} NegCov subsections, "
            f"{def_count} definitions"
        )
        return "leveraged", "high", reasons

    if negcov_subs >= 8 and def_count >= 200 and leveraged_signals >= 4:
        feats: list[str] = []
        if has_grower:
            feats.append("grower baskets")
        if has_avail:
            feats.append("Available Amount")
        if has_incr:
            feats.append("Incremental facility")
        if has_ebitda:
            feats.append("Consolidated EBITDA")
        if has_maint:
            feats.append("maintenance covenants")
        reasons.append(
            f"{negcov_subs} NegCov subsections, {def_count} definitions, "
            f"leveraged features: {', '.join(feats)}"
        )
        return "leveraged", "high", reasons

    # ── Leveraged (medium confidence) ──
    if has_grower and (negcov_subs >= 4 or def_count >= 100):
        reasons.append(
            f"Grower baskets present, {negcov_subs} NegCov subsections, "
            f"{def_count} definitions"
        )
        return "leveraged", "medium", reasons

    if negcov_subs >= 6 and def_count >= 150:
        feats = []
        if has_avail:
            feats.append("Available Amount")
        if has_incr:
            feats.append("Incremental facility")
        if has_ebitda:
            feats.append("Consolidated EBITDA")
        reasons.append(
            f"{negcov_subs} NegCov subsections, {def_count} definitions"
            + (f", plus: {', '.join(feats)}" if feats else "")
        )
        return "leveraged", "medium", reasons

    if has_avail and has_incr and def_count >= 100:
        reasons.append(
            f"Available Amount + Incremental facility, {def_count} definitions, "
            f"{negcov_subs} NegCov subsections"
        )
        return "leveraged", "medium", reasons

    # ── Investment Grade (high confidence) ──
    if not has_negcov and not has_grower:
        reasons.append("No grower baskets, no negative covenants")
        return "investment_grade", "high", reasons

    # ── Investment Grade (medium confidence) ──
    if (not has_grower and negcov_subs <= 3 and def_count < 100
            and not has_avail and not has_incr):
        reasons.append(
            f"No grower baskets, {negcov_subs} NegCov subsections, "
            f"{def_count} definitions, no leveraged features"
        )
        return "investment_grade", "medium", reasons

    if (not has_grower and negcov_subs <= 5 and def_count < 150
            and not has_avail and not has_incr and not has_maint):
        reasons.append(
            f"No grower baskets, {negcov_subs} NegCov subsections, "
            f"{def_count} definitions, no leveraged features"
        )
        return "investment_grade", "medium", reasons

    # ── Uncertain ──
    reason_parts: list[str] = []
    if has_grower:
        reason_parts.append("has grower baskets")
    else:
        reason_parts.append("no grower baskets")
    reason_parts.append(f"{negcov_subs} NegCov subsections")
    reason_parts.append(f"{def_count} definitions")
    if has_avail:
        reason_parts.append("has Available Amount")
    if has_incr:
        reason_parts.append("has Incremental facility")
    if has_ebitda:
        reason_parts.append("has Consolidated EBITDA")
    if has_maint:
        reason_parts.append("has maintenance covenants")
    reasons.append("Mixed signals: " + ", ".join(reason_parts))
    return "uncertain", "medium", reasons
