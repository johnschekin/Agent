#!/usr/bin/env python3
"""Migrate ontology v2.5.1 → v2.6.0 and update bootstrap_all.json.

Three structural changes:
  1. Create debt_capacity.incremental L1 family absorbing free_clear, ratio, builders
  2. Clean-delete 4 duplicate L1 families (acquisition_debt, contribution_debt,
     subordinated_debt, ied) whose concepts already exist under indebtedness
  3. Clean-delete cash_flow.carve_outs (redundant with cash_flow.inv children)

Usage:
    python3 scripts/migrate_ontology_v2_5_1_to_v2_6_0.py --dry-run
    python3 scripts/migrate_ontology_v2_5_1_to_v2_6_0.py

Outputs:
    data/ontology/r36a_production_ontology_v2.6.0.json  (new)
    data/bootstrap/bootstrap_all.json                    (modified in-place, backed up)
    Migration report JSON to stdout.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import orjson

    def load_json(path: Path) -> Any:
        return orjson.loads(path.read_bytes())

    def write_json(path: Path, obj: Any) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))

    def dump_json(obj: Any) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

except ImportError:

    def load_json(path: Path) -> Any:
        with open(path) as f:
            return json.load(f)

    def write_json(path: Path, obj: Any) -> None:
        with open(path, "w") as f:
            json.dump(obj, f, indent=2)

    def dump_json(obj: Any) -> None:
        json.dump(obj, sys.stdout, indent=2)
        print()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ONTOLOGY_SRC = Path("data/ontology/r36a_production_ontology_v2.5.1.json")
ONTOLOGY_DST = Path("data/ontology/r36a_production_ontology_v2.6.0.json")
BOOTSTRAP_PATH = Path("data/bootstrap/bootstrap_all.json")

# Families to reparent under new debt_capacity.incremental parent
REPARENT_FAMILY_IDS = [
    "debt_capacity.incremental.free_clear",
    "debt_capacity.incremental.ratio",
    "debt_capacity.incremental.builders",
]

# L1 families to delete (duplicates of indebtedness subtree)
DELETE_L1_FAMILY_IDS = [
    "debt_capacity.incremental.acquisition_debt",
    "debt_capacity.incremental.contribution_debt",
    "debt_capacity.incremental.subordinated_debt",
    "debt_capacity.incremental.ied",
]

# L1 family to delete from cash_flow
DELETE_CF_FAMILY_ID = "cash_flow.carve_outs"

NEW_PARENT_ID = "debt_capacity.incremental"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_all_ids(node: dict[str, Any]) -> list[str]:
    """Collect all node IDs in a subtree (inclusive)."""
    ids = [node["id"]]
    for child in node.get("children", []):
        ids.extend(collect_all_ids(child))
    return ids


def count_nodes(node: dict[str, Any]) -> int:
    """Count nodes in a subtree (inclusive)."""
    return len(collect_all_ids(node))


def bump_levels(node: dict[str, Any], delta: int) -> None:
    """Recursively increase level by delta."""
    node["level"] = node["level"] + delta
    for child in node.get("children", []):
        bump_levels(child, delta)


def set_family_id(node: dict[str, Any], family_id: str) -> None:
    """Recursively set family_id on all descendants."""
    node["family_id"] = family_id
    for child in node.get("children", []):
        set_family_id(child, family_id)


def find_domain(domains: list[dict[str, Any]], domain_id: str) -> dict[str, Any]:
    """Find a domain by ID."""
    for d in domains:
        if d["id"] == domain_id:
            return d
    raise ValueError(f"Domain {domain_id!r} not found")


def remove_child_by_id(
    parent: dict[str, Any], child_id: str
) -> dict[str, Any] | None:
    """Remove a child from parent.children by ID, returning it."""
    children = parent.get("children", [])
    for i, c in enumerate(children):
        if c["id"] == child_id:
            return children.pop(i)
    return None


def purge_concept_ids_in_red_flags(
    node: dict[str, Any], deleted_ids: set[str]
) -> int:
    """Recursively clean concept_ids in red_flags. Returns count of refs removed."""
    removed = 0
    for rf in node.get("red_flags", []):
        cids = rf.get("concept_ids", [])
        original_len = len(cids)
        rf["concept_ids"] = [c for c in cids if c not in deleted_ids]
        removed += original_len - len(rf["concept_ids"])
    for child in node.get("children", []):
        removed += purge_concept_ids_in_red_flags(child, deleted_ids)
    return removed


def count_all_nodes(domains: list[dict[str, Any]]) -> int:
    """Count total nodes across all domains (domains themselves are nodes)."""
    total = 0
    for d in domains:
        total += count_nodes(d)
    return total


def collect_all_node_ids(domains: list[dict[str, Any]]) -> set[str]:
    """Collect every node ID in the ontology."""
    ids: set[str] = set()
    for d in domains:
        ids.update(collect_all_ids(d))
    return ids


def collect_family_nodes(domains: list[dict[str, Any]]) -> dict[str, str]:
    """Map family_id -> node_id for all type='family' nodes."""
    families: dict[str, str] = {}

    def _walk(node: dict[str, Any]) -> None:
        if node.get("type") == "family":
            families[node.get("family_id", node["id"])] = node["id"]
        for child in node.get("children", []):
            _walk(child)

    for d in domains:
        # domains themselves may have type="domain" but children may be families
        for child in d.get("children", []):
            _walk(child)
    return families


def verify_level_consistency(
    node: dict[str, Any], expected_level: int, errors: list[str]
) -> None:
    """Check that node.level == expected and recurse."""
    if node.get("level") != expected_level:
        errors.append(
            f"Level mismatch: {node['id']} has level={node.get('level')} "
            f"expected {expected_level}"
        )
    for child in node.get("children", []):
        verify_level_consistency(child, expected_level + 1, errors)


# ---------------------------------------------------------------------------
# Migration steps
# ---------------------------------------------------------------------------

def apply_change_1(
    ont: dict[str, Any], report: dict[str, Any]
) -> None:
    """Create debt_capacity.incremental parent, reparenting free_clear/ratio/builders."""
    dc = find_domain(ont["domains"], "debt_capacity")
    children = dc["children"]

    # Find the position of the first reparented family
    insert_idx: int | None = None
    reparented_nodes: list[dict[str, Any]] = []

    for fid in REPARENT_FAMILY_IDS:
        for i, c in enumerate(children):
            if c["id"] == fid:
                if insert_idx is None:
                    insert_idx = i
                reparented_nodes.append(c)
                break

    assert insert_idx is not None, "Could not find free_clear in debt_capacity.children"
    assert len(reparented_nodes) == 3, f"Expected 3 families to reparent, got {len(reparented_nodes)}"

    # Remove the 3 families from dc.children
    for node in reparented_nodes:
        children.remove(node)

    # Count descendant nodes before level bump
    descendant_count = sum(count_nodes(n) for n in reparented_nodes)
    report["change_1"] = {
        "description": "Create debt_capacity.incremental parent",
        "reparented_families": [n["id"] for n in reparented_nodes],
        "descendant_nodes_affected": descendant_count,
    }

    # Bump levels (+1) and change type from "family" to "concept" on the 3 root nodes
    for node in reparented_nodes:
        node["type"] = "concept"
        bump_levels(node, 1)
        # family_id stays the same (they are already debt_capacity.incremental.*)

    # Create the new parent node
    new_parent: dict[str, Any] = {
        "id": NEW_PARENT_ID,
        "name": "Incremental Debt",
        "type": "family",
        "level": 1,
        "domain_id": "debt_capacity",
        "family_id": NEW_PARENT_ID,
        "corpus_prevalence": "high",
        "extraction_difficulty": "medium",
        "definition": (
            "Umbrella family for incremental debt capacity concepts including "
            "free-and-clear capacity, ratio-based capacity, and builder mechanisms "
            "that allow borrowers to grow their accordion beyond closing-date levels."
        ),
        "children": reparented_nodes,
    }

    # Insert at original position
    children.insert(insert_idx, new_parent)

    report["change_1"]["new_parent_id"] = NEW_PARENT_ID
    report["change_1"]["new_l1_count_in_dc"] = len(children)


def apply_change_2(
    ont: dict[str, Any], report: dict[str, Any]
) -> set[str]:
    """Clean-delete 4 duplicate L1 families. Returns set of deleted node IDs."""
    dc = find_domain(ont["domains"], "debt_capacity")
    deleted_ids: set[str] = set()
    per_family: dict[str, int] = {}

    for fid in DELETE_L1_FAMILY_IDS:
        node = remove_child_by_id(dc, fid)
        if node is None:
            print(f"WARNING: L1 family {fid!r} not found in debt_capacity.children", file=sys.stderr)
            continue
        ids = collect_all_ids(node)
        deleted_ids.update(ids)
        per_family[fid] = len(ids)

    report["change_2"] = {
        "description": "Clean-delete 4 duplicate L1 families",
        "families_deleted": per_family,
        "total_nodes_deleted": len(deleted_ids),
    }
    return deleted_ids


def apply_change_3(
    ont: dict[str, Any], report: dict[str, Any]
) -> set[str]:
    """Clean-delete cash_flow.carve_outs. Returns set of deleted node IDs."""
    cf = find_domain(ont["domains"], "cash_flow")
    node = remove_child_by_id(cf, DELETE_CF_FAMILY_ID)
    deleted_ids: set[str] = set()
    if node is None:
        print(f"WARNING: {DELETE_CF_FAMILY_ID!r} not found in cash_flow.children", file=sys.stderr)
        report["change_3"] = {"description": "cash_flow.carve_outs not found", "nodes_deleted": 0}
        return deleted_ids

    ids = collect_all_ids(node)
    deleted_ids.update(ids)
    report["change_3"] = {
        "description": "Clean-delete cash_flow.carve_outs",
        "nodes_deleted": len(ids),
        "deleted_ids": sorted(ids),
    }
    return deleted_ids


def purge_edges(
    ont: dict[str, Any], deleted_ids: set[str], report: dict[str, Any]
) -> None:
    """Remove edges referencing any deleted node."""
    original = len(ont["edges"])
    ont["edges"] = [
        e
        for e in ont["edges"]
        if e["source_id"] not in deleted_ids and e["target_id"] not in deleted_ids
    ]
    removed = original - len(ont["edges"])
    report["edges_purged"] = removed
    report["edges_remaining"] = len(ont["edges"])


def purge_red_flag_concept_ids(
    ont: dict[str, Any], deleted_ids: set[str], report: dict[str, Any]
) -> None:
    """Clean concept_ids in red_flags across the entire tree."""
    total_removed = 0
    for domain in ont["domains"]:
        total_removed += purge_concept_ids_in_red_flags(domain, deleted_ids)
    report["red_flag_concept_ids_removed"] = total_removed


def update_bootstrap(
    bootstrap: dict[str, Any],
    deleted_ids: set[str],
    report: dict[str, Any],
) -> None:
    """Update bootstrap: change family_id for reparented, remove entries for deleted families."""
    updated_keys: list[str] = []
    removed_keys: list[str] = []

    # Entries whose family_id matches a reparented family need family_id → debt_capacity.incremental
    reparent_fids = set(REPARENT_FAMILY_IDS)

    keys_to_remove: list[str] = []
    for key, entry in bootstrap.items():
        fid = entry.get("family_id", "")

        # If the entry's concept_id is in the deleted set, remove it
        if entry.get("id", key) in deleted_ids:
            keys_to_remove.append(key)
            continue

        # If the entry's family_id matches a deleted L1 family, remove it
        if fid in {f for f in DELETE_L1_FAMILY_IDS}:
            keys_to_remove.append(key)
            continue

        # If the family_id is one of the reparented families, update to new parent
        if fid in reparent_fids:
            entry["family_id"] = NEW_PARENT_ID
            updated_keys.append(key)

    for key in keys_to_remove:
        del bootstrap[key]
        removed_keys.append(key)

    report["bootstrap"] = {
        "entries_updated_family_id": sorted(updated_keys),
        "entries_removed": sorted(removed_keys),
        "remaining_count": len(bootstrap),
    }


def update_metadata(
    ont: dict[str, Any], report: dict[str, Any]
) -> None:
    """Bump version, recompute statistics."""
    meta = ont["metadata"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Version
    old_version = meta.get("version", "2.5.1")
    meta["version"] = "2.6.0"
    meta["version_date"] = now

    # Recount
    node_count = count_all_nodes(ont["domains"])
    edge_count = len(ont["edges"])
    meta["node_count"] = node_count
    meta["edge_count"] = edge_count

    # Update description
    meta["description"] = meta["description"].replace(
        "3538 nodes", f"{node_count} nodes"
    ).replace(
        "1118 relationship edges", f"{edge_count} relationship edges"
    )

    # Recompute edge_statistics.by_type
    stats = ont["statistics"]
    stats["node_count"] = node_count
    stats["edge_count"] = edge_count
    stats["generated_at"] = now

    by_type: dict[str, int] = Counter()
    for e in ont["edges"]:
        etype = e.get("edge_type", "UNKNOWN")
        by_type[etype] += 1
    stats["edge_statistics"]["by_type"] = dict(sorted(by_type.items()))
    stats["edge_statistics"]["total"] = edge_count

    # Append to growth_history
    history = stats.get("growth_history", [])
    if history:
        prev = history[-1]
        prev_nodes = prev.get("nodes", 3538)
        prev_edges = prev.get("edges", 1118)
    else:
        prev_nodes = 3538
        prev_edges = 1118

    history.append({
        "round": "v2.6.0-migration",
        "nodes": node_count,
        "edges": edge_count,
        "node_delta": node_count - prev_nodes,
        "edge_delta": edge_count - prev_edges,
        "node_growth_pct": round((node_count - prev_nodes) / prev_nodes * 100, 2),
    })

    # Add patch record
    meta["v260_migration"] = {
        "applied_at": now,
        "from_version": old_version,
        "changes": [
            "Change 1: Created debt_capacity.incremental parent (reparented free_clear, ratio, builders)",
            "Change 2: Deleted 4 duplicate L1 families (acquisition_debt, contribution_debt, subordinated_debt, ied)",
            "Change 3: Deleted cash_flow.carve_outs (redundant with cash_flow.inv)",
        ],
    }

    report["metadata"] = {
        "version": f"{old_version} -> 2.6.0",
        "node_count": node_count,
        "edge_count": edge_count,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(
    ont: dict[str, Any], deleted_ids: set[str], report: dict[str, Any]
) -> bool:
    """Run all validation checks. Returns True if no blocking errors."""
    errors: list[str] = []
    warnings: list[str] = []
    all_ids = collect_all_node_ids(ont["domains"])

    # 1. No deleted IDs remain
    remaining_deleted = deleted_ids & all_ids
    if remaining_deleted:
        errors.append(f"{len(remaining_deleted)} deleted IDs still present: {sorted(remaining_deleted)[:5]}")

    # 2. No dangling edges
    for e in ont["edges"]:
        if e["source_id"] not in all_ids:
            errors.append(f"Dangling edge source: {e['source_id']}")
        if e["target_id"] not in all_ids:
            errors.append(f"Dangling edge target: {e['target_id']}")

    # 3. Level consistency
    for domain in ont["domains"]:
        verify_level_consistency(domain, 0, errors)

    # 4. No dangling concept_ids in red_flags (warning-level)
    def _check_rf(node: dict[str, Any]) -> None:
        for rf in node.get("red_flags", []):
            for cid in rf.get("concept_ids", []):
                if cid not in all_ids:
                    warnings.append(f"Dangling concept_id in red_flag {rf.get('id','?')}: {cid}")
        for child in node.get("children", []):
            _check_rf(child)

    for domain in ont["domains"]:
        _check_rf(domain)

    # 5. Statistics match
    meta = ont["metadata"]
    actual_nodes = count_all_nodes(ont["domains"])
    actual_edges = len(ont["edges"])
    if meta["node_count"] != actual_nodes:
        errors.append(f"metadata.node_count={meta['node_count']} != actual {actual_nodes}")
    if meta["edge_count"] != actual_edges:
        errors.append(f"metadata.edge_count={meta['edge_count']} != actual {actual_edges}")

    # 6. New parent exists and has correct structure
    dc = find_domain(ont["domains"], "debt_capacity")
    inc_found = False
    for c in dc["children"]:
        if c["id"] == NEW_PARENT_ID:
            inc_found = True
            if c.get("type") != "family":
                errors.append(f"{NEW_PARENT_ID} should be type=family, got {c.get('type')}")
            if c.get("level") != 1:
                errors.append(f"{NEW_PARENT_ID} should be level=1, got {c.get('level')}")
            child_ids = [ch["id"] for ch in c.get("children", [])]
            for fid in REPARENT_FAMILY_IDS:
                if fid not in child_ids:
                    errors.append(f"{fid} not found in {NEW_PARENT_ID}.children")
    if not inc_found:
        errors.append(f"{NEW_PARENT_ID} not found in debt_capacity.children")

    # 7. No orphan family_ids (every node's family_id refs a family node)
    family_nodes = collect_family_nodes(ont["domains"])
    # Also include the domain-level families
    for d in ont["domains"]:
        family_nodes[d["id"]] = d["id"]

    def _check_family_id(node: dict[str, Any]) -> None:
        fid = node.get("family_id")
        if fid and fid not in family_nodes and fid not in all_ids:
            warnings.append(f"Orphan family_id: {node['id']} has family_id={fid}")
        for child in node.get("children", []):
            _check_family_id(child)

    for domain in ont["domains"]:
        for child in domain.get("children", []):
            _check_family_id(child)

    report["validation"] = {
        "errors": errors,
        "warnings": warnings[:20],  # Cap to avoid giant output
        "warning_count": len(warnings),
        "passed": len(errors) == 0,
    }

    if errors:
        for e in errors:
            print(f"VALIDATION ERROR: {e}", file=sys.stderr)
    if warnings:
        print(f"Validation: {len(warnings)} warnings (non-blocking)", file=sys.stderr)

    return len(errors) == 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate ontology v2.5.1 → v2.6.0"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing files",
    )
    parser.add_argument(
        "--ontology",
        type=Path,
        default=ONTOLOGY_SRC,
        help=f"Source ontology path (default: {ONTOLOGY_SRC})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ONTOLOGY_DST,
        help=f"Output ontology path (default: {ONTOLOGY_DST})",
    )
    parser.add_argument(
        "--bootstrap",
        type=Path,
        default=BOOTSTRAP_PATH,
        help=f"Bootstrap file path (default: {BOOTSTRAP_PATH})",
    )
    args = parser.parse_args()

    # Load
    print(f"Loading ontology from {args.ontology}", file=sys.stderr)
    ont = load_json(args.ontology)
    assert isinstance(ont, dict), "Ontology must be a JSON object"

    print(f"Loading bootstrap from {args.bootstrap}", file=sys.stderr)
    bootstrap = load_json(args.bootstrap)
    assert isinstance(bootstrap, dict), "Bootstrap must be a JSON object"

    # Deep copy to avoid mutating source
    ont = copy.deepcopy(ont)
    bootstrap = copy.deepcopy(bootstrap)

    # Pre-migration counts
    pre_nodes = count_all_nodes(ont["domains"])
    pre_edges = len(ont["edges"])

    report: dict[str, Any] = {
        "migration": "v2.5.1 -> v2.6.0",
        "dry_run": args.dry_run,
        "pre_migration": {"nodes": pre_nodes, "edges": pre_edges},
    }

    # Apply changes
    print("Applying Change 1: Create debt_capacity.incremental parent...", file=sys.stderr)
    apply_change_1(ont, report)

    print("Applying Change 2: Delete 4 duplicate L1 families...", file=sys.stderr)
    deleted_ids = apply_change_2(ont, report)

    print("Applying Change 3: Delete cash_flow.carve_outs...", file=sys.stderr)
    deleted_ids |= apply_change_3(ont, report)

    # Shared cleanup
    print(f"Purging edges referencing {len(deleted_ids)} deleted nodes...", file=sys.stderr)
    purge_edges(ont, deleted_ids, report)

    print("Purging concept_ids in red_flags...", file=sys.stderr)
    purge_red_flag_concept_ids(ont, deleted_ids, report)

    # Update bootstrap
    print("Updating bootstrap...", file=sys.stderr)
    update_bootstrap(bootstrap, deleted_ids, report)

    # Update metadata
    print("Updating metadata and statistics...", file=sys.stderr)
    update_metadata(ont, report)

    # Post-migration counts
    post_nodes = count_all_nodes(ont["domains"])
    post_edges = len(ont["edges"])
    report["post_migration"] = {"nodes": post_nodes, "edges": post_edges}
    report["delta"] = {
        "nodes": post_nodes - pre_nodes,
        "edges": post_edges - pre_edges,
    }

    # Validate
    print("Running validation...", file=sys.stderr)
    valid = validate(ont, deleted_ids, report)

    if not valid:
        print("VALIDATION FAILED — aborting", file=sys.stderr)
        dump_json(report)
        sys.exit(1)

    print("Validation passed.", file=sys.stderr)

    # Write
    if args.dry_run:
        print("DRY RUN — no files written", file=sys.stderr)
    else:
        # Backup bootstrap
        backup = args.bootstrap.with_suffix(".json.bak")
        shutil.copy2(args.bootstrap, backup)
        print(f"Backed up bootstrap to {backup}", file=sys.stderr)

        # Write ontology
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, ont)
        print(f"Wrote ontology to {args.output}", file=sys.stderr)

        # Write bootstrap
        write_json(args.bootstrap, bootstrap)
        print(f"Updated bootstrap at {args.bootstrap}", file=sys.stderr)

    # Output report
    dump_json(report)


if __name__ == "__main__":
    main()
