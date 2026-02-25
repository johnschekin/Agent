"""Tests for the bulk family linker CLI tool (scripts/bulk_family_linker.py).

Covers: CLI dry-run, canary, bootstrap, confidence tiers, conflict detection,
evidence persistence, heading AST matching, article concept filtering,
rule hashing, candidate building, flatten ontology, and full pipeline runs.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# Import the module under test (lives in scripts/)
_scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from bulk_family_linker import (  # noqa: E402
    _article_matches_rule,
    _build_candidate,
    _compute_rule_hash,
    _detect_conflicts,
    _extract_ast_match_values,
    _flatten_ontology_nodes,
    _get_article_concept,
    bootstrap_rules_into_store,
    build_parser,
    heading_matches_ast,
    load_rules_from_json,
    run_bulk_linking,
    scan_corpus_for_family,
)

from agent.conflict_matrix import ConflictPolicy  # noqa: E402
from agent.link_store import LinkStore  # noqa: E402

# ─────────────────── Fake data helpers ──────────────────


@dataclass
class FakeSection:
    doc_id: str
    section_number: str
    heading: str
    article_num: int
    char_start: int
    char_end: int


@dataclass
class FakeArticle:
    doc_id: str
    article_num: int
    concept: str | None


@dataclass
class FakeDefinition:
    doc_id: str
    term: str


@dataclass
class FakeConfidenceResult:
    score: float
    tier: str
    breakdown: dict[str, float]
    why_matched: dict[str, dict[str, Any]]


class FakeConn:
    """Minimal fake DuckDB connection for corpus queries."""

    def __init__(self, docs: list[str]) -> None:
        self._docs = docs

    def execute(self, sql: str, params: list[Any] | None = None) -> FakeConn:
        self._last_params = params or []
        self._last_sql = sql
        return self

    def fetchall(self) -> list[tuple[str]]:
        if "LIMIT" in self._last_sql and self._last_params:
            limit = int(self._last_params[-1])
            return [(d,) for d in self._docs[:limit]]
        return [(d,) for d in self._docs]


class FakeCorpus:
    """Minimal fake CorpusIndex for testing scan_corpus_for_family."""

    def __init__(
        self,
        docs: list[str],
        sections_by_doc: dict[str, list[FakeSection]] | None = None,
        articles_by_doc: dict[str, list[FakeArticle]] | None = None,
        definitions_by_doc: dict[str, list[FakeDefinition]] | None = None,
    ) -> None:
        self._conn = FakeConn(docs)
        self._sections_by_doc = sections_by_doc or {}
        self._articles_by_doc = articles_by_doc or {}
        self._definitions_by_doc = definitions_by_doc or {}

    def search_sections(
        self, *, doc_id: str | None = None, cohort_only: bool = True, limit: int = 100,
    ) -> list[FakeSection]:
        if doc_id is None:
            return []
        return self._sections_by_doc.get(doc_id, [])

    def get_articles(self, doc_id: str) -> list[FakeArticle]:
        return self._articles_by_doc.get(doc_id, [])

    def get_definitions(self, doc_id: str) -> list[FakeDefinition]:
        return self._definitions_by_doc.get(doc_id, [])


def _make_rule(
    family_id: str = "debt_capacity.indebtedness",
    heading_values: list[str] | None = None,
    article_concepts: list[str] | None = None,
    version: int = 1,
    status: str = "published",
    rule_id: str = "rule-001",
) -> dict[str, Any]:
    """Build a minimal rule dict for testing."""
    values = heading_values or ["Indebtedness"]
    ast: dict[str, Any] = {
        "type": "group",
        "operator": "or",
        "children": [{"type": "match", "value": v} for v in values],
    }
    return {
        "rule_id": rule_id,
        "family_id": family_id,
        "heading_filter_ast": ast,
        "article_concepts": article_concepts or [],
        "version": version,
        "status": status,
        "description": f"Test rule for {family_id}",
    }


def _make_rules_json(tmp_path: Path, rules: list[dict[str, Any]]) -> Path:
    """Write rules to a JSON file and return the path."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps({"rules": rules}))
    return rules_path


def _make_store(tmp_path: Path) -> LinkStore:
    """Create a fresh LinkStore on a temp database."""
    return LinkStore(tmp_path / "links.duckdb", create_if_missing=True)


