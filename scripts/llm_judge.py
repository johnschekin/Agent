#!/usr/bin/env python3
"""Precision self-evaluation for extracted matches.

This tool samples candidate matches and classifies each as:
- correct
- partial
- wrong

Backends:
- heuristic (default): deterministic lexical/rule-based evaluator
- mock: uses `expected_verdict` when provided, otherwise heuristic
- anthropic: optional API-backed mode (falls back unless --strict-backend)

Usage:
    python3 scripts/llm_judge.py \
      --matches workspaces/indebtedness/results/latest_matches.json \
      --concept-id debt_capacity.indebtedness \
      --sample 20
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import orjson

    def dump_json(obj: Any) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def load_json(path: Path) -> Any:
        return orjson.loads(path.read_bytes())

    def write_json(path: Path, obj: Any) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
except ImportError:

    def dump_json(obj: Any) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def load_json(path: Path) -> Any:
        return json.loads(path.read_text())

    def write_json(path: Path, obj: Any) -> None:
        path.write_text(json.dumps(obj, indent=2, default=str))


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "shall",
    "will",
    "such",
    "any",
    "all",
    "not",
    "are",
    "its",
    "per",
    "via",
    "upon",
    "under",
    "term",
    "terms",
    "concept",
    "capacity",
}

COMPETING_TOPIC_KEYWORDS = {
    "liens",
    "investments",
    "restricted payments",
    "asset sale",
    "change of control",
    "fundamental changes",
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("matches", "hits", "results", "rows", "data"):
            val = payload.get(key)
            if isinstance(val, list):
                return [row for row in val if isinstance(row, dict)]
        # Some payloads are a dict keyed by doc_id -> row payload.
        if payload and all(isinstance(v, dict) for v in payload.values()):
            out: list[dict[str, Any]] = []
            for key, row in payload.items():
                copied = dict(row)
                copied.setdefault("doc_id", str(key))
                out.append(copied)
            return out
    return []


def _load_match_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows
    payload = load_json(path)
    return _extract_rows(payload)


def _normalize_match(row: dict[str, Any], idx: int) -> dict[str, Any]:
    text_fields = (
        "clause_text",
        "matched_text",
        "text",
        "section_text",
        "context",
    )
    clause_text = ""
    for field in text_fields:
        val = row.get(field)
        if isinstance(val, str) and val.strip():
            clause_text = val.strip()
            break
    return {
        "row_index": idx,
        "doc_id": str(row.get("doc_id", "") or ""),
        "section": str(row.get("section", row.get("section_path", "")) or ""),
        "heading": str(row.get("heading", "") or ""),
        "clause_text": clause_text,
        "raw": row,
    }


def _concept_tokens(concept_id: str, concept_name: str) -> set[str]:
    seed = f"{concept_id} {concept_name}".lower().replace(".", " ").replace("_", " ")
    tokens = set(re.findall(r"[a-z][a-z0-9]{2,}", seed))
    return {tok for tok in tokens if tok not in STOPWORDS}


def _heuristic_verdict(
    *,
    concept_tokens: set[str],
    clause_text: str,
) -> tuple[str, str, dict[str, Any]]:
    text = (clause_text or "").strip()
    if not text:
        return "wrong", "No clause text available for judging.", {"matched_tokens": []}

    lower = text.lower()
    token_hits = sorted({tok for tok in concept_tokens if re.search(rf"\b{re.escape(tok)}\b", lower)})
    hit_count = len(token_hits)
    concept_token_count = max(1, len(concept_tokens))
    hit_ratio = hit_count / concept_token_count

    competing_hits = sorted(
        kw for kw in COMPETING_TOPIC_KEYWORDS
        if kw in lower and kw not in token_hits
    )

    verdict = "wrong"
    reason = "Concept tokens were not detected in the clause."
    if hit_count >= 2 and hit_ratio >= 0.20:
        verdict = "correct"
        reason = "Clause contains multiple concept tokens and a strong lexical match."
    elif hit_count >= 1:
        verdict = "partial"
        reason = "Clause contains a limited lexical signal for the concept."

    if competing_hits and hit_count <= 1:
        verdict = "wrong"
        reason = "Clause appears to target a competing covenant topic."

    details = {
        "matched_tokens": token_hits,
        "concept_token_count": concept_token_count,
        "hit_ratio": round(hit_ratio, 4),
        "competing_topic_hits": competing_hits,
    }
    return verdict, reason, details


def _anthropic_verdict(
    *,
    concept_id: str,
    concept_name: str,
    clause_text: str,
    model: str,
) -> tuple[str, str, dict[str, Any]]:
    try:
        import anthropic  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - dependency optional
        raise RuntimeError(f"anthropic SDK unavailable: {exc}") from exc

    client = anthropic.Anthropic()
    prompt = (
        "You are judging extraction precision.\n"
        f"Concept ID: {concept_id}\n"
        f"Concept Name: {concept_name}\n"
        "Task: classify the clause as one of [correct, partial, wrong].\n"
        "Return compact JSON only with keys: verdict, reasoning.\n"
        f"Clause: {clause_text}\n"
    )
    response = client.messages.create(
        model=model,
        max_tokens=200,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
    )
    text_parts: list[str] = []
    for block in getattr(response, "content", []):
        txt = getattr(block, "text", "")
        if isinstance(txt, str):
            text_parts.append(txt)
    raw = "\n".join(text_parts).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - dependency optional
        raise RuntimeError(f"anthropic returned non-JSON output: {raw[:120]}") from exc

    verdict = str(parsed.get("verdict", "wrong")).strip().lower()
    if verdict not in {"correct", "partial", "wrong"}:
        verdict = "wrong"
    reasoning = str(parsed.get("reasoning", "") or "").strip() or "No reasoning provided."
    return verdict, reasoning, {"provider_raw": raw}


def _judge_row(
    *,
    backend: str,
    strict_backend: bool,
    concept_id: str,
    concept_name: str,
    concept_tokens: set[str],
    row: dict[str, Any],
    model: str,
) -> tuple[str, str, dict[str, Any], str]:
    clause_text = str(row.get("clause_text", "") or "")
    if backend == "mock":
        expected = str(row.get("raw", {}).get("expected_verdict", "")).strip().lower()
        if expected in {"correct", "partial", "wrong"}:
            return expected, "Using expected_verdict from input row (mock mode).", {}, "mock"
        verdict, reason, details = _heuristic_verdict(
            concept_tokens=concept_tokens,
            clause_text=clause_text,
        )
        return verdict, reason, details, "heuristic_fallback"

    if backend == "anthropic":
        try:
            verdict, reason, details = _anthropic_verdict(
                concept_id=concept_id,
                concept_name=concept_name,
                clause_text=clause_text,
                model=model,
            )
            return verdict, reason, details, "anthropic"
        except Exception as exc:  # pragma: no cover - dependency optional
            if strict_backend:
                raise
            log(f"Warning: anthropic backend unavailable, using heuristic fallback ({exc})")
            verdict, reason, details = _heuristic_verdict(
                concept_tokens=concept_tokens,
                clause_text=clause_text,
            )
            details = dict(details)
            details["fallback_reason"] = str(exc)
            return verdict, reason, details, "heuristic_fallback"

    verdict, reason, details = _heuristic_verdict(
        concept_tokens=concept_tokens,
        clause_text=clause_text,
    )
    return verdict, reason, details, "heuristic"


def main() -> None:
    parser = argparse.ArgumentParser(description="Precision self-evaluation for extracted matches.")
    parser.add_argument("--matches", required=True, help="Path to matches JSON/JSONL payload.")
    parser.add_argument("--concept-id", required=True, help="Concept ID being evaluated.")
    parser.add_argument("--concept-name", default="", help="Optional concept name.")
    parser.add_argument("--sample", type=int, default=20, help="Random sample size.")
    parser.add_argument("--seed", type=int, default=42, help="Sampling random seed.")
    parser.add_argument(
        "--backend",
        choices=("heuristic", "mock", "anthropic"),
        default="heuristic",
        help="Judge backend.",
    )
    parser.add_argument("--model", default="claude-3-5-haiku-latest", help="LLM model id.")
    parser.add_argument(
        "--strict-backend",
        action="store_true",
        help="Fail instead of falling back when requested backend is unavailable.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path (default: stdout only).",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help=(
            "Optional workspace path; when --output is omitted, report is written to "
            "workspace/results/judge/<concept_id>_<timestamp>.json"
        ),
    )
    args = parser.parse_args()

    matches_path = Path(args.matches)
    if not matches_path.exists():
        log(f"Error: matches file not found at {matches_path}")
        sys.exit(1)

    rows = _load_match_rows(matches_path)
    normalized = [_normalize_match(row, idx) for idx, row in enumerate(rows)]
    normalized = [row for row in normalized if row.get("clause_text") or row.get("doc_id")]

    total_candidates = len(normalized)
    if total_candidates == 0:
        result = {
            "schema_version": "llm_judge_v1",
            "status": "empty",
            "concept_id": args.concept_id,
            "concept_name": args.concept_name,
            "backend_requested": args.backend,
            "backend_used": args.backend,
            "n_candidates": 0,
            "n_sampled": 0,
            "precision_estimate": 0.0,
            "weighted_precision_estimate": 0.0,
            "correct": 0,
            "partial": 0,
            "wrong": 0,
            "sample_results": [],
        }
        dump_json(result)
        return

    sample_n = max(1, min(int(args.sample), total_candidates))
    rng = random.Random(args.seed)
    sampled = normalized if sample_n >= total_candidates else rng.sample(normalized, sample_n)

    concept_tokens = _concept_tokens(args.concept_id, args.concept_name)
    if not concept_tokens:
        concept_tokens = {"indebtedness"} if "indebtedness" in args.concept_id.lower() else set()

    sample_results: list[dict[str, Any]] = []
    correct = 0
    partial = 0
    wrong = 0
    backend_used_values: set[str] = set()

    for row in sampled:
        verdict, reasoning, details, backend_used = _judge_row(
            backend=args.backend,
            strict_backend=bool(args.strict_backend),
            concept_id=args.concept_id,
            concept_name=args.concept_name,
            concept_tokens=concept_tokens,
            row=row,
            model=args.model,
        )
        backend_used_values.add(backend_used)
        if verdict == "correct":
            correct += 1
        elif verdict == "partial":
            partial += 1
        else:
            wrong += 1

        sample_results.append(
            {
                "doc_id": row.get("doc_id", ""),
                "section": row.get("section", ""),
                "heading": row.get("heading", ""),
                "clause_text": row.get("clause_text", ""),
                "verdict": verdict,
                "judge_reasoning": reasoning,
                "judge_details": details,
                "backend_used": backend_used,
            }
        )

    n_sampled = len(sample_results)
    precision_estimate = round(correct / n_sampled, 4) if n_sampled > 0 else 0.0
    weighted_precision = round((correct + 0.5 * partial) / n_sampled, 4) if n_sampled > 0 else 0.0
    run_id = f"llm_judge_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"

    wrong_examples = [row for row in sample_results if row["verdict"] == "wrong"][:10]
    partial_examples = [row for row in sample_results if row["verdict"] == "partial"][:10]
    correct_examples = [row for row in sample_results if row["verdict"] == "correct"][:10]

    result = {
        "schema_version": "llm_judge_v1",
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "ok",
        "concept_id": args.concept_id,
        "concept_name": args.concept_name,
        "backend_requested": args.backend,
        "backend_used": sorted(backend_used_values),
        "model": args.model,
        "matches_path": str(matches_path),
        "n_candidates": total_candidates,
        "sample_requested": int(args.sample),
        "n_sampled": n_sampled,
        "seed": args.seed,
        "precision_estimate": precision_estimate,
        "weighted_precision_estimate": weighted_precision,
        "correct": correct,
        "partial": partial,
        "wrong": wrong,
        "wrong_examples": wrong_examples,
        "partial_examples": partial_examples,
        "correct_examples": correct_examples,
        "sample_results": sample_results,
    }

    output_path: Path | None = None
    if args.output:
        output_path = Path(args.output)
    elif args.workspace:
        workspace = Path(args.workspace)
        output_path = (
            workspace
            / "results"
            / "judge"
            / f"{args.concept_id}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(output_path, result)
        result["output_path"] = str(output_path)

    dump_json(result)


if __name__ == "__main__":
    main()
