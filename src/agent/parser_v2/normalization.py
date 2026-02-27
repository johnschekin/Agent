"""Deterministic normalization for parser_v2."""

from __future__ import annotations

from agent.parser_v2.types import NormalizedText


_ZERO_WIDTH_CHARS = frozenset({"\u200b", "\u200c", "\u200d", "\ufeff"})


def normalize_for_parser_v2(text: str) -> NormalizedText:
    """Normalize text and emit reversible offset maps.

    Current deterministic transforms:
    1. Collapse CRLF and CR to LF.
    2. Convert non-breaking space to plain space.
    3. Remove zero-width characters.
    """

    raw = text or ""
    norm_chars: list[str] = []
    raw_to_norm = [0] * (len(raw) + 1)
    norm_to_raw: list[int] = [0]

    flags = {
        "crlf_normalized": False,
        "cr_normalized": False,
        "nbsp_normalized": False,
        "zero_width_removed": False,
    }

    norm_idx = 0
    i = 0
    while i < len(raw):
        ch = raw[i]
        next_i = i + 1
        emitted = ""

        if ch == "\r" and i + 1 < len(raw) and raw[i + 1] == "\n":
            emitted = "\n"
            next_i = i + 2
            flags["crlf_normalized"] = True
        elif ch == "\r":
            emitted = "\n"
            flags["cr_normalized"] = True
        elif ch == "\u00a0":
            emitted = " "
            flags["nbsp_normalized"] = True
        elif ch in _ZERO_WIDTH_CHARS:
            emitted = ""
            flags["zero_width_removed"] = True
        else:
            emitted = ch

        for raw_pos in range(i, next_i):
            raw_to_norm[raw_pos] = norm_idx

        if emitted:
            norm_chars.append(emitted)
            norm_idx += 1
            norm_to_raw.append(next_i)

        i = next_i

    raw_to_norm[len(raw)] = norm_idx
    normalized = "".join(norm_chars)

    return NormalizedText(
        raw_text=raw,
        normalized_text=normalized,
        raw_to_normalized=tuple(raw_to_norm),
        normalized_to_raw=tuple(norm_to_raw),
        normalization_flags=flags,
    )