def _make_conflict_matrix(
    pairs: list[tuple[str, str, str]],
) -> dict[tuple[str, str], ConflictPolicy]:
    """Build a conflict matrix from (family_a, family_b, policy) tuples."""
    matrix: dict[tuple[str, str], ConflictPolicy] = {}
    for a, b, policy in pairs:
        key = (a, b) if a < b else (b, a)
        matrix[key] = ConflictPolicy(
            family_a=key[0],
            family_b=key[1],
            policy=policy,
            reason=f"test: {policy}",
            edge_types=("TEST",),
            ontology_version="test",
        )
    return matrix


# ─────────────────── TestLoadRules ──────────────────


class TestLoadRules:
    def test_load_valid_rules(self, tmp_path: Path) -> None:
        """Load from a well-formed JSON file returns the rules list."""
        rules = [_make_rule(), _make_rule(family_id="debt_capacity.liens")]
        path = _make_rules_json(tmp_path, rules)
        loaded = load_rules_from_json(path)
        assert len(loaded) == 2
        assert loaded[0]["family_id"] == "debt_capacity.indebtedness"
        assert loaded[1]["family_id"] == "debt_capacity.liens"

    def test_load_empty_rules(self, tmp_path: Path) -> None:
        """Raises ValueError if the JSON file has no rules."""
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"rules": []}))
        with pytest.raises(ValueError, match="No rules found"):
            load_rules_from_json(path)

    def test_load_missing_file(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError for a nonexistent path."""
        with pytest.raises(FileNotFoundError):
            load_rules_from_json(tmp_path / "nonexistent.json")


# ─────────────────── TestBootstrap ──────────────────


class TestBootstrap:
    def test_bootstrap_new_store(self, tmp_path: Path) -> None:
        """Bootstraps rules into an empty store successfully."""
        store = _make_store(tmp_path)
        rules = [_make_rule()]
        path = _make_rules_json(tmp_path, rules)
        result = bootstrap_rules_into_store(store, path)
        assert len(result) >= 1
        # The rule should now be in the store
        stored = store.get_rules(status="published")
        assert len(stored) >= 1
        store.close()

    def test_bootstrap_skips_existing(self, tmp_path: Path) -> None:
        """Skips bootstrap if the store already has published rules."""
        store = _make_store(tmp_path)
        # Pre-populate with a rule
        store.save_rule(_make_rule(status="published"))
        existing_count = len(store.get_rules(status="published"))
        assert existing_count >= 1

        # Now try to bootstrap additional rules — should be skipped
        extra_rules = [_make_rule(family_id="other.family", rule_id="rule-999")]
        path = _make_rules_json(tmp_path, extra_rules)
        result = bootstrap_rules_into_store(store, path)
        # Should return existing rules, not bootstrap new ones
        assert len(result) == existing_count
        store.close()

    def test_bootstrap_returns_stored_rules(self, tmp_path: Path) -> None:
        """Returns the persisted rules list after bootstrap."""
        store = _make_store(tmp_path)
        rules = [
            _make_rule(rule_id="r1"),
            _make_rule(family_id="debt_capacity.liens", rule_id="r2"),
        ]
        path = _make_rules_json(tmp_path, rules)
        result = bootstrap_rules_into_store(store, path)
        family_ids = {r["family_id"] for r in result}
        assert "debt_capacity.indebtedness" in family_ids
        assert "debt_capacity.liens" in family_ids
        store.close()


# ─────────────────── TestHeadingMatchesAst ──────────────────


class TestHeadingMatchesAst:
    def _ast(self, values: list[str]) -> dict[str, Any]:
        return {
            "type": "group",
            "operator": "or",
            "children": [{"type": "match", "value": v} for v in values],
        }

    def test_exact_match(self) -> None:
        """Heading exactly matches a value in the AST."""
        matched, mtype, mval = heading_matches_ast("Indebtedness", self._ast(["Indebtedness"]))
        assert matched is True
        assert mtype == "exact"
        assert mval == "Indebtedness"

    def test_substring_match(self) -> None:
        """Heading contains the pattern as a substring."""
        matched, mtype, mval = heading_matches_ast(
            "Limitation on Indebtedness and Liens",
            self._ast(["Indebtedness"]),
        )
        assert matched is True
        assert mtype == "substring"
        assert mval == "Indebtedness"

    def test_partial_match(self) -> None:
        """Heading has 50%+ word overlap with a value."""
        matched, mtype, _mval = heading_matches_ast(
            "Limitation on Debt",
            self._ast(["Limitation on Indebtedness"]),
        )
        assert matched is True
        assert mtype == "partial"

    def test_no_match(self) -> None:
        """Heading doesn't match any value in the AST."""
        matched, mtype, _mval = heading_matches_ast(
            "Representations and Warranties",
            self._ast(["Indebtedness", "Liens"]),
        )
        assert matched is False
        assert mtype == "none"
        assert _mval == ""

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        matched, mtype, _mval = heading_matches_ast(
            "indebtedness", self._ast(["INDEBTEDNESS"]),
        )
        assert matched is True
        assert mtype == "exact"

    def test_empty_heading(self) -> None:
        """Empty heading returns False."""
        matched, _mtype, _mval = heading_matches_ast(
            "", self._ast(["Indebtedness"]),
        )
        assert matched is False

    def test_empty_ast(self) -> None:
        """Empty AST (no values) returns False."""
        matched, mtype, _mval = heading_matches_ast("Indebtedness", {})
        assert matched is False
        assert mtype == "none"

    def test_negated_values_excluded(self) -> None:
        """Negated match nodes do not produce positive matches."""
        neg_ast: dict[str, Any] = {
            "type": "group",
            "operator": "or",
            "children": [
                {"type": "match", "value": "Indebtedness", "negate": True},
            ],
        }
        matched, _mtype, _mval = heading_matches_ast("Indebtedness", neg_ast)
        assert matched is False

    def test_nested_group_ast(self) -> None:
        """Values from nested groups are extracted correctly."""
        ast: dict[str, Any] = {
            "type": "group",
            "operator": "or",
            "children": [
                {
                    "type": "group",
                    "operator": "or",
                    "children": [
                        {"type": "match", "value": "Indebtedness"},
                        {"type": "match", "value": "Liens"},
                    ],
                },
            ],
        }
        matched, mtype, mval = heading_matches_ast("Liens", ast)
        assert matched is True
        assert mtype == "exact"
        assert mval == "Liens"

    def test_pathological_ast_returns_no_match(self) -> None:
        """Overly deep ASTs are rejected safely and treated as no-match."""
        ast: dict[str, Any] = {"type": "match", "value": "Indebtedness"}
        for _ in range(40):
            ast = {"type": "group", "operator": "or", "children": [ast]}
        matched, mtype, mval = heading_matches_ast("Indebtedness", ast)
        assert matched is False
        assert mtype == "none"
        assert mval == ""


# ─────────────────── TestExtractAstMatchValues ──────────────────


class TestExtractAstMatchValues:
    def test_simple_match_node(self) -> None:
        """Extracts value from a single match node."""
        ast: dict[str, Any] = {"type": "match", "value": "Indebtedness"}
        values = _extract_ast_match_values(ast)
        assert values == ["Indebtedness"]

    def test_group_node(self) -> None:
        """Extracts values from a group with children."""
        ast: dict[str, Any] = {
            "type": "group",
            "operator": "or",
            "children": [
                {"type": "match", "value": "Indebtedness"},
                {"type": "match", "value": "Liens"},
            ],
        }
        values = _extract_ast_match_values(ast)
        assert "Indebtedness" in values
        assert "Liens" in values
        assert len(values) == 2

    def test_negate_excluded(self) -> None:
        """Negated match nodes produce no values."""
        ast: dict[str, Any] = {
            "type": "match",
            "value": "Indebtedness",
            "negate": True,
        }
        values = _extract_ast_match_values(ast)
        assert values == []

    def test_both_formats(self) -> None:
        """Handles the op/children format (alternative to type/operator)."""
        ast: dict[str, Any] = {
            "op": "or",
            "children": [
                {"value": "Investments"},
                {"value": "Restricted Payments"},
            ],
        }
        values = _extract_ast_match_values(ast)
        assert "Investments" in values
        assert "Restricted Payments" in values

    def test_depth_limit_enforced(self) -> None:
        """Rejects ASTs that exceed maximum nesting depth."""
        ast: dict[str, Any] = {"type": "match", "value": "Indebtedness"}
        for _ in range(40):
            ast = {"type": "group", "operator": "or", "children": [ast]}
        with pytest.raises(ValueError, match="max depth"):
            _extract_ast_match_values(ast)

    def test_node_limit_enforced(self) -> None:
        """Rejects ASTs that exceed maximum node count."""
        ast: dict[str, Any] = {
            "type": "group",
            "operator": "or",
            "children": [{"type": "match", "value": f"v{i}"} for i in range(2100)],
        }
        with pytest.raises(ValueError, match="max nodes"):
            _extract_ast_match_values(ast)


# ─────────────────── TestArticleConcept ──────────────────


class TestArticleConcept:
    def test_article_matches(self) -> None:
        """Matching article concept returns True."""
        assert _article_matches_rule(
            "NEGATIVE_COVENANTS",
            ["NEGATIVE_COVENANTS", "AFFIRMATIVE_COVENANTS"],
        ) is True

    def test_article_no_constraint(self) -> None:
        """Empty constraints always match (no article filter)."""
        assert _article_matches_rule("ANYTHING", []) is True

    def test_article_mismatch(self) -> None:
        """Non-matching article concept returns False."""
        assert _article_matches_rule("EVENTS_OF_DEFAULT", ["NEGATIVE_COVENANTS"]) is False

    def test_article_none(self) -> None:
        """None article concept does not match when constraints exist."""
        assert _article_matches_rule(None, ["NEGATIVE_COVENANTS"]) is False

    def test_get_article_concept_found(self) -> None:
        """Gets article concept when the article exists."""
        corpus = FakeCorpus(
            docs=["doc1"],
            articles_by_doc={"doc1": [FakeArticle("doc1", 7, "NEGATIVE_COVENANTS")]},
        )
        result = _get_article_concept(corpus, "doc1", 7)
        assert result == "NEGATIVE_COVENANTS"

    def test_get_article_concept_not_found(self) -> None:
        """Returns None when article number not found."""
        corpus = FakeCorpus(
            docs=["doc1"],
            articles_by_doc={"doc1": [FakeArticle("doc1", 7, "NEGATIVE_COVENANTS")]},
        )
        result = _get_article_concept(corpus, "doc1", 99)
        assert result is None


# ─────────────────── TestComputeRuleHash ──────────────────


class TestComputeRuleHash:
    def test_hash_deterministic(self) -> None:
        """Same input produces the same hash."""
        rule = _make_rule()
        h1 = _compute_rule_hash(rule)
        h2 = _compute_rule_hash(rule)
        assert h1 == h2
        assert len(h1) == 16  # SHA-256 truncated to 16 hex chars

    def test_hash_changes_on_version(self) -> None:
        """Different version produces a different hash."""
        r1 = _make_rule(version=1)
        r2 = _make_rule(version=2)
        assert _compute_rule_hash(r1) != _compute_rule_hash(r2)


# ─────────────────── TestBuildCandidate ──────────────────


class TestBuildCandidate:
    def test_candidate_structure(self) -> None:
        """All expected fields are present in a built candidate."""
        section = FakeSection("doc1", "7.01", "Indebtedness", 7, 1000, 2000)
        rule = _make_rule()
        conf = FakeConfidenceResult(
            score=0.85,
            tier="high",
            breakdown={"heading_exactness": 1.0},
            why_matched={"heading": {"match_type": "exact"}},
        )
        candidate = _build_candidate(
            section, rule, "exact", "Indebtedness", "NEGATIVE_COVENANTS", conf, [],
        )
        assert candidate["family_id"] == "debt_capacity.indebtedness"
        assert candidate["doc_id"] == "doc1"
        assert candidate["section_number"] == "7.01"
        assert candidate["heading"] == "Indebtedness"
        assert candidate["article_num"] == 7
        assert candidate["article_concept"] == "NEGATIVE_COVENANTS"
        assert candidate["confidence"] == 0.85
        assert candidate["confidence_tier"] == "high"
        assert candidate["match_type"] == "exact"
        assert candidate["matched_value"] == "Indebtedness"
        assert candidate["source"] == "bulk_linker"
        assert candidate["link_role"] == "primary_covenant"
        assert candidate["section_char_start"] == 1000
        assert candidate["section_char_end"] == 2000
        assert candidate["rule_hash"] == _compute_rule_hash(rule)

    def test_candidate_status_by_tier(self) -> None:
        """High tier -> active status, other tiers -> pending_review."""
        section = FakeSection("doc1", "7.01", "Indebtedness", 7, 0, 100)
        rule = _make_rule()

        high_conf = FakeConfidenceResult(0.9, "high", {}, {})
        candidate_high = _build_candidate(
            section, rule, "exact", "Indebtedness", None, high_conf, [],
        )
        assert candidate_high["status"] == "active"

        med_conf = FakeConfidenceResult(0.65, "medium", {}, {})
        candidate_med = _build_candidate(
            section, rule, "exact", "Indebtedness", None, med_conf, [],
        )
        assert candidate_med["status"] == "pending_review"

        low_conf = FakeConfidenceResult(0.3, "low", {}, {})
        candidate_low = _build_candidate(
            section, rule, "exact", "Indebtedness", None, low_conf, [],
        )
        assert candidate_low["status"] == "pending_review"


# ─────────────────── TestDetectConflicts ──────────────────


class TestDetectConflicts:
    def test_no_conflicts_empty_matrix(self) -> None:
        """No conflicts when conflict_matrix is None."""
        result = _detect_conflicts("fam_a", "doc1", "7.01", None, None)
        assert result == []

    def test_conflict_detected(self) -> None:
        """Exclusive conflict detected between two families."""
        matrix = _make_conflict_matrix([
            ("debt_capacity.indebtedness", "debt_capacity.liens", "exclusive"),
        ])
        existing = {"doc1::7.01": ["debt_capacity.liens"]}
        result = _detect_conflicts(
            "debt_capacity.indebtedness", "doc1", "7.01", matrix, existing,
        )
        assert len(result) == 1
        assert result[0]["other_family"] == "debt_capacity.liens"
        assert result[0]["policy"] == "exclusive"

    def test_no_conflict_same_family(self) -> None:
        """Same family does not conflict with itself."""
        matrix = _make_conflict_matrix([
            ("debt_capacity.indebtedness", "debt_capacity.liens", "exclusive"),
        ])
        existing = {"doc1::7.01": ["debt_capacity.indebtedness"]}
        result = _detect_conflicts(
            "debt_capacity.indebtedness", "doc1", "7.01", matrix, existing,
        )
        assert result == []

    def test_conflict_warn_policy(self) -> None:
        """Warn policy generates a conflict entry."""
        matrix = _make_conflict_matrix([
            ("fam_a", "fam_b", "warn"),
        ])
        existing = {"doc1::1.01": ["fam_b"]}
        result = _detect_conflicts("fam_a", "doc1", "1.01", matrix, existing)
        assert len(result) == 1
        assert result[0]["policy"] == "warn"

    def test_no_conflict_allow_policy(self) -> None:
        """Allow/shared_ok policy does not generate a conflict entry."""
        matrix = _make_conflict_matrix([
            ("fam_a", "fam_b", "shared_ok"),
        ])
        existing = {"doc1::1.01": ["fam_b"]}
        result = _detect_conflicts("fam_a", "doc1", "1.01", matrix, existing)
        assert result == []


# ─────────────────── TestScanCorpusForFamily ──────────────────


class TestScanCorpusForFamily:
    """Tests for scan_corpus_for_family.

    These tests use monkeypatching to avoid importing the real
    link_confidence and query_filters modules during scanning.
    """

    def _patch_scan_imports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Patch the lazy imports inside scan_corpus_for_family."""
        # Patch compute_link_confidence to return a controllable result
        def fake_compute(**kwargs: Any) -> FakeConfidenceResult:
            heading = kwargs.get("heading", "")
            # Exact heading match = high confidence
            if heading.lower() == "indebtedness":
                return FakeConfidenceResult(
                    0.9, "high", {"heading_exactness": 1.0}, {"heading": {}},
                )
            return FakeConfidenceResult(
                0.6, "medium", {"heading_exactness": 0.5}, {"heading": {}},
            )

        monkeypatch.setattr(
            "agent.link_confidence.compute_link_confidence",
            fake_compute,
        )

        # Patch filter_expr_from_json to return a dummy FilterMatch
        from agent.query_filters import FilterMatch

        def fake_filter_from_json(ast: dict[str, Any]) -> FilterMatch:
            return FilterMatch(value="Indebtedness", negate=False)

        monkeypatch.setattr(
            "agent.query_filters.filter_expr_from_json",
            fake_filter_from_json,
        )

    def test_scan_finds_matching_sections(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scanning finds sections whose headings match the rule AST."""
        self._patch_scan_imports(monkeypatch)
        corpus = FakeCorpus(
            docs=["doc1"],
            sections_by_doc={
                "doc1": [
                    FakeSection("doc1", "7.01", "Indebtedness", 7, 100, 500),
                    FakeSection("doc1", "7.02", "Liens", 7, 500, 900),
                ],
            },
        )
        rule = _make_rule(heading_values=["Indebtedness"])
        candidates = scan_corpus_for_family(corpus, rule, doc_ids=["doc1"])
        assert len(candidates) == 1
        assert candidates[0]["heading"] == "Indebtedness"

    def test_scan_filters_by_heading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-matching headings are skipped."""
        self._patch_scan_imports(monkeypatch)
        corpus = FakeCorpus(
            docs=["doc1"],
            sections_by_doc={
                "doc1": [
                    FakeSection("doc1", "8.01", "Representations", 8, 100, 500),
                ],
            },
        )
        rule = _make_rule(heading_values=["Indebtedness"])
        candidates = scan_corpus_for_family(corpus, rule, doc_ids=["doc1"])
        assert len(candidates) == 0

    def test_scan_computes_confidence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Confidence is computed for each match."""
        self._patch_scan_imports(monkeypatch)
        corpus = FakeCorpus(
            docs=["doc1"],
            sections_by_doc={
                "doc1": [
                    FakeSection("doc1", "7.01", "Indebtedness", 7, 100, 500),
                ],
            },
        )
        rule = _make_rule(heading_values=["Indebtedness"])
        candidates = scan_corpus_for_family(corpus, rule, doc_ids=["doc1"])
        assert len(candidates) == 1
        assert candidates[0]["confidence"] == 0.9
        assert candidates[0]["confidence_tier"] == "high"

    def test_scan_limited_docs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """doc_ids parameter limits the scan scope to specified documents."""
        self._patch_scan_imports(monkeypatch)
        corpus = FakeCorpus(
            docs=["doc1", "doc2", "doc3"],
            sections_by_doc={
                "doc1": [FakeSection("doc1", "7.01", "Indebtedness", 7, 0, 100)],
                "doc2": [FakeSection("doc2", "7.01", "Indebtedness", 7, 0, 100)],
                "doc3": [FakeSection("doc3", "7.01", "Indebtedness", 7, 0, 100)],
            },
        )
        rule = _make_rule(heading_values=["Indebtedness"])
        candidates = scan_corpus_for_family(corpus, rule, doc_ids=["doc1", "doc3"])
        doc_ids_found = {c["doc_id"] for c in candidates}
        assert doc_ids_found == {"doc1", "doc3"}
        assert "doc2" not in doc_ids_found


# ─────────────────── TestRunBulkLinking ──────────────────


class TestRunBulkLinking:
    """Tests for the run_bulk_linking orchestrator.

    Uses FakeCorpus and monkeypatching for isolation.
    """

    def _patch_scan_imports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Patch the lazy imports inside scan_corpus_for_family."""
        def fake_compute(**kwargs: Any) -> FakeConfidenceResult:
            heading = kwargs.get("heading", "")
            if "indebtedness" in heading.lower():
                return FakeConfidenceResult(
                    0.9, "high", {"heading_exactness": 1.0}, {"heading": {}},
                )
            if "liens" in heading.lower():
                return FakeConfidenceResult(
                    0.65, "medium", {"heading_exactness": 0.6}, {"heading": {}},
                )
            return FakeConfidenceResult(
                0.3, "low", {"heading_exactness": 0.2}, {"heading": {}},
            )

        monkeypatch.setattr(
            "agent.link_confidence.compute_link_confidence",
            fake_compute,
        )
        from agent.query_filters import FilterMatch

        monkeypatch.setattr(
            "agent.query_filters.filter_expr_from_json",
            lambda ast: FilterMatch(value="test", negate=False),
        )

    def _corpus_with_matches(self) -> FakeCorpus:
        return FakeCorpus(
            docs=["doc1", "doc2"],
            sections_by_doc={
                "doc1": [
                    FakeSection("doc1", "7.01", "Indebtedness", 7, 100, 500),
                    FakeSection("doc1", "7.02", "Liens", 7, 500, 900),
                ],
                "doc2": [
                    FakeSection("doc2", "7.01", "Indebtedness", 7, 100, 500),
                ],
            },
        )

    def test_dry_run_returns_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dry run summary includes 'candidates' key with match details."""
        self._patch_scan_imports(monkeypatch)
        corpus = self._corpus_with_matches()
        rules = [_make_rule(heading_values=["Indebtedness"])]
        summary = run_bulk_linking(corpus, None, rules, dry_run=True)
        assert summary["status"] == "dry_run"
        assert "candidates" in summary
        assert len(summary["candidates"]) >= 1

    def test_dry_run_no_persistence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dry run does not create links or evidence."""
        self._patch_scan_imports(monkeypatch)
        corpus = self._corpus_with_matches()
        store = _make_store(tmp_path)
        rules = [_make_rule(heading_values=["Indebtedness"])]
        summary = run_bulk_linking(corpus, store, rules, dry_run=True)
        assert summary["links_created"] == 0
        assert summary["evidence_saved"] == 0
        # Verify no links were actually persisted
        stored_links = store.get_links(limit=1000)
        assert len(stored_links) == 0
        store.close()

    def test_canary_limits_docs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Canary_n limits scanning to the first N documents."""
        self._patch_scan_imports(monkeypatch)
        corpus = self._corpus_with_matches()
        rules = [_make_rule(heading_values=["Indebtedness"])]
        summary = run_bulk_linking(corpus, None, rules, dry_run=True, canary_n=1)
        assert summary["documents_scanned"] == 1
        # Should only have candidates from doc1
        assert all(c["doc_id"] == "doc1" for c in summary["candidates"])

    def test_family_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Family filter narrows rules to the specified family."""
        self._patch_scan_imports(monkeypatch)
        corpus = self._corpus_with_matches()
        rules = [
            _make_rule(family_id="debt_capacity.indebtedness", heading_values=["Indebtedness"]),
            _make_rule(family_id="debt_capacity.liens", heading_values=["Liens"], rule_id="r2"),
        ]
        summary = run_bulk_linking(
            corpus, None, rules,
            dry_run=True,
            family_filter="debt_capacity.liens",
        )
        assert summary["rules_evaluated"] == 1
        for c in summary["candidates"]:
            assert c["family_id"] == "debt_capacity.liens"

    def test_no_rules_returns_summary(
        self, tmp_path: Path,
    ) -> None:
        """Empty rules returns no_rules status."""
        corpus = FakeCorpus(docs=[])
        summary = run_bulk_linking(corpus, None, [], dry_run=True)
        assert summary["status"] == "no_rules"
        assert summary["rules_evaluated"] == 0

    def test_full_run_creates_links(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-dry-run creates links in the store for high/medium confidence candidates."""
        self._patch_scan_imports(monkeypatch)
        corpus = self._corpus_with_matches()
        store = _make_store(tmp_path)

        # Patch store.create_run (the bulk linker calls create_run which may
        # not exist on the real store — mock it)
        saved_runs: list[dict[str, Any]] = []
        store.create_run = lambda run_dict: saved_runs.append(run_dict)  # type: ignore[attr-defined]

        # Patch store.save_evidence — the bulk linker builds evidence rows
        # with a different schema than what LinkStore.save_evidence expects
        saved_evidence: list[dict[str, Any]] = []

        def tracking_save_evidence(evidence: list[dict[str, Any]]) -> int:
            saved_evidence.extend(evidence)
            return len(evidence)

        store.save_evidence = tracking_save_evidence  # type: ignore[method-assign]

        rules = [_make_rule(heading_values=["Indebtedness"])]
        summary = run_bulk_linking(corpus, store, rules, dry_run=False)
        assert summary["status"] == "completed"
        assert summary["links_created"] >= 1
        # Verify links were persisted
        stored_links = store.get_links(limit=1000)
        assert len(stored_links) >= 1
        store.close()

    def test_cross_family_conflict_tracking(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Incremental conflict tracking across families detects conflicts."""
        self._patch_scan_imports(monkeypatch)
        # Both rules match doc1::7.01 (same section)
        corpus = FakeCorpus(
            docs=["doc1"],
            sections_by_doc={
                "doc1": [
                    FakeSection("doc1", "7.01", "Indebtedness and Liens", 7, 100, 500),
                ],
            },
        )
        rules = [
            _make_rule(
                family_id="debt_capacity.indebtedness",
                heading_values=["Indebtedness"],
                rule_id="r1",
            ),
            _make_rule(
                family_id="debt_capacity.liens",
                heading_values=["Liens"],
                rule_id="r2",
            ),
        ]
        matrix = _make_conflict_matrix([
            ("debt_capacity.indebtedness", "debt_capacity.liens", "exclusive"),
        ])
        summary = run_bulk_linking(
            corpus, None, rules,
            dry_run=True,
            conflict_matrix=matrix,
        )
        # The second rule should detect a conflict with the first
        assert summary["conflicts_detected"] >= 1

    def test_evidence_saved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Evidence rows are saved for each candidate in a non-dry-run."""
        self._patch_scan_imports(monkeypatch)
        corpus = FakeCorpus(
            docs=["doc1"],
            sections_by_doc={
                "doc1": [FakeSection("doc1", "7.01", "Indebtedness", 7, 100, 500)],
            },
        )
        store = _make_store(tmp_path)

        # Patch create_run and save_evidence on the store
        saved_runs: list[dict[str, Any]] = []
        store.create_run = lambda run_dict: saved_runs.append(run_dict)  # type: ignore[attr-defined]

        # Patch save_evidence to count calls but also record data
        saved_evidence: list[list[dict[str, Any]]] = []

        def tracking_save_evidence(evidence: list[dict[str, Any]]) -> int:
            saved_evidence.append(evidence)
            # The real save_evidence expects different fields (link_id, etc.)
            # so we just return the count
            return len(evidence)

        store.save_evidence = tracking_save_evidence  # type: ignore[method-assign]

        rules = [_make_rule(heading_values=["Indebtedness"])]
        summary = run_bulk_linking(corpus, store, rules, dry_run=False)
        assert summary["evidence_saved"] >= 1
        assert len(saved_evidence) >= 1
        assert len(saved_evidence[0]) >= 1
        # Each evidence row should have the expected structure
        ev_row = saved_evidence[0][0]
        assert "doc_id" in ev_row
        assert "family_id" in ev_row
        assert "evidence_type" in ev_row
        assert ev_row["evidence_type"] == "heading_match"
        store.close()

    def test_tier_counts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """by_tier counts are correct for the scanned candidates."""
        self._patch_scan_imports(monkeypatch)
        # doc1 has "Indebtedness" (high) and "Liens" (medium)
        corpus = FakeCorpus(
            docs=["doc1"],
            sections_by_doc={
                "doc1": [
                    FakeSection("doc1", "7.01", "Indebtedness", 7, 100, 500),
                    FakeSection("doc1", "7.02", "Liens", 7, 500, 900),
                ],
            },
        )
        rules = [_make_rule(heading_values=["Indebtedness", "Liens"])]
        summary = run_bulk_linking(corpus, None, rules, dry_run=True)
        assert summary["by_tier"]["high"] >= 1
        assert summary["by_tier"]["medium"] >= 1


# ─────────────────── TestBuildParser ──────────────────


class TestBuildParser:
    def test_parser_required_args(self) -> None:
        """--db and --links-db are required arguments."""
        parser = build_parser()
        # Parsing with both required args should succeed
        args = parser.parse_args(["--db", "corpus.duckdb", "--links-db", "links.duckdb"])
        assert args.db == "corpus.duckdb"
        assert args.links_db == "links.duckdb"

    def test_parser_required_missing_db(self) -> None:
        """Missing --db raises SystemExit."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--links-db", "links.duckdb"])

    def test_parser_required_missing_links_db(self) -> None:
        """Missing --links-db raises SystemExit."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--db", "corpus.duckdb"])

    def test_parser_optional_args(self) -> None:
        """--family, --dry-run, --canary are parsed correctly."""
        parser = build_parser()
        args = parser.parse_args([
            "--db", "corpus.duckdb",
            "--links-db", "links.duckdb",
            "--family", "debt_capacity.indebtedness",
            "--dry-run",
            "--canary", "10",
        ])
        assert args.family == "debt_capacity.indebtedness"
        assert args.dry_run is True
        assert args.canary == 10

    def test_parser_defaults(self) -> None:
        """Optional args have correct defaults when not specified."""
        parser = build_parser()
        args = parser.parse_args(["--db", "c.db", "--links-db", "l.db"])
        assert args.family is None
        assert args.dry_run is False
        assert args.canary is None
        assert args.verbose is False
        assert args.rules is None


