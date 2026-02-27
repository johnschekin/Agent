#!/usr/bin/env python3
"""Build a deterministic adjudication queue from gold fixtures.

Default behavior creates a 200-item P0 queue skewed toward hard parser categories.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "data" / "fixtures" / "gold" / "v1" / "packs" / "v1-seed-1000-candidate" / "fixtures.jsonl"
DEFAULT_OUT = ROOT / "data" / "fixtures" / "gold" / "v1" / "adjudication" / "p0_adjudication_queue_200.jsonl"
DEFAULT_MANIFEST = ROOT / "data" / "fixtures" / "gold" / "v1" / "adjudication" / "p0_adjudication_queue_200.manifest.json"

DEFAULT_TARGETS: dict[str, int] = {
    "ambiguous_alpha_roman": 60,
    "high_letter_continuation": 60,
    "nonstruct_parent_chain": 45,
    "xref_vs_structural": 35,
}

SPLIT_PRIORITY = {
    "val": 0,
    "test": 1,
    "holdout": 2,
    "train": 3,
}

DECISION_PRIORITY = {
    "review": 0,
    "abstain": 1,
    "accepted": 2,
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                rows.append(json.loads(s))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Queue output exists: {path}. Pass --overwrite to replace.")
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def _doc_key(fx: dict[str, Any]) -> str:
    source = fx.get("source", {})
    return str(source.get("doc_id") or "").strip()


def _section_key(fx: dict[str, Any]) -> tuple[str, str]:
    source = fx.get("source", {})
    doc_id = str(source.get("doc_id") or "").strip()
    section_number = str(source.get("section_number") or "").strip()
    return doc_id, section_number


def _priority_key(fx: dict[str, Any]) -> tuple[int, int, float, str]:
    split = str(fx.get("split") or "").strip()
    decision = str(fx.get("gold_decision") or "").strip()
    candidate_score = float((fx.get("source") or {}).get("candidate_score") or 0.0)
    fixture_id = str(fx.get("fixture_id") or "")
    return (
        SPLIT_PRIORITY.get(split, 99),
        DECISION_PRIORITY.get(decision, 99),
        -candidate_score,
        fixture_id,
    )


def _parse_targets(spec: str) -> dict[str, int]:
    targets: dict[str, int] = {}
    for token in [p.strip() for p in spec.split(",") if p.strip()]:
        if ":" not in token:
            raise ValueError(f"Invalid target token (expected category:count): {token}")
        category, count_s = token.split(":", 1)
        category = category.strip()
        count = int(count_s.strip())
        if count < 0:
            raise ValueError(f"Target count must be >= 0: {token}")
        targets[category] = count
    if not targets:
        raise ValueError("No valid targets provided.")
    return targets


def _parse_min_splits(spec: str) -> dict[str, int]:
    spec = str(spec or "").strip()
    if not spec:
        return {}
    parsed: dict[str, int] = {}
    for token in [p.strip() for p in spec.split(",") if p.strip()]:
        if ":" not in token:
            raise ValueError(f"Invalid split floor token (expected split:count): {token}")
        split, count_s = token.split(":", 1)
        split = split.strip()
        count = int(count_s.strip())
        if split not in {"train", "val", "test", "holdout"}:
            raise ValueError(f"Unsupported split in --min-splits: {split}")
        if count < 0:
            raise ValueError(f"Split floor must be >= 0: {token}")
        parsed[split] = count
    return parsed


def _rebalance_to_split_floors(
    selected: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
    *,
    targets: dict[str, int],
    min_splits: dict[str, int],
) -> list[dict[str, Any]]:
    if not min_splits:
        return selected

    selected_ids = {str(fx.get("fixture_id") or "") for fx in selected}
    selected_sections = {_section_key(fx) for fx in selected}
    selected_docs = {_doc_key(fx) for fx in selected if _doc_key(fx)}

    candidates_by_cat_split: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for category, rows in grouped.items():
        for fx in rows:
            split = str(fx.get("split") or "").strip()
            candidates_by_cat_split[(category, split)].append(fx)

    max_iterations = max(1000, len(selected) * 20)
    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        split_counts = Counter(str(fx.get("split") or "") for fx in selected)
        deficits = [
            (split, floor - int(split_counts.get(split, 0)))
            for split, floor in min_splits.items()
            if int(split_counts.get(split, 0)) < floor
        ]
        if not deficits:
            return selected
        deficits.sort(key=lambda x: (-x[1], x[0]))
        need_split, _deficit = deficits[0]

        swapped = False
        category_order = sorted(targets.keys(), key=lambda c: (-targets[c], c))
        for category in category_order:
            # Find an incoming candidate in the needed split for this category.
            incoming: dict[str, Any] | None = None
            for cand in candidates_by_cat_split.get((category, need_split), []):
                cand_id = str(cand.get("fixture_id") or "")
                if cand_id in selected_ids:
                    continue
                cand_section = _section_key(cand)
                if cand_section in selected_sections:
                    continue
                cand_doc = _doc_key(cand)
                if cand_doc and cand_doc in selected_docs:
                    continue
                incoming = cand
                break
            if incoming is None:
                continue

            # Remove one selected item from same category whose split can spare one.
            remove_idx: int | None = None
            best_surplus = -1
            for idx, current in enumerate(selected):
                if str(current.get("category") or "") != category:
                    continue
                current_split = str(current.get("split") or "").strip()
                current_floor = int(min_splits.get(current_split, 0))
                if int(split_counts.get(current_split, 0)) - 1 < current_floor:
                    continue
                surplus = int(split_counts.get(current_split, 0)) - current_floor
                if surplus > best_surplus:
                    best_surplus = surplus
                    remove_idx = idx
            if remove_idx is None:
                continue

            outgoing = selected[remove_idx]
            outgoing_id = str(outgoing.get("fixture_id") or "")
            outgoing_section = _section_key(outgoing)
            outgoing_doc = _doc_key(outgoing)

            incoming_id = str(incoming.get("fixture_id") or "")
            incoming_section = _section_key(incoming)
            incoming_doc = _doc_key(incoming)

            # Swap in place.
            selected[remove_idx] = incoming

            # Update fast-lookup sets.
            selected_ids.discard(outgoing_id)
            selected_sections.discard(outgoing_section)
            if outgoing_doc:
                selected_docs.discard(outgoing_doc)

            selected_ids.add(incoming_id)
            selected_sections.add(incoming_section)
            if incoming_doc:
                selected_docs.add(incoming_doc)

            swapped = True
            break

        if not swapped:
            break

    final_counts = Counter(str(fx.get("split") or "") for fx in selected)
    unsatisfied = {
        split: {"need": floor, "have": int(final_counts.get(split, 0))}
        for split, floor in min_splits.items()
        if int(final_counts.get(split, 0)) < floor
    }
    if unsatisfied:
        raise RuntimeError(f"Could not satisfy split floors: {unsatisfied}")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Build adjudication queue from fixture JSONL")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES, help="Fixture JSONL input")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Adjudication queue JSONL output")
    parser.add_argument("--manifest-out", type=Path, default=DEFAULT_MANIFEST, help="Manifest JSON output")
    parser.add_argument(
        "--targets",
        default=",".join(f"{k}:{v}" for k, v in DEFAULT_TARGETS.items()),
        help="Comma-separated category targets, e.g. a:60,b:40",
    )
    parser.add_argument(
        "--min-splits",
        default="",
        help="Optional minimum counts by split, e.g. train:40,val:20",
    )
    parser.add_argument("--queue-id", default="p0-adjudication", help="Queue identifier")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite outputs")
    args = parser.parse_args()

    targets = _parse_targets(args.targets)
    min_splits = _parse_min_splits(args.min_splits)
    target_total = sum(targets.values())
    if target_total <= 0:
        raise ValueError("Total target size must be > 0")
    if sum(min_splits.values()) > target_total:
        raise ValueError(
            f"Sum of --min-splits ({sum(min_splits.values())}) exceeds queue size ({target_total})"
        )

    fixtures = _read_jsonl(args.fixtures)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fx in fixtures:
        category = str(fx.get("category") or "").strip()
        if category in targets:
            grouped[category].append(fx)

    for category in grouped:
        grouped[category].sort(key=_priority_key)

    selected: list[dict[str, Any]] = []
    selected_sections: set[tuple[str, str]] = set()
    selected_docs: set[str] = set()
    selected_ids: set[str] = set()
    selected_counts = Counter()

    def try_take(category: str, need: int, allow_doc_reuse: bool) -> int:
        taken = 0
        for fx in grouped.get(category, []):
            if taken >= need:
                break
            fixture_id = str(fx.get("fixture_id") or "")
            if fixture_id in selected_ids:
                continue
            section = _section_key(fx)
            if section in selected_sections:
                continue
            doc_id = _doc_key(fx)
            if not allow_doc_reuse and doc_id in selected_docs:
                continue

            selected.append(fx)
            selected_ids.add(fixture_id)
            selected_sections.add(section)
            if doc_id:
                selected_docs.add(doc_id)
            selected_counts[category] += 1
            taken += 1
        return taken

    # Pass 1: enforce category targets with doc-unique preference.
    for category, target in targets.items():
        taken = try_take(category, target, allow_doc_reuse=False)
        if taken < target:
            try_take(category, target - taken, allow_doc_reuse=True)

    # Pass 2: if any shortfall remains, fill from priority categories.
    shortfall = target_total - len(selected)
    if shortfall > 0:
        priority_categories = sorted(
            targets.keys(),
            key=lambda c: (
                -targets[c],  # larger target first
                c,
            ),
        )
        for category in priority_categories:
            if shortfall <= 0:
                break
            added = try_take(category, shortfall, allow_doc_reuse=True)
            shortfall -= added

    if len(selected) != target_total:
        raise RuntimeError(
            f"Could not satisfy target size {target_total}. Selected {len(selected)}."
        )

    selected = _rebalance_to_split_floors(
        selected,
        grouped,
        targets=targets,
        min_splits=min_splits,
    )

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    queue_rows: list[dict[str, Any]] = []
    for i, fx in enumerate(selected, start=1):
        queue_rows.append(
            {
                "queue_id": args.queue_id,
                "queue_item_id": f"{args.queue_id.upper()}-{i:04d}",
                "priority_rank": i,
                "status": "pending",
                "assigned_to": None,
                "created_at": created_at,
                "fixture_id": fx.get("fixture_id"),
                "category": fx.get("category"),
                "split": fx.get("split"),
                "gold_decision": fx.get("gold_decision"),
                "reason_codes": list(fx.get("reason_codes") or []),
                "ambiguity_class": (fx.get("adjudication") or {}).get("ambiguity_class"),
                "source": {
                    "doc_id": (fx.get("source") or {}).get("doc_id"),
                    "section_number": (fx.get("source") or {}).get("section_number"),
                    "snapshot_id": (fx.get("source") or {}).get("snapshot_id"),
                    "candidate_score": (fx.get("source") or {}).get("candidate_score"),
                },
            },
        )

    _write_jsonl(args.out, queue_rows, overwrite=args.overwrite)

    split_counts = Counter(str(r.get("split") or "") for r in queue_rows)
    decision_counts = Counter(str(r.get("gold_decision") or "") for r in queue_rows)
    category_counts = Counter(str(r.get("category") or "") for r in queue_rows)
    manifest = {
        "version": "gold-adjudication-queue-v1",
        "queue_id": args.queue_id,
        "created_at": created_at,
        "input_fixtures": str(args.fixtures),
        "output_queue": str(args.out),
        "targets": targets,
        "min_splits": min_splits,
        "counts": {
            "queue_size": len(queue_rows),
            "doc_count": len({str((r.get("source") or {}).get("doc_id") or "") for r in queue_rows}),
            "by_category": dict(sorted(category_counts.items())),
            "by_split": dict(sorted(split_counts.items())),
            "by_decision": dict(sorted(decision_counts.items())),
        },
        "notes": "Deterministic selection with category targets and split-aware priority.",
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    if args.manifest_out.exists() and not args.overwrite:
        raise FileExistsError(
            f"Manifest output exists: {args.manifest_out}. Pass --overwrite to replace."
        )
    args.manifest_out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"status": "ok", **manifest["counts"], "manifest_out": str(args.manifest_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
