#!/usr/bin/env python3
"""Build OpenAI Batch API request JSONL files for fixture adjudication.

This script converts a queue/packet JSONL into one or more OpenAI Batch request
files, chunked at a configurable row count (default: 50 rows per batch).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT_FILE = ROOT / "docs" / "operations" / "openai_batch_adjudication_prompt_v1.txt"


@dataclass(frozen=True)
class PreparedRequest:
    custom_id: str
    request: dict[str, Any]
    raw_text_len: int
    fixture_id: str


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: row must be JSON object")
            rows.append(obj)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "fixture_id",
            "schema_version",
            "category",
            "source_type",
            "source",
            "text",
            "gold_nodes",
            "gold_decision",
            "reason_codes",
            "adjudication",
            "split",
        ],
        "properties": {
            "fixture_id": {"type": "string", "minLength": 1},
            "schema_version": {"type": "string", "const": "gold-fixture-v1"},
            "category": {"type": "string", "minLength": 1},
            "source_type": {"type": "string", "enum": ["corpus", "synthetic"]},
            "source": {
                "type": "object",
                "additionalProperties": False,
                "required": ["doc_id", "section_number", "snapshot_id"],
                "properties": {
                    "doc_id": {"type": "string", "minLength": 1},
                    "section_number": {"type": "string", "minLength": 1},
                    "snapshot_id": {"type": "string", "minLength": 1},
                },
            },
            "text": {
                "type": "object",
                "additionalProperties": False,
                "required": ["raw_text", "char_start", "char_end", "normalization"],
                "properties": {
                    "raw_text": {"type": "string"},
                    "char_start": {"type": "integer", "minimum": 0},
                    "char_end": {"type": "integer", "minimum": 0},
                    "normalization": {"type": "string"},
                },
            },
            "gold_nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "clause_id",
                        "label",
                        "parent_id",
                        "depth",
                        "level_type",
                        "span_start",
                        "span_end",
                        "is_structural",
                        "xref_suspected",
                    ],
                    "properties": {
                        "clause_id": {"type": "string", "minLength": 1},
                        "label": {"type": "string", "minLength": 1},
                        "parent_id": {"type": "string"},
                        "depth": {"type": "integer", "minimum": 0},
                        "level_type": {"type": "string", "minLength": 1},
                        "span_start": {"type": "integer", "minimum": 0},
                        "span_end": {"type": "integer", "minimum": 0},
                        "is_structural": {"type": "boolean"},
                        "xref_suspected": {"type": "boolean"},
                    },
                },
            },
            "gold_decision": {"type": "string", "enum": ["accepted", "review", "abstain"]},
            "reason_codes": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "adjudication": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "human_verified",
                    "ambiguity_class",
                    "adjudicator_id",
                    "adjudicated_at",
                    "rationale",
                ],
                "properties": {
                    "human_verified": {"type": "boolean"},
                    "ambiguity_class": {"type": "string", "enum": ["none", "A1", "A2", "A3"]},
                    "adjudicator_id": {"type": "string", "minLength": 1},
                    "adjudicated_at": {"type": "string", "minLength": 1},
                    "rationale": {"type": "string", "minLength": 1},
                },
            },
            "split": {"type": "string", "enum": ["train", "val", "test", "holdout"]},
        },
    }


def _build_fixture_index(fixtures: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_source_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in fixtures:
        fixture_id = str(row.get("fixture_id") or "").strip()
        if fixture_id:
            by_id[fixture_id] = row
        src = row.get("source") or {}
        key = (
            str(src.get("doc_id") or "").strip(),
            str(src.get("section_number") or "").strip(),
            str(row.get("category") or "").strip(),
        )
        if all(key):
            by_source_key[key] = row
    return by_id, by_source_key


def _summarize_seed_nodes(nodes: list[dict[str, Any]]) -> dict[str, int]:
    duplicate_count = 0
    structural_count = 0
    xref_count = 0
    for node in nodes:
        cid = str(node.get("clause_id") or "")
        if "_dup" in cid:
            duplicate_count += 1
        if bool(node.get("is_structural")):
            structural_count += 1
        if bool(node.get("xref_suspected")):
            xref_count += 1
    return {
        "node_count": len(nodes),
        "structural_count": structural_count,
        "xref_count": xref_count,
        "duplicate_id_count": duplicate_count,
    }


def _resolve_fixture(
    packet_row: dict[str, Any],
    *,
    by_id: dict[str, dict[str, Any]],
    by_source_key: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    fixture_id = str(packet_row.get("fixture_id") or "").strip()
    if fixture_id and fixture_id in by_id:
        return by_id[fixture_id]
    src = packet_row.get("source") or {}
    key = (
        str(src.get("doc_id") or "").strip(),
        str(src.get("section_number") or "").strip(),
        str(packet_row.get("category") or "").strip(),
    )
    return by_source_key.get(key)


def _build_user_payload(packet_row: dict[str, Any], fixture_row: dict[str, Any]) -> tuple[dict[str, Any], int]:
    src = fixture_row.get("source") or {}
    text_obj = fixture_row.get("text") or {}
    raw_text = str(text_obj.get("raw_text") or "")
    raw_text_len = len(raw_text)
    seed_nodes = list(fixture_row.get("gold_nodes") or [])

    payload = {
        "task_type": "gold_fixture_adjudication",
        "queue_item_id": str(packet_row.get("queue_item_id") or "").strip(),
        "fixture_context": {
            "fixture_id": str(fixture_row.get("fixture_id") or "").strip(),
            "category": str(fixture_row.get("category") or "").strip(),
            "source": {
                "doc_id": str(src.get("doc_id") or "").strip(),
                "section_number": str(src.get("section_number") or "").strip(),
                "snapshot_id": str(src.get("snapshot_id") or "").strip(),
            },
            "split": str(fixture_row.get("split") or packet_row.get("split") or "").strip(),
            "seed_gold_decision": str(fixture_row.get("gold_decision") or "").strip(),
            "seed_reason_codes": list(fixture_row.get("reason_codes") or []),
        },
        "seed_parser_summary": _summarize_seed_nodes(seed_nodes),
        "raw_text_char_len": raw_text_len,
        "raw_text": raw_text,
    }
    return payload, raw_text_len


def _build_batch_request(
    *,
    custom_id: str,
    model: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    max_completion_tokens: int,
    temperature: float | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "max_completion_tokens": max_completion_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "gold_fixture_v1",
                "strict": True,
                "schema": _response_schema(),
            },
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
        ],
    }
    if temperature is not None:
        body["temperature"] = temperature

    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": body,
    }


def _write_submit_script(out_dir: Path) -> Path:
    script_path = out_dir / "submit_openai_batches.sh"
    content = """#!/usr/bin/env bash
