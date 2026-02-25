"""Integration tests for scripts/exploratory_discoverer.py.

Uses a mock CorpusIndex to avoid needing a real DuckDB.
Tests the pipeline logic, not the database queries.
"""
from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_bootstrap(tmp_path: Path) -> Path:
    """Create a minimal bootstrap_all.json."""
    bootstrap = {
        "debt_capacity.indebtedness.general_basket": {
            "id": "debt_capacity.indebtedness.general_basket",
            "name": "General Debt Basket",
            "family_id": "debt_capacity.indebtedness",
            "search_strategy": {
                "heading_patterns": ["Indebtedness", "Limitation on Indebtedness"],
                "keyword_anchors": ["incur", "Permitted Indebtedness"],
            },
        },
        "debt_capacity.liens.general": {
            "id": "debt_capacity.liens.general",
            "name": "General Lien Basket",
            "family_id": "debt_capacity.liens",
            "search_strategy": {
                "heading_patterns": ["Liens", "Limitation on Liens"],
                "keyword_anchors": ["lien", "encumbrance"],
            },
        },
    }
    path = tmp_path / "bootstrap_all.json"
    path.write_text(json.dumps(bootstrap))
    return path


def _make_family_notes(tmp_path: Path) -> Path:
    """Create minimal family notes."""
    notes = {
        "debt_capacity.indebtedness": {
            "status": "active",
            "location_guidance": "Negative covenants article",
            "primary_location": "Negative covenants article",
            "co_examine": ["indebtedness section"],
            "notes": "Always a section",
        },
        "debt_capacity.liens": {
            "status": "active",
            "location_guidance": "Negative covenants article",
            "notes": "Adjacent to indebtedness",
        },
    }
    path = tmp_path / "family_notes.json"
    path.write_text(json.dumps(notes))
    return path


# ---------------------------------------------------------------------------
# Tests for helper functions
# ---------------------------------------------------------------------------

class TestBootstrapLoading:
    def test_load_heading_patterns(self, tmp_path: Path) -> None:
        from scripts.exploratory_discoverer import load_bootstrap_heading_patterns

        bootstrap_path = _make_bootstrap(tmp_path)
        patterns = load_bootstrap_heading_patterns(bootstrap_path)

        assert "debt_capacity.indebtedness" in patterns
        assert "debt_capacity.liens" in patterns
        assert "Indebtedness" in patterns["debt_capacity.indebtedness"]

    def test_load_family_notes(self, tmp_path: Path) -> None:
        from scripts.exploratory_discoverer import load_family_notes

        notes_path = _make_family_notes(tmp_path)
        notes = load_family_notes(notes_path)

        assert "debt_capacity.indebtedness" in notes
        assert "debt_capacity.liens" in notes


class TestFamilyMatching:
    def test_match_families_to_sections(self) -> None:
        from scripts.exploratory_discoverer import match_families_to_sections

        family_headings = {
            "debt_capacity.indebtedness": ["Indebtedness", "Limitation on Indebtedness"],
            "debt_capacity.liens": ["Liens"],
        }
        all_sections = {
            "doc1": [
                {"heading": "Indebtedness", "section_number": "7.01", "article_num": 7},
                {"heading": "Liens", "section_number": "7.02", "article_num": 7},
                {"heading": "Events of Default", "section_number": "8.01", "article_num": 8},
            ],
        }

        result = match_families_to_sections(family_headings, all_sections)

        assert "debt_capacity.indebtedness" in result
        assert "debt_capacity.liens" in result
        assert len(result["debt_capacity.indebtedness"]) == 1
        assert result["debt_capacity.indebtedness"][0] == ("doc1", "7.01", 7)


class TestOrderedSections:
    def test_build_ordered_sections(self) -> None:
        from scripts.exploratory_discoverer import build_ordered_sections

        all_sections = {
            "doc1": [
                {"section_number": "7.01", "heading": "Indebtedness", "article_num": 7},
                {"section_number": "7.02", "heading": "Liens", "article_num": 7},
            ],
        }

        without, with_h = build_ordered_sections(all_sections)

        assert len(without["doc1"]) == 2
        assert without["doc1"][0] == ("doc1", "7.01", 7, 0)
        assert with_h["doc1"][1] == ("doc1", "7.02", "Liens", 7, 1)


class TestReportStructure:
    def test_build_report_minimal(self) -> None:
        from agent.discovery import CooccurrenceMatrix
        from scripts.exploratory_discoverer import build_report

        cooc = CooccurrenceMatrix(
            families=("a", "b"),
            doc_matrix=((10, 5), (5, 8)),
            article_matrix=((10, 3), (3, 8)),
            adjacency_matrix=((0, 2), (2, 0)),
        )

        report = build_report(
            params={"sample": None, "seed": 42},
            corpus_stats={"docs_analyzed": 100, "families_matched": 2, "sections_matched": 50},
            cooccurrence=cooc,
            correlations=[],
            adjacency_patterns={},
            anomalies_by_family={},
            clusters_by_family={},
            template_conditioned={},
        )

        assert report["status"] == "ok"
        assert report["corpus_stats"]["docs_analyzed"] == 100
        assert report["cooccurrence"]["families"] == ["a", "b"]
        assert report["cooccurrence"]["doc_level"] == [[10, 5], [5, 8]]
