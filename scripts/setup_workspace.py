#!/usr/bin/env python3
"""Initialize an agent workspace from expert materials.

Usage:
    python3 scripts/setup_workspace.py --family indebtedness \\
      --ontology data/ontology/r36a_production_ontology_v2.5.1.json \\
      --bootstrap data/bootstrap/bootstrap_all.json \\
      --output workspaces/indebtedness

Outputs structured JSON to stdout, human messages to stderr.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def load_json(path: Path) -> object:
        return orjson.loads(path.read_bytes())

    def write_json(path: Path, obj: object) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def load_json(path: Path) -> object:
        with open(path) as f:
            return json.load(f)

    def write_json(path: Path, obj: object) -> None:
        with open(path, "w") as f:
            json.dump(obj, f, indent=2, default=str)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def collect_ontology_ids(tree: object) -> set[str]:
    """Collect all ontology node IDs from an arbitrarily nested tree."""
    out: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            node_id = node.get("id")
            if isinstance(node_id, str) and node_id.strip():
                out.add(node_id)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(tree)
    return out


def validate_node_ids(tree: object, valid_ids: set[str]) -> list[str]:
    """Return sorted list of IDs present in tree that do not exist in valid_ids."""
    found = collect_ontology_ids(tree)
    return sorted(node_id for node_id in found if node_id not in valid_ids)


def _strategy_concept_id(entry: dict[str, Any]) -> str | None:
    """Extract a concept ID from a strategy-like object."""
    for key in ("concept_id", "id"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def extract_family_subtree(
    ontology: object,
    family_name: str,
    *,
    family_id: str | None = None,
) -> tuple[object, int]:
    """Extract the family subtree from the ontology.

    The ontology has structure: {domains: [{id, name, children: [{id, name, children: [...]}]}]}
    Family matching: search node IDs for the family name component
    (e.g., "indebtedness" matches nodes with ID containing ".indebtedness" or "indebtedness.").

    Returns (subtree, node_count).
    """
    family_lower = family_name.lower()
    family_id_norm = (family_id or "").strip()

    def node_matches(node: object) -> bool:
        """Check if a node matches the family name."""
        if not isinstance(node, dict):
            return False
        node_id_raw = node.get("id", "")
        node_id = node_id_raw if isinstance(node_id_raw, str) else ""
        if family_id_norm:
            return node_id == family_id_norm
        # Check ID field — the primary match for this ontology format
        if isinstance(node_id, str):
            # Match as a path component: debt_capacity.indebtedness, indebtedness.general_basket
            parts = node_id.lower().split(".")
            if family_lower in parts:
                return True
        # Also check name field
        node_name = node.get("name", "")
        return isinstance(node_name, str) and family_lower == node_name.lower()

    def count_nodes(node: object) -> int:
        """Count total nodes in a subtree."""
        if isinstance(node, dict):
            total = 1
            for key in ("children", "concepts", "subconcepts", "nodes", "items", "members"):
                children = node.get(key)
                if isinstance(children, list):
                    for child in children:
                        total += count_nodes(child)
            return total
        elif isinstance(node, list):
            return sum(count_nodes(item) for item in node)
        return 0

    def search_tree(node: object) -> object | None:
        """Recursively search for the family node."""
        if isinstance(node, dict):
            if node_matches(node):
                return node

            # Search in child containers
            for key in ("children", "concepts", "subconcepts", "nodes", "items",
                         "members", "families", "dimensions", "categories", "domains"):
                children = node.get(key)
                if isinstance(children, list):
                    for child in children:
                        result = search_tree(child)
                        if result is not None:
                            return result

            # Search all dict values that are dicts
            for val in node.values():
                if isinstance(val, dict):
                    result = search_tree(val)
                    if result is not None:
                        return result

        elif isinstance(node, list):
            for item in node:
                result = search_tree(item)
                if result is not None:
                    return result

        return None

    subtree = search_tree(ontology)
    if subtree is None:
        return {}, 0

    node_count = count_nodes(subtree)
    return subtree, node_count


def extract_bootstrap_strategies(
    bootstrap: object,
    family_name: str,
    *,
    valid_ids: set[str] | None = None,
) -> list[dict]:
    """Extract bootstrap strategies matching the family name."""
    family_lower = family_name.lower()
    results: list[dict] = []

    def matches_family(entry: dict) -> bool:
        for key in ("family", "concept_family", "concept_id", "id", "name"):
            val = entry.get(key)
            if isinstance(val, str) and family_lower in val.lower():
                return True
        return False

    def append_if_valid(entry: dict[str, Any]) -> None:
        concept_id = _strategy_concept_id(entry)
        if valid_ids is not None and concept_id is not None and concept_id not in valid_ids:
            return
        results.append(entry)

    if isinstance(bootstrap, list):
        for entry in bootstrap:
            if isinstance(entry, dict) and matches_family(entry):
                append_if_valid(entry)
    elif isinstance(bootstrap, dict):
        # Check if it's keyed by family name
        for key, val in bootstrap.items():
            if family_lower in key.lower():
                if isinstance(val, list):
                    for v in val:
                        if isinstance(v, dict):
                            append_if_valid(v)
                elif isinstance(val, dict):
                    append_if_valid(val)

        # Also check if there's a top-level list
        for list_key in ("strategies", "concepts", "entries", "items"):
            entries = bootstrap.get(list_key)
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and matches_family(entry):
                        append_if_valid(entry)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize an agent workspace from expert materials."
    )
    parser.add_argument(
        "--family", required=True, help='Family name (e.g., "indebtedness")'
    )
    parser.add_argument(
        "--family-id",
        default=None,
        help=(
            "Optional exact ontology family id "
            "(e.g., debt_capacity.indebtedness)."
        ),
    )
    parser.add_argument(
        "--ontology", required=True, help="Path to production ontology JSON"
    )
    parser.add_argument(
        "--bootstrap", default=None, help="Path to bootstrap strategies JSON"
    )
    parser.add_argument(
        "--expert-materials",
        default=None,
        help="Directory with expert materials to copy",
    )
    parser.add_argument(
        "--output", required=True, help="Workspace output directory"
    )
    args = parser.parse_args()

    ontology_path = Path(args.ontology)
    if not ontology_path.exists():
        log(f"Error: ontology file not found at {ontology_path}")
        sys.exit(1)

    output = Path(args.output)

    # Create workspace directory structure
    subdirs = ["context", "strategies", "evidence", "results"]
    for subdir in subdirs:
        (output / subdir).mkdir(parents=True, exist_ok=True)
    log(f"Created workspace directory structure at {output}")

    # Extract family subtree from ontology
    log(f"Loading ontology from {ontology_path}")
    ontology = load_json(ontology_path)
    ontology_ids = collect_ontology_ids(ontology)
    if not ontology_ids:
        log("Error: ontology has no node IDs; expected id-bearing production ontology.")
        sys.exit(1)

    subtree, node_count = extract_family_subtree(
        ontology,
        args.family,
        family_id=args.family_id,
    )
    if node_count == 0:
        log(f"Error: family '{args.family}' was not found in ontology.")
        sys.exit(1)
    invalid_subtree_ids = validate_node_ids(subtree, ontology_ids)
    if invalid_subtree_ids:
        preview = ", ".join(invalid_subtree_ids[:5])
        log(
            "Error: extracted subtree contains IDs not present in ontology: "
            + preview
        )
        sys.exit(1)

    subtree_path = output / "context" / "ontology_subtree.json"
    write_json(subtree_path, subtree)
    log(f"Extracted ontology subtree: {node_count} node(s)")

    # Extract bootstrap strategies
    bootstrap_count = 0
    bootstrap_rejected_invalid_ids = 0
    if args.bootstrap:
        bootstrap_path = Path(args.bootstrap)
        if not bootstrap_path.exists():
            log(f"Warning: bootstrap file not found at {bootstrap_path}")
        else:
            log(f"Loading bootstrap strategies from {bootstrap_path}")
            bootstrap = load_json(bootstrap_path)
            strategies = extract_bootstrap_strategies(
                bootstrap,
                args.family,
                valid_ids=ontology_ids,
            )

            # Count rejected family strategies that failed ontology ID validation.
            all_family_strategies = extract_bootstrap_strategies(bootstrap, args.family)
            bootstrap_rejected_invalid_ids = len(all_family_strategies) - len(strategies)
            bootstrap_count = len(strategies)

            # Write bootstrap strategy to context
            bootstrap_context_path = output / "context" / "bootstrap_strategy.json"
            write_json(bootstrap_context_path, strategies)
            log(f"Extracted {bootstrap_count} bootstrap strategy/strategies")
            if bootstrap_rejected_invalid_ids > 0:
                log(
                    "Dropped "
                    f"{bootstrap_rejected_invalid_ids} bootstrap entries "
                    "with non-ontology concept IDs"
                )

            # Write individual strategy files to strategies/
            for i, strat in enumerate(strategies):
                concept_id = strat.get("concept_id", strat.get("id", f"{args.family}_{i}"))
                strat_path = output / "strategies" / f"{concept_id}_v001.json"
                write_json(strat_path, strat)

    # Copy expert materials if provided
    if args.expert_materials:
        expert_dir = Path(args.expert_materials)
        if not expert_dir.exists():
            log(f"Warning: expert materials directory not found at {expert_dir}")
        elif not expert_dir.is_dir():
            log(f"Warning: expert materials path is not a directory: {expert_dir}")
        else:
            dest = output / "context" / "expert_materials"
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(expert_dir, dest)
            file_count = sum(1 for _ in dest.rglob("*") if _.is_file())
            log(f"Copied {file_count} expert material file(s)")

    summary = {
        "family": args.family,
        "workspace": str(output),
        "ontology_nodes": node_count,
        "bootstrap_concepts": bootstrap_count,
        "bootstrap_rejected_invalid_ids": bootstrap_rejected_invalid_ids,
        "directories_created": subdirs,
    }
    dump_json(summary)


if __name__ == "__main__":
    main()