set -euo pipefail

OPENAI_API_KEY="${OPENAI_API_KEY:-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}"

if [[ -z "$OPENAI_API_KEY" ]]; then
  echo "OPENAI_API_KEY is not set"
  exit 1
fi

OUT_DIR="${1:-%s}"
WINDOW="${2:-24h}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found"
  exit 1
fi

shopt -s nullglob
request_files=("$OUT_DIR"/openai_batch_requests_*.jsonl)
if [[ ${#request_files[@]} -eq 0 ]]; then
  echo "No openai_batch_requests_*.jsonl files found under $OUT_DIR"
  exit 1
fi

for request_file in "${request_files[@]}"; do
  base="$(basename "$request_file" .jsonl)"
  upload_json="$OUT_DIR/${base}.file.json"
  batch_json="$OUT_DIR/${base}.batch.json"

  echo "Uploading: $request_file"
  curl -sS https://api.openai.com/v1/files \\
    -H "Authorization: Bearer $OPENAI_API_KEY" \\
    -F purpose="batch" \\
    -F file="@${request_file}" > "$upload_json"

  file_id="$(jq -r '.id // empty' "$upload_json")"
  if [[ -z "$file_id" ]]; then
    echo "Failed to obtain file_id from $upload_json"
    cat "$upload_json"
    exit 1
  fi

  payload="$(jq -n \\
    --arg input_file_id "$file_id" \\
    --arg completion_window "$WINDOW" \\
    --arg request_file "$(basename "$request_file")" \\
    '{input_file_id:$input_file_id, endpoint:"/v1/chat/completions", completion_window:$completion_window, metadata:{job:"gold-fixture-adjudication", request_file:$request_file}}')"

  curl -sS https://api.openai.com/v1/batches \\
    -H "Authorization: Bearer $OPENAI_API_KEY" \\
    -H "Content-Type: application/json" \\
    -d "$payload" > "$batch_json"

  batch_id="$(jq -r '.id // empty' "$batch_json")"
  if [[ -z "$batch_id" ]]; then
    echo "Failed to obtain batch_id from $batch_json"
    cat "$batch_json"
    exit 1
  fi
  echo "Created batch: $batch_id for $(basename "$request_file")"
done
""" % str(out_dir)
    script_path.write_text(content, encoding="utf-8")
    return script_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build OpenAI Batch adjudication request files.")
    parser.add_argument("--packet", type=Path, required=True, help="Input packet/queue JSONL path.")
    parser.add_argument("--fixtures", type=Path, required=True, help="Fixture source JSONL path.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory for batch files.")
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT_FILE, help="System prompt template path.")
    parser.add_argument("--batch-size", type=int, default=50, help="Rows per batch request file.")
    parser.add_argument("--model", default="gpt-5", help="Model used for batch requests.")
    parser.add_argument("--max-completion-tokens", type=int, default=7000, help="max_completion_tokens sent to API.")
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Optional temperature. Omitted when not set.",
    )
    parser.add_argument("--min-text-chars", type=int, default=1, help="Skip rows with shorter raw_text.")
    parser.add_argument(
        "--max-text-chars",
        type=int,
        default=0,
        help="If >0, skip rows with raw_text length above this threshold.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")
    if args.max_completion_tokens <= 0:
        raise SystemExit("--max-completion-tokens must be > 0")
    if args.temperature is not None and args.temperature < 0:
        raise SystemExit("--temperature must be >= 0")
    if args.min_text_chars < 0:
        raise SystemExit("--min-text-chars must be >= 0")

    packet_rows = _load_jsonl(args.packet.resolve())
    fixture_rows = _load_jsonl(args.fixtures.resolve())
    prompt = args.prompt_file.resolve().read_text(encoding="utf-8").strip()
    by_id, by_source_key = _build_fixture_index(fixture_rows)

    prepared: list[PreparedRequest] = []
    skipped: list[dict[str, Any]] = []

    for row in packet_rows:
        queue_item_id = str(row.get("queue_item_id") or "").strip()
        if not queue_item_id:
            skipped.append(
                {
                    "queue_item_id": "",
                    "fixture_id": str(row.get("fixture_id") or ""),
                    "reason": "missing_queue_item_id",
                }
            )
            continue

        fixture = _resolve_fixture(row, by_id=by_id, by_source_key=by_source_key)
        if fixture is None:
            skipped.append(
                {
                    "queue_item_id": queue_item_id,
                    "fixture_id": str(row.get("fixture_id") or ""),
                    "reason": "fixture_not_found",
                }
            )
            continue

        user_payload, raw_text_len = _build_user_payload(row, fixture)
        if raw_text_len < args.min_text_chars:
            skipped.append(
                {
                    "queue_item_id": queue_item_id,
                    "fixture_id": str(fixture.get("fixture_id") or ""),
                    "reason": "text_too_short",
                    "raw_text_len": raw_text_len,
                }
            )
            continue
        if args.max_text_chars and raw_text_len > args.max_text_chars:
            skipped.append(
                {
                    "queue_item_id": queue_item_id,
                    "fixture_id": str(fixture.get("fixture_id") or ""),
                    "reason": "text_too_long",
                    "raw_text_len": raw_text_len,
                }
            )
            continue

        custom_id = f"adjudication:{queue_item_id}"
        request = _build_batch_request(
            custom_id=custom_id,
            model=args.model,
            system_prompt=prompt,
            user_payload=user_payload,
            max_completion_tokens=args.max_completion_tokens,
            temperature=args.temperature,
        )
        prepared.append(
            PreparedRequest(
                custom_id=custom_id,
                request=request,
                raw_text_len=raw_text_len,
                fixture_id=str(fixture.get("fixture_id") or ""),
            )
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)

    batch_files: list[dict[str, Any]] = []
    prepared_requests = [p.request for p in prepared]
    for idx in range(0, len(prepared_requests), args.batch_size):
        chunk = prepared_requests[idx : idx + args.batch_size]
        file_no = (idx // args.batch_size) + 1
        out_file = args.out_dir / f"openai_batch_requests_{file_no:03d}.jsonl"
        _write_jsonl(out_file, chunk)
        first = chunk[0]["custom_id"] if chunk else ""
        last = chunk[-1]["custom_id"] if chunk else ""
        batch_files.append(
            {
                "file": str(out_file),
                "row_count": len(chunk),
                "first_custom_id": first,
                "last_custom_id": last,
            }
        )

    skipped_path = args.out_dir / "openai_batch_skipped_rows.json"
    skipped_path.write_text(json.dumps(skipped, indent=2) + "\n", encoding="utf-8")

    submit_script = _write_submit_script(args.out_dir.resolve())

    lengths = [p.raw_text_len for p in prepared]
    length_summary = {}
    if lengths:
        sorted_lengths = sorted(lengths)
        n = len(sorted_lengths)
        length_summary = {
            "min": sorted_lengths[0],
            "p50": sorted_lengths[n // 2],
            "p90": sorted_lengths[int(0.9 * (n - 1))],
            "p95": sorted_lengths[int(0.95 * (n - 1))],
            "max": sorted_lengths[-1],
        }

    skipped_reason_counts = Counter(str(item.get("reason") or "") for item in skipped)
    manifest = {
        "schema_version": "openai-batch-adjudication-manifest-v1",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "packet_path": str(args.packet.resolve()),
        "fixtures_path": str(args.fixtures.resolve()),
        "prompt_file": str(args.prompt_file.resolve()),
        "model": args.model,
        "temperature": args.temperature,
        "batch_size": args.batch_size,
        "max_completion_tokens": args.max_completion_tokens,
        "min_text_chars": args.min_text_chars,
        "max_text_chars": args.max_text_chars if args.max_text_chars else None,
        "counts": {
            "packet_rows": len(packet_rows),
            "prepared_rows": len(prepared),
            "skipped_rows": len(skipped),
            "batch_files": len(batch_files),
        },
        "prepared_text_length_summary": length_summary,
        "skipped_reason_counts": dict(skipped_reason_counts),
        "batch_files": batch_files,
        "skipped_path": str(skipped_path),
        "submit_script": str(submit_script),
    }
    manifest_path = args.out_dir / "openai_batch_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "ok",
                "prepared_rows": len(prepared),
                "skipped_rows": len(skipped),
                "batch_files": len(batch_files),
                "manifest": str(manifest_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
