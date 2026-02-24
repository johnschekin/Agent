#!/usr/bin/env python3
"""Generate ontology-driven `swarm/swarm.conf` assignments.

Produces one assignment per family with wave/pane distribution and subtree
whitelist entries (`family_id,family_id.*`) for scalable concept gating.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import orjson

    def _load_json(path: Path) -> Any:
        return orjson.loads(path.read_bytes())

    def _dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def _load_json(path: Path) -> Any:
        with path.open() as f:
            return json.load(f)

    def _dump_json(obj: object) -> None:
        print(json.dumps(obj, indent=2, default=str))


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _slug(text: str) -> str:
    lowered = text.strip().lower()
    lowered = lowered.replace("-", "_").replace(" ", "_")
    lowered = re.sub(r"[^a-z0-9_]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered)
    return lowered.strip("_")


@dataclass(frozen=True, slots=True)
class FamilyNode:
    family_id: str
    name: str
    tail: str
    order: int


def _collect_family_nodes(ontology: object) -> list[FamilyNode]:
    families: list[FamilyNode] = []
    order = 0

    def walk(node: object) -> None:
        nonlocal order
        if isinstance(node, dict):
            if str(node.get("type", "")).strip().lower() == "family":
                family_id = str(node.get("id", "")).strip()
                name = str(node.get("name", "")).strip()
                if family_id:
                    tail = family_id.split(".")[-1]
                    families.append(
                        FamilyNode(
                            family_id=family_id,
                            name=name,
                            tail=tail,
                            order=order,
                        )
                    )
                    order += 1
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(ontology)
    return families


def _family_key_map(families: list[FamilyNode], *, key_style: str) -> dict[str, str]:
    if key_style == "family_id":
        return {family.family_id: _slug(family.family_id.replace(".", "_")) for family in families}

    tail_counts: dict[str, int] = {}
    for family in families:
        tail_counts[family.tail] = tail_counts.get(family.tail, 0) + 1

    out: dict[str, str] = {}
    for family in families:
        if tail_counts[family.tail] == 1:
            out[family.family_id] = _slug(family.tail)
        else:
            out[family.family_id] = _slug(family.family_id.replace(".", "_"))
    return out


def _parse_csv_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {part.strip() for part in str(raw).split(",") if part.strip()}


def _load_depends_map(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"depends map not found: {path}")
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("depends map must be a JSON object")
    out: dict[str, list[str]] = {}
    for k, v in payload.items():
        key = str(k).strip()
        if not key:
            continue
        if isinstance(v, list):
            deps = [str(item).strip() for item in v if str(item).strip()]
        elif isinstance(v, str):
            deps = [part.strip() for part in v.split(",") if part.strip()]
        else:
            deps = []
        out[key] = deps
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate swarm.conf from ontology families.")
    parser.add_argument("--ontology", required=True, help="Path to ontology JSON.")
    parser.add_argument("--output", default="swarm/swarm.conf", help="Output swarm.conf path.")
    parser.add_argument("--session-name", default="agent-swarm", help="SESSION_NAME value.")
    parser.add_argument("--backend", default="opus46", help="DEFAULT_BACKEND value.")
    parser.add_argument("--panes", type=int, default=4, help="DEFAULT_PANES value.")
    parser.add_argument(
        "--startup-wait-seconds",
        type=int,
        default=2,
        help="STARTUP_WAIT_SECONDS value.",
    )
    parser.add_argument(
        "--order",
        choices=("ontology", "alpha"),
        default="alpha",
        help="Family ordering mode before wave assignment.",
    )
    parser.add_argument(
        "--key-style",
        choices=("tail", "family_id"),
        default="tail",
        help="Family key style used in swarm assignments.",
    )
    parser.add_argument(
        "--wave1-count",
        type=int,
        default=5,
        help="Number of non-anchor families assigned to Wave 1.",
    )
    parser.add_argument(
        "--wave2-anchors",
        default="debt_capacity.indebtedness,debt_capacity.liens,cash_flow.rp,cash_flow.inv",
        help="Comma-separated family IDs reserved for Wave 2.",
    )
    parser.add_argument(
        "--wave4-families",
        default="",
        help="Optional comma-separated family IDs to place in Wave 4.",
    )
    parser.add_argument(
        "--depends-map",
        default=None,
        help=(
            "Optional JSON map of dependencies. Keys can be family_id or assignment key; "
            "values are dependency family keys."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated config text to stdout instead of writing file.",
    )
    args = parser.parse_args()

    if args.panes <= 0:
        parser.error("--panes must be > 0")
    if args.startup_wait_seconds <= 0:
        parser.error("--startup-wait-seconds must be > 0")
    if args.wave1_count < 0:
        parser.error("--wave1-count must be >= 0")

    ontology_path = Path(args.ontology)
    if not ontology_path.exists():
        _log(f"Error: ontology file not found at {ontology_path}")
        sys.exit(1)

    families = _collect_family_nodes(_load_json(ontology_path))
    if not families:
        _log("Error: no family nodes found in ontology.")
        sys.exit(1)

    if args.order == "alpha":
        families = sorted(families, key=lambda f: (f.family_id, f.order))
    else:
        families = sorted(families, key=lambda f: f.order)

    key_map = _family_key_map(families, key_style=args.key_style)
    by_id = {family.family_id: family for family in families}

    wave2_anchors = _parse_csv_set(args.wave2_anchors)
    wave4_families = _parse_csv_set(args.wave4_families)
    invalid_anchors = sorted(v for v in wave2_anchors if v not in by_id)
    invalid_wave4 = sorted(v for v in wave4_families if v not in by_id)

    anchor_ids = [family.family_id for family in families if family.family_id in wave2_anchors]
    wave4_ids = [family.family_id for family in families if family.family_id in wave4_families]
    remaining_ids = [
        family.family_id
        for family in families
        if family.family_id not in wave2_anchors
        and family.family_id not in wave4_families
    ]
    wave1_ids = remaining_ids[: args.wave1_count]
    wave3_ids = [fid for fid in remaining_ids if fid not in set(wave1_ids)]

    depends_map = _load_depends_map(Path(args.depends_map) if args.depends_map else None)

    pane_counters: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    assignments: list[dict[str, Any]] = []

    def add_family(family_id: str, wave: int) -> None:
        pane = pane_counters[wave] % args.panes
        pane_counters[wave] += 1
        family_key = key_map[family_id]
        whitelist = f"{family_id},{family_id}.*"
        deps = depends_map.get(family_id, depends_map.get(family_key, []))
        assignments.append(
            {
                "family_id": family_id,
                "family_name": by_id[family_id].name,
                "family_key": family_key,
                "wave": wave,
                "pane": pane,
                "backend": args.backend,
                "whitelist": whitelist,
                "depends_on": deps,
            }
        )

    for family_id in wave1_ids:
        add_family(family_id, 1)
    for family_id in anchor_ids:
        add_family(family_id, 2)
    for family_id in wave3_ids:
        add_family(family_id, 3)
    for family_id in wave4_ids:
        add_family(family_id, 4)

    lines: list[str] = [
        "# Swarm defaults",
        f"SESSION_NAME={args.session_name}",
        f"DEFAULT_BACKEND={args.backend}",
        f"DEFAULT_PANES={args.panes}",
        f"STARTUP_WAIT_SECONDS={args.startup_wait_seconds}",
        "",
        "# Auto-generated by scripts/generate_swarm_conf.py",
        f"# generated_at={datetime.now(UTC).isoformat()}",
        f"# ontology={ontology_path}",
        "# Assignment format:",
        "# family|pane|wave|backend|concept_whitelist_csv|depends_on_csv(optional)",
    ]
    for row in sorted(assignments, key=lambda r: (r["wave"], r["pane"], r["family_key"])):
        depends_csv = ",".join(str(v) for v in row["depends_on"] if str(v).strip())
        line = (
            f"{row['family_key']}|{row['pane']}|{row['wave']}|{row['backend']}|"
            f"{row['whitelist']}"
        )
        if depends_csv:
            line += f"|{depends_csv}"
        lines.append(line)
    conf_text = "\n".join(lines).strip() + "\n"

    output_path = Path(args.output)
    if args.dry_run:
        _log("---- generated swarm.conf (dry-run) ----")
        _log(conf_text.rstrip("\n"))
        _log("---- end generated swarm.conf ----")
    else:
        if output_path.exists() and not args.force:
            _log(f"Error: output exists at {output_path}. Use --force to overwrite.")
            sys.exit(1)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(conf_text)
        _log(f"Wrote {output_path} with {len(assignments)} assignments.")

    payload = {
        "schema_version": "swarm_conf_generation_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "ontology": str(ontology_path),
        "output": str(output_path),
        "dry_run": bool(args.dry_run),
        "summary": {
            "total_families": len(families),
            "assignment_count": len(assignments),
            "wave1_count": len(wave1_ids),
            "wave2_count": len(anchor_ids),
            "wave3_count": len(wave3_ids),
            "wave4_count": len(wave4_ids),
            "invalid_wave2_anchors": invalid_anchors,
            "invalid_wave4_families": invalid_wave4,
        },
        "assignments": assignments,
    }
    _dump_json(payload)

    if invalid_anchors or invalid_wave4:
        sys.exit(1)


if __name__ == "__main__":
    main()
