#!/usr/bin/env python3
"""Generate seed strategies for all ontology node IDs.

Creates one strategy per ontology node and marks seed source:
- bootstrap: exact concept id found in bootstrap config
- derived: copied from nearest ancestor/family bootstrap entry
- empty: minimal fallback strategy (name-derived)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import orjson

    def load_json(path: Path) -> Any:
        return orjson.loads(path.read_bytes())

    def dump_json_stdout(obj: Any) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def write_json(path: Path, obj: Any) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
except Exception:

    def load_json(path: Path) -> Any:
        return json.loads(path.read_text())

    def dump_json_stdout(obj: Any) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def write_json(path: Path, obj: Any) -> None:
        path.write_text(json.dumps(obj, indent=2, default=str))


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, tuple):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _family_from_id(concept_id: str) -> str:
    parts = [p for p in concept_id.split(".") if p]
    if len(parts) >= 2:
        return parts[1]
    if parts:
        return parts[0]
    return "unknown"


def _profile_type_for_id(concept_id: str) -> str:
    parts = [p for p in concept_id.split(".") if p]
    if len(parts) == 2:
        return "family_core"
    if len(parts) >= 4:
        return "concept_advanced"
    return "concept_standard"


def _title_from_id(concept_id: str) -> str:
    leaf = concept_id.split(".")[-1] if concept_id else "concept"
    return leaf.replace("_", " ").strip().title() or "Concept"


def _name_keywords(name: str) -> list[str]:
    clean = re.sub(r"\s+", " ", name.strip())
    if not clean:
        return ["concept"]
    parts = [p.lower() for p in re.split(r"[^A-Za-z0-9]+", clean) if p]
    out: list[str] = []
    if clean:
        out.append(clean)
    out.extend(p for p in parts if len(p) >= 3)
    dedup: list[str] = []
    seen: set[str] = set()
    for token in out:
        if token and token not in seen:
            seen.add(token)
            dedup.append(token)
    return dedup[:8] if dedup else ["concept"]


def collect_ontology_nodes(tree: Any) -> dict[str, dict[str, Any]]:
    """Collect ontology hierarchy nodes keyed by id with parent linkage.

    For production ontology files, we intentionally traverse only the
    `domains -> children` hierarchy so we seed true ontology nodes
    (and avoid metadata/reference objects that also carry `id` fields).
    """
    nodes: dict[str, dict[str, Any]] = {}

    def walk(node: Any, parent_id: str | None) -> None:
        if isinstance(node, dict):
            node_id = node.get("id")
            current_parent = parent_id
            if isinstance(node_id, str) and node_id.strip():
                clean_id = node_id.strip()
                nodes[clean_id] = {
                    "id": clean_id,
                    "name": str(node.get("name", "")).strip(),
                    "level": node.get("level"),
                    "parent_id": parent_id,
                }
                current_parent = clean_id
            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    walk(child, current_parent)
        elif isinstance(node, list):
            for item in node:
                walk(item, parent_id)

    roots: Any = tree
    if isinstance(tree, dict) and isinstance(tree.get("domains"), list):
        roots = tree["domains"]
    walk(roots, None)
    return nodes


def collect_bootstrap_entries(payload: Any) -> dict[str, dict[str, Any]]:
    """Collect bootstrap entries keyed by concept id."""
    out: dict[str, dict[str, Any]] = {}
    if isinstance(payload, dict):
        items = payload.items()
    elif isinstance(payload, list):
        items = [(None, row) for row in payload]
    else:
        return out

    for maybe_key, row in items:
        if not isinstance(row, dict):
            continue
        concept_id = row.get("id")
        if not isinstance(concept_id, str) or not concept_id.strip():
            if isinstance(maybe_key, str) and maybe_key.strip():
                concept_id = maybe_key.strip()
            else:
                continue
        clean_id = concept_id.strip()
        search = row.get("search_strategy")
        if not isinstance(search, dict):
            search = row
        out[clean_id] = {
            "id": clean_id,
            "name": str(row.get("name", "")).strip(),
            "family_id": str(row.get("family_id", "")).strip(),
            "search_strategy": search,
        }
    return out


def _ancestor_ids(concept_id: str) -> list[str]:
    parts = [p for p in concept_id.split(".") if p]
    out: list[str] = []
    for i in range(len(parts) - 1, 0, -1):
        out.append(".".join(parts[:i]))
    return out


def _select_source_entry(
    concept_id: str,
    family: str,
    bootstrap_map: dict[str, dict[str, Any]],
    family_seed: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Return (seed_source, entry, source_concept_id)."""
    direct = bootstrap_map.get(concept_id)
    if direct is not None:
        return "bootstrap", direct, concept_id

    for ancestor_id in _ancestor_ids(concept_id):
        anc = bootstrap_map.get(ancestor_id)
        if anc is not None:
            return "derived", anc, ancestor_id

    fam = family_seed.get(family)
    if fam is not None:
        return "derived", fam, str(fam.get("id", ""))

    return "empty", None, None


