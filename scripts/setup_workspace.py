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


def extract_family_subtree(ontology: object, family_name: str) -> tuple[object, int]:
    """Extract the family subtree from the ontology.

    The ontology has structure: {domains: [{id, name, children: [{id, name, children: [...]}]}]}
    Family matching: search node IDs for the family name component
    (e.g., "indebtedness" matches nodes with ID containing ".indebtedness" or "indebtedness.").

    Returns (subtree, node_count).
    """
    family_lower = family_name.lower()

    def node_matches(node: object) -> bool:
        """Check if a node matches the family name."""
        if not isinstance(node, dict):
            return False
        # Check ID field — the primary match for this ontology format
        node_id = node.get("id", "")
        if isinstance(node_id, str):
            # Match as a path component: debt_capacity.indebtedness, indebtedness.general_basket
            parts = node_id.lower().split(".")
            if family_lower in parts:
                return True
        # Also check name field
        node_name = node.get("name", "")
        if isinstance(node_name, str) and family_lower == node_name.lower():
            return True
        return False

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
    bootstrap: object, family_name: str
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

    if isinstance(bootstrap, list):
        for entry in bootstrap:
            if isinstance(entry, dict) and matches_family(entry):
                results.append(entry)
    elif isinstance(bootstrap, dict):
        # Check if it's keyed by family name
        for key, val in bootstrap.items():
            if family_lower in key.lower():
                if isinstance(val, list):
                    results.extend(v for v in val if isinstance(v, dict))
                elif isinstance(val, dict):
                    results.append(val)

        # Also check if there's a top-level list
        for list_key in ("strategies", "concepts", "entries", "items"):
            entries = bootstrap.get(list_key)
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and matches_family(entry):
                        results.append(entry)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize an agent workspace from expert materials."
    )
    parser.add_argument(
        "--family", required=True, help='Family name (e.g., "indebtedness")'
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

    subtree, node_count = extract_family_subtree(ontology, args.family)
    subtree_path = output / "context" / "ontology_subtree.json"
    write_json(subtree_path, subtree)
    log(f"Extracted ontology subtree: {node_count} node(s)")

    # Extract bootstrap strategies
    bootstrap_count = 0
    if args.bootstrap:
        bootstrap_path = Path(args.bootstrap)
        if not bootstrap_path.exists():
            log(f"Warning: bootstrap file not found at {bootstrap_path}")
        else:
            log(f"Loading bootstrap strategies from {bootstrap_path}")
            bootstrap = load_json(bootstrap_path)
            strategies = extract_bootstrap_strategies(bootstrap, args.family)
            bootstrap_count = len(strategies)

            # Write bootstrap strategy to context
            bootstrap_context_path = output / "context" / "bootstrap_strategy.json"
            write_json(bootstrap_context_path, strategies)
            log(f"Extracted {bootstrap_count} bootstrap strategy/strategies")

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
        "directories_created": subdirs,
    }
    dump_json(summary)


if __name__ == "__main__":
    main()
