#!/usr/bin/env python3
"""Validate daily run bundles for hybrid parser/ML execution."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_DAY_ID_RE = re.compile(r"^day([1-9]|1[0-9]|2[0-2])$")
ALLOWED_BLOCKER_STATUS = {"open", "re-attributed", "closed"}
ALLOWED_BLOCKING_SCOPE = {"day_close", "launch"}
ALLOWED_REDTEAM_STATUS = {
    "not_started",
    "blocked",
    "ready",
    "in_review",
    "complete",
}
ALLOWED_REDTEAM_VERDICTS = {"pass", "partial_pass", "fail"}

DEFAULT_MANIFEST_REQUIRED_KEYS = (
    "git",
    "parser",
    "inputs",
    "command_exit_codes",
    "output_artifacts",
)
DEFAULT_CANONICAL_PRIMARY_OUTPUT_KEYS = (
    "validate_report",
    "replay_report",
    "clause_guardrail_report",
    "parent_guardrail_report",
    "parser_v1_tests_log",
)
DEFAULT_REASONING_REQUIRED_FIELDS = (
    "row_id",
    "witness",
    "hypothesis_A",
    "hypothesis_B",
    "why_A_survives",
    "why_B_survives",
    "final_decision",
    "confidence",
)
DEFAULT_ADJ_BATCH_GLOBS = (
    "**/*manual_adjudication_batch*.jsonl",
    "**/*adjudication_batch*.jsonl",
)
DEFAULT_ADJ_LINEAGE_ATTESTATION_PREFIX = "MANUAL_ADJUDICATION_ATTESTATION"
DEFAULT_ADJ_LINEAGE_EVENT_PREFIX = "MANUAL_ADJ_LINEAGE"
DEFAULT_ADJ_QUEUE_UPDATE_GLOBS = (
    "**/*queue*_updates*.jsonl",
    "**/*adjudication_queue_delta*.jsonl",
)
DEFAULT_MANUAL_ONLY_PROTECTED_PATH_GLOBS = (
    "**/*manual_adjudication_batch*.jsonl",
    "**/*manual_reasoning*.jsonl",
    "**/*queue*_updates*.jsonl",
    "**/*adjudication_queue_delta*.jsonl",
)
DEFAULT_MANUAL_ONLY_ALLOWED_LINE_PREFIXES = (
    DEFAULT_ADJ_LINEAGE_EVENT_PREFIX,
    DEFAULT_ADJ_LINEAGE_ATTESTATION_PREFIX,
    "MANUAL_REASONING_ATTESTATION",
    "QUEUE_LINKAGE_ATTESTATION",
)
DEFAULT_MANUAL_ONLY_ALLOWED_READONLY_PATTERNS = (
    r"^python3?\s+scripts/validate_manual_adjudication_log\.py\b",
    r"^python3?\s+scripts/build_reaudit_sample\.py\b",
    r"^python3?\s+scripts/filter_training_eligible_adjudication_rows\.py\b",
    r"^python3?\s+scripts/validate_day_bundle\.py\b",
)
DEFAULT_REDTEAM_ARTIFACT_GLOBS = (
    "**/red_team/adversarial_subagent_review*.json",
    "**/red_team_adversarial_subagent_review*.json",
    "**/red_team_review*.json",
)
DEFAULT_REDTEAM_REQUIRED_STATUSES = ("in_review", "complete")
DEFAULT_REDTEAM_REQUIRED_FIELDS = (
    "schema_version",
    "day_id",
    "review_mode",
    "subagent_id",
    "adversarial_findings",
    "verdict",
    "completed_at",
)

CHECK_SEVERITY: dict[str, str] = {
    "VAL-FILE-001": "critical",
    "VAL-JSON-001": "critical",
    "VAL-MANIFEST-001": "critical",
    "VAL-INDEX-001": "critical",
    "VAL-INDEX-002": "critical",
    "VAL-HASH-001": "critical",
    "VAL-EXIT-001": "critical",
    "VAL-GATE-001": "critical",
    "VAL-BLOCKER-001": "critical",
    "VAL-BLOCKER-002": "critical",
    "VAL-REDTEAM-001": "critical",
    "VAL-REDTEAM-002": "critical",
    "VAL-REDTEAM-003": "high",
    "VAL-GOV-001": "high",
    "VAL-CANON-001": "critical",
    "VAL-CANON-002": "critical",
    "VAL-CANON-003": "critical",
    "VAL-CANON-004": "high",
    "VAL-CONSIST-001": "high",
    "VAL-TIME-001": "high",
    "VAL-PROV-001": "high",
    "VAL-PROV-002": "high",
    "VAL-GL0-PARENT-001": "high",
    "VAL-ADJ-REASON-001": "critical",
    "VAL-ADJ-REASON-002": "critical",
    "VAL-ADJ-REASON-003": "critical",
    "VAL-ADJ-QUEUE-001": "critical",
    "VAL-ADJ-SPLIT-001": "critical",
    "VAL-ADJ-SYNTH-001": "critical",
    "VAL-ADJ-QUALITY-001": "medium",
    "VAL-ADJ-EXPORT-001": "critical",
    "VAL-MIG-001": "critical",
    "VAL-FREEZE-001": "high",
}


class InputError(ValueError):
    """Raised when CLI/profile input is invalid."""


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    artifact_id: str
    paths: tuple[str, ...]
    kind: str
    when: str
    generated: bool


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    spec: ArtifactSpec
    path: Path | None
    relative_path: str | None


@dataclass(frozen=True, slots=True)
class CheckResult:
    check_id: str
    severity: str
    status: str
    message: str
    artifact_path: str | None = None
    expected: Any = None
    actual: Any = None


@dataclass(frozen=True, slots=True)
class ReasoningCoverage:
    batch_path: str
    reasoning_path: str
    missing_row_ids: list[str]
    extra_row_ids: list[str]


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InputError(f"Expected JSON object in {path}")
    return payload


def _load_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise InputError(f"Invalid JSON in {path}:{line_no}: {exc}") from exc
            if not isinstance(obj, dict):
                raise InputError(f"Expected JSON object in {path}:{line_no}")
            rows.append(obj)
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if re.fullmatch(r"[+-]?\d+", raw):
            try:
                return int(raw)
            except ValueError:
                return None
    return None


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _resolve_path(path_str: str, run_dir: Path, repo_root: Path) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    in_run = (run_dir / p).resolve()
    if in_run.exists():
        return in_run
    return (repo_root / p).resolve()


def _load_profile(path: Path) -> dict[str, Any]:
    profile = _load_json(path)
    if str(profile.get("schema_version") or "").strip() != "day-bundle-validator-profile-v1":
        raise InputError("Profile schema_version must be day-bundle-validator-profile-v1")
    if not isinstance(profile.get("required_artifacts"), list):
        raise InputError("Profile must include required_artifacts[]")
    if not isinstance(profile.get("required_checks"), list):
        raise InputError("Profile must include required_checks[]")
    return profile


def _build_artifact_specs(profile: dict[str, Any]) -> list[ArtifactSpec]:
    specs: list[ArtifactSpec] = []
    for idx, raw in enumerate(profile.get("required_artifacts", []), start=1):
        if not isinstance(raw, dict):
            raise InputError(f"required_artifacts[{idx}] must be an object")
        artifact_id = str(raw.get("id") or "").strip()
        if not artifact_id:
            raise InputError(f"required_artifacts[{idx}] missing id")
        raw_paths = raw.get("paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            raise InputError(f"required_artifacts[{idx}] must include non-empty paths[]")
        paths = tuple(str(x).strip() for x in raw_paths if str(x).strip())
        if not paths:
            raise InputError(f"required_artifacts[{idx}] has empty paths[] entries")
        specs.append(
            ArtifactSpec(
                artifact_id=artifact_id,
                paths=paths,
                kind=str(raw.get("kind") or "json").strip(),
                when=str(raw.get("when") or "always").strip(),
                generated=bool(raw.get("generated", False)),
            )
        )
    return specs


def _resolve_artifacts(
    *,
    specs: list[ArtifactSpec],
    run_dir: Path,
    repo_root: Path,
    json_out: Path,
    workspace_dirty: bool,
) -> tuple[dict[str, ResolvedArtifact], list[str], list[str]]:
    resolved: dict[str, ResolvedArtifact] = {}
    missing: list[str] = []
    generated_errors: list[str] = []

    for spec in specs:
        if spec.when == "dirty" and not workspace_dirty:
            resolved[spec.artifact_id] = ResolvedArtifact(spec, None, None)
            continue

        if spec.generated:
            expected_paths = {(run_dir / rel).resolve() for rel in spec.paths}
            if json_out.resolve() not in expected_paths:
                expected_path_str = sorted(map(str, expected_paths))
                generated_errors.append(
                    f"{spec.artifact_id}: --json-out must equal one of "
                    f"{expected_path_str}",
                )
            rel_path = None
            try:
                rel_path = str(json_out.resolve().relative_to(run_dir.resolve()))
            except ValueError:
                rel_path = str(json_out.resolve())
            resolved[spec.artifact_id] = ResolvedArtifact(spec, json_out.resolve(), rel_path)
            continue

        chosen: Path | None = None
        chosen_rel: str | None = None
        for rel in spec.paths:
            p = (run_dir / rel).resolve()
            if p.exists():
                chosen, chosen_rel = p, rel
                break
        if chosen is None:
            for rel in spec.paths:
                p = _resolve_path(rel, run_dir, repo_root)
                if p.exists():
                    chosen, chosen_rel = p, rel
                    break
        if chosen is None:
            missing.append(f"{spec.artifact_id}: any of {list(spec.paths)}")
        resolved[spec.artifact_id] = ResolvedArtifact(spec, chosen, chosen_rel)
    return resolved, missing, generated_errors


def _collect_hash_pairs(payload: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    pairs: list[tuple[str, str, str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.endswith("_sha256"):
                    base = key[:-7]
                    path_key = f"{base}_path"
                    path_val = node.get(path_key)
                    if isinstance(path_val, str) and path_val.strip():
                        pairs.append((path_key, key, path_val.strip(), str(value).strip()))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return pairs


def _check_result(
    *,
    check_id: str,
    ok: bool,
    message_ok: str,
    message_fail: str,
    artifact_path: str | None = None,
    expected: Any = None,
    actual: Any = None,
    warn_only_ids: set[str],
    allow_warn_only: bool,
) -> CheckResult:
    severity = CHECK_SEVERITY[check_id]
    if ok:
        return CheckResult(
            check_id=check_id,
            severity=severity,
            status="pass",
            message=message_ok,
            artifact_path=artifact_path,
            expected=expected,
            actual=actual,
        )
    demote = check_id in warn_only_ids or (
        allow_warn_only and severity in {"high", "medium", "low"}
    )
    return CheckResult(
        check_id=check_id,
        severity=severity,
        status="warn" if demote else "fail",
        message=message_fail,
        artifact_path=artifact_path,
        expected=expected,
        actual=actual,
    )


def _profile_expected_days(profile: dict[str, Any]) -> set[str]:
    raw = profile.get("applies_to_days", [])
    days = {str(x).strip() for x in raw if str(x).strip()} if isinstance(raw, list) else set()
    return days


def _extract_markdown_reasoning(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        m_header = re.match(r"^\s*###\s*row_id:\s*(\S+)\s*$", line)
        if m_header:
            if current is not None:
                rows.append(current)
            current = {"row_id": m_header.group(1).strip()}
            continue
        m_field = re.match(r"^\s*-\s*([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$", line)
        if m_field and current is not None:
            current[m_field.group(1)] = m_field.group(2)
    if current is not None:
        rows.append(current)
    return rows


def _batch_id_from_stem(stem: str) -> str:
    for prefix in (
        "manual_adjudication_batch_",
        "adjudication_batch_",
        "manual_adjudication_",
        "adjudication_",
    ):
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


def _find_reasoning_file(run_dir: Path, batch_id: str) -> tuple[Path | None, list[str]]:
    candidates: list[Path] = []
    for ext in (".jsonl", ".md"):
        pattern = f"**/manual_reasoning_{batch_id}{ext}"
        candidates.extend(run_dir.glob(pattern))
    unique_sorted = sorted({p.resolve() for p in candidates})
    if not unique_sorted:
        return None, []
    if len(unique_sorted) > 1:
        return None, [str(p) for p in unique_sorted]
    return unique_sorted[0], []


def _run_manual_reasoning_checks(
    *,
    run_dir: Path,
    profile: dict[str, Any],
) -> tuple[list[str], list[str], list[ReasoningCoverage], list[dict[str, Any]]]:
    adj_cfg = profile.get("adjudication", {})
    if not isinstance(adj_cfg, dict):
        adj_cfg = {}

    batch_globs = adj_cfg.get("batch_globs", list(DEFAULT_ADJ_BATCH_GLOBS))
    if not isinstance(batch_globs, list):
        batch_globs = list(DEFAULT_ADJ_BATCH_GLOBS)
    batch_exclude_globs = adj_cfg.get("batch_exclude_globs", [])
    if not isinstance(batch_exclude_globs, list):
        batch_exclude_globs = []
    required_fields = adj_cfg.get(
        "reasoning_required_fields",
        list(DEFAULT_REASONING_REQUIRED_FIELDS),
    )
    if not isinstance(required_fields, list):
        required_fields = list(DEFAULT_REASONING_REQUIRED_FIELDS)
    required_fields_norm = [str(x).strip() for x in required_fields if str(x).strip()]
    min_chars_cfg = adj_cfg.get("reasoning_min_chars", {})
    if not isinstance(min_chars_cfg, dict):
        min_chars_cfg = {}
    reasoning_min_chars: dict[str, int] = {}
    for field, raw_min in min_chars_cfg.items():
        key = str(field).strip()
        if not key:
            continue
        min_len = _coerce_int(raw_min)
        if min_len is None:
            continue
        reasoning_min_chars[key] = max(0, min_len)

    batch_files_set: set[Path] = set()
    for glob_pat in batch_globs:
        if not str(glob_pat).strip():
            continue
        for p in run_dir.glob(str(glob_pat)):
            if p.is_file():
                rel = str(p.relative_to(run_dir))
                if any(
                    fnmatch.fnmatch(rel, str(ex_pat).strip())
                    for ex_pat in batch_exclude_globs
                    if str(ex_pat).strip()
                ):
                    continue
                batch_files_set.add(p.resolve())
    batch_files = sorted(batch_files_set)

    missing_reasoning: list[str] = []
    field_failures: list[str] = []
    coverage_failures: list[ReasoningCoverage] = []
    field_failure_details: list[dict[str, Any]] = []

    for batch_file in batch_files:
        batch_rows = _load_jsonl_objects(batch_file)
        batch_row_ids: list[str] = []
        batch_decisions: dict[str, str] = {}
        for idx, row in enumerate(batch_rows, start=1):
            row_id = str(row.get("row_id") or "").strip()
            if not row_id:
                row_id = f"row_{idx}"
            batch_row_ids.append(row_id)
            decision = str(row.get("decision") or "").strip().lower()
            if decision:
                batch_decisions[row_id] = decision

        batch_id = _batch_id_from_stem(batch_file.stem)
        reasoning_file, ambiguous = _find_reasoning_file(run_dir, batch_id)
        if ambiguous:
            missing_reasoning.append(
                f"{batch_file}: multiple reasoning files found {ambiguous}",
            )
            continue
        if reasoning_file is None:
            missing_reasoning.append(
                f"{batch_file}: missing manual_reasoning_{batch_id}.jsonl|.md",
            )
            continue

        if reasoning_file.suffix.lower() == ".jsonl":
            reasoning_rows = _load_jsonl_objects(reasoning_file)
        elif reasoning_file.suffix.lower() == ".md":
            reasoning_rows = _extract_markdown_reasoning(reasoning_file)
        else:
            missing_reasoning.append(
                f"{batch_file}: unsupported reasoning extension {reasoning_file.suffix}",
            )
            continue

        reasoning_row_ids: list[str] = []
        for ridx, row in enumerate(reasoning_rows, start=1):
            row_id = str(row.get("row_id") or "").strip()
            if not row_id:
                field_failures.append(
                    f"{reasoning_file}: row {ridx} missing row_id",
                )
                field_failure_details.append(
                    {
                        "reasoning_file": str(reasoning_file),
                        "row_index": ridx,
                        "row_id": "",
                        "field": "row_id",
                    }
                )
                continue
            reasoning_row_ids.append(row_id)
            for field in required_fields_norm:
                val = row.get(field)
                if not isinstance(val, str) or not val.strip():
                    field_failures.append(
                        f"{reasoning_file}: row_id={row_id} missing field {field}",
                    )
                    field_failure_details.append(
                        {
                            "reasoning_file": str(reasoning_file),
                            "row_index": ridx,
                            "row_id": row_id,
                            "field": field,
                        }
                    )
                    continue
                min_chars = reasoning_min_chars.get(field)
                if min_chars is not None and len(val.strip()) < min_chars:
                    field_failures.append(
                        f"{reasoning_file}: row_id={row_id} field {field} "
                        f"too short ({len(val.strip())} < {min_chars})",
                    )
                    field_failure_details.append(
                        {
                            "reasoning_file": str(reasoning_file),
                            "row_index": ridx,
                            "row_id": row_id,
                            "field": field,
                            "min_chars": min_chars,
                            "actual_length": len(val.strip()),
                        }
                    )
            reasoning_decision = str(row.get("final_decision") or "").strip().lower()
            adjudication_decision = batch_decisions.get(row_id, "")
            if (
                reasoning_decision
                and adjudication_decision
                and reasoning_decision != adjudication_decision
            ):
                field_failures.append(
                    f"{reasoning_file}: row_id={row_id} final_decision "
                    f"'{reasoning_decision}' != adjudication decision '{adjudication_decision}'",
                )
                field_failure_details.append(
                    {
                        "reasoning_file": str(reasoning_file),
                        "row_index": ridx,
                        "row_id": row_id,
                        "field": "final_decision",
                        "expected": adjudication_decision,
                        "actual": reasoning_decision,
                    }
                )

        missing = sorted(set(batch_row_ids) - set(reasoning_row_ids))
        extra = sorted(set(reasoning_row_ids) - set(batch_row_ids))
        if missing or extra:
            coverage_failures.append(
                ReasoningCoverage(
                    batch_path=str(batch_file),
                    reasoning_path=str(reasoning_file),
                    missing_row_ids=missing,
                    extra_row_ids=extra,
                )
            )

    return missing_reasoning, field_failures, coverage_failures, field_failure_details


def _collect_manual_only_protected_paths(
    *,
    run_dir: Path,
    profile: dict[str, Any],
) -> set[str]:
    adj_cfg = profile.get("adjudication", {})
    if not isinstance(adj_cfg, dict):
        adj_cfg = {}
    manual_cfg = adj_cfg.get("manual_only", {})
    if not isinstance(manual_cfg, dict):
        manual_cfg = {}
    raw_globs = manual_cfg.get(
        "protected_path_globs",
        list(DEFAULT_MANUAL_ONLY_PROTECTED_PATH_GLOBS),
    )
    if not isinstance(raw_globs, list):
        raw_globs = list(DEFAULT_MANUAL_ONLY_PROTECTED_PATH_GLOBS)
    paths: set[str] = set()
    for item in raw_globs:
        pattern = str(item).strip()
        if not pattern:
            continue
        for candidate in run_dir.glob(pattern):
            if candidate.is_file():
                paths.add(candidate.relative_to(run_dir).as_posix())
    return paths


def _detect_synthetic_generation(
    *,
    command_log_path: Path,
    run_dir: Path,
    profile: dict[str, Any],
) -> list[str]:
    suspicious_lines: list[str] = []
    lines = [
        raw_line.strip()
        for raw_line in command_log_path.read_text(encoding="utf-8").splitlines()
        if raw_line.strip() and not raw_line.strip().startswith("#")
    ]
    write_patterns = (
        re.compile(
            r"(?i)\b(cat|echo|printf|python|python3|node|perl|ruby|awk|jq)\b.*(?:>|>>)\s*\S*adjudication\S*\.jsonl\b"
        ),
        re.compile(r"(?i)\btee\b\s+\S*adjudication\S*\.jsonl\b"),
        re.compile(
            r"(?i)\b(cat|python|python3|node|perl|ruby)\b.*<<.*adjudication.*\.jsonl"
        ),
    )
    for line in lines:
        for pat in write_patterns:
            if pat.search(line):
                suspicious_lines.append(line)
                break

    adj_cfg = profile.get("adjudication", {})
    if not isinstance(adj_cfg, dict):
        adj_cfg = {}
    manual_cfg = adj_cfg.get("manual_only", {})
    if not isinstance(manual_cfg, dict):
        manual_cfg = {}
    if not _is_truthy(manual_cfg.get("require", True)):
        return suspicious_lines

    protected_paths = _collect_manual_only_protected_paths(run_dir=run_dir, profile=profile)
    if not protected_paths:
        return suspicious_lines
    protected_tokens = set(protected_paths)
    protected_tokens.update(Path(path).name for path in protected_paths)

    raw_prefixes = manual_cfg.get(
        "allowed_line_prefixes",
        list(DEFAULT_MANUAL_ONLY_ALLOWED_LINE_PREFIXES),
    )
    if not isinstance(raw_prefixes, list):
        raw_prefixes = list(DEFAULT_MANUAL_ONLY_ALLOWED_LINE_PREFIXES)
    allowed_prefixes = tuple(str(item).strip() for item in raw_prefixes if str(item).strip())

    raw_allow_patterns = manual_cfg.get(
        "allowed_readonly_command_patterns",
        list(DEFAULT_MANUAL_ONLY_ALLOWED_READONLY_PATTERNS),
    )
    if not isinstance(raw_allow_patterns, list):
        raw_allow_patterns = list(DEFAULT_MANUAL_ONLY_ALLOWED_READONLY_PATTERNS)
    allow_patterns: list[re.Pattern[str]] = []
    for raw in raw_allow_patterns:
        pattern = str(raw).strip()
        if not pattern:
            continue
        try:
            allow_patterns.append(re.compile(pattern))
        except re.error:
            suspicious_lines.append(
                f"manual_only invalid allowlist regex pattern: {pattern}",
            )

    mutator_command_pattern = re.compile(
        r"(?i)\b(python|python3|node|perl|ruby|jq|awk|sed|cp|mv|rsync|tee|cat|echo|printf)\b"
    )
    for line in lines:
        if line in suspicious_lines:
            continue
        if allowed_prefixes and line.startswith(allowed_prefixes):
            continue
        if any(pattern.search(line) for pattern in allow_patterns):
            continue
        if not mutator_command_pattern.search(line):
            continue
        if any(token and token in line for token in protected_tokens):
            suspicious_lines.append(f"manual_only protected artifact scripting: {line}")

    return suspicious_lines


def _collect_adjudication_batch_files(
    *,
    run_dir: Path,
    profile: dict[str, Any],
) -> list[Path]:
    adj_cfg = profile.get("adjudication", {})
    if not isinstance(adj_cfg, dict):
        adj_cfg = {}
    batch_globs = adj_cfg.get("batch_globs", list(DEFAULT_ADJ_BATCH_GLOBS))
    if not isinstance(batch_globs, list):
        batch_globs = list(DEFAULT_ADJ_BATCH_GLOBS)
    batch_exclude_globs = adj_cfg.get("batch_exclude_globs", [])
    if not isinstance(batch_exclude_globs, list):
        batch_exclude_globs = []
    found: set[Path] = set()
    for pat in batch_globs:
        pattern = str(pat).strip()
        if not pattern:
            continue
        for candidate in run_dir.glob(pattern):
            if candidate.is_file():
                rel = str(candidate.relative_to(run_dir))
                if any(
                    fnmatch.fnmatch(rel, str(ex_pat).strip())
                    for ex_pat in batch_exclude_globs
                    if str(ex_pat).strip()
                ):
                    continue
                found.add(candidate.resolve())
    return sorted(found)


def _validate_adjudication_lineage_attestation(
    *,
    command_log_path: Path,
    run_dir: Path,
    repo_root: Path,
    profile: dict[str, Any],
) -> list[str]:
    uniqueness_failures = _validate_attestation_uniqueness(run_dir)
    batch_files = _collect_adjudication_batch_files(run_dir=run_dir, profile=profile)
    if not batch_files:
        return uniqueness_failures

    adj_cfg = profile.get("adjudication", {})
    if not isinstance(adj_cfg, dict):
        adj_cfg = {}
    prefix = str(
        adj_cfg.get(
            "lineage_attestation_prefix",
            DEFAULT_ADJ_LINEAGE_ATTESTATION_PREFIX,
        )
        or ""
    ).strip()
    if not prefix:
        prefix = DEFAULT_ADJ_LINEAGE_ATTESTATION_PREFIX
    lineage_event_prefix = str(
        adj_cfg.get(
            "lineage_event_prefix",
            DEFAULT_ADJ_LINEAGE_EVENT_PREFIX,
        )
        or ""
    ).strip()
    if not lineage_event_prefix:
        lineage_event_prefix = DEFAULT_ADJ_LINEAGE_EVENT_PREFIX

    lines = [
        line.strip()
        for line in command_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    failures: list[str] = []
    if not any(prefix in line for line in lines):
        failures.append(
            f"missing adjudication lineage attestation prefix '{prefix}' in command_log",
        )
        return [*uniqueness_failures, *failures]

    for batch_file in batch_files:
        batch_id = _batch_id_from_stem(batch_file.stem)
        if any(
            prefix in line and (f"batch_id={batch_id}" in line or batch_id in line)
            for line in lines
        ):
            continue
        failures.append(
            f"missing lineage attestation for batch_id={batch_id}",
        )
    for batch_file in batch_files:
        batch_id = _batch_id_from_stem(batch_file.stem)
        attestation_file, ambiguous = _find_lineage_attestation_file(
            run_dir=run_dir,
            batch_id=batch_id,
        )
        if ambiguous:
            failures.append(
                f"{batch_file}: multiple lineage attestation files found {ambiguous}",
            )
            continue
        if attestation_file is None:
            failures.append(
                f"{batch_file}: missing manual_adjudication_attestation_{batch_id}.json",
            )
            continue
        try:
            payload = _load_json(attestation_file)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{attestation_file}: invalid JSON ({exc})")
            continue
        failures.extend(
            _validate_lineage_attestation_payload(
                payload=payload,
                attestation_file=attestation_file,
                batch_id=batch_id,
                batch_file=batch_file,
                command_log_path=command_log_path,
                run_dir=run_dir,
                repo_root=repo_root,
                command_lines=lines,
                lineage_event_prefix=lineage_event_prefix,
            )
        )
    return [*uniqueness_failures, *failures]


def _find_lineage_attestation_file(
    *,
    run_dir: Path,
    batch_id: str,
) -> tuple[Path | None, list[str]]:
    candidates: list[Path] = []
    for pattern in (
        f"**/manual_adjudication_attestation_{batch_id}.json",
        f"**/adjudication_attestation_{batch_id}.json",
    ):
        candidates.extend(run_dir.glob(pattern))
    unique = sorted({path.resolve() for path in candidates})
    if not unique:
        return None, []
    if len(unique) > 1:
        return None, [str(path) for path in unique]
    return unique[0], []


def _collect_attestation_files(run_dir: Path) -> list[Path]:
    candidates: set[Path] = set()
    for pattern in (
        "**/manual_adjudication_attestation*.json",
        "**/adjudication_attestation*.json",
    ):
        for path in run_dir.glob(pattern):
            if path.is_file():
                candidates.add(path.resolve())
    return sorted(candidates)


def _validate_attestation_uniqueness(run_dir: Path) -> list[str]:
    failures: list[str] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for path in _collect_attestation_files(run_dir):
        try:
            payload = _load_json(path)
        except Exception:  # noqa: BLE001
            continue
        if str(payload.get("schema_version") or "").strip() != "manual-adjudication-attestation-v1":
            continue
        batch_id = str(payload.get("batch_id") or "").strip()
        batch_path = str(payload.get("batch_path") or "").strip()
        if not batch_id or not batch_path:
            continue
        status = str(payload.get("status") or "active").strip().lower()
        grouped.setdefault((batch_id, batch_path), []).append(
            {
                "path": str(path),
                "status": status,
                "payload": payload,
            }
        )

    for (batch_id, batch_path), items in grouped.items():
        active = [item for item in items if item["status"] != "superseded"]
        if len(active) > 1:
            failures.append(
                "multiple active attestations for "
                f"batch_id={batch_id} batch_path={batch_path}: "
                f"{[item['path'] for item in active]}",
            )
        for item in items:
            if item["status"] == "superseded":
                superseded_by = str(
                    item["payload"].get("superseded_by") or ""
                ).strip()
                if not superseded_by:
                    failures.append(
                        f"{item['path']}: status=superseded requires non-empty superseded_by",
                    )
    return failures


def _validate_lineage_attestation_payload(
    *,
    payload: dict[str, Any],
    attestation_file: Path,
    batch_id: str,
    batch_file: Path,
    command_log_path: Path,
    run_dir: Path,
    repo_root: Path,
    command_lines: list[str],
    lineage_event_prefix: str,
) -> list[str]:
    failures: list[str] = []
    required_fields = (
        "schema_version",
        "batch_id",
        "batch_path",
        "batch_sha256",
        "reasoning_path",
        "reasoning_sha256",
        "command_log_path",
        "command_log_sha256",
        "attestor_id",
        "attested_at",
    )
    for field in required_fields:
        if field not in payload:
            failures.append(f"{attestation_file}: missing required field '{field}'")

    if str(payload.get("schema_version") or "").strip() != "manual-adjudication-attestation-v1":
        failures.append(
            f"{attestation_file}: schema_version must be manual-adjudication-attestation-v1",
        )
    if str(payload.get("batch_id") or "").strip() != batch_id:
        failures.append(
            f"{attestation_file}: batch_id mismatch expected {batch_id}",
        )

    if _parse_iso(payload.get("attested_at")) is None:
        failures.append(f"{attestation_file}: attested_at must be ISO-8601 datetime")
    if not str(payload.get("attestor_id") or "").strip():
        failures.append(f"{attestation_file}: attestor_id must be non-empty")

    batch_path = _resolve_path(str(payload.get("batch_path") or ""), run_dir, repo_root)
    reasoning_path = _resolve_path(str(payload.get("reasoning_path") or ""), run_dir, repo_root)
    command_path = _resolve_path(str(payload.get("command_log_path") or ""), run_dir, repo_root)

    expected_batch_sha = str(payload.get("batch_sha256") or "").strip()
    expected_reasoning_sha = str(payload.get("reasoning_sha256") or "").strip()
    expected_command_sha = str(payload.get("command_log_sha256") or "").strip()

    if not batch_path.exists():
        failures.append(f"{attestation_file}: batch_path missing {payload.get('batch_path')}")
    elif expected_batch_sha and _sha256_file(batch_path) != expected_batch_sha:
        failures.append(f"{attestation_file}: batch_sha256 mismatch for {batch_path}")

    if not reasoning_path.exists():
        failures.append(
            f"{attestation_file}: reasoning_path missing {payload.get('reasoning_path')}"
        )
    elif expected_reasoning_sha and _sha256_file(reasoning_path) != expected_reasoning_sha:
        failures.append(f"{attestation_file}: reasoning_sha256 mismatch for {reasoning_path}")

    if not command_path.exists():
        failures.append(
            f"{attestation_file}: command_log_path missing {payload.get('command_log_path')}"
        )
    elif expected_command_sha and _sha256_file(command_path) != expected_command_sha:
        failures.append(f"{attestation_file}: command_log_sha256 mismatch for {command_path}")

    if batch_path.resolve() != batch_file.resolve():
        failures.append(
            f"{attestation_file}: batch_path does not reference expected batch file {batch_file}",
        )

    event_specs: list[tuple[str, str]] = []
    if expected_batch_sha and isinstance(payload.get("batch_path"), str):
        event_specs.append((str(payload.get("batch_path")).strip(), expected_batch_sha))
    if expected_reasoning_sha and isinstance(payload.get("reasoning_path"), str):
        event_specs.append(
            (str(payload.get("reasoning_path")).strip(), expected_reasoning_sha),
        )
    queue_path_raw = str(payload.get("queue_update_path") or "").strip()
    queue_sha_raw = str(payload.get("queue_update_sha256") or "").strip()
    if queue_path_raw and queue_sha_raw:
        event_specs.append((queue_path_raw, queue_sha_raw))

    for artifact_rel, artifact_sha in event_specs:
        has_line = any(
            lineage_event_prefix in line
            and f"artifact={artifact_rel}" in line
            and f"sha256={artifact_sha}" in line
            and "writer=" in line
            and "action=" in line
            and ("ts=" in line or "timestamp=" in line)
            for line in command_lines
        )
        if not has_line:
            failures.append(
                f"{attestation_file}: missing {lineage_event_prefix} event for "
                f"artifact={artifact_rel} sha256={artifact_sha}",
            )
    return failures


def _validate_queue_linkage(
    *,
    run_dir: Path,
    profile: dict[str, Any],
) -> list[str]:
    batch_files = _collect_adjudication_batch_files(run_dir=run_dir, profile=profile)
    if not batch_files:
        return []

    adj_cfg = profile.get("adjudication", {})
    if not isinstance(adj_cfg, dict):
        adj_cfg = {}
    queue_globs = adj_cfg.get("queue_update_globs", list(DEFAULT_ADJ_QUEUE_UPDATE_GLOBS))
    if not isinstance(queue_globs, list):
        queue_globs = list(DEFAULT_ADJ_QUEUE_UPDATE_GLOBS)

    queue_updates: set[Path] = set()
    for pattern in queue_globs:
        pat = str(pattern).strip()
        if not pat:
            continue
        for candidate in run_dir.glob(pat):
            if candidate.is_file():
                queue_updates.add(candidate.resolve())

    if not queue_updates:
        return ["missing queue update artifact for adjudicated batch linkage"]

    update_rows: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for path in sorted(queue_updates):
        for row in _load_jsonl_objects(path):
            queue_item_id = str(row.get("queue_item_id") or "").strip()
            if queue_item_id:
                update_rows[queue_item_id] = row

    for batch_file in batch_files:
        for row in _load_jsonl_objects(batch_file):
            queue_item_id = str(row.get("queue_item_id") or "").strip()
            adjudication_id = str(row.get("adjudication_id") or "").strip()
            if not queue_item_id:
                failures.append(f"{batch_file}: row missing queue_item_id")
                continue
            if not adjudication_id:
                failures.append(f"{batch_file}: row missing adjudication_id for {queue_item_id}")
                continue
            update = update_rows.get(queue_item_id)
            if update is None:
                failures.append(f"{batch_file}: queue update missing for {queue_item_id}")
                continue
            update_status = str(update.get("status") or "").strip().lower()
            decision = str(row.get("decision") or "").strip().lower()
            allowed_statuses = {"adjudicated", "complete", "done"}
            if decision == "accepted":
                allowed_statuses = {"accepted", "adjudicated", "complete", "done"}
            elif decision == "review":
                allowed_statuses = {"review", "needs_review"}
            elif decision == "abstain":
                allowed_statuses = {"abstain"}
            if update_status not in allowed_statuses:
                failures.append(
                    f"queue update {queue_item_id} invalid status '{update_status}' "
                    f"for decision '{decision}'",
                )
            update_adj_id = str(update.get("adjudication_id") or "").strip()
            if update_adj_id != adjudication_id:
                failures.append(
                    f"queue update {queue_item_id} adjudication_id mismatch "
                    f"expected {adjudication_id} got {update_adj_id}",
                )
    return failures


def _validate_batch_split_homogeneity(
    *,
    run_dir: Path,
    profile: dict[str, Any],
) -> list[str]:
    batch_files = _collect_adjudication_batch_files(run_dir=run_dir, profile=profile)
    if not batch_files:
        return []
    adj_cfg = profile.get("adjudication", {})
    if not isinstance(adj_cfg, dict):
        adj_cfg = {}
    require_split_field = _is_truthy(adj_cfg.get("require_split_field", False))
    failures: list[str] = []
    for batch_file in batch_files:
        rows = _load_jsonl_objects(batch_file)
        splits = [
            str(row.get("split") or "").strip()
            for row in rows
            if str(row.get("split") or "").strip()
        ]
        if require_split_field and len(splits) != len(rows):
            failures.append(f"{batch_file}: split field missing in one or more rows")
            continue
        if splits and len(set(splits)) > 1:
            failures.append(
                f"{batch_file}: mixed split values {sorted(set(splits))} are not allowed",
            )
    return failures


def _validate_migration_map(
    *,
    run_dir: Path,
    repo_root: Path,
    profile: dict[str, Any],
) -> list[str]:
    cfg = profile.get("migration_map", {})
    if not isinstance(cfg, dict):
        cfg = {}
    required = _is_truthy(cfg.get("require", False))
    globs = cfg.get("globs", ["**/filename_migration_map*.json"])
    if not isinstance(globs, list):
        globs = ["**/filename_migration_map*.json"]

    map_files: set[Path] = set()
    for glob_pat in globs:
        pat = str(glob_pat).strip()
        if not pat:
            continue
        for candidate in run_dir.glob(pat):
            if candidate.is_file():
                map_files.add(candidate.resolve())
    ordered_maps = sorted(map_files)

    failures: list[str] = []
    if required and not ordered_maps:
        return ["missing required filename migration map artifact"]
    for map_file in ordered_maps:
        try:
            payload = _load_json(map_file)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{map_file}: invalid JSON ({exc})")
            continue
        if str(payload.get("schema_version") or "").strip() != "artifact-filename-migration-map-v1":
            failures.append(
                f"{map_file}: schema_version must be artifact-filename-migration-map-v1",
            )
        mappings = payload.get("mappings")
        if not isinstance(mappings, list):
            failures.append(f"{map_file}: mappings must be a list")
            continue
        for idx, mapping in enumerate(mappings, start=1):
            if not isinstance(mapping, dict):
                failures.append(f"{map_file}: mappings[{idx}] must be an object")
                continue
            old_path_raw = str(mapping.get("old_path") or "").strip()
            new_path_raw = str(mapping.get("new_path") or "").strip()
            old_sha = str(mapping.get("old_sha256") or "").strip()
            new_sha = str(mapping.get("new_sha256") or "").strip()
            if not old_path_raw or not new_path_raw:
                failures.append(
                    f"{map_file}: mappings[{idx}] missing old_path/new_path",
                )
                continue
            if not old_sha or not new_sha:
                failures.append(
                    f"{map_file}: mappings[{idx}] missing old_sha256/new_sha256",
                )
                continue
            old_path = _resolve_path(old_path_raw, run_dir, repo_root)
            new_path = _resolve_path(new_path_raw, run_dir, repo_root)
            if not old_path.exists():
                failures.append(
                    f"{map_file}: mappings[{idx}] old_path missing {old_path_raw}",
                )
            else:
                old_actual = _sha256_file(old_path)
                if old_actual != old_sha:
                    failures.append(
                        f"{map_file}: mappings[{idx}] old_sha256 mismatch for {old_path_raw}",
                    )
            if not new_path.exists():
                failures.append(
                    f"{map_file}: mappings[{idx}] new_path missing {new_path_raw}",
                )
            else:
                new_actual = _sha256_file(new_path)
                if new_actual != new_sha:
                    failures.append(
                        f"{map_file}: mappings[{idx}] new_sha256 mismatch for {new_path_raw}",
                    )
    return failures


def _validate_adjudication_quality(
    *,
    run_dir: Path,
    profile: dict[str, Any],
) -> tuple[list[str], bool]:
    cfg = profile.get("adjudication_quality", {})
    if not isinstance(cfg, dict):
        cfg = {}
    if not _is_truthy(cfg.get("require", False)):
        return [], False

    min_unique_timestamp_ratio = float(cfg.get("min_unique_timestamp_ratio", 0.5))
    min_unique_witness_ratio = float(cfg.get("min_unique_witness_ratio", 0.6))
    min_unique_reasoning_ratio = float(cfg.get("min_unique_reasoning_ratio", 0.6))
    waiver_path_raw = str(cfg.get("waiver_path") or "").strip()

    batch_files = _collect_adjudication_batch_files(run_dir=run_dir, profile=profile)
    if not batch_files:
        return [], False

    timestamp_values: list[str] = []
    witness_values: list[str] = []
    reasoning_templates: list[str] = []
    failures: list[str] = []

    for batch_file in batch_files:
        rows = _load_jsonl_objects(batch_file)
        batch_id = _batch_id_from_stem(batch_file.stem)
        reasoning_file, ambiguous = _find_reasoning_file(run_dir, batch_id)
        if ambiguous:
            failures.append(
                f"{batch_file}: ambiguous reasoning file candidates {ambiguous}",
            )
            continue
        reasoning_rows = _load_jsonl_objects(reasoning_file) if reasoning_file else []
        reasoning_by_id = {
            str(row.get("row_id") or "").strip(): row
            for row in reasoning_rows
        }
        for row in rows:
            adjudicated_at = str(row.get("adjudicated_at") or "").strip()
            if adjudicated_at:
                timestamp_values.append(adjudicated_at)
            snippets = row.get("witness_snippets")
            if isinstance(snippets, list):
                joined = " | ".join(str(s).strip() for s in snippets if str(s).strip())
                if joined:
                    witness_values.append(joined)
            rid = str(row.get("row_id") or "").strip()
            rrow = reasoning_by_id.get(rid, {})
            template = "|".join(
                [
                    str(rrow.get("final_decision") or row.get("decision") or "").strip(),
                    str(rrow.get("hypothesis_A") or "").strip(),
                    str(rrow.get("hypothesis_B") or "").strip(),
                    str(rrow.get("why_A_survives") or "").strip(),
                    str(rrow.get("why_B_survives") or "").strip(),
                ]
            )
            if template.strip("|"):
                reasoning_templates.append(template)

    def ratio_unique(values: list[str]) -> float:
        if not values:
            return 1.0
        return len(set(values)) / float(len(values))

    ts_ratio = ratio_unique(timestamp_values)
    witness_ratio = ratio_unique(witness_values)
    reasoning_ratio = ratio_unique(reasoning_templates)

    if ts_ratio < min_unique_timestamp_ratio:
        failures.append(
            f"timestamp uniqueness ratio {ts_ratio:.3f} below {min_unique_timestamp_ratio:.3f}",
        )
    if witness_ratio < min_unique_witness_ratio:
        failures.append(
            f"witness uniqueness ratio {witness_ratio:.3f} below {min_unique_witness_ratio:.3f}",
        )
    if reasoning_ratio < min_unique_reasoning_ratio:
        failures.append(
            "reasoning-template uniqueness ratio "
            f"{reasoning_ratio:.3f} below {min_unique_reasoning_ratio:.3f}",
        )

    if not failures or not waiver_path_raw:
        return failures, False
    waiver_path = _resolve_path(waiver_path_raw, run_dir, run_dir)
    if not waiver_path.exists():
        return failures, False
    try:
        waiver_payload = _load_json(waiver_path)
    except Exception:
        return failures, False
    approved = _is_truthy(waiver_payload.get("approved", False))
    return ([], True) if approved else (failures, False)


def _collect_redteam_artifacts(
    *,
    run_dir: Path,
    glob_patterns: list[str],
) -> list[Path]:
    found: set[Path] = set()
    for pat in glob_patterns:
        pattern = str(pat).strip()
        if not pattern:
            continue
        for candidate in run_dir.glob(pattern):
            if candidate.is_file():
                found.add(candidate.resolve())
    return sorted(found)


def _validate_redteam_artifact_payload(
    *,
    payload: dict[str, Any],
    artifact_path: Path,
    day_id: str,
    required_fields: list[str],
) -> list[str]:
    errors: list[str] = []
    for field in required_fields:
        if field not in payload:
            errors.append(f"{artifact_path}: missing required field '{field}'")

    review_mode = str(payload.get("review_mode") or "").strip()
    if review_mode != "adversarial_subagent":
        errors.append(
            f"{artifact_path}: review_mode must be 'adversarial_subagent', got '{review_mode}'"
        )

    subagent_id = str(payload.get("subagent_id") or "").strip()
    if not subagent_id:
        errors.append(f"{artifact_path}: subagent_id must be a non-empty string")

    verdict = str(payload.get("verdict") or "").strip()
    if verdict not in ALLOWED_REDTEAM_VERDICTS:
        errors.append(
            f"{artifact_path}: verdict must be one of {sorted(ALLOWED_REDTEAM_VERDICTS)}"
        )

    findings = payload.get("adversarial_findings")
    if not isinstance(findings, list) or not findings:
        errors.append(
            f"{artifact_path}: adversarial_findings must be a non-empty list"
        )

    completed_at = payload.get("completed_at")
    if _parse_iso(completed_at) is None:
        errors.append(f"{artifact_path}: completed_at must be ISO-8601 datetime")

    payload_day = str(payload.get("day_id") or "").strip()
    if payload_day and payload_day != day_id:
        errors.append(
            f"{artifact_path}: day_id mismatch expected '{day_id}', got '{payload_day}'"
        )

    return errors


def _validate_redteam_freshness(
    *,
    run_dir: Path,
    repo_root: Path,
    profile: dict[str, Any],
    gate_summary: dict[str, Any],
    manifest: dict[str, Any],
    day_id: str,
) -> list[str]:
    redteam_cfg = profile.get("red_team", {})
    if not isinstance(redteam_cfg, dict):
        redteam_cfg = {}

    required_statuses = {
        str(x).strip()
        for x in redteam_cfg.get(
            "require_adversarial_subagent_statuses",
            list(DEFAULT_REDTEAM_REQUIRED_STATUSES),
        )
        if str(x).strip()
    }
    redteam_status = str(gate_summary.get("red_team_status") or "").strip()
    if redteam_status not in required_statuses:
        return []

    output_artifacts = manifest.get("output_artifacts", {})
    if not isinstance(output_artifacts, dict):
        output_artifacts = {}

    pointer_key = str(
        redteam_cfg.get("manifest_output_pointer_key")
        or "red_team_adversarial_review"
    ).strip()
    manifest_pointer_raw = str(output_artifacts.get(pointer_key) or "").strip()
    gate_pointer_raw = str(gate_summary.get("red_team_artifact") or "").strip()
    pointer_raw = gate_pointer_raw or manifest_pointer_raw
    failures: list[str] = []
    if not pointer_raw:
        return ["red-team freshness check missing active red-team artifact pointer"]
    pointer_path = _resolve_path(pointer_raw, run_dir, repo_root)
    if not pointer_path.exists():
        return [f"red-team freshness pointer missing file: {pointer_raw}"]

    try:
        pointer_payload = _load_json(pointer_path)
    except Exception as exc:  # noqa: BLE001
        return [f"red-team freshness pointer invalid JSON: {pointer_raw} ({exc})"]

    gate_subagent_id = str(gate_summary.get("red_team_subagent_id") or "").strip()
    artifact_subagent_id = str(pointer_payload.get("subagent_id") or "").strip()
    if gate_subagent_id and artifact_subagent_id != gate_subagent_id:
        failures.append(
            "gate_summary.red_team_subagent_id does not match active red-team artifact "
            f"subagent_id ({gate_subagent_id} != {artifact_subagent_id})",
        )

    pointer_completed_at = _parse_iso(pointer_payload.get("completed_at"))
    if pointer_completed_at is None:
        failures.append("active red-team artifact completed_at is missing/invalid")
        return failures

    artifact_globs = [
        str(x).strip()
        for x in redteam_cfg.get(
            "artifact_globs",
            list(DEFAULT_REDTEAM_ARTIFACT_GLOBS),
        )
        if str(x).strip()
    ]
    candidates = _collect_redteam_artifacts(run_dir=run_dir, glob_patterns=artifact_globs)
    latest_completed_at = pointer_completed_at
    latest_path = pointer_path.resolve()
    for candidate in candidates:
        try:
            payload = _load_json(candidate)
        except Exception:  # noqa: BLE001
            continue
        payload_day = str(payload.get("day_id") or "").strip()
        if payload_day and payload_day != day_id:
            continue
        completed_at = _parse_iso(payload.get("completed_at"))
        if completed_at is None:
            continue
        if completed_at > latest_completed_at:
            latest_completed_at = completed_at
            latest_path = candidate.resolve()

    if latest_path != pointer_path.resolve():
        failures.append(
            "active red-team pointer is stale; newer adversarial artifact exists at "
            f"{latest_path}",
        )

    return failures


def _validate_adjudication_export_policy(
    *,
    run_dir: Path,
    profile: dict[str, Any],
) -> list[str]:
    cfg = profile.get("adjudication_export", {})
    if not isinstance(cfg, dict):
        cfg = {}
    if not _is_truthy(cfg.get("require", True)):
        return []

    uncertain_decisions = {
        str(x).strip().lower()
        for x in cfg.get("uncertain_decisions", ["review", "abstain"])
        if str(x).strip()
    }
    eligibility_field = str(
        cfg.get("eligibility_field") or "training_export_eligible"
    ).strip()
    override_field = str(
        cfg.get("allow_override_field") or "allow_uncertain_training_export"
    ).strip()

    failures: list[str] = []
    for batch_file in _collect_adjudication_batch_files(run_dir=run_dir, profile=profile):
        rows = _load_jsonl_objects(batch_file)
        for idx, row in enumerate(rows, start=1):
            decision = str(row.get("decision") or "").strip().lower()
            if decision not in uncertain_decisions:
                continue
            eligible = _is_truthy(row.get(eligibility_field, False))
            allow_override = _is_truthy(row.get(override_field, False))
            if eligible and not allow_override:
                row_id = str(row.get("row_id") or f"row_{idx}").strip()
                failures.append(
                    f"{batch_file}: row_id={row_id} decision={decision} has "
                    f"{eligibility_field}=true without {override_field}=true",
                )
    return failures


def _validate_temporal_provenance(
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    profile: dict[str, Any],
) -> list[str]:
    batch_files = _collect_adjudication_batch_files(run_dir=run_dir, profile=profile)
    if not batch_files:
        return []

    failures: list[str] = []
    batch_max_ts: dict[Path, datetime] = {}
    max_adjudicated_at: datetime | None = None
    for batch_file in batch_files:
        batch_rows = _load_jsonl_objects(batch_file)
        row_times: list[datetime] = []
        for idx, row in enumerate(batch_rows, start=1):
            raw = row.get("adjudicated_at")
            if raw is None:
                continue
            parsed = _parse_iso(raw)
            if parsed is None:
                row_id = str(row.get("row_id") or f"row_{idx}").strip()
                failures.append(
                    f"{batch_file}: row_id={row_id} adjudicated_at is missing/invalid",
                )
                continue
            row_times.append(parsed)
        if row_times:
            batch_max = max(row_times)
            batch_max_ts[batch_file.resolve()] = batch_max
            if max_adjudicated_at is None or batch_max > max_adjudicated_at:
                max_adjudicated_at = batch_max

    if max_adjudicated_at is None:
        return failures

    for batch_file in batch_files:
        batch_max = batch_max_ts.get(batch_file.resolve())
        if batch_max is None:
            continue
        batch_id = _batch_id_from_stem(batch_file.stem)
        attestation_file, ambiguous = _find_lineage_attestation_file(
            run_dir=run_dir,
            batch_id=batch_id,
        )
        if ambiguous:
            failures.append(
                f"{batch_file}: ambiguous attestation files {ambiguous}",
            )
            continue
        if attestation_file is None:
            continue
        try:
            payload = _load_json(attestation_file)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{attestation_file}: invalid JSON ({exc})")
            continue
        attested_at = _parse_iso(payload.get("attested_at"))
        if attested_at is None:
            failures.append(f"{attestation_file}: attested_at missing/invalid")
            continue
        if attested_at < batch_max:
            failures.append(
                f"{attestation_file}: attested_at ({attested_at.isoformat()}) is before "
                f"latest adjudicated_at ({batch_max.isoformat()})",
            )

    for sample_path in sorted(run_dir.glob("**/manual_reaudit_sample*.jsonl")):
        sample_rows = _load_jsonl_objects(sample_path)
        sample_times: list[datetime] = []
        for idx, row in enumerate(sample_rows, start=1):
            raw = row.get("created_at")
            if raw is None:
                continue
            parsed = _parse_iso(raw)
            if parsed is None:
                row_id = str(row.get("row_id") or f"row_{idx}").strip()
                failures.append(
                    f"{sample_path}: row_id={row_id} created_at missing/invalid",
                )
                continue
            sample_times.append(parsed)
        if sample_times and min(sample_times) < max_adjudicated_at:
            failures.append(
                f"{sample_path}: created_at is before latest adjudicated_at "
                f"({max_adjudicated_at.isoformat()})",
            )

    manifest_generated = _parse_iso(manifest.get("generated_at"))
    manifest_updated = _parse_iso(manifest.get("updated_at"))
    if manifest_generated and manifest_generated < max_adjudicated_at:
        failures.append(
            "manifest.generated_at is before latest adjudicated_at "
            f"({max_adjudicated_at.isoformat()})",
        )
    if manifest_updated and manifest_updated < max_adjudicated_at:
        failures.append(
            "manifest.updated_at is before latest adjudicated_at "
            f"({max_adjudicated_at.isoformat()})",
        )

    return failures


def _validate_canonicalization_provenance(
    *,
    workspace_dirty: bool,
    run_dir: Path,
    profile: dict[str, Any],
    manifest: dict[str, Any],
    command_log_path: Path | None,
) -> list[str]:
    if not workspace_dirty:
        return []

    output_artifacts = manifest.get("output_artifacts", {})
    if not isinstance(output_artifacts, dict):
        output_artifacts = {}
    command_exit_codes = manifest.get("command_exit_codes", {})
    if not isinstance(command_exit_codes, dict):
        command_exit_codes = {}

    canonical_cfg = profile.get("canonical", {})
    if not isinstance(canonical_cfg, dict):
        canonical_cfg = {}
    primary_keys = [
        str(x).strip()
        for x in canonical_cfg.get(
            "primary_output_keys",
            DEFAULT_CANONICAL_PRIMARY_OUTPUT_KEYS,
        )
        if str(x).strip()
    ]
    primary_paths = [
        str(output_artifacts.get(key) or "").strip()
        for key in primary_keys
        if str(output_artifacts.get(key) or "").strip()
    ]
    if not primary_paths:
        return ["canonicalization provenance missing canonical primary output paths"]

    failures: list[str] = []
    promote_keys = sorted(
        key for key in command_exit_codes if key.startswith("promote_canonical_")
    )
    if not promote_keys:
        failures.append(
            "workspace is dirty but manifest.command_exit_codes has no "
            "promote_canonical_* entries",
        )
    for key in promote_keys:
        code = _coerce_int(command_exit_codes.get(key))
        if code != 0:
            failures.append(f"manifest.command_exit_codes.{key} is non-zero ({code})")

    if command_log_path is None or not command_log_path.exists():
        failures.append("canonicalization provenance requires command_log.txt")
        return failures

    lines = [
        line.strip()
        for line in command_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for path in primary_paths:
        if not any(
            path in line and ("cp " in line or "promote_canonical" in line)
            for line in lines
        ):
            failures.append(
                "missing canonicalization command evidence in command_log for "
                f"{path}",
            )

    return failures


def _validate_post_validation_freeze(
    *,
    run_dir: Path,
    profile: dict[str, Any],
    command_exit_codes: dict[str, Any],
) -> list[str]:
    if "validate_day_bundle" not in command_exit_codes:
        return []

    cfg = profile.get("freeze", {})
    if not isinstance(cfg, dict):
        cfg = {}
    if not _is_truthy(cfg.get("require", True)):
        return []

    anchor_name = str(cfg.get("anchor_exit_code_file") or "validate_day_bundle.exit_code").strip()
    anchor_candidates = [
        run_dir / anchor_name,
        run_dir / "canonical" / anchor_name,
    ]
    anchor = next((p for p in anchor_candidates if p.exists()), None)
    if anchor is None:
        return [f"post-validation freeze anchor missing: {anchor_name}"]

    include_globs = cfg.get("mutable_include_globs", ["*", "**/*"])
    if not isinstance(include_globs, list):
        include_globs = ["*", "**/*"]
    include_globs = [str(x).strip() for x in include_globs if str(x).strip()]

    exclude_globs = cfg.get(
        "mutable_exclude_globs",
        [
            "validate_day_bundle.exit_code",
            "day_validator_report.json",
            "canonical/day_validator_report.json",
            "artifact_index.json",
            ".DS_Store",
            "**/.DS_Store",
        ],
    )
    if not isinstance(exclude_globs, list):
        exclude_globs = []
    exclude_globs = [str(x).strip() for x in exclude_globs if str(x).strip()]

    anchor_ns = anchor.stat().st_mtime_ns
    late_files: list[str] = []
    for candidate in run_dir.rglob("*"):
        if not candidate.is_file():
            continue
        rel = str(candidate.relative_to(run_dir))
        included = any(fnmatch.fnmatch(rel, pattern) for pattern in include_globs)
        excluded = any(fnmatch.fnmatch(rel, pattern) for pattern in exclude_globs)
        if not included or excluded:
            continue
        if candidate.stat().st_mtime_ns > anchor_ns:
            late_files.append(rel)

    if late_files:
        late_files.sort()
    return late_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a day evidence bundle.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--day-id", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--allow-warn-only", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    repo_root = args.repo_root.resolve()
    json_out = args.json_out.resolve()
    generated_at = datetime.now().astimezone().isoformat()

    try:
        if not ALLOWED_DAY_ID_RE.fullmatch(args.day_id):
            raise InputError("--day-id must be day1..day22")
        if not run_dir.exists() or not run_dir.is_dir():
            raise InputError(f"--run-dir does not exist or is not a directory: {run_dir}")

        profile = _load_profile(args.profile.resolve())
        expected_days = _profile_expected_days(profile)
        if expected_days and args.day_id not in expected_days:
            expected_days_str = ", ".join(sorted(expected_days))
            raise InputError(
                f"Profile {args.profile} does not apply to {args.day_id}; "
                f"expected one of [{expected_days_str}]",
            )

        required_checks = [str(x).strip() for x in profile.get("required_checks", [])]
        if not required_checks:
            raise InputError("Profile required_checks[] cannot be empty")
        unknown_checks = [check for check in required_checks if check not in CHECK_SEVERITY]
        if unknown_checks:
            raise InputError(f"Unknown check ids in profile: {unknown_checks}")

        warn_only_ids = {
            str(x).strip()
            for x in profile.get("warn_only_checks", [])
            if str(x).strip()
        } if isinstance(profile.get("warn_only_checks"), list) else set()

        specs = _build_artifact_specs(profile)

        # Pre-read manifest to know if dirty.
        workspace_dirty = False
        for spec in specs:
            if spec.artifact_id != "run_manifest":
                continue
            for rel in spec.paths:
                cand = (run_dir / rel).resolve()
                if cand.exists():
                    manifest_probe = _load_json(cand)
                    git_probe = manifest_probe.get("git")
                    if isinstance(git_probe, dict):
                        workspace_dirty = bool(git_probe.get("is_dirty"))
                    break

        resolved, missing_artifacts, generated_errors = _resolve_artifacts(
            specs=specs,
            run_dir=run_dir,
            repo_root=repo_root,
            json_out=json_out,
            workspace_dirty=workspace_dirty,
        )

        parsed_json: dict[str, dict[str, Any]] = {}
        parse_errors: list[str] = []
        for artifact_id, artifact in resolved.items():
            if artifact.path is None or artifact.spec.generated:
                continue
            if artifact.spec.kind not in {"json", "generated_json"}:
                continue
            try:
                parsed_json[artifact_id] = _load_json(artifact.path)
            except Exception as exc:  # noqa: BLE001
                parse_errors.append(f"{artifact_id}: {exc}")

        manifest = parsed_json.get("run_manifest", {})
        blockers = parsed_json.get("blocker_register", {})
        gate_summary = parsed_json.get("gate_summary", {})
        git_meta = manifest.get("git", {}) if isinstance(manifest, dict) else {}
        if isinstance(git_meta, dict):
            workspace_dirty = bool(git_meta.get("is_dirty"))

        checks: list[CheckResult] = []

        checks.append(
            _check_result(
                check_id="VAL-FILE-001",
                ok=(not missing_artifacts and not generated_errors),
                message_ok="All required artifacts are present.",
                message_fail="Missing required artifacts or generated-output mismatch.",
                expected="all required artifacts present",
                actual={"missing": missing_artifacts, "generated_errors": generated_errors},
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )
        checks.append(
            _check_result(
                check_id="VAL-JSON-001",
                ok=not parse_errors,
                message_ok="Required JSON artifacts parsed successfully.",
                message_fail="One or more required JSON artifacts failed to parse.",
                expected="all required JSON parse",
                actual=parse_errors,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        required_manifest_keys = [
            str(x).strip()
            for x in profile.get("required_manifest_keys", DEFAULT_MANIFEST_REQUIRED_KEYS)
            if str(x).strip()
        ]
        missing_manifest = [
            key for key in required_manifest_keys
            if not isinstance(manifest, dict) or key not in manifest
        ]
        checks.append(
            _check_result(
                check_id="VAL-MANIFEST-001",
                ok=not missing_manifest,
                message_ok="Manifest contains required top-level keys.",
                message_fail="Manifest missing required top-level keys.",
                artifact_path=(
                    str(resolved["run_manifest"].path)
                    if "run_manifest" in resolved and resolved["run_manifest"].path
                    else None
                ),
                expected=required_manifest_keys,
                actual=missing_manifest,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        index_payload = parsed_json.get("artifact_index", {})
        index_errors: list[str] = []
        indexed_paths: set[Path] = set()
        if isinstance(index_payload, dict):
            artifact_rows = index_payload.get("artifacts", [])
            if isinstance(artifact_rows, list):
                for idx, row in enumerate(artifact_rows, start=1):
                    if not isinstance(row, dict):
                        index_errors.append(f"artifact_index.artifacts[{idx}] must be object")
                        continue
                    row_path = str(row.get("path") or "").strip()
                    row_sha = str(row.get("sha256") or "").strip()
                    if not row_path:
                        index_errors.append(
                            f"artifact_index.artifacts[{idx}] missing path",
                        )
                        continue
                    resolved_path = _resolve_path(row_path, run_dir, repo_root)
                    if not resolved_path.exists():
                        index_errors.append(
                            f"artifact_index.artifacts[{idx}] missing file {row_path}",
                        )
                        continue
                    indexed_paths.add(resolved_path.resolve())
                    if not row_sha:
                        index_errors.append(
                            f"artifact_index.artifacts[{idx}] missing sha256 for {row_path}",
                        )
                        continue
                    actual_sha = _sha256_file(resolved_path)
                    if actual_sha != row_sha:
                        index_errors.append(
                            f"artifact_index.artifacts[{idx}] sha mismatch for {row_path}",
                        )
            else:
                index_errors.append("artifact_index.artifacts must be a list")
        else:
            index_errors.append("artifact_index payload missing/invalid")
        checks.append(
            _check_result(
                check_id="VAL-INDEX-001",
                ok=not index_errors,
                message_ok="Artifact index hashes resolve and match disk bytes.",
                message_fail="Artifact index is missing entries, files, or matching hashes.",
                artifact_path=(
                    str(resolved["artifact_index"].path)
                    if "artifact_index" in resolved and resolved["artifact_index"].path
                    else None
                ),
                expected="artifact_index.artifacts[*].path exists and sha256 matches",
                actual=index_errors,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        index_coverage_errors: list[str] = []
        canonical_cfg = profile.get("canonical", {})
        if not isinstance(canonical_cfg, dict):
            canonical_cfg = {}
        index_cfg = profile.get("index", {})
        if not isinstance(index_cfg, dict):
            index_cfg = {}
        index_primary_keys = [
            str(x).strip()
            for x in canonical_cfg.get(
                "primary_output_keys",
                DEFAULT_CANONICAL_PRIMARY_OUTPUT_KEYS,
            )
            if str(x).strip()
        ]
        output_artifacts = (
            manifest.get("output_artifacts", {})
            if isinstance(manifest, dict)
            else {}
        )
        if not isinstance(output_artifacts, dict):
            output_artifacts = {}

        require_manifest_output_coverage = _is_truthy(
            index_cfg.get("require_manifest_output_coverage", False),
        )
        require_run_dir_coverage = _is_truthy(
            index_cfg.get("require_run_dir_coverage", False),
        )
        run_dir_include_globs = [
            str(x).strip()
            for x in index_cfg.get("run_dir_include_globs", ["**/*"])
            if str(x).strip()
        ] if isinstance(index_cfg.get("run_dir_include_globs"), list) else ["**/*"]
        run_dir_exclude_globs = [
            str(x).strip()
            for x in index_cfg.get("run_dir_exclude_globs", ["artifact_index.json"])
            if str(x).strip()
        ] if isinstance(index_cfg.get("run_dir_exclude_globs"), list) else [
            "artifact_index.json"
        ]
        manifest_output_exclude_keys = {
            str(x).strip()
            for x in index_cfg.get("manifest_output_exclude_keys", [])
            if str(x).strip()
        } if isinstance(index_cfg.get("manifest_output_exclude_keys"), list) else set()

        for key in index_primary_keys:
            raw_path = str(output_artifacts.get(key) or "").strip()
            if not raw_path:
                index_coverage_errors.append(
                    f"manifest.output_artifacts missing primary key '{key}'",
                )
                continue
            resolved_primary_path = _resolve_path(raw_path, run_dir, repo_root).resolve()
            if not resolved_primary_path.exists():
                index_coverage_errors.append(
                    f"primary output '{key}' path missing on disk: {raw_path}",
                )
                continue
            if resolved_primary_path not in indexed_paths:
                index_coverage_errors.append(
                    f"primary output '{key}' not present in artifact_index: {raw_path}",
                )
        if require_manifest_output_coverage:
            for key, raw in output_artifacts.items():
                if str(key) in manifest_output_exclude_keys:
                    continue
                raw_path = str(raw or "").strip()
                if not raw_path:
                    index_coverage_errors.append(
                        f"manifest.output_artifacts.{key} is empty",
                    )
                    continue
                resolved_output_path = _resolve_path(raw_path, run_dir, repo_root).resolve()
                if not resolved_output_path.exists():
                    index_coverage_errors.append(
                        f"manifest.output_artifacts.{key} missing file {raw_path}",
                    )
                    continue
                if resolved_output_path not in indexed_paths:
                    index_coverage_errors.append(
                        f"manifest.output_artifacts.{key} not present in artifact_index: "
                        f"{raw_path}",
                    )
        if require_run_dir_coverage:
            for candidate in run_dir.rglob("*"):
                if not candidate.is_file():
                    continue
                rel = str(candidate.relative_to(run_dir))
                included = any(
                    fnmatch.fnmatch(rel, pattern)
                    for pattern in run_dir_include_globs
                )
                excluded = any(
                    fnmatch.fnmatch(rel, pattern)
                    for pattern in run_dir_exclude_globs
                )
                if not included or excluded:
                    continue
                if candidate.resolve() not in indexed_paths:
                    index_coverage_errors.append(
                        f"run_dir artifact not present in artifact_index: {rel}",
                    )
        checks.append(
            _check_result(
                check_id="VAL-INDEX-002",
                ok=not index_coverage_errors,
                message_ok="Artifact index covers all canonical primary outputs.",
                message_fail="Artifact index is missing one or more canonical primary outputs.",
                artifact_path=(
                    str(resolved["artifact_index"].path)
                    if "artifact_index" in resolved and resolved["artifact_index"].path
                    else None
                ),
                expected={
                    "primary_output_keys": index_primary_keys,
                    "require_manifest_output_coverage": require_manifest_output_coverage,
                    "manifest_output_exclude_keys": sorted(manifest_output_exclude_keys),
                    "require_run_dir_coverage": require_run_dir_coverage,
                    "run_dir_include_globs": run_dir_include_globs,
                    "run_dir_exclude_globs": run_dir_exclude_globs,
                },
                actual=index_coverage_errors,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        hash_mismatches: list[dict[str, Any]] = []
        hash_pairs = _collect_hash_pairs(manifest if isinstance(manifest, dict) else {})
        for path_key, hash_key, path_str, expected_hash in hash_pairs:
            if not expected_hash:
                continue
            p = _resolve_path(path_str, run_dir, repo_root)
            if not p.exists():
                hash_mismatches.append(
                    {
                        "path_key": path_key,
                        "hash_key": hash_key,
                        "path": path_str,
                        "reason": "missing_file",
                    }
                )
                continue
            actual_hash = _sha256_file(p)
            if actual_hash != expected_hash:
                hash_mismatches.append(
                    {
                        "path_key": path_key,
                        "hash_key": hash_key,
                        "path": path_str,
                        "expected": expected_hash,
                        "actual": actual_hash,
                    }
                )
        checks.append(
            _check_result(
                check_id="VAL-HASH-001",
                ok=not hash_mismatches,
                message_ok="Manifest hash declarations match artifact bytes.",
                message_fail="Manifest hash declarations mismatch.",
                expected=f"{len(hash_pairs)} declared hash/path pairs",
                actual=hash_mismatches,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        exit_mismatches: list[dict[str, Any]] = []
        command_exit_codes = manifest.get("command_exit_codes", {})
        if not isinstance(command_exit_codes, dict):
            command_exit_codes = {}
            exit_mismatches.append({"reason": "manifest.command_exit_codes missing/invalid"})
        for command_name, expected_raw in command_exit_codes.items():
            expected = _coerce_int(expected_raw)
            if expected is None:
                exit_mismatches.append(
                    {
                        "command": command_name,
                        "reason": "non_integer_expected_exit",
                        "actual": expected_raw,
                    }
                )
                continue
            candidates = [
                run_dir / f"{command_name}.exit_code",
                run_dir / "canonical" / f"{command_name}.exit_code",
            ]
            chosen = next((p for p in candidates if p.exists()), None)
            if chosen is None:
                exit_mismatches.append(
                    {"command": command_name, "reason": "missing_exit_code_file"}
                )
                continue
            actual = _coerce_int(chosen.read_text(encoding="utf-8").strip())
            if actual is None or actual != expected:
                exit_mismatches.append(
                    {
                        "command": command_name,
                        "path": str(chosen),
                        "expected": expected,
                        "actual": actual,
                    }
                )
        checks.append(
            _check_result(
                check_id="VAL-EXIT-001",
                ok=not exit_mismatches,
                message_ok="Manifest command exit codes match .exit_code files.",
                message_fail="Manifest command exit codes mismatch .exit_code files.",
                expected="manifest command_exit_codes == *.exit_code",
                actual=exit_mismatches,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        gate_failures: list[str] = []
        gate_rules = profile.get("gate_rules", {})
        if not isinstance(gate_rules, dict):
            gate_rules = {}
        required_output_keys = [
            str(x).strip()
            for x in gate_rules.get("required_output_artifact_keys", [])
            if str(x).strip()
        ]
        non_blocking_commands = {
            str(x).strip()
            for x in gate_rules.get("non_blocking_commands", [])
            if str(x).strip()
        }
        if not isinstance(gate_summary, dict) or not gate_summary:
            gate_failures.append("missing gate summary payload")
        else:
            status = str(gate_summary.get("status") or "").strip().lower()
            if status not in {"pass", "fail", "go", "no-go", "green", "red"}:
                gate_failures.append("gate_summary.status missing/invalid")
            outputs = manifest.get("output_artifacts", {}) if isinstance(manifest, dict) else {}
            if not isinstance(outputs, dict):
                outputs = {}
            for key in required_output_keys:
                raw_path = str(outputs.get(key) or "").strip()
                if not raw_path:
                    gate_failures.append(f"missing output_artifacts.{key}")
                    continue
                p = _resolve_path(raw_path, run_dir, repo_root)
                if not p.exists():
                    gate_failures.append(f"output_artifacts.{key} missing file {raw_path}")
            if status in {"pass", "go", "green"}:
                for cmd, code_raw in command_exit_codes.items():
                    code = _coerce_int(code_raw)
                    if code is None:
                        continue
                    if code != 0 and cmd not in non_blocking_commands:
                        gate_failures.append(
                            f"blocking command '{cmd}' has non-zero exit code {code}",
                        )
        checks.append(
            _check_result(
                check_id="VAL-GATE-001",
                ok=not gate_failures,
                message_ok="Gate summary is consistent with machine outputs.",
                message_fail="Gate summary inconsistent with machine outputs.",
                artifact_path=(
                    str(resolved["gate_summary"].path)
                    if "gate_summary" in resolved and resolved["gate_summary"].path
                    else None
                ),
                expected="consistent gate summary",
                actual=gate_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        blocker_rows = blockers.get("blockers", []) if isinstance(blockers, dict) else []
        blocker_errors: list[str] = []
        if not isinstance(blocker_rows, list):
            blocker_rows = []
            blocker_errors.append("blockers.blockers missing/invalid list")
        for idx, block in enumerate(blocker_rows, start=1):
            if not isinstance(block, dict):
                blocker_errors.append(f"blockers[{idx}] must be object")
                continue
            status = str(block.get("status") or "").strip()
            if status not in ALLOWED_BLOCKER_STATUS:
                blocker_errors.append(f"blockers[{idx}] invalid status '{status}'")
            if status == "closed":
                resolution = str(block.get("resolution") or "").strip()
                resolved_at = str(block.get("resolved_at") or "").strip()
                evidence = block.get("resolution_evidence")
                if not resolution:
                    blocker_errors.append(f"blockers[{idx}] closed without resolution")
                if not resolved_at:
                    blocker_errors.append(f"blockers[{idx}] closed without resolved_at")
                if not isinstance(evidence, list) or not any(str(x).strip() for x in evidence):
                    blocker_errors.append(
                        f"blockers[{idx}] closed without resolution_evidence[]",
                    )
        checks.append(
            _check_result(
                check_id="VAL-BLOCKER-001",
                ok=not blocker_errors,
                message_ok="Blocker lifecycle fields are valid.",
                message_fail="Blocker lifecycle fields are invalid.",
                artifact_path=(
                    str(resolved["blocker_register"].path)
                    if "blocker_register" in resolved and resolved["blocker_register"].path
                    else None
                ),
                expected="valid blocker lifecycle values",
                actual=blocker_errors,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        scope_errors: list[str] = []
        for idx, block in enumerate(blocker_rows, start=1):
            if not isinstance(block, dict):
                continue
            scope = str(block.get("blocking_scope") or "").strip()
            if scope not in ALLOWED_BLOCKING_SCOPE:
                scope_errors.append(f"blockers[{idx}] invalid blocking_scope '{scope}'")
        checks.append(
            _check_result(
                check_id="VAL-BLOCKER-002",
                ok=not scope_errors,
                message_ok="Blockers include valid blocking_scope values.",
                message_fail="Blockers missing/invalid blocking_scope values.",
                artifact_path=(
                    str(resolved["blocker_register"].path)
                    if "blocker_register" in resolved and resolved["blocker_register"].path
                    else None
                ),
                expected=sorted(ALLOWED_BLOCKING_SCOPE),
                actual=scope_errors,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        redteam_failures: list[str] = []
        if isinstance(gate_summary, dict):
            redteam_status = str(gate_summary.get("red_team_status") or "").strip()
            if redteam_status not in ALLOWED_REDTEAM_STATUS:
                redteam_failures.append(
                    "gate_summary.red_team_status must be one of "
                    f"{sorted(ALLOWED_REDTEAM_STATUS)}",
                )
            if redteam_status and redteam_status != "not_started":
                validator_passed = _is_truthy(gate_summary.get("validator_passed"))
                validator_exit = _coerce_int(gate_summary.get("validator_exit_code"))
                if not validator_passed:
                    redteam_failures.append(
                        "red_team_status indicates progress but validator_passed is not true",
                    )
                if validator_exit != 0:
                    redteam_failures.append(
                        "red_team_status indicates progress but validator_exit_code != 0",
                    )
        else:
            redteam_failures.append("missing gate_summary payload for red-team checks")
        checks.append(
            _check_result(
                check_id="VAL-REDTEAM-001",
                ok=not redteam_failures,
                message_ok="Red-team state satisfies enum and validator-first policy.",
                message_fail="Red-team state violates enum or validator-first policy.",
                expected={
                    "red_team_status": sorted(ALLOWED_REDTEAM_STATUS),
                    "policy": "non-not_started requires validator_passed=true and exit_code=0",
                },
                actual=redteam_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        redteam_cfg = profile.get("red_team", {})
        if not isinstance(redteam_cfg, dict):
            redteam_cfg = {}
        required_statuses = {
            str(x).strip()
            for x in redteam_cfg.get(
                "require_adversarial_subagent_statuses",
                list(DEFAULT_REDTEAM_REQUIRED_STATUSES),
            )
            if str(x).strip()
        }
        artifact_globs = [
            str(x).strip()
            for x in redteam_cfg.get(
                "artifact_globs",
                list(DEFAULT_REDTEAM_ARTIFACT_GLOBS),
            )
            if str(x).strip()
        ]
        required_redteam_fields = [
            str(x).strip()
            for x in redteam_cfg.get(
                "required_fields",
                list(DEFAULT_REDTEAM_REQUIRED_FIELDS),
            )
            if str(x).strip()
        ]

        output_artifacts = (
            manifest.get("output_artifacts", {})
            if isinstance(manifest, dict)
            else {}
        )
        if not isinstance(output_artifacts, dict):
            output_artifacts = {}

        redteam_artifact_failures: list[str] = []
        redteam_status = (
            str(gate_summary.get("red_team_status") or "").strip()
            if isinstance(gate_summary, dict)
            else ""
        )
        if redteam_status in required_statuses:
            candidates = _collect_redteam_artifacts(
                run_dir=run_dir,
                glob_patterns=artifact_globs,
            )
            if not candidates:
                redteam_artifact_failures.append(
                    "red-team status requires adversarial subagent review artifact, none found",
                )
            valid_candidates: set[Path] = set()
            for candidate in candidates:
                try:
                    payload = _load_json(candidate)
                except Exception as exc:  # noqa: BLE001
                    redteam_artifact_failures.append(f"{candidate}: invalid JSON ({exc})")
                    continue
                payload_errors = _validate_redteam_artifact_payload(
                    payload=payload,
                    artifact_path=candidate,
                    day_id=args.day_id,
                    required_fields=required_redteam_fields,
                )
                if payload_errors:
                    redteam_artifact_failures.extend(payload_errors)
                    continue
                valid_candidates.add(candidate.resolve())

            if not valid_candidates:
                redteam_artifact_failures.append(
                    "no valid adversarial subagent red-team artifact passed schema checks",
                )
            else:
                pointer_key = str(
                    redteam_cfg.get("manifest_output_pointer_key")
                    or "red_team_adversarial_review"
                ).strip()
                pointer_raw = str(output_artifacts.get(pointer_key) or "").strip()
                if not pointer_raw:
                    redteam_artifact_failures.append(
                        f"manifest.output_artifacts.{pointer_key} missing",
                    )
                else:
                    pointer_path = _resolve_path(pointer_raw, run_dir, repo_root).resolve()
                    if pointer_path not in valid_candidates:
                        redteam_artifact_failures.append(
                            "manifest red-team pointer does not reference a valid adversarial "
                            "subagent artifact",
                        )
        checks.append(
            _check_result(
                check_id="VAL-REDTEAM-002",
                ok=not redteam_artifact_failures,
                message_ok="Adversarial subagent red-team artifact policy satisfied.",
                message_fail="Adversarial subagent red-team artifact policy violated.",
                expected={
                    "required_statuses": sorted(required_statuses),
                    "artifact_globs": artifact_globs,
                    "required_fields": required_redteam_fields,
                },
                actual=redteam_artifact_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )
        redteam_freshness_failures: list[str] = []
        if isinstance(gate_summary, dict) and isinstance(manifest, dict):
            redteam_freshness_failures = _validate_redteam_freshness(
                run_dir=run_dir,
                repo_root=repo_root,
                profile=profile,
                gate_summary=gate_summary,
                manifest=manifest,
                day_id=args.day_id,
            )
        checks.append(
            _check_result(
                check_id="VAL-REDTEAM-003",
                ok=not redteam_freshness_failures,
                message_ok="Active red-team pointer freshness is valid.",
                message_fail="Active red-team pointer freshness failed.",
                expected=(
                    "active pointer references latest round artifact and subagent id "
                    "matches gate summary when declared"
                ),
                actual=redteam_freshness_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        gov_failures: list[str] = []
        if isinstance(gate_summary, dict) and isinstance(output_artifacts, dict):
            redteam_status = str(gate_summary.get("red_team_status") or "").strip()
            if redteam_status in required_statuses:
                pointer_key = str(
                    redteam_cfg.get("manifest_output_pointer_key")
                    or "red_team_adversarial_review"
                ).strip()
                manifest_redteam_pointer = str(
                    output_artifacts.get(pointer_key) or ""
                ).strip()
                gate_redteam_pointer = str(
                    gate_summary.get("red_team_artifact") or ""
                ).strip()
                if not manifest_redteam_pointer:
                    gov_failures.append(
                        f"manifest.output_artifacts.{pointer_key} missing/empty",
                    )
                if not gate_redteam_pointer:
                    gov_failures.append(
                        "gate_summary.red_team_artifact missing/empty",
                    )
                if (
                    manifest_redteam_pointer
                    and gate_redteam_pointer
                    and manifest_redteam_pointer != gate_redteam_pointer
                ):
                    gov_failures.append(
                        "gate_summary.red_team_artifact does not match manifest "
                        f"output_artifacts.{pointer_key}",
                    )
                gate_verdict = str(gate_summary.get("red_team_verdict") or "").strip()
                if gate_redteam_pointer:
                    redteam_path = _resolve_path(
                        gate_redteam_pointer,
                        run_dir,
                        repo_root,
                    )
                    if not redteam_path.exists():
                        gov_failures.append(
                            "gate_summary.red_team_artifact missing file "
                            f"{gate_redteam_pointer}",
                        )
                    else:
                        try:
                            redteam_payload = _load_json(redteam_path)
                        except Exception as exc:  # noqa: BLE001
                            gov_failures.append(
                                f"gate_summary.red_team_artifact invalid JSON: "
                                f"{redteam_path} ({exc})",
                            )
                        else:
                            artifact_verdict = str(
                                redteam_payload.get("verdict") or ""
                            ).strip()
                            if (
                                gate_verdict
                                and artifact_verdict
                                and gate_verdict != artifact_verdict
                            ):
                                gov_failures.append(
                                    "gate_summary.red_team_verdict does not match "
                                    "red-team artifact verdict",
                                )

                blocker_rows_for_gov = (
                    blockers.get("blockers", [])
                    if isinstance(blockers, dict)
                    else []
                )
                for idx, block in enumerate(blocker_rows_for_gov, start=1):
                    if not isinstance(block, dict):
                        continue
                    blocker_id = str(block.get("blocker_id") or "").strip()
                    scope = str(block.get("blocking_scope") or "").strip()
                    status = str(block.get("status") or "").strip()
                    if "REDTEAM" not in blocker_id:
                        continue
                    if scope != "day_close":
                        continue
                    if status not in {"open", "re-attributed"}:
                        continue
                    evidence_artifact = str(block.get("evidence_artifact") or "").strip()
                    if not evidence_artifact:
                        gov_failures.append(
                            f"blockers[{idx}] {blocker_id} missing evidence_artifact",
                        )
                        continue
                    if gate_redteam_pointer and evidence_artifact != gate_redteam_pointer:
                        gov_failures.append(
                            f"blockers[{idx}] {blocker_id} evidence_artifact does not "
                            "match gate_summary.red_team_artifact",
                        )
        checks.append(
            _check_result(
                check_id="VAL-GOV-001",
                ok=not gov_failures,
                message_ok="Governance pointers are round-consistent and not stale.",
                message_fail="Governance pointers are stale or inconsistent.",
                expected=(
                    "manifest/gate red-team pointers and open day-close red-team blocker "
                    "evidence must be round-consistent"
                ),
                actual=gov_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        canonical_artifact = resolved.get("canonical_policy")
        canon1_failures: list[str] = []
        if workspace_dirty and (
            canonical_artifact is None or canonical_artifact.path is None
        ):
            canon1_failures.append("workspace dirty but canonical policy artifact missing")
        checks.append(
            _check_result(
                check_id="VAL-CANON-001",
                ok=not canon1_failures,
                message_ok="Canonical policy artifact exists when workspace is dirty.",
                message_fail="Canonical policy artifact missing for dirty workspace.",
                artifact_path=(
                    str(canonical_artifact.path)
                    if canonical_artifact and canonical_artifact.path
                    else None
                ),
                expected="canonical policy required when dirty",
                actual=canon1_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        canonical_cfg = profile.get("canonical", {})
        if not isinstance(canonical_cfg, dict):
            canonical_cfg = {}
        markers = [
            str(x).strip()
            for x in canonical_cfg.get("path_markers", ["/canonical/"])
            if str(x).strip()
        ]
        primary_keys = [
            str(x).strip()
            for x in canonical_cfg.get(
                "primary_output_keys",
                DEFAULT_CANONICAL_PRIMARY_OUTPUT_KEYS,
            )
            if str(x).strip()
        ]
        output_artifacts = (
            manifest.get("output_artifacts", {})
            if isinstance(manifest, dict)
            else {}
        )
        if not isinstance(output_artifacts, dict):
            output_artifacts = {}

        canon2_failures: list[str] = []
        if workspace_dirty:
            for key in primary_keys:
                raw_path = str(output_artifacts.get(key) or "").strip()
                if not raw_path:
                    canon2_failures.append(f"missing output_artifacts.{key}")
                    continue
                if not any(marker in raw_path for marker in markers):
                    canon2_failures.append(
                        f"output_artifacts.{key} not routed to canonical path",
                    )
        checks.append(
            _check_result(
                check_id="VAL-CANON-002",
                ok=not canon2_failures,
                message_ok="Primary output pointers are canonical-routed when dirty.",
                message_fail="Primary output pointers are not canonical-routed when dirty.",
                expected={"primary_output_keys": primary_keys, "markers": markers},
                actual=canon2_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        canon3_failures: list[str] = []
        if workspace_dirty:
            for key, raw in output_artifacts.items():
                if "dirty" not in str(key):
                    continue
                p = str(raw or "").strip()
                if not p:
                    canon3_failures.append(f"{key} is empty")
                    continue
                if any(marker in p for marker in markers):
                    canon3_failures.append(
                        f"{key} points to canonical path but should be diagnostic-only",
                    )
        checks.append(
            _check_result(
                check_id="VAL-CANON-003",
                ok=not canon3_failures,
                message_ok="Dirty outputs are diagnostic-only.",
                message_fail="Dirty outputs are not diagnostic-only.",
                expected="dirty* outputs should not route to canonical",
                actual=canon3_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )
        command_log_for_canon = resolved.get("command_log")
        canon4_failures = _validate_canonicalization_provenance(
            workspace_dirty=workspace_dirty,
            run_dir=run_dir,
            profile=profile,
            manifest=manifest if isinstance(manifest, dict) else {},
            command_log_path=(
                command_log_for_canon.path
                if command_log_for_canon is not None
                else None
            ),
        )
        checks.append(
            _check_result(
                check_id="VAL-CANON-004",
                ok=not canon4_failures,
                message_ok="Canonicalization command provenance is valid.",
                message_fail="Canonicalization command provenance is missing/incomplete.",
                expected=(
                    "dirty workspace requires promote_canonical_* exit codes and command "
                    "log evidence for canonical primary outputs"
                ),
                actual=canon4_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        consist_failures: list[str] = []
        if isinstance(gate_summary, dict):
            gs_codes = gate_summary.get("command_exit_codes")
            if isinstance(gs_codes, dict) and isinstance(command_exit_codes, dict):
                for key, expected_raw in command_exit_codes.items():
                    if key not in gs_codes:
                        continue
                    expected = _coerce_int(expected_raw)
                    actual = _coerce_int(gs_codes.get(key))
                    if expected is None or actual is None:
                        continue
                    if expected != actual:
                        consist_failures.append(
                            f"gate_summary.command_exit_codes.{key}={actual} "
                            f"!= manifest.command_exit_codes.{key}={expected}",
                        )
        checks.append(
            _check_result(
                check_id="VAL-CONSIST-001",
                ok=not consist_failures,
                message_ok="Cross-artifact claims are consistent.",
                message_fail="Cross-artifact claims are inconsistent.",
                expected="gate summary exits align with manifest exits where declared",
                actual=consist_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        time_failures: list[str] = []
        for label, payload in (
            ("manifest", manifest),
            ("blocker_register", blockers),
            ("gate_summary", gate_summary),
        ):
            if not isinstance(payload, dict):
                continue
            first_generated = _parse_iso(payload.get("first_generated_at"))
            generated = _parse_iso(payload.get("generated_at"))
            updated = _parse_iso(payload.get("updated_at"))
            if generated and updated and generated > updated:
                time_failures.append(f"{label}: generated_at > updated_at")
            if first_generated and generated and first_generated > generated:
                time_failures.append(f"{label}: first_generated_at > generated_at")
            if first_generated and updated and first_generated > updated:
                time_failures.append(f"{label}: first_generated_at > updated_at")
        checks.append(
            _check_result(
                check_id="VAL-TIME-001",
                ok=not time_failures,
                message_ok="Timestamp fields are non-decreasing.",
                message_fail="Timestamp fields are inconsistent.",
                expected="first_generated_at <= generated_at <= updated_at",
                actual=time_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        prov_failures: list[str] = []
        prov_cfg = profile.get("provenance", {})
        if not isinstance(prov_cfg, dict):
            prov_cfg = {}
        require_dirty_snapshot = _is_truthy(
            prov_cfg.get("require_dirty_snapshot", False),
        )
        if workspace_dirty:
            clean_source = (
                manifest.get("clean_source_verification", {})
                if isinstance(manifest, dict)
                else {}
            )
            if not isinstance(clean_source, dict):
                clean_source = {}
            worktree_path_raw = str(clean_source.get("worktree_info_path") or "").strip()
            if not worktree_path_raw:
                prov_failures.append(
                    "workspace dirty but clean_source_verification.worktree_info_path missing",
                )
            else:
                worktree_path = _resolve_path(worktree_path_raw, run_dir, repo_root)
                if not worktree_path.exists():
                    prov_failures.append(
                        "clean_source_verification.worktree_info_path missing: "
                        f"{worktree_path_raw}",
                    )
                else:
                    worktree = _load_json(worktree_path)
                    manifest_sha = str((git_meta or {}).get("commit_sha") or "").strip()
                    worktree_sha = str(
                        worktree.get("commit_sha")
                        or worktree.get("commit")
                        or ""
                    ).strip()
                    if manifest_sha and worktree_sha and manifest_sha != worktree_sha:
                        prov_failures.append(
                            f"commit mismatch: manifest={manifest_sha} clean_source={worktree_sha}",
                        )
            if require_dirty_snapshot:
                dirty_snapshot_path_raw = str(
                    clean_source.get("dirty_snapshot_path") or ""
                ).strip()
                dirty_snapshot_sha = str(
                    clean_source.get("dirty_snapshot_sha256") or ""
                ).strip()
                if not dirty_snapshot_path_raw:
                    prov_failures.append(
                        "workspace dirty but clean_source_verification.dirty_snapshot_path "
                        "missing",
                    )
                else:
                    dirty_snapshot_path = _resolve_path(
                        dirty_snapshot_path_raw,
                        run_dir,
                        repo_root,
                    )
                    if not dirty_snapshot_path.exists():
                        prov_failures.append(
                            "clean_source_verification.dirty_snapshot_path missing: "
                            f"{dirty_snapshot_path_raw}",
                        )
                    else:
                        if dirty_snapshot_sha:
                            actual_dirty_sha = _sha256_file(dirty_snapshot_path)
                            if actual_dirty_sha != dirty_snapshot_sha:
                                prov_failures.append(
                                    "dirty snapshot sha mismatch: "
                                    f"expected={dirty_snapshot_sha} actual={actual_dirty_sha}",
                                )
                        try:
                            dirty_payload = _load_json(dirty_snapshot_path)
                        except Exception as exc:  # noqa: BLE001
                            prov_failures.append(
                                f"dirty snapshot invalid JSON: {dirty_snapshot_path} ({exc})",
                            )
                        else:
                            schema_version = str(
                                dirty_payload.get("schema_version") or ""
                            ).strip()
                            if schema_version != "dirty-worktree-snapshot-v1":
                                prov_failures.append(
                                    "dirty snapshot schema_version must be "
                                    "dirty-worktree-snapshot-v1",
                                )
                            status_lines = dirty_payload.get("status_porcelain_lines")
                            if not isinstance(status_lines, list):
                                prov_failures.append(
                                    "dirty snapshot status_porcelain_lines must be a list",
                                )
                            status_sha = str(
                                dirty_payload.get("status_porcelain_sha256") or ""
                            ).strip()
                            diff_sha = str(
                                dirty_payload.get("diff_sha256") or ""
                            ).strip()
                            if not status_sha:
                                prov_failures.append(
                                    "dirty snapshot status_porcelain_sha256 missing/empty",
                                )
                            if not diff_sha:
                                prov_failures.append(
                                    "dirty snapshot diff_sha256 missing/empty",
                                )
        checks.append(
            _check_result(
                check_id="VAL-PROV-001",
                ok=not prov_failures,
                message_ok="Commit provenance alignment is valid.",
                message_fail="Commit provenance alignment failed.",
                expected="manifest and clean-source commit SHA alignment when dirty",
                actual=prov_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )
        prov_temporal_failures = _validate_temporal_provenance(
            run_dir=run_dir,
            manifest=manifest if isinstance(manifest, dict) else {},
            profile=profile,
        )
        checks.append(
            _check_result(
                check_id="VAL-PROV-002",
                ok=not prov_temporal_failures,
                message_ok="Temporal provenance ordering is valid.",
                message_fail="Temporal provenance ordering failed.",
                expected=(
                    "adjudicated_at <= attested_at <= manifest/generated artifacts and "
                    "re-audit created_at not before adjudications"
                ),
                actual=prov_temporal_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        gl0_parent_failures: list[str] = []
        if args.day_id == "day1":
            parent_exit = _coerce_int(command_exit_codes.get("edge_case_clause_parent_guardrail"))
            if parent_exit not in (None, 0):
                has_required_blocker = False
                for block in blocker_rows:
                    if not isinstance(block, dict):
                        continue
                    scope = str(block.get("blocking_scope") or "").strip()
                    status = str(block.get("status") or "").strip()
                    owner = str(block.get("owner") or "").strip()
                    eta = str(block.get("eta_utc") or "").strip()
                    hypotheses = block.get("hypotheses")
                    has_hypotheses = isinstance(hypotheses, list) and any(
                        str(x).strip() for x in hypotheses
                    )
                    if (
                        scope == "launch"
                        and status in {"open", "re-attributed"}
                        and owner
                        and eta
                        and has_hypotheses
                    ):
                        has_required_blocker = True
                        break
                if not has_required_blocker:
                    gl0_parent_failures.append(
                        "parent guardrail failed without open launch-scoped blocker "
                        "with owner/eta/hypotheses",
                    )
        checks.append(
            _check_result(
                check_id="VAL-GL0-PARENT-001",
                ok=not gl0_parent_failures,
                message_ok="GL0 parent-guardrail debt registration policy satisfied.",
                message_fail="GL0 parent-guardrail debt registration policy not satisfied.",
                expected="open launch blocker with owner/eta/hypotheses on parent fail",
                actual=gl0_parent_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        # New hard enforcement checks.
        missing_reasoning, field_failures, coverage_failures, field_failure_details = (
            _run_manual_reasoning_checks(run_dir=run_dir, profile=profile)
        )
        checks.append(
            _check_result(
                check_id="VAL-ADJ-REASON-001",
                ok=not missing_reasoning,
                message_ok="Reasoning artifact exists for every adjudication batch.",
                message_fail="Missing or ambiguous manual reasoning artifact(s).",
                expected="manual_reasoning_<batch_id>.jsonl|.md for each batch",
                actual=missing_reasoning,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )
        checks.append(
            _check_result(
                check_id="VAL-ADJ-REASON-002",
                ok=not field_failures,
                message_ok="Reasoning rows contain required fields.",
                message_fail="Reasoning rows missing required fields.",
                expected=list(DEFAULT_REASONING_REQUIRED_FIELDS),
                actual=field_failure_details,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )
        checks.append(
            _check_result(
                check_id="VAL-ADJ-REASON-003",
                ok=not coverage_failures,
                message_ok="Reasoning rows have exact 1:1 row_id coverage with adjudication.",
                message_fail="Reasoning/adjudication row_id coverage mismatch.",
                expected="exact 1:1 row_id mapping",
                actual=[
                    {
                        "batch_path": item.batch_path,
                        "reasoning_path": item.reasoning_path,
                        "missing_row_ids": item.missing_row_ids,
                        "extra_row_ids": item.extra_row_ids,
                    }
                    for item in coverage_failures
                ],
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        queue_link_failures = _validate_queue_linkage(run_dir=run_dir, profile=profile)
        checks.append(
            _check_result(
                check_id="VAL-ADJ-QUEUE-001",
                ok=not queue_link_failures,
                message_ok="Queue linkage updates exist and match adjudication rows.",
                message_fail="Queue linkage updates are missing or inconsistent.",
                expected="queue update rows for each adjudication row with status+adjudication_id",
                actual=queue_link_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        split_failures = _validate_batch_split_homogeneity(run_dir=run_dir, profile=profile)
        checks.append(
            _check_result(
                check_id="VAL-ADJ-SPLIT-001",
                ok=not split_failures,
                message_ok="Adjudication batches are split-homogeneous.",
                message_fail="Adjudication batch contains mixed or missing split data.",
                expected="single split value per batch when split is present/required",
                actual=split_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        command_log_artifact = resolved.get("command_log")
        synthetic_failures: list[str] = []
        lineage_failures: list[str] = []
        if command_log_artifact is None or command_log_artifact.path is None:
            synthetic_failures.append("command_log artifact missing for synthetic-generation check")
        else:
            synthetic_failures = _detect_synthetic_generation(
                command_log_path=command_log_artifact.path,
                run_dir=run_dir,
                profile=profile,
            )
            lineage_failures = _validate_adjudication_lineage_attestation(
                command_log_path=command_log_artifact.path,
                run_dir=run_dir,
                repo_root=repo_root,
                profile=profile,
            )
        adj_synth_failures = [*synthetic_failures, *lineage_failures]
        checks.append(
            _check_result(
                check_id="VAL-ADJ-SYNTH-001",
                ok=not adj_synth_failures,
                message_ok="No synthetic generation and lineage attestation exists.",
                message_fail="Synthetic generation detected or lineage attestation missing.",
                artifact_path=(
                    str(command_log_artifact.path)
                    if command_log_artifact and command_log_artifact.path
                    else None
                ),
                expected=(
                    "no scripted writes to adjudication*.jsonl and "
                    f"{DEFAULT_ADJ_LINEAGE_ATTESTATION_PREFIX} batch attestations present"
                ),
                actual=adj_synth_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        quality_failures, quality_waived = _validate_adjudication_quality(
            run_dir=run_dir,
            profile=profile,
        )
        quality_expected = {
            "enforced": _is_truthy(
                (profile.get("adjudication_quality") or {}).get("require", False)
                if isinstance(profile.get("adjudication_quality"), dict)
                else False,
            )
        }
        if quality_waived:
            quality_expected["waiver"] = "applied"
        checks.append(
            _check_result(
                check_id="VAL-ADJ-QUALITY-001",
                ok=not quality_failures,
                message_ok=(
                    "Adjudication quality heuristics satisfied."
                    if not quality_waived
                    else "Adjudication quality heuristics waived by approved waiver."
                ),
                message_fail="Adjudication quality heuristics failed.",
                expected=quality_expected,
                actual=quality_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )
        export_policy_failures = _validate_adjudication_export_policy(
            run_dir=run_dir,
            profile=profile,
        )
        checks.append(
            _check_result(
                check_id="VAL-ADJ-EXPORT-001",
                ok=not export_policy_failures,
                message_ok="Adjudication export policy is valid.",
                message_fail="Adjudication export policy violated.",
                expected=(
                    "review/abstain rows must not be training-export-eligible unless "
                    "explicit uncertain-export override is present"
                ),
                actual=export_policy_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        migration_failures = _validate_migration_map(
            run_dir=run_dir,
            repo_root=repo_root,
            profile=profile,
        )
        checks.append(
            _check_result(
                check_id="VAL-MIG-001",
                ok=not migration_failures,
                message_ok="Filename migration map hashes are valid.",
                message_fail="Filename migration map is missing or hash-invalid.",
                expected="migration map paths + sha256 fields match on-disk bytes",
                actual=migration_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )
        freeze_failures = _validate_post_validation_freeze(
            run_dir=run_dir,
            profile=profile,
            command_exit_codes=command_exit_codes if isinstance(command_exit_codes, dict) else {},
        )
        checks.append(
            _check_result(
                check_id="VAL-FREEZE-001",
                ok=not freeze_failures,
                message_ok="Post-validation freeze is valid.",
                message_fail="Mutable artifacts changed after final validator anchor.",
                expected=(
                    "no mutable run_dir files modified after validate_day_bundle.exit_code "
                    "anchor"
                ),
                actual=freeze_failures,
                warn_only_ids=warn_only_ids,
                allow_warn_only=args.allow_warn_only,
            )
        )

        selected = [check for check in checks if check.check_id in required_checks]
        failed_ids = [check.check_id for check in selected if check.status == "fail"]
        warning_ids = [check.check_id for check in selected if check.status == "warn"]
        status = "pass" if not failed_ids else "fail"
        summary = {
            "total_checks": len(selected),
            "passed": sum(1 for check in selected if check.status == "pass"),
            "failed": len(failed_ids),
            "warnings": len(warning_ids),
        }

        report = {
            "schema_version": "day-bundle-validator-report-v1",
            "generated_at": generated_at,
            "day_id": args.day_id,
            "run_dir": str(run_dir),
            "status": status,
            "strict_mode": bool(args.strict),
            "profile": {
                "path": str(args.profile.resolve()),
                "id": str(profile.get("profile_id") or ""),
                "version": str(profile.get("profile_version") or ""),
            },
            "summary": summary,
            "checks": [
                {
                    "check_id": check.check_id,
                    "severity": check.severity,
                    "status": check.status,
                    "message": check.message,
                    "artifact_path": check.artifact_path,
                    "expected": check.expected,
                    "actual": check.actual,
                }
                for check in selected
            ],
            "failed_check_ids": failed_ids,
            "warnings": warning_ids,
        }
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": status,
                    "failed_checks": failed_ids,
                    "warnings": warning_ids,
                },
                indent=2,
            )
        )
        return 0 if status == "pass" else 2
    except InputError as exc:
        report = {
            "schema_version": "day-bundle-validator-report-v1",
            "generated_at": generated_at,
            "day_id": args.day_id,
            "run_dir": str(run_dir),
            "status": "fail",
            "summary": {"total_checks": 0, "passed": 0, "failed": 1, "warnings": 0},
            "checks": [
                {
                    "check_id": "VAL-INPUT-001",
                    "severity": "critical",
                    "status": "fail",
                    "message": str(exc),
                    "artifact_path": None,
                    "expected": None,
                    "actual": None,
                }
            ],
            "failed_check_ids": ["VAL-INPUT-001"],
            "warnings": [],
        }
        try:
            json_out.parent.mkdir(parents=True, exist_ok=True)
            json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        print(json.dumps({"status": "fail", "error": str(exc)}, indent=2))
        return 3
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "fail", "error": f"internal_error: {exc}"}, indent=2))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
