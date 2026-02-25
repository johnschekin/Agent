"""Integration tests for scripts/discovery_seeder.py.

Uses mock CorpusIndex to avoid needing a real DuckDB.
Tests the per-family discovery pipeline logic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_bootstrap(tmp_path: Path) -> Path:
    bootstrap = {
        "debt_capacity.indebtedness.general_basket": {
            "id": "debt_capacity.indebtedness.general_basket",
            "name": "General Debt Basket",
            "family_id": "debt_capacity.indebtedness",
            "search_strategy": {
                "heading_patterns": ["Indebtedness", "Limitation on Indebtedness"],
                "keyword_anchors": ["incur", "Permitted Indebtedness"],
                "concept_specific_keywords": ["aggregate principal amount"],
            },
        },
    }
    path = tmp_path / "bootstrap_all.json"
    path.write_text(json.dumps(bootstrap))
    return path


def _make_family_notes(tmp_path: Path) -> Path:
    notes = {
        "debt_capacity.indebtedness": {
            "status": "active",
            "location_guidance": "Negative covenants article",
            "primary_location": "Negative covenants article",
            "co_examine": ["indebtedness section"],
            "structural_variants": ["Bond-style", "Regular"],
            "notes": "Always a section in the negative covenants article.",
        },
    }
    path = tmp_path / "family_notes.json"
    path.write_text(json.dumps(notes))
    return path


def _mock_corpus() -> MagicMock:
    """Create a mock CorpusIndex with realistic section data."""
    corpus = MagicMock()
    corpus.doc_ids.return_value = ["doc1", "doc2", "doc3"]

    # Sections query returns rows for each doc
    def query_side_effect(sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        if "FROM sections" in sql and params:
            doc_id = params[0]
            if doc_id == "doc1":
                return [
                    ("7.01", "Indebtedness", 7, 0, 5000),
                    ("7.02", "Liens", 7, 5000, 3000),
                    ("7.03", "Investments", 7, 8000, 4000),
                ]
            elif doc_id == "doc2":
                return [
                    ("6.01", "Limitation on Indebtedness", 6, 0, 6000),
                    ("6.02", "Limitation on Liens", 6, 6000, 3500),
                ]
            elif doc_id == "doc3":
                return [
                    ("7.01", "Events of Default", 7, 0, 8000),
                    ("7.02", "Conditions Precedent", 7, 8000, 2000),
                ]
        return []

    corpus.query.side_effect = query_side_effect

    # Section text
    def get_section_text(doc_id: str, section_number: str) -> str | None:
        texts = {
            ("doc1", "7.01"): (
                "The Borrower will not, and will not permit any Restricted Subsidiary to, "
                "directly or indirectly, create, incur, assume or suffer to exist any "
                "Indebtedness, except Permitted Indebtedness. The aggregate principal "
                "amount of all Indebtedness incurred pursuant to this Section shall not "
                "exceed the greater of $500,000,000 and Consolidated EBITDA."
            ),
            ("doc1", "7.02"): (
                "The Borrower will not create or permit to exist any Lien on any property "
                "or asset now owned or hereafter acquired by it, except Permitted Liens."
            ),
            ("doc2", "6.01"): (
                "Neither the Borrower nor any Restricted Subsidiary shall incur any "
                "Indebtedness; provided, however, that the Borrower and any Restricted "
                "Subsidiary may incur Indebtedness if the Consolidated Total Leverage "
                "Ratio does not exceed 4.00 to 1.00."
            ),
        }
        return texts.get((doc_id, section_number))

    corpus.get_section_text.side_effect = get_section_text

    # Definitions
    def get_definitions(doc_id: str, **kwargs: Any) -> list[Any]:
        mock_def = MagicMock()
        mock_def.term = "Indebtedness"
        return [mock_def]

    corpus.get_definitions.side_effect = get_definitions

    return corpus


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBootstrapLoading:
    def test_load_family_concepts(self, tmp_path: Path) -> None:
        from scripts.discovery_seeder import load_family_concepts

        bootstrap_path = _make_bootstrap(tmp_path)
        families = load_family_concepts(bootstrap_path)

        assert "debt_capacity.indebtedness" in families
        assert len(families["debt_capacity.indebtedness"]) == 1

    def test_load_heading_patterns(self, tmp_path: Path) -> None:
        from scripts.discovery_seeder import (
            load_family_concepts,
            load_family_heading_patterns,
        )

        bootstrap_path = _make_bootstrap(tmp_path)
        families = load_family_concepts(bootstrap_path)
        patterns = load_family_heading_patterns(
            families["debt_capacity.indebtedness"]
        )

        assert "Indebtedness" in patterns
        assert "Limitation on Indebtedness" in patterns


class TestSectionMatching:
    def test_match_family_sections(self) -> None:
        from scripts.discovery_seeder import match_family_sections

        corpus = _mock_corpus()
        heading_patterns = ["Indebtedness", "Limitation on Indebtedness"]

        matched, non_matched = match_family_sections(
            corpus, heading_patterns, ["doc1", "doc2", "doc3"],
        )

        assert len(matched) == 2  # doc1/7.01 and doc2/6.01
        assert len(non_matched) > 0
        assert matched[0]["doc_id"] == "doc1"
        assert matched[0]["heading"] == "Indebtedness"


class TestDiscoverySteps:
    def test_discover_headings(self) -> None:
        from scripts.discovery_seeder import discover_headings

        matched = [
            {"heading": "Indebtedness", "doc_id": "d1", "section_number": "7.01"},
            {"heading": "Indebtedness", "doc_id": "d2", "section_number": "7.01"},
            {"heading": "Limitation on Indebtedness", "doc_id": "d3", "section_number": "6.01"},
        ]

        result = discover_headings(matched, [], None, "debt_capacity.indebtedness")

        assert len(result["heading_patterns"]) >= 1
        assert "indebtedness" in result["heading_patterns"]

    def test_discover_headings_with_exploratory(self) -> None:
        from scripts.discovery_seeder import discover_headings

        matched = [
            {"heading": "Indebtedness", "doc_id": "d1", "section_number": "7.01"},
        ] * 5

        exploratory = {
            "adjacency_patterns": {
                "debt_capacity.indebtedness": [
                    {"heading": "liens", "position": 1, "frequency": 100, "doc_count": 80},
                ],
            },
        }

        result = discover_headings(
            matched, [], exploratory, "debt_capacity.indebtedness",
        )

        assert "liens" in result["negative_heading_patterns"]

    def test_analyze_structural_position(self) -> None:
        from scripts.discovery_seeder import analyze_structural_position

        matched = [
            {"article_num": 7, "section_number": "7.01"},
            {"article_num": 7, "section_number": "7.01"},
            {"article_num": 7, "section_number": "7.01"},
            {"article_num": 6, "section_number": "6.01"},
        ]

        result = analyze_structural_position(matched)

        assert 7 in result["primary_articles"]
        assert "7.01" in result["primary_sections"]

    def test_extract_template_patterns_with_notes(self) -> None:
        from scripts.discovery_seeder import extract_template_patterns

        family_notes = {
            "debt_capacity.indebtedness": {
                "location_guidance": "Negative covenants article",
                "structural_variants": ["Bond-style combined", "Regular separate"],
                "co_examine": ["indebtedness section"],
            },
        }

        result = extract_template_patterns(
            None, [], None, "debt_capacity.indebtedness", family_notes,
        )

        assert any("Location:" in n for n in result["concept_notes"])
        assert any("Structural variant:" in n for n in result["concept_notes"])
        assert any("Co-examine:" in n for n in result["concept_notes"])

    def test_extract_cross_family_signals(self) -> None:
        from scripts.discovery_seeder import extract_cross_family_signals

        exploratory = {
            "cooccurrence": {
                "families": [
                    "debt_capacity.indebtedness",
                    "debt_capacity.liens",
                    "cash_flow.rp",
                ],
                "doc_level": [
                    [100, 95, 80],
                    [95, 100, 70],
                    [80, 70, 100],
                ],
            },
            "adjacency_patterns": {
                "debt_capacity.indebtedness": [
                    {"heading": "liens", "position": 1, "frequency": 90},
                ],
            },
        }

        result = extract_cross_family_signals(
            exploratory, "debt_capacity.indebtedness",
        )

        assert len(result["concept_notes"]) >= 1
        assert result["fallback_escalation"] is not None
        assert "liens" in result["fallback_escalation"]

    def test_discover_dna(self) -> None:
        from scripts.discovery_seeder import discover_dna_phrases

        corpus = _mock_corpus()
        matched = [
            {"doc_id": "doc1", "section_number": "7.01"},
            {"doc_id": "doc2", "section_number": "6.01"},
        ]
        non_matched = [
            {"doc_id": "doc1", "section_number": "7.02"},
        ]

        result = discover_dna_phrases(corpus, matched, non_matched)

        assert "dna_tier1" in result
        assert "dna_tier2" in result
        assert isinstance(result["dna_tier1"], list)


class TestMergeAndValidate:
    def test_merge_dry_run(self, tmp_path: Path) -> None:
        from scripts.discovery_seeder import merge_and_validate

        base = {
            "family": "debt_capacity.indebtedness",
            "heading_patterns": ["Indebtedness"],
            "keyword_anchors": [],
        }
        discovery = {
            "heading_patterns": ["Indebtedness", "Limitation on Indebtedness"],
            "dna_tier1": ["aggregate principal amount"],
            "dna_tier2": [],  # empty → should NOT override
        }

        result = merge_and_validate(
            base, discovery,
            dry_run=True, workspace=tmp_path,
            family_id="debt_capacity.indebtedness",
        )

        # heading_patterns should be overridden (non-empty discovery)
        assert len(result["heading_patterns"]) == 2
        # dna_tier2 should NOT override (empty list)
        assert "dna_tier2" not in result or result.get("dna_tier2") == []
        # dna_tier1 should be set
        assert result["dna_tier1"] == ["aggregate principal amount"]
        assert result["validation_status"] == "discovery_seeded"

    def test_merge_writes_file(self, tmp_path: Path) -> None:
        from scripts.discovery_seeder import merge_and_validate

        base = {"family": "test", "heading_patterns": ["Test"]}
        discovery = {"dna_tier1": ["test phrase"]}

        merge_and_validate(
            base, discovery,
            dry_run=False, workspace=tmp_path,
            family_id="test_family",
        )

        strategies_dir = tmp_path / "strategies"
        assert strategies_dir.exists()
        files = list(strategies_dir.glob("test_family_v*.json"))
        assert len(files) == 1
        content = json.loads(files[0].read_bytes())
        assert content["dna_tier1"] == ["test phrase"]
        assert content["version"] == 1