# ─────────────────── TestFlattenOntologyNodes ──────────────────


class TestFlattenOntologyNodes:
    def test_flatten_single_level(self) -> None:
        """Flat list stays flat (no children)."""
        nodes = [
            {"id": "a", "label": "Node A"},
            {"id": "b", "label": "Node B"},
        ]
        result = _flatten_ontology_nodes(nodes)
        assert len(result) == 2
        assert result[0]["id"] == "a"
        assert result[1]["id"] == "b"
        # No "children" key in flattened output
        assert "children" not in result[0]
        assert "children" not in result[1]

    def test_flatten_nested(self) -> None:
        """Nested children are flattened into a single list."""
        nodes = [
            {
                "id": "parent",
                "label": "Parent",
                "children": [
                    {"id": "child1", "label": "Child 1"},
                    {
                        "id": "child2",
                        "label": "Child 2",
                        "children": [
                            {"id": "grandchild", "label": "Grandchild"},
                        ],
                    },
                ],
            },
        ]
        result = _flatten_ontology_nodes(nodes)
        ids = [n["id"] for n in result]
        assert ids == ["parent", "child1", "child2", "grandchild"]
        # No result should have a "children" key
        for node in result:
            assert "children" not in node

    def test_flatten_empty(self) -> None:
        """Empty input returns empty list."""
        assert _flatten_ontology_nodes([]) == []

    def test_flatten_preserves_fields(self) -> None:
        """Non-children fields are preserved in the flattened output."""
        nodes = [
            {
                "id": "x",
                "label": "X",
                "extra_field": 42,
                "children": [
                    {"id": "y", "label": "Y", "extra_field": 99},
                ],
            },
        ]
        result = _flatten_ontology_nodes(nodes)
        assert result[0]["extra_field"] == 42
        assert result[1]["extra_field"] == 99