def _build_strategy(
    *,
    concept_id: str,
    concept_name: str,
    family: str,
    seed_source: str,
    source_entry: dict[str, Any] | None,
    source_concept_id: str | None,
) -> dict[str, Any]:
    search: dict[str, Any] = {}
    if source_entry is not None:
        maybe_search = source_entry.get("search_strategy")
        if isinstance(maybe_search, dict):
            search = maybe_search
        elif isinstance(source_entry, dict):
            search = source_entry

    heading_patterns = _as_str_list(search.get("heading_patterns"))
    keyword_anchors = _as_str_list(search.get("keyword_anchors"))
    keyword_anchors_section_only = _as_str_list(
        search.get("keyword_anchors_in_section_only")
    )
    concept_specific_keywords = _as_str_list(search.get("concept_specific_keywords"))
    defined_term_dependencies = _as_str_list(search.get("defined_term_dependencies"))
    concept_notes = _as_str_list(search.get("concept_specific_notes"))
    xref_follow = _as_str_list(search.get("xref_follow"))
    fallback_escalation = search.get("fallback_escalation")
    if not isinstance(fallback_escalation, str):
        fallback_escalation = None

    name_keywords = _name_keywords(concept_name)
    if not heading_patterns:
        heading_patterns = [concept_name]
    if not keyword_anchors:
        keyword_anchors = name_keywords[:3]
    if not concept_specific_keywords:
        concept_specific_keywords = name_keywords[:5]

    update_notes = [f"seed_source={seed_source}"]
    if source_concept_id:
        update_notes.append(f"seed_parent={source_concept_id}")

    return {
        "concept_id": concept_id,
        "concept_name": concept_name,
        "family": family,
        "profile_type": _profile_type_for_id(concept_id),
        "heading_patterns": heading_patterns,
        "keyword_anchors": keyword_anchors,
        "keyword_anchors_section_only": keyword_anchors_section_only,
        "concept_specific_keywords": concept_specific_keywords,
        "defined_term_dependencies": defined_term_dependencies,
        "concept_notes": concept_notes,
        "fallback_escalation": fallback_escalation,
        "xref_follow": xref_follow,
        "validation_status": "bootstrap",
        "version": 1,
        "update_notes": update_notes,
        # Metadata field for seed inspection; ignored by load_strategy.
        "seed_source": seed_source,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate seed strategies for all ontology node IDs.",
    )
    parser.add_argument("--ontology", required=True, help="Path to ontology JSON.")
    parser.add_argument("--bootstrap", required=True, help="Path to bootstrap JSON.")
    parser.add_argument(
        "--output",
        required=True,
        help="Output aggregate JSON path (strategy bundle).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional directory to write per-node seed strategy JSON files.",
    )
    args = parser.parse_args()

    ontology_path = Path(args.ontology).resolve()
    bootstrap_path = Path(args.bootstrap).resolve()
    output_path = Path(args.output).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else None

    if not ontology_path.exists():
        _log(f"Error: ontology file not found: {ontology_path}")
        sys.exit(1)
    if not bootstrap_path.exists():
        _log(f"Error: bootstrap file not found: {bootstrap_path}")
        sys.exit(1)

    ontology = load_json(ontology_path)
    bootstrap_payload = load_json(bootstrap_path)
    ontology_nodes = collect_ontology_nodes(ontology)
    bootstrap_map = collect_bootstrap_entries(bootstrap_payload)

    if not ontology_nodes:
        _log("Error: no ontology node IDs found.")
        sys.exit(1)

    family_seed: dict[str, dict[str, Any]] = {}
    for concept_id, entry in bootstrap_map.items():
        family = _family_from_id(concept_id)
        if family not in family_seed:
            family_seed[family] = entry

    strategies: dict[str, dict[str, Any]] = {}
    seed_counter: Counter[str] = Counter()
    for concept_id in sorted(ontology_nodes.keys()):
        node = ontology_nodes[concept_id]
        name = str(node.get("name") or "").strip() or _title_from_id(concept_id)
        family = _family_from_id(concept_id)
        seed_source, source_entry, source_concept_id = _select_source_entry(
            concept_id,
            family,
            bootstrap_map,
            family_seed,
        )
        strategy = _build_strategy(
            concept_id=concept_id,
            concept_name=name,
            family=family,
            seed_source=seed_source,
            source_entry=source_entry,
            source_concept_id=source_concept_id,
        )
        strategies[concept_id] = strategy
        seed_counter[seed_source] += 1

    invalid_ids = sorted(set(strategies.keys()) - set(ontology_nodes.keys()))
    if invalid_ids:
        _log("Error: generated strategies contain invalid ontology IDs.")
        _log(", ".join(invalid_ids[:10]))
        sys.exit(1)

    output_payload = {
        "schema_version": "strategy_seed_all_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "ontology_path": str(ontology_path),
        "bootstrap_path": str(bootstrap_path),
        "total_ontology_nodes": len(ontology_nodes),
        "total_seeded": len(strategies),
        "seed_counts": {
            "bootstrap": int(seed_counter.get("bootstrap", 0)),
            "derived": int(seed_counter.get("derived", 0)),
            "empty": int(seed_counter.get("empty", 0)),
        },
        "strategies": strategies,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, output_payload)

    written_files = 0
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        for concept_id, strategy in strategies.items():
            file_path = output_dir / f"{concept_id}_v001.json"
            write_json(file_path, strategy)
            written_files += 1

    dump_json_stdout(
        {
            "status": "ok",
            "output": str(output_path),
            "output_dir": str(output_dir) if output_dir is not None else None,
            "total_ontology_nodes": len(ontology_nodes),
            "total_seeded": len(strategies),
            "seed_counts": output_payload["seed_counts"],
            "per_node_files_written": written_files,
            "invalid_ids": invalid_ids,
        }
    )


if __name__ == "__main__":
    main()
