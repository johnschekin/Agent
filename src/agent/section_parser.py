"""Section parser for credit agreement HTML documents.

Parses HTML credit agreements to extract article and section boundaries with:
- Article detection (ARTICLE I, ARTICLE II, etc.)
- Section detection (Section 1.01, 2.14, etc.)
- Heading extraction
- Character span boundaries (global offsets in normalized text)

3-phase approach:
    1. Find articles (ARTICLE I, ARTICLE II, etc.) using regex.
    2. Find sections (Section X.YY) within each article's char range.
    3. Extract headings from text following section number.

Standalone module -- no imports from vantage_platform or termintelligence.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutlineSection:
    """A section in the document outline (e.g., Section 7.02)."""

    number: str         # "7.02"
    heading: str        # "Indebtedness"
    char_start: int     # Global char offset in normalized text
    char_end: int       # Global char offset (exclusive)
    article_num: int
    word_count: int


@dataclass(frozen=True, slots=True)
class OutlineArticle:
    """An article containing sections (e.g., ARTICLE VII)."""

    num: int
    label: str          # "VII" or "7"
    title: str
    char_start: int
    char_end: int
    sections: tuple[OutlineSection, ...]


# ---------------------------------------------------------------------------
# Roman numeral / spelled-out number maps
# ---------------------------------------------------------------------------

_ROMAN_MAP: dict[str, int] = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
    "XXI": 21, "XXII": 22, "XXIII": 23, "XXIV": 24, "XXV": 25,
}

_WORD_NUM_MAP: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


def _roman_to_int(s: str) -> int | None:
    """Convert Roman numeral string to int, or None if not recognised."""
    return _ROMAN_MAP.get(s.upper())


def _word_to_int(s: str) -> int | None:
    """Convert spelled-out number to int, or None if not recognised."""
    return _WORD_NUM_MAP.get(s.lower())


def _label_to_int(label: str) -> int | None:
    """Convert any article label (Roman, digit, word) to int."""
    if label.isdigit():
        return int(label)
    result = _roman_to_int(label)
    if result is not None:
        return result
    return _word_to_int(label)


# ---------------------------------------------------------------------------
# Regex patterns -- proven across 1,198 EDGAR CAs
# ---------------------------------------------------------------------------

# Article heading: "ARTICLE VII", "Article 7", "ARTICLE ONE"
# Uses [IVX]+ for Roman numerals with post-validation via _ROMAN_MAP,
# avoiding alternation-ordering bugs with IV/IX/etc.
_ARTICLE_RE = re.compile(
    r"(?:^|\n)\s*(?:ARTICLE|Article)\s+"
    r"([IVX]+|"
    r"\d{1,2}|"
    r"[Oo]ne|[Tt]wo|[Tt]hree|[Ff]our|[Ff]ive|"
    r"[Ss]ix|[Ss]even|[Ee]ight|[Nn]ine|[Tt]en|"
    r"[Ee]leven|[Tt]welve|[Tt]hirteen|[Ff]ourteen|[Ff]ifteen)"
    r"\s*[.\-\u2013\u2014]?\s*([^\n]{0,120})",
    re.MULTILINE,
)

# Section heading: "Section 2.14", "SECTION 2.14", "§ 7.01"
# Uses [^\n]{0,120} instead of (.{0,120}?)(?:\n|$) to avoid failing on
# lines longer than 120 chars (the lazy quantifier cannot reach the newline
# anchor when the heading text exceeds 120 chars, causing entire sections
# to be silently dropped).
_SECTION_RE = re.compile(
    r"(?:^|\n)\s*(?:Section|SECTION|§)\s+"
    r"(\d{1,2}\.\d{2})"
    r"\s*[.\-\u2013\u2014]?\s*([^\n]{0,120})",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Heading extraction helpers
# ---------------------------------------------------------------------------

def _extract_heading(raw: str) -> str:
    """Extract a clean section/article heading from raw captured text.

    The raw text is everything after the section number on the same line
    (up to 120 chars).  We extract the heading portion -- typically the
    first few Title Case or ALL CAPS words before body text begins.

    Heading extraction strategy:
    1. Strip leading/trailing punctuation and whitespace.
    2. Truncate at first sentence boundary (". " followed by uppercase).
    3. Truncate at 120 chars.
    4. Reject if result looks like body text (>12 words).
    """
    if not raw:
        return ""
    # Take only up to the first newline (should not occur with [^\n] capture,
    # but defensive)
    nl_pos = raw.find("\n")
    if nl_pos >= 0:
        raw = raw[:nl_pos]
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", raw).strip()
    # Strip leading punctuation artifacts from HTML tables
    cleaned = re.sub(r"^[.\-\u2013\u2014;,:]+\s*", "", cleaned)
    # Strip trailing punctuation
    cleaned = cleaned.rstrip(".;,: ")
    if not cleaned:
        return ""

    # Truncate at first sentence boundary: ". " followed by uppercase letter
    # This separates "Defined Terms. As used in this Agreement..." into
    # heading="Defined Terms" and discards body text.
    sent_match = re.search(r"\.\s+[A-Z]", cleaned)
    if sent_match:
        cleaned = cleaned[:sent_match.start()].rstrip()

    # Also truncate at "; " which often separates heading from body in some CAs
    semi_match = re.search(r";\s+", cleaned)
    if semi_match and semi_match.start() > 3:
        candidate = cleaned[:semi_match.start()].rstrip()
        # Only truncate if the pre-semicolon text is plausible heading length
        if len(candidate.split()) <= 8:
            cleaned = candidate

    # Truncate to 120 chars
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rsplit(" ", 1)[0]

    # Reject if it looks like body text (too many words)
    if len(cleaned.split()) > 12:
        return ""

    return cleaned


def _extract_article_title(text: str, match_end: int) -> str:
    """Extract article title from text following an ARTICLE match.

    Looks at subsequent lines for an ALL-CAPS or Title Case title when
    the inline title capture is empty (common in EDGAR HTML where the
    article number and title are on separate lines).
    """
    scan_end = min(match_end + 300, len(text))
    scan_text = text[match_end:scan_end]

    lines = scan_text.split("\n", 3)
    for line in lines[:3]:
        candidate = line.strip()
        if not candidate:
            continue
        # Stop if it looks like another ARTICLE or SECTION heading
        if re.match(r"(?:ARTICLE|Article|Section|SECTION|§)\s", candidate):
            break
        # Accept if it starts with uppercase and is plausible heading length
        if candidate[0].isupper() and len(candidate.split()) <= 12:
            return _extract_heading(candidate)
        break
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_outline(text: str) -> list[OutlineArticle]:
    """Parse a normalized credit agreement text into articles and sections.

    3-phase approach:
    1. Find articles (ARTICLE I, ARTICLE II, etc.) using regex.
    2. Find sections (Section X.YY) within each article's char range.
    3. Extract headings from text following section number.

    Args:
        text: Normalized text (output of normalize_html or strip_html).

    Returns:
        List of OutlineArticle, each containing its sections.
    """
    if not text:
        return []

    # Phase 1: Find all articles
    articles = _find_articles(text)

    # Phase 2: Find all sections and assign to articles
    sections = _find_all_sections(text, articles)

    # Phase 3: Group sections into articles and build OutlineArticle objects
    return _build_articles(articles, sections)


def find_sections(text: str) -> list[OutlineSection]:
    """Find all sections in text without requiring article structure.

    Useful for documents that don't have clear article boundaries.

    Args:
        text: Normalized text.

    Returns:
        List of OutlineSection (article_num will be 0 for all).
    """
    if not text:
        return []

    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return []

    # Deduplicate by section number (prefer match with heading, then earliest)
    best: dict[str, re.Match[str]] = {}
    for m in matches:
        number = m.group(1)
        if number not in best:
            best[number] = m
        else:
            cur_heading = _extract_heading(best[number].group(2) or "")
            new_heading = _extract_heading(m.group(2) or "")
            if new_heading and not cur_heading:
                best[number] = m

    deduped = sorted(best.values(), key=lambda m: m.start())

    results: list[OutlineSection] = []
    for i, m in enumerate(deduped):
        number = m.group(1)
        heading = _extract_heading(m.group(2) or "")
        char_start = m.start()

        # char_end: start of next section, or end of text
        if i + 1 < len(deduped):
            char_end = deduped[i + 1].start()
        else:
            char_end = len(text)

        section_text = text[char_start:char_end]
        word_count = len(section_text.split())

        results.append(OutlineSection(
            number=number,
            heading=heading,
            char_start=char_start,
            char_end=char_end,
            article_num=0,
            word_count=word_count,
        ))

    return results


# ---------------------------------------------------------------------------
# Internal: Phase 1 -- article detection
# ---------------------------------------------------------------------------

def _find_articles(text: str) -> list[dict[str, int | str]]:
    """Find all ARTICLE headings and compute their char spans."""
    matches: list[dict[str, int | str]] = []

    for m in _ARTICLE_RE.finditer(text):
        label = m.group(1)
        num = _label_to_int(label)
        if num is None:
            continue

        # Extract title: first try the inline capture (group 2), then fallback
        raw_title = (m.group(2) or "").strip()
        title = _extract_heading(raw_title)
        if not title:
            title = _extract_article_title(text, m.end())

        matches.append({
            "num": num,
            "label": label,
            "title": title,
            "char_start": m.start(),
        })

    if not matches:
        return []

    # Deduplicate by article number: prefer the one with a title, then earliest
    best: dict[int, dict[str, int | str]] = {}
    for a in matches:
        num = a["num"]
        assert isinstance(num, int)
        if num not in best:
            best[num] = a
        else:
            cur = best[num]
            if a["title"] and not cur["title"]:
                best[num] = a

    deduped = sorted(best.values(), key=lambda a: a["char_start"])

    # Compute char_end: next article's start, or end of text
    for i, a in enumerate(deduped):
        if i + 1 < len(deduped):
            a["char_end"] = deduped[i + 1]["char_start"]
        else:
            a["char_end"] = len(text)

    return deduped


# ---------------------------------------------------------------------------
# Internal: Phase 2 -- section detection
# ---------------------------------------------------------------------------

def _find_all_sections(
    text: str,
    articles: list[dict[str, int | str]],
) -> list[dict[str, int | str]]:
    """Find all section headings in the text and assign article numbers."""
    article_starts = [a["char_start"] for a in articles]

    matches: list[dict[str, int | str]] = []

    for m in _SECTION_RE.finditer(text):
        number = m.group(1)
        heading = _extract_heading(m.group(2) or "")
        char_start = m.start()

        # Find which article contains this section
        article_num = _find_article_num(char_start, articles, article_starts)

        matches.append({
            "number": number,
            "heading": heading,
            "char_start": char_start,
            "article_num": article_num,
        })

    if not matches:
        return []

    # Deduplicate by section number: prefer match with heading, then one inside
    # a detected article, then earliest occurrence
    best: dict[str, dict[str, int | str]] = {}
    for s in matches:
        key = str(s["number"])
        if key not in best:
            best[key] = s
        else:
            cur = best[key]
            cur_has_heading = bool(cur["heading"])
            new_has_heading = bool(s["heading"])
            cur_in_article = int(cur["article_num"]) > 0
            new_in_article = int(s["article_num"]) > 0
            if (new_has_heading and not cur_has_heading) or (
                new_has_heading == cur_has_heading
                and new_in_article
                and not cur_in_article
            ):
                best[key] = s

    deduped = sorted(best.values(), key=lambda s: s["char_start"])

    # Compute char_end and word_count
    for i, s in enumerate(deduped):
        if i + 1 < len(deduped):
            next_s = deduped[i + 1]
            # If next section is in the same article, end at its start
            if next_s["article_num"] == s["article_num"]:
                s["char_end"] = next_s["char_start"]
            else:
                # End at the article boundary
                art = _find_article_dict(int(s["article_num"]), articles)
                s["char_end"] = art["char_end"] if art else next_s["char_start"]
        else:
            # Last section: end at article boundary or text end
            art = _find_article_dict(int(s["article_num"]), articles)
            s["char_end"] = art["char_end"] if art else len(text)

        section_text = text[int(s["char_start"]):int(s["char_end"])]
        s["word_count"] = len(section_text.split())

    return deduped


def _find_article_num(
    char_pos: int,
    articles: list[dict[str, int | str]],
    starts: list[int | str],
) -> int:
    """Find which article number contains the given char position.

    Uses bisect for O(log N) lookup.
    """
    if not articles:
        return 0
    int_starts = [int(s) for s in starts]
    idx = bisect_right(int_starts, char_pos) - 1
    if idx >= 0:
        a = articles[idx]
        if int(a["char_start"]) <= char_pos < int(a["char_end"]):
            return int(a["num"])
    return 0


def _find_article_dict(
    num: int,
    articles: list[dict[str, int | str]],
) -> dict[str, int | str] | None:
    """Find an article dict by its number."""
    for a in articles:
        if int(a["num"]) == num:
            return a
    return None


# ---------------------------------------------------------------------------
# Internal: Phase 3 -- build OutlineArticle objects
# ---------------------------------------------------------------------------

def _build_articles(
    articles: list[dict[str, int | str]],
    sections: list[dict[str, int | str]],
) -> list[OutlineArticle]:
    """Build OutlineArticle objects from raw article/section dicts."""
    # Group sections by article number
    sections_by_article: dict[int, list[OutlineSection]] = {}
    for s in sections:
        art_num = int(s["article_num"])
        sec = OutlineSection(
            number=str(s["number"]),
            heading=str(s["heading"]),
            char_start=int(s["char_start"]),
            char_end=int(s["char_end"]),
            article_num=art_num,
            word_count=int(s["word_count"]),
        )
        if art_num not in sections_by_article:
            sections_by_article[art_num] = []
        sections_by_article[art_num].append(sec)

    result: list[OutlineArticle] = []
    for a in articles:
        num = int(a["num"])
        art_sections = tuple(sections_by_article.get(num, ()))
        result.append(OutlineArticle(
            num=num,
            label=str(a["label"]),
            title=str(a["title"]),
            char_start=int(a["char_start"]),
            char_end=int(a["char_end"]),
            sections=art_sections,
        ))

    # If there are sections not assigned to any article, create a synthetic
    # article 0 to hold them
    orphan_sections = sections_by_article.get(0, [])
    if orphan_sections and not articles:
        result.append(OutlineArticle(
            num=0,
            label="",
            title="",
            char_start=orphan_sections[0].char_start,
            char_end=orphan_sections[-1].char_end,
            sections=tuple(orphan_sections),
        ))

    return result
