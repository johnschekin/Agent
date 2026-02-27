"""Tests for ontology contract normalization helpers."""
from __future__ import annotations

from agent.ontology_contract import extract_ontology_version, normalize_ontology


def test_extract_ontology_version_prefers_metadata() -> None:
    payload = {"metadata": {"version": "2.5.1"}, "version": "legacy-v1"}
    assert extract_ontology_version(payload) == "2.5.1"


def test_normalize_ontology_flattens_domains_and_edges() -> None:
    payload = {
        "metadata": {"version": "2.5.1"},
        "domains": [
            {
                "id": "debt_capacity",
                "type": "domain",
                "children": [
                    {
                        "id": "debt_capacity.indebtedness",
                        "type": "family",
                        "domain_id": "debt_capacity",
                        "children": [
                            {
                                "id": "debt_capacity.indebtedness.other_debt",
                                "type": "concept",
                            }
                        ],
                    }
                ],
            }
        ],
        "edges": [
            {
                "source_id": "debt_capacity.indebtedness",
                "target_id": "debt_capacity.indebtedness.other_debt",
                "edge_type": "includes",
            }
        ],
    }
    normalized = normalize_ontology(payload)
    assert normalized.ontology_version == "2.5.1"
    assert set(normalized.nodes_by_id.keys()) == {
        "debt_capacity",
        "debt_capacity.indebtedness",
        "debt_capacity.indebtedness.other_debt",
    }
    assert len(normalized.edges) == 1
    assert normalized.edges[0]["source"] == "debt_capacity.indebtedness"
    assert normalized.edges[0]["target"] == "debt_capacity.indebtedness.other_debt"


def test_normalize_ontology_supports_legacy_nodes_and_edges() -> None:
    payload = {
        "ontology_version": "legacy-v2",
        "nodes": [
            {"id": "fam.a", "type": "family"},
            {"id": "fam.a.child", "type": "concept"},
        ],
        "edges": [
            {"source": "fam.a", "target": "fam.a.child", "edge_type": "contains"},
        ],
    }
    normalized = normalize_ontology(payload)
    assert normalized.ontology_version == "legacy-v2"
    assert set(normalized.nodes_by_id.keys()) == {"fam.a", "fam.a.child"}
    assert normalized.edges[0]["source_id"] == "fam.a"
    assert normalized.edges[0]["target_id"] == "fam.a.child"

