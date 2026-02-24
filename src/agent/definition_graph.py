"""Definition dependency graph helpers.

Baseline graph analytics inspired by TI round5_def_dependency:
- parse definition-to-definition references
- return graph summary + centrality-like hub scores
- provide overlap scoring utility for strategy gates
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_QUOTED_TERM_RE = re.compile(r'["\u201c]([A-Z][^"\u201d]{1,100})["\u201d]')


@dataclass(frozen=True, slots=True)
class DefinitionGraphSummary:
    node_count: int
    edge_count: int
    hubs: tuple[tuple[str, int], ...]
    sinks: tuple[str, ...]
    sources: tuple[str, ...]


def normalize_term(term: str) -> str:
    return " ".join((term or "").split()).strip()


def dependency_overlap(text: str, dependencies: tuple[str, ...] | list[str]) -> float:
    """Fraction of dependency terms referenced in text."""
    normalized = [normalize_term(dep).lower() for dep in dependencies if normalize_term(dep)]
    if not normalized:
        return 1.0
    hay = (text or "").lower()
    hits = sum(1 for dep in normalized if dep in hay)
    return hits / max(1, len(normalized))


def build_definition_dependency_graph(
    definitions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build lightweight dependency graph from definition records.

    Expected input fields:
      - term
      - definition_text
    """
    terms = [normalize_term(str(d.get("term", ""))) for d in definitions]
    known_terms = {t for t in terms if t}
    if not known_terms:
        return {
            "nodes": [],
            "edges": [],
            "summary": DefinitionGraphSummary(0, 0, (), (), ()),
        }

    edges: set[tuple[str, str]] = set()
    outgoing: dict[str, set[str]] = {t: set() for t in known_terms}
    incoming: dict[str, set[str]] = {t: set() for t in known_terms}

    for row in definitions:
        src = normalize_term(str(row.get("term", "")))
        if not src or src not in known_terms:
            continue
        definition_text = str(row.get("definition_text", "") or "")
        refs = _extract_referenced_terms(definition_text, known_terms, source_term=src)
        for dst in refs:
            edge = (src, dst)
            if edge in edges:
                continue
            edges.add(edge)
            outgoing[src].add(dst)
            incoming[dst].add(src)

    hubs = sorted(
        ((node, len(neighbors)) for node, neighbors in outgoing.items()),
        key=lambda kv: (-kv[1], kv[0]),
    )
    sinks = sorted(node for node, neighbors in outgoing.items() if not neighbors)
    sources = sorted(node for node, neighbors in incoming.items() if not neighbors)

    summary = DefinitionGraphSummary(
        node_count=len(known_terms),
        edge_count=len(edges),
        hubs=tuple(hubs[:20]),
        sinks=tuple(sinks[:50]),
        sources=tuple(sources[:50]),
    )
    return {
        "nodes": sorted(known_terms),
        "edges": sorted(({"from": src, "to": dst} for src, dst in edges), key=lambda row: (row["from"], row["to"])),
        "summary": {
            "node_count": summary.node_count,
            "edge_count": summary.edge_count,
            "hubs": [{"term": term, "out_degree": degree} for term, degree in summary.hubs],
            "sinks": list(summary.sinks),
            "sources": list(summary.sources),
        },
    }


def _extract_referenced_terms(
    definition_text: str,
    known_terms: set[str],
    *,
    source_term: str,
) -> set[str]:
    refs: set[str] = set()
    known_lower = {term.lower(): term for term in known_terms}

    for match in _QUOTED_TERM_RE.finditer(definition_text):
        candidate = normalize_term(match.group(1))
        resolved = known_lower.get(candidate.lower())
        if resolved and resolved != source_term:
            refs.add(resolved)

    # Fallback phrase scan for known terms not quoted in this definition.
    hay = definition_text.lower()
    for lower, original in known_lower.items():
        if original == source_term:
            continue
        if lower in hay:
            refs.add(original)
    return refs

