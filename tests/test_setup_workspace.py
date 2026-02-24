"""Tests for setup_workspace ontology ID validation behavior."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_setup_module() -> object:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "setup_workspace.py"
    spec = importlib.util.spec_from_file_location("setup_workspace", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_collect_ontology_ids_and_validate_node_ids() -> None:
    mod = _load_setup_module()
    ontology = {
        "domains": [
            {
                "id": "debt_capacity",
                "children": [
                    {
                        "id": "debt_capacity.indebtedness",
                        "children": [
                            {"id": "debt_capacity.indebtedness.general_basket"},
                            {"id": "debt_capacity.indebtedness.ratio_debt"},
                        ],
                    }
                ],
            }
        ]
    }
    valid_ids = mod.collect_ontology_ids(ontology)
    assert "debt_capacity.indebtedness" in valid_ids
    assert "debt_capacity.indebtedness.general_basket" in valid_ids

    good_subtree = {
        "id": "debt_capacity.indebtedness",
        "children": [{"id": "debt_capacity.indebtedness.general_basket"}],
    }
    bad_subtree = {
        "id": "debt_capacity.indebtedness",
        "children": [{"id": "debt_capacity.indebtedness.not_real"}],
    }

    assert mod.validate_node_ids(good_subtree, valid_ids) == []
    assert mod.validate_node_ids(bad_subtree, valid_ids) == [
        "debt_capacity.indebtedness.not_real"
    ]


def test_extract_bootstrap_strategies_filters_non_ontology_ids() -> None:
    mod = _load_setup_module()
    bootstrap = {
        "strategies": [
            {
                "concept_id": "debt_capacity.indebtedness.general_basket",
                "family": "indebtedness",
            },
            {
                "concept_id": "vp_only.indebtedness.legacy",
                "family": "indebtedness",
            },
            {
                "concept_id": "liens.permitted_liens",
                "family": "liens",
            },
        ]
    }

    all_family = mod.extract_bootstrap_strategies(bootstrap, "indebtedness")
    assert len(all_family) == 2

    filtered = mod.extract_bootstrap_strategies(
        bootstrap,
        "indebtedness",
        valid_ids={"debt_capacity.indebtedness.general_basket"},
    )
    assert len(filtered) == 1
    assert filtered[0]["concept_id"] == "debt_capacity.indebtedness.general_basket"


def test_extract_family_subtree_prefers_exact_family_id() -> None:
    mod = _load_setup_module()
    ontology = {
        "domains": [
            {
                "id": "domain_a",
                "children": [
                    {
                        "id": "domain_a.governance",
                        "type": "family",
                        "children": [{"id": "domain_a.governance.child_a"}],
                    }
                ],
            },
            {
                "id": "domain_b",
                "children": [
                    {
                        "id": "domain_b.governance",
                        "type": "family",
                        "children": [{"id": "domain_b.governance.child_b"}],
                    }
                ],
            },
        ]
    }

    subtree, count = mod.extract_family_subtree(
        ontology,
        "governance",
        family_id="domain_b.governance",
    )
    assert count == 2
    assert subtree["id"] == "domain_b.governance"
