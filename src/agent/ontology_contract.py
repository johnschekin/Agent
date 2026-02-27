"""Ontology contract adapter for Wave 3 linking.

Normalizes ontology payload shape differences so linker/runtime code can use a
stable contract:
- node tree from ``domains`` (preferred) or legacy ``nodes``
- edge endpoints from ``source_id``/``target_id`` or legacy ``source``/``target``
- release version from ``metadata.version`` (fallbacks supported)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedOntology:
    """Normalized ontology payload used by linker and conflict matrix."""

    nodes_by_id: dict[str, dict[str, Any]]
    edges: list[dict[str, Any]]
    ontology_version: str


def _flatten_node_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten nested ontology node trees into deterministic pre-order list."""
    result: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        flat = {k: v for k, v in node.items() if k != "children"}
        result.append(flat)
        children = node.get("children")
        if isinstance(children, list) and children:
            result.extend(_flatten_node_tree(children))
    return result


def extract_ontology_version(payload: dict[str, Any] | None) -> str:
    """Return ontology release version from payload metadata."""
    if not isinstance(payload, dict):
        return "unknown"
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        value = str(metadata.get("version") or "").strip()
        if value:
            return value
    for key in ("ontology_version", "version", "release_version"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return "unknown"


def normalize_ontology(payload: dict[str, Any] | None) -> NormalizedOntology:
    """Normalize ontology payload to stable node/edge/version structure."""
    if not isinstance(payload, dict):
        return NormalizedOntology(nodes_by_id={}, edges=[], ontology_version="unknown")

    raw_nodes = payload.get("domains")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        raw_nodes = []

    flattened = _flatten_node_tree(raw_nodes)
    nodes_by_id: dict[str, dict[str, Any]] = {}
    for node in flattened:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        nodes_by_id[node_id] = node

    raw_edges = payload.get("edges")
    normalized_edges: list[dict[str, Any]] = []
    if isinstance(raw_edges, list):
        for raw in raw_edges:
            if not isinstance(raw, dict):
                continue
            source = str(raw.get("source_id") or raw.get("source") or "").strip()
            target = str(raw.get("target_id") or raw.get("target") or "").strip()
            edge_type = str(raw.get("edge_type") or "").strip()
            if not source or not target or not edge_type:
                continue
            normalized_edges.append(
                {
                    **raw,
                    "source": source,
                    "target": target,
                    "source_id": source,
                    "target_id": target,
                    "edge_type": edge_type,
                }
            )

    return NormalizedOntology(
        nodes_by_id=nodes_by_id,
        edges=normalized_edges,
        ontology_version=extract_ontology_version(payload),
    )

