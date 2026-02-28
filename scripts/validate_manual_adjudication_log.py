#!/usr/bin/env python3
"""Validate manual adjudication log batches against protocol v1."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "manual-adjudication-log-v1"
REPORT_SCHEMA_VERSION = "manual-adjudication-validator-report-v1"
ALLOWED_DECISIONS = {"accepted", "review", "abstain"}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
IN_SCOPE_CLASSES = {
    "ambiguous_alpha_roman",
    "high_letter_continuation",
    "xref_vs_structural",
    "nonstruct_parent_chain",
}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_FIELDS = (
    "schema_version",
    "adjudication_id",
    "row_id",
    "queue_item_id",
    "fixture_id",
    "doc_id",
    "section_number",
    "edge_case_class",
    "witness_snippets",
    "candidate_interpretations",
    "decision",
    "decision_rationale",
    "confidence_level",
    "adjudicator_id",
    "adjudicated_at",
    "corpus_build_id",
    "section_text_sha256",
    "doc_text_sha256",
    "source_snapshot_id",
)


@dataclass(frozen=True, slots=True)
class ValidationError:
    reason_code: str
    row_index: int
    row_id: str
    field_path: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "row_index": self.row_index,
            "row_id": self.row_id,
            "field_path": self.field_path,
            "message": self.message,
        }


def _parse_iso_datetime(raw: str) -> datetime | None:
    value = raw.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: row must be a JSON object")
            rows.append(obj)
    return rows


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_hypothesis(
    *,
    candidate_interpretations: dict[str, Any],
    hypothesis_key: str,
    row_index: int,
    row_id: str,
    errors: list[ValidationError],
) -> None:
    path = f"candidate_interpretations.{hypothesis_key}"
    hypothesis = candidate_interpretations.get(hypothesis_key)
    if not isinstance(hypothesis, dict):
        errors.append(
            ValidationError(
                "E_CANDIDATE_MISSING_HYPOTHESIS",
                row_index,
                row_id,
                path,
                f"missing hypothesis '{hypothesis_key}' object",
            )
        )
        return

    interpretation = hypothesis.get("interpretation")
    survives = hypothesis.get("survives")
    reason = hypothesis.get("reason")
    if not _is_non_empty_string(interpretation):
        errors.append(
            ValidationError(
                "E_CANDIDATE_INTERPRETATION",
                row_index,
                row_id,
                f"{path}.interpretation",
                "interpretation must be a non-empty string",
            )
        )
    if not isinstance(survives, bool):
        errors.append(
            ValidationError(
                "E_CANDIDATE_SURVIVES",
                row_index,
                row_id,
                f"{path}.survives",
                "survives must be boolean",
            )
        )
    if not _is_non_empty_string(reason):
        errors.append(
            ValidationError(
                "E_CANDIDATE_REASON",
                row_index,
                row_id,
                f"{path}.reason",
                "reason must be a non-empty string",
            )
        )


def _validate_row(row: dict[str, Any], row_index: int, errors: list[ValidationError]) -> None:
    row_id = str(row.get("row_id") or "").strip()
    row_ref = row_id or f"row_{row_index}"

    for field in REQUIRED_FIELDS:
        if field not in row:
            errors.append(
                ValidationError(
                    "E_REQUIRED_FIELD",
                    row_index,
                    row_ref,
                    field,
                    "required field is missing",
                )
            )

    if str(row.get("schema_version") or "").strip() != SCHEMA_VERSION:
        errors.append(
            ValidationError(
                "E_SCHEMA_VERSION",
                row_index,
                row_ref,
                "schema_version",
                f"schema_version must be '{SCHEMA_VERSION}'",
            )
        )

    if not _is_non_empty_string(row.get("doc_id")):
        errors.append(
            ValidationError(
                "E_DOC_ID",
                row_index,
                row_ref,
                "doc_id",
                "doc_id must be a non-empty string",
            )
        )
    if not _is_non_empty_string(row.get("section_number")):
        errors.append(
            ValidationError(
                "E_SECTION_NUMBER",
                row_index,
                row_ref,
                "section_number",
                "section_number must be a non-empty string",
            )
        )

    edge_case_class = str(row.get("edge_case_class") or "").strip()
    if not edge_case_class:
        errors.append(
            ValidationError(
                "E_EDGE_CASE_CLASS",
                row_index,
                row_ref,
                "edge_case_class",
                "edge_case_class must be a non-empty string",
            )
        )

    witness = row.get("witness_snippets")
    if isinstance(witness, list):
        has_witness = any(_is_non_empty_string(item) for item in witness)
    else:
        has_witness = _is_non_empty_string(witness)
    if not has_witness:
        errors.append(
            ValidationError(
                "E_WITNESS",
                row_index,
                row_ref,
                "witness_snippets",
                "witness_snippets must include at least one non-empty snippet",
            )
        )

    candidate_interpretations = row.get("candidate_interpretations")
    if not isinstance(candidate_interpretations, dict):
        errors.append(
            ValidationError(
                "E_CANDIDATE_SHAPE",
                row_index,
                row_ref,
                "candidate_interpretations",
                "candidate_interpretations must be an object with A and B",
            )
        )
    else:
        _validate_hypothesis(
            candidate_interpretations=candidate_interpretations,
            hypothesis_key="A",
            row_index=row_index,
            row_id=row_ref,
            errors=errors,
        )
        _validate_hypothesis(
            candidate_interpretations=candidate_interpretations,
            hypothesis_key="B",
            row_index=row_index,
            row_id=row_ref,
            errors=errors,
        )

    decision = str(row.get("decision") or "").strip()
    if decision not in ALLOWED_DECISIONS:
        errors.append(
            ValidationError(
                "E_DECISION",
                row_index,
                row_ref,
                "decision",
                f"decision must be one of {sorted(ALLOWED_DECISIONS)}",
            )
        )

    confidence = str(row.get("confidence_level") or "").strip()
    if confidence not in ALLOWED_CONFIDENCE:
        errors.append(
            ValidationError(
                "E_CONFIDENCE",
                row_index,
                row_ref,
                "confidence_level",
                f"confidence_level must be one of {sorted(ALLOWED_CONFIDENCE)}",
            )
        )

    decision_rationale = str(row.get("decision_rationale") or "").strip()
    if len(decision_rationale) < 20:
        errors.append(
            ValidationError(
                "E_DECISION_RATIONALE",
                row_index,
                row_ref,
                "decision_rationale",
                "decision_rationale must be non-trivial prose (>=20 chars)",
            )
        )

    adjudicated_at = str(row.get("adjudicated_at") or "").strip()
    if _parse_iso_datetime(adjudicated_at) is None:
        errors.append(
            ValidationError(
                "E_ADJUDICATED_AT",
                row_index,
                row_ref,
                "adjudicated_at",
                "adjudicated_at must be ISO-8601 datetime",
            )
        )

    corpus_build_id = str(row.get("corpus_build_id") or "").strip()
    section_hash = str(row.get("section_text_sha256") or "").strip()
    doc_hash = str(row.get("doc_text_sha256") or "").strip()
    source_snapshot_id = str(row.get("source_snapshot_id") or "").strip()

    if not _is_non_empty_string(corpus_build_id):
        errors.append(
            ValidationError(
                "E_CORPUS_BUILD_ID",
                row_index,
                row_ref,
                "corpus_build_id",
                "corpus_build_id must be a non-empty string",
            )
        )

    if not HEX64_RE.fullmatch(section_hash):
        errors.append(
            ValidationError(
                "E_SECTION_HASH",
                row_index,
                row_ref,
                "section_text_sha256",
                "section_text_sha256 must be lowercase 64-char hex",
            )
        )

    if not HEX64_RE.fullmatch(doc_hash):
        errors.append(
            ValidationError(
                "E_DOC_HASH",
                row_index,
                row_ref,
                "doc_text_sha256",
                "doc_text_sha256 must be lowercase 64-char hex",
            )
        )

    expected_snapshot = f"{corpus_build_id}:{section_hash}"
    if source_snapshot_id != expected_snapshot:
        errors.append(
            ValidationError(
                "E_SOURCE_SNAPSHOT_ID",
                row_index,
                row_ref,
                "source_snapshot_id",
                "source_snapshot_id must equal '{corpus_build_id}:{section_text_sha256}'",
            )
        )

    if not _is_non_empty_string(row.get("adjudication_id")):
        errors.append(
            ValidationError(
                "E_ADJUDICATION_ID",
                row_index,
                row_ref,
                "adjudication_id",
                "adjudication_id must be a non-empty string",
            )
        )
    if not _is_non_empty_string(row.get("queue_item_id")):
        errors.append(
            ValidationError(
                "E_QUEUE_ITEM_ID",
                row_index,
                row_ref,
                "queue_item_id",
                "queue_item_id must be a non-empty string",
            )
        )
    if not _is_non_empty_string(row.get("fixture_id")):
        errors.append(
            ValidationError(
                "E_FIXTURE_ID",
                row_index,
                row_ref,
                "fixture_id",
                "fixture_id must be a non-empty string",
            )
        )
    if not _is_non_empty_string(row.get("adjudicator_id")):
        errors.append(
            ValidationError(
                "E_ADJUDICATOR_ID",
                row_index,
                row_ref,
                "adjudicator_id",
                "adjudicator_id must be a non-empty string",
            )
        )


def _enforce_gl1_thresholds(rows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    total = len(rows)
    if total < 800:
        failures.append(f"GL1 total labels below threshold: have={total} need>=800")

    counts = Counter(str(row.get("edge_case_class") or "").strip() for row in rows)
    for cls in sorted(IN_SCOPE_CLASSES):
        count = int(counts.get(cls, 0))
        if count < 150:
            failures.append(f"GL1 per-class minimum failed for {cls}: have={count} need>=150")
        if count > 250:
            failures.append(f"GL1 class balance max exceeded for {cls}: have={count} need<=250")
    return failures


def _build_report(
    *,
    log_path: Path,
    rows: list[dict[str, Any]],
    errors: list[ValidationError],
    gl1_failures: list[str],
) -> dict[str, Any]:
    status = "fail" if errors or gl1_failures else "pass"

    in_scope_counts = Counter(str(r.get("edge_case_class") or "").strip() for r in rows)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "log_path": str(log_path),
        "row_count": len(rows),
        "summary": {
            "error_count": len(errors),
            "gl1_failure_count": len(gl1_failures),
        },
        "class_counts": {
            cls: int(in_scope_counts.get(cls, 0))
            for cls in sorted(IN_SCOPE_CLASSES)
        },
        "errors": [err.to_dict() for err in errors],
        "gl1_failures": gl1_failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate manual adjudication log batch.")
    parser.add_argument("--log", type=Path, required=True, help="Path to adjudication JSONL log")
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout")
    parser.add_argument("--json-out", type=Path, help="Write JSON report to this path")
    parser.add_argument(
        "--enforce-gl1-thresholds",
        action="store_true",
        help="Enforce GL1 total/per-class thresholds",
    )
    args = parser.parse_args()

    log_path = args.log.resolve()
    if not log_path.exists():
        print(json.dumps({"status": "fail", "error": f"log not found: {log_path}"}))
        return 3

    try:
        rows = _load_jsonl(log_path)
    except ValueError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}))
        return 3

    errors: list[ValidationError] = []
    row_ids: set[str] = set()
    adjudication_ids: set[str] = set()
    rationale_to_row_ids: dict[str, list[str]] = {}
    for row_index, row in enumerate(rows, start=1):
        _validate_row(row, row_index, errors)
        row_id = str(row.get("row_id") or "").strip()
        if row_id:
            if row_id in row_ids:
                errors.append(
                    ValidationError(
                        "E_DUPLICATE_ROW_ID",
                        row_index,
                        row_id,
                        "row_id",
                        "row_id must be unique within log",
                    )
                )
            row_ids.add(row_id)
        adjudication_id = str(row.get("adjudication_id") or "").strip()
        if adjudication_id:
            if adjudication_id in adjudication_ids:
                errors.append(
                    ValidationError(
                        "E_DUPLICATE_ADJUDICATION_ID",
                        row_index,
                        row_id or f"row_{row_index}",
                        "adjudication_id",
                        "adjudication_id must be unique within log",
                    )
                )
            adjudication_ids.add(adjudication_id)

        rationale = str(row.get("decision_rationale") or "").strip()
        if rationale:
            rationale_to_row_ids.setdefault(rationale, []).append(row_id or f"row_{row_index}")

    for _rationale, rationale_row_ids in rationale_to_row_ids.items():
        if len(rationale_row_ids) <= 1:
            continue
        for duplicate_row_id in rationale_row_ids:
            errors.append(
                ValidationError(
                    "E_DUPLICATE_DECISION_RATIONALE",
                    0,
                    duplicate_row_id,
                    "decision_rationale",
                    "decision_rationale must be unique within batch (exact duplicate found)",
                )
            )

    decisions = [str(row.get("decision") or "").strip() for row in rows if row.get("decision")]
    if len(rows) >= 10 and decisions:
        unique_decisions = {d for d in decisions if d}
        if unique_decisions == {"review"}:
            errors.append(
                ValidationError(
                    "E_ALL_REVIEW_DECISIONS",
                    0,
                    "",
                    "decision",
                    "batch-level collapse: all decisions are 'review'; "
                    "training utility is insufficient",
                )
            )

    gl1_failures: list[str] = []
    if args.enforce_gl1_thresholds:
        gl1_failures = _enforce_gl1_thresholds(rows)

    report = _build_report(log_path=log_path, rows=rows, errors=errors, gl1_failures=gl1_failures)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"manual-adjudication-log validation: status={report['status']} "
            f"rows={report['row_count']} errors={report['summary']['error_count']} "
            f"gl1_failures={report['summary']['gl1_failure_count']}"
        )

    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
