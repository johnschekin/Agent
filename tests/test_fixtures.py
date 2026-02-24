"""Fixture sanity checks."""
from __future__ import annotations

from pathlib import Path


def test_fixture_html_corpus_has_five_documents() -> None:
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    html_files = sorted(
        [*fixtures_dir.glob("*.htm"), *fixtures_dir.glob("*.html")]
    )
    assert len(html_files) >= 5
