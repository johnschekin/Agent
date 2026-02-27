"""Ontology-aware conflict policy matrix for family link deconfliction.

Pre-computed from ontology edges. Each pair of families has a conflict policy
that determines how the system handles sections linked to both families:

Policies (in priority order):

* **exclusive** (5) — must not share sections (e.g., EXCLUDES_FROM, PREVENTS)
* **warn** (4) — show warning, allow with explicit confirmation
* **compound_covenant** (3) — both families linked, each must have independent evidence
* **shared_ok** (2) — sharing is expected (e.g., COMPLEMENTS, CROSS_REFERENCES)
* **expected_overlap** (1) — expected to overlap (e.g., MIRRORS)
* **independent** (0) — no relationship (default)

Symmetric storage: ``(family_a, family_b)`` always has ``family_a < family_b``
lexicographically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Edge-to-policy mapping
# ---------------------------------------------------------------------------

EDGE_TO_POLICY: dict[str, str] = {
    "EXCLUDES_FROM": "exclusive",
    "PREVENTS": "exclusive",
    "BLOCKED_BY": "exclusive",
    "CONSTRAINS": "warn",
    "RECLASSIFIES_TO": "warn",
    "TRIGGERS": "warn",
    "MODIFIES": "warn",
    "CONDITIONAL_ON": "warn",
    "SHARED_CAP": "shared_ok",
    "STACKS_WITH": "shared_ok",
    "COMPLEMENTS": "shared_ok",
    "CROSS_REFERENCES": "shared_ok",
    "EXTENDS": "shared_ok",
    "MIRRORS": "expected_overlap",
    "FEEDS_INTO": "independent",
    "DEPENDS_ON": "independent",
    "ENABLES": "independent",
    "IMPLEMENTS": "independent",
}

POLICY_PRIORITY: dict[str, int] = {
    "exclusive": 5,
    "warn": 4,
    "compound_covenant": 3,
    "shared_ok": 2,
    "expected_overlap": 1,
    "independent": 0,
}

ALL_POLICIES: frozenset[str] = frozenset(POLICY_PRIORITY.keys())


# ---------------------------------------------------------------------------
# Conflict policy entry
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ConflictPolicy:
    """A conflict policy between two families."""

    family_a: str  # lexicographically smaller
    family_b: str
    policy: str    # one of ALL_POLICIES
    reason: str    # human-readable explanation
    edge_types: tuple[str, ...]  # ontology edge types that contributed
    ontology_version: str


# ---------------------------------------------------------------------------
# Matrix builder
# ---------------------------------------------------------------------------

def _canonical_pair(a: str, b: str) -> tuple[str, str]:
    """Return the canonical (lexicographically ordered) pair."""
    return (a, b) if a < b else (b, a)


def build_conflict_matrix(
    ontology_edges: list[dict[str, Any]],
    ontology_nodes: dict[str, Any],
    *,
    ontology_version: str = "unknown",
) -> list[ConflictPolicy]:
    """Walk ontology edges, resolve to family pairs, aggregate to highest-priority policy.

    Parameters
    ----------
    ontology_edges:
        List of edge dicts, each with: ``source``, ``target``, ``edge_type``,
        and optionally ``source_family``, ``target_family``.
    ontology_nodes:
        Dict mapping concept_id to node info (used to resolve concept → family).
    ontology_version:
        Version string for provenance tracking.

    Returns
    -------
    list[ConflictPolicy]
        One entry per family pair with conflicts. Pairs with only "independent"
        relationships are excluded.
    """
    # Accumulate edges per family pair
    pair_edges: dict[tuple[str, str], list[tuple[str, str]]] = {}  # (a, b) → [(edge_type, policy)]

    for edge in ontology_edges:
        edge_type = str(edge.get("edge_type") or "").strip()
        if not edge_type:
            continue
        policy = EDGE_TO_POLICY.get(edge_type)
        if not policy:
            continue

        # Resolve families for source and target
        source_family = _resolve_family(edge, "source", ontology_nodes)
        target_family = _resolve_family(edge, "target", ontology_nodes)

        if not source_family or not target_family:
            continue
        if source_family == target_family:
            continue  # Intra-family edges don't create conflicts

        pair = _canonical_pair(source_family, target_family)
        if pair not in pair_edges:
            pair_edges[pair] = []
        pair_edges[pair].append((edge_type, policy))

    # Aggregate: highest-priority policy wins
    results: list[ConflictPolicy] = []
    for (family_a, family_b), edges in sorted(pair_edges.items()):
        # Find highest priority policy
        best_policy = "independent"
        best_priority = 0
        all_edge_types: list[str] = []

        for edge_type, policy in edges:
            all_edge_types.append(edge_type)
            prio = POLICY_PRIORITY.get(policy, 0)
            if prio > best_priority:
                best_priority = prio
                best_policy = policy

        # Skip pure "independent" pairs
        if not best_policy or best_policy == "independent":
            continue

        # Build reason string
        reason = _build_reason(best_policy, all_edge_types, family_a, family_b)

        results.append(ConflictPolicy(
            family_a=family_a,
            family_b=family_b,
            policy=best_policy,
            reason=reason,
            edge_types=tuple(sorted(set(all_edge_types))),
            ontology_version=ontology_version,
        ))

    return sorted(results, key=lambda p: (p.family_a, p.family_b))


def _resolve_family(
    edge: dict[str, Any],
    role: str,  # "source" | "target"
    nodes: dict[str, Any],
) -> str:
    """Resolve the family_id for a concept in an edge.

    Tries edge['source_family'] / edge['target_family'] first (pre-resolved),
    then falls back to looking up the concept in the nodes dict.
    """
    # Pre-resolved family
    family_key = f"{role}_family"
    if family_key in edge and edge[family_key]:
        return str(edge[family_key])

    # Look up concept → family
    concept_id = _get_concept_id(edge, role)
    if not concept_id:
        return ""
    if concept_id in nodes:
        node = nodes[concept_id]
        if isinstance(node, dict):
            return str(
                node.get(
                    "family_id",
                    node.get("family", node.get("domain_id", concept_id)),
                )
            )
    return concept_id


def _get_concept_id(edge: dict[str, Any], role: str) -> str:
    """Return concept identifier for ``role`` from any supported edge shape."""
    for key in (f"{role}_id", role):
        value = str(edge.get(key) or "").strip()
        if value:
            return value
    return ""


def _build_reason(
    policy: str,
    edge_types: list[str],
    family_a: str,
    family_b: str,
) -> str:
    """Build a human-readable reason string for a conflict policy."""
    unique_edges = sorted(set(edge_types))
    edge_list = ", ".join(unique_edges)

    if policy == "exclusive":  # noqa: SIM116
        return f"{family_a} and {family_b} are mutually exclusive ({edge_list})"
    elif policy == "warn":
        return f"{family_a} and {family_b} may conflict ({edge_list}), manual review recommended"
    elif policy == "compound_covenant":
        return f"{family_a} and {family_b} may share compound covenant sections ({edge_list})"
    elif policy == "shared_ok":
        return f"{family_a} and {family_b} can share sections ({edge_list})"
    elif policy == "expected_overlap":
        return f"{family_a} and {family_b} are expected to overlap ({edge_list})"
    return f"{family_a} and {family_b} are related ({edge_list})"


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def matrix_to_dict(
    policies: list[ConflictPolicy],
) -> dict[tuple[str, str], ConflictPolicy]:
    """Convert a policy list to a lookup dict keyed by (family_a, family_b)."""
    return {(p.family_a, p.family_b): p for p in policies}


def lookup_policy(
    matrix: dict[tuple[str, str], ConflictPolicy],
    family_a: str,
    family_b: str,
) -> str:
    """Look up the conflict policy between two families.

    Returns the policy string, or ``"independent"`` if no entry exists.
    """
    pair = _canonical_pair(family_a, family_b)
    entry = matrix.get(pair)
    return entry.policy if entry else "independent"


def get_conflicting_families(
    matrix: dict[tuple[str, str], ConflictPolicy],
    family_id: str,
    *,
    min_policy: str = "warn",
) -> list[ConflictPolicy]:
    """Get all families that conflict with ``family_id`` at or above ``min_policy``.

    Parameters
    ----------
    matrix:
        The conflict matrix dict.
    family_id:
        The family to check against.
    min_policy:
        Minimum policy level to include (default "warn").

    Returns
    -------
    list[ConflictPolicy]
        Conflicting families sorted by priority (highest first).
    """
    min_prio = POLICY_PRIORITY.get(min_policy, 0)
    results: list[ConflictPolicy] = []
    for (a, b), policy in matrix.items():
        if a == family_id or b == family_id:
            prio = POLICY_PRIORITY.get(policy.policy, 0)
            if prio >= min_prio:
                results.append(policy)
    return sorted(results, key=lambda p: POLICY_PRIORITY.get(p.policy, 0), reverse=True)


def check_section_conflicts(
    matrix: dict[tuple[str, str], ConflictPolicy],
    linked_families: list[str],
) -> list[ConflictPolicy]:
    """Check for conflicts among families linked to the same section.

    Parameters
    ----------
    matrix:
        The conflict matrix dict.
    linked_families:
        List of family_ids all linked to one section.

    Returns
    -------
    list[ConflictPolicy]
        All conflict policies that fire, sorted by priority (highest first).
    """
    conflicts: list[ConflictPolicy] = []
    seen: set[tuple[str, str]] = set()

    for i, fa in enumerate(linked_families):
        for fb in linked_families[i + 1:]:
            pair = _canonical_pair(fa, fb)
            if pair in seen:
                continue
            seen.add(pair)
            entry = matrix.get(pair)
            if entry and entry.policy != "independent":
                conflicts.append(entry)

    return sorted(conflicts, key=lambda p: POLICY_PRIORITY.get(p.policy, 0), reverse=True)


# ---------------------------------------------------------------------------
# Serialization helpers (for storage in DuckDB)
# ---------------------------------------------------------------------------

def policy_to_row(p: ConflictPolicy) -> dict[str, Any]:
    """Convert a ConflictPolicy to a dict suitable for DuckDB insertion."""
    try:
        import orjson
        edge_json = orjson.dumps(list(p.edge_types)).decode("utf-8")
    except ImportError:
        import json
        edge_json = json.dumps(list(p.edge_types))
    return {
        "family_a": p.family_a,
        "family_b": p.family_b,
        "policy": p.policy,
        "reason": p.reason,
        "edge_types": edge_json,
        "ontology_version": p.ontology_version,
    }


def row_to_policy(row: dict[str, Any]) -> ConflictPolicy:
    """Convert a DuckDB row dict to a ConflictPolicy."""
    try:
        import orjson
        edge_types = orjson.loads(row["edge_types"])
    except ImportError:
        import json
        edge_types = json.loads(row["edge_types"])
    return ConflictPolicy(
        family_a=row["family_a"],
        family_b=row["family_b"],
        policy=row["policy"],
        reason=row["reason"],
        edge_types=tuple(edge_types),
        ontology_version=row.get("ontology_version", "unknown"),
    )
