"""HTML text extraction and encoding-safe file reading.

Provides robust HTML-to-text conversion with optional character-level inverse
map for span provenance. The inverse map enables resolving any normalized-text
offset back to the raw HTML source.

Two extraction modes:
- ``strip_html`` — simple text extraction (no offset tracking).
- ``normalize_html`` — full normalization with character-level inverse map.

Encoding-safe file reading handles EDGAR documents with mixed encodings
(UTF-8 -> CP1252 -> replace fallback).

Ported from vantage_platform/infra/html.py + vantage_platform/infra/io.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import NavigableString


# ---------------------------------------------------------------------------
# Inverse map types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InverseMapEntry:
    """Single entry in an inverse map: normalized offset -> original offset."""

    normalized_start: int
    original_start: int
    length: int

    def __post_init__(self) -> None:
        if self.length < 0:
            raise ValueError(f"length must be non-negative, got {self.length}")


type InverseMap = tuple[InverseMapEntry, ...]


# ---------------------------------------------------------------------------
# Block-level tags that generate paragraph breaks
# ---------------------------------------------------------------------------

_BLOCK_TAGS: list[str] = [
    "p", "div", "br", "tr", "li",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "table",
]


# ---------------------------------------------------------------------------
# Image-overlay PDF detection
# ---------------------------------------------------------------------------


def _is_image_overlay_pdf(html: str) -> bool:
    """Detect image-overlay PDF format (scanned PDFs uploaded to EDGAR).

    These files have page images (<IMG>) with invisible text overlays in
    ``<FONT size="1" style="font-size:1pt;color:white">`` tags.
    """
    return bool(re.search(
        r'<FONT[^>]*(?:color:\s*white|font-size:\s*1pt)[^>]*>',
        html[:10_000],
        re.IGNORECASE,
    ))


# ---------------------------------------------------------------------------
# HTML text extraction
# ---------------------------------------------------------------------------


def strip_html(raw_html: str, *, preserve_newlines: bool = True) -> str:
    """Extract text from HTML with optional paragraph-break preservation.

    Args:
        raw_html: Raw HTML string.
        preserve_newlines: If True (default), insert newlines at block-level
            element boundaries.

    Returns:
        Cleaned text string. Empty string if *raw_html* is empty.
    """
    if not raw_html:
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")

    if preserve_newlines:
        _insert_block_newlines(soup)
        text = soup.get_text(separator=" ")
        text = _collapse_whitespace(text)
    else:
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_html(raw_html: str) -> tuple[str, InverseMap]:
    """Convert HTML to structured text with character-level inverse map.

    The inverse map allows resolving any normalized-text offset back to
    the raw HTML source — essential for UI highlighting, source-byte
    provenance, and section boundary anchoring.

    Algorithm:
        1. Parse HTML, handle image-overlay PDF format.
        2. Insert newlines before block-level elements.
        3. Get full text with space separator.
        4. Walk through text, applying whitespace collapse while recording
           which raw-text segments survive into the normalized output.
        5. Build InverseMapEntry runs from the surviving segments.
        6. Adjust for leading whitespace strip().
        7. Merge adjacent runs with contiguous offsets (RLE compression).

    Args:
        raw_html: Raw HTML string.

    Returns:
        Tuple of (normalized_text, inverse_map).
    """
    if not raw_html:
        return ("", ())

    soup = BeautifulSoup(raw_html, "html.parser")

    # Phase 0: Handle image-overlay PDFs
    if _is_image_overlay_pdf(raw_html):
        for font_tag in soup.find_all("font"):
            style = str(font_tag.get("style") or "").lower()
            size = str(font_tag.get("size") or "")
            if "color:white" in style or "font-size:1pt" in style or size == "1":
                for child in list(font_tag.children):
                    if isinstance(child, NavigableString) and "  " in str(child):
                        new_text = re.sub(r"  +", "\n", str(child))
                        child.replace_with(NavigableString(new_text))

    # Phase 1: Insert block-element newlines and extract full text.
    _insert_block_newlines(soup)
    raw_text = soup.get_text(separator=" ")

    # Phase 2: Walk raw_text, apply whitespace collapse, record segments.
    segments: list[tuple[int, int, str]] = []
    i = 0
    while i < len(raw_text):
        if raw_text[i] != "\n" and raw_text[i].isspace():
            j = i
            while j < len(raw_text) and raw_text[j] != "\n" and raw_text[j].isspace():
                j += 1
            segments.append((i, j, " "))
            i = j
        elif raw_text[i] == "\n":
            j = i
            while j < len(raw_text) and raw_text[j] == "\n":
                j += 1
            if j - i >= 3:
                segments.append((i, j, "\n\n"))
            else:
                segments.append((i, j, raw_text[i:j]))
            i = j
        else:
            j = i
            while j < len(raw_text) and not raw_text[j].isspace():
                j += 1
            segments.append((i, j, raw_text[i:j]))
            i = j

    # Phase 3: Build normalized text and InverseMapEntry runs.
    runs: list[InverseMapEntry] = []
    norm_pos = 0
    result_parts: list[str] = []

    for raw_start, raw_end, collapsed in segments:
        if not collapsed:
            continue
        seg_len = len(collapsed)

        if collapsed == raw_text[raw_start:raw_end]:
            runs.append(InverseMapEntry(
                normalized_start=norm_pos,
                original_start=raw_start,
                length=seg_len,
            ))
        else:
            runs.append(InverseMapEntry(
                normalized_start=norm_pos,
                original_start=raw_start,
                length=min(seg_len, 1),
            ))

        result_parts.append(collapsed)
        norm_pos += seg_len

    full_text = "".join(result_parts)
    normalized = full_text.strip()

    # Phase 4: Adjust for leading strip.
    strip_start = len(full_text) - len(full_text.lstrip())

    if strip_start > 0:
        adjusted: list[InverseMapEntry] = []
        for run in runs:
            new_start = run.normalized_start - strip_start
            if new_start + run.length <= 0:
                continue
            if new_start < 0:
                clip = -new_start
                adjusted.append(InverseMapEntry(
                    normalized_start=0,
                    original_start=run.original_start + clip,
                    length=run.length - clip,
                ))
            else:
                adjusted.append(InverseMapEntry(
                    normalized_start=new_start,
                    original_start=run.original_start,
                    length=run.length,
                ))
        runs = adjusted

    # Phase 5: Merge adjacent runs (RLE compression).
    merged: list[InverseMapEntry] = []
    for run in runs:
        if run.length <= 0:
            continue
        if (
            merged
            and merged[-1].normalized_start + merged[-1].length == run.normalized_start
            and merged[-1].original_start + merged[-1].length == run.original_start
        ):
            merged[-1] = InverseMapEntry(
                normalized_start=merged[-1].normalized_start,
                original_start=merged[-1].original_start,
                length=merged[-1].length + run.length,
            )
        else:
            merged.append(run)

    return (normalized, tuple(merged))


# ---------------------------------------------------------------------------
# Encoding-safe file reading
# ---------------------------------------------------------------------------


def read_file(fpath: Path, *, min_size: int = 0) -> str:
    """Read a text file with encoding fallback: UTF-8 -> CP1252 -> replace.

    CP1252 fallback handles law-firm Word docs with smart quotes (0x93/0x94).

    Args:
        fpath: Path to the file.
        min_size: Minimum file size in bytes. Returns empty string if smaller.

    Returns:
        File contents as a string. Empty string on failure or below min_size.
    """
    try:
        if min_size > 0 and fpath.stat().st_size < min_size:
            return ""
        try:
            return fpath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return fpath.read_text(encoding="cp1252")
            except UnicodeDecodeError:
                with open(fpath, errors="replace") as f:
                    return f.read()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _insert_block_newlines(soup: BeautifulSoup) -> None:
    """Insert newline characters before block-level HTML elements."""
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")


def _collapse_whitespace(text: str) -> str:
    """Collapse horizontal whitespace (preserving newlines) and limit blanks."""
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text
