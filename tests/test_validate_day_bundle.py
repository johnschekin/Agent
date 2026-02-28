from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_day_bundle.py"
PROFILE = ROOT / "config" / "day_bundle_validator" / "day2_day5_governance_profile.json"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_bundle(
    tmp_path: Path,
    *,
    include_reasoning: bool = True,
    mismatch_reasoning_ids: bool = False,
    synthetic_command: bool = False,
    red_team_status: str = "not_started",
    include_adversarial_redteam_artifact: bool = False,
) -> tuple[Path, Path]:
    run_dir = tmp_path / "day2_bundle"
    run_dir.mkdir(parents=True, exist_ok=True)

    output_artifacts: dict[str, object] = {
        "day_validator_report_primary": "canonical/day_validator_report.json",
        "adjudication_validation_report_primary": (
            "canonical/adjudication/manual_adjudication_validation_report.json"
        ),
        "red_team_adversarial_review_primary": (
            "canonical/red_team/adversarial_subagent_review_day2.json"
        ),
    }
    if include_adversarial_redteam_artifact:
        output_artifacts["red_team_adversarial_review"] = (
            "red_team/adversarial_subagent_review_day2.json"
        )

    _write_json(
        run_dir / "day_run_manifest.json",
        {
            "schema_version": "day-run-manifest-v1",
            "generated_at": "2026-02-27T12:00:00+00:00",
            "updated_at": "2026-02-27T12:01:00+00:00",
            "git": {"commit_sha": "abc123", "is_dirty": False},
            "parser": {"version": "0.1.0"},
            "inputs": {"source": "test"},
            "command_exit_codes": {"cmd_ok": 0},
            "output_artifacts": output_artifacts,
        },
    )
    _write_json(
        run_dir / "day_blocker_register.json",
        {
            "schema_version": "day-blocker-register-v1",
            "generated_at": "2026-02-27T12:00:00+00:00",
            "updated_at": "2026-02-27T12:00:00+00:00",
            "blockers": [
                {
                    "blocker_id": "BLK-1",
                    "status": "open",
                    "blocking_scope": "day_close",
                    "owner": "owner",
                    "eta_utc": "2026-02-28T00:00:00Z",
                    "hypotheses": ["h1"],
                }
            ],
        },
    )
    gate_summary: dict[str, object] = {
        "schema_version": "day-gate-summary-v1",
        "generated_at": "2026-02-27T12:00:00+00:00",
        "updated_at": "2026-02-27T12:00:30+00:00",
        "status": "pass",
        "red_team_status": red_team_status,
        "validator_passed": True,
        "validator_exit_code": 0,
        "command_exit_codes": {"cmd_ok": 0},
    }
    if include_adversarial_redteam_artifact and red_team_status in {"in_review", "complete"}:
        gate_summary["red_team_artifact"] = "red_team/adversarial_subagent_review_day2.json"
        gate_summary["red_team_verdict"] = "partial_pass"

    _write_json(run_dir / "day_gate_summary.json", gate_summary)

    _write_json(
        run_dir / "adjudication" / "manual_adjudication_validation_report.json",
        {
            "schema_version": "manual-adjudication-validator-report-v1",
            "status": "pass",
            "row_count": 2,
            "errors": [],
        },
    )

    _write_json(
        run_dir / "canonical" / "day_validator_report.json",
        {
            "schema_version": "day-bundle-validator-report-v1",
            "status": "pass",
            "day_id": "day2",
        },
    )
    _write_json(
        run_dir / "canonical" / "adjudication" / "manual_adjudication_validation_report.json",
        {
            "schema_version": "manual-adjudication-validator-report-v1",
            "status": "pass",
            "row_count": 2,
            "errors": [],
        },
    )
    canonical_redteam_payload = {
        "schema_version": "red-team-adversarial-subagent-review-v1",
        "day_id": "day2",
        "review_mode": "adversarial_subagent",
        "subagent_id": "agent-redteam-canonical",
        "adversarial_findings": [
            {
                "severity": "low",
                "summary": "canonical placeholder",
            }
        ],
        "verdict": "partial_pass",
        "completed_at": "2026-02-27T12:03:00+00:00",
    }
    _write_json(
        run_dir / "canonical" / "red_team" / "adversarial_subagent_review_day2.json",
        canonical_redteam_payload,
    )

    if include_adversarial_redteam_artifact:
        _write_json(
            run_dir / "red_team" / "adversarial_subagent_review_day2.json",
            {
                "schema_version": "red-team-adversarial-subagent-review-v1",
                "day_id": "day2",
                "review_mode": "adversarial_subagent",
                "subagent_id": "agent-redteam-001",
                "adversarial_findings": [
                    {
                        "severity": "high",
                        "summary": "example finding",
                    }
                ],
                "verdict": "partial_pass",
                "completed_at": "2026-02-27T12:03:00+00:00",
            },
        )
    batch_path = run_dir / "adjudication" / "manual_adjudication_batch_test20.jsonl"
    _write_jsonl(
        batch_path,
        [
            {
                "row_id": "row-1",
                "queue_item_id": "Q-0001",
                "adjudication_id": "ADJ-0001",
                "split": "train",
                "decision": "accepted",
            },
            {
                "row_id": "row-2",
                "queue_item_id": "Q-0002",
                "adjudication_id": "ADJ-0002",
                "split": "train",
                "decision": "review",
            },
        ],
    )

    _write_jsonl(
        run_dir / "adjudication" / "p0_adjudication_queue_updates_test20.jsonl",
        [
            {
                "queue_item_id": "Q-0001",
                "status": "accepted",
                "adjudication_id": "ADJ-0001",
            },
            {
                "queue_item_id": "Q-0002",
                "status": "review",
                "adjudication_id": "ADJ-0002",
            },
        ],
    )

    legacy_alias_path = run_dir / "adjudication" / "legacy_alias_test20.jsonl"
    legacy_alias_path.write_text(batch_path.read_text(encoding="utf-8"), encoding="utf-8")

    if include_reasoning:
        reasoning_rows = [
            {
                "row_id": "row-1",
                "witness": "Primary accepted clause evidence with concrete span support.",
                "hypothesis_A": "Accepted determination is supportable.",
                "hypothesis_B": "Review is unnecessary on this row.",
                "why_A_survives": (
                    "The witness text directly supports accepted status with no conflict."
                ),
                "why_B_survives": (
                    "Counter-hypothesis lacks contradictory indicators in the same span."
                ),
                "final_decision": "accepted",
                "confidence": "high",
            },
            {
                "row_id": "row-2",
                "witness": "Secondary row has ambiguity requiring explicit review evidence.",
                "hypothesis_A": "Review status is appropriate for unresolved ambiguity.",
                "hypothesis_B": "Accepted status would overstate certainty.",
                "why_A_survives": (
                    "Competing indicators remain unresolved and justify review routing."
                ),
                "why_B_survives": (
                    "Accepted hypothesis fails because structural evidence is incomplete."
                ),
                "final_decision": "review",
                "confidence": "medium",
            },
        ]
        if mismatch_reasoning_ids:
            reasoning_rows = reasoning_rows[:1]
        _write_jsonl(
            run_dir / "adjudication" / "manual_reasoning_test20.jsonl",
            reasoning_rows,
        )

    command_lines = []
    if synthetic_command:
        command_lines.append(
            "cat > artifacts/launch_run_2026-02-27_day2/adjudication/"
            "manual_adjudication_batch_test20.jsonl <<'JSONL'"
        )
    else:
        batch_rel = "adjudication/manual_adjudication_batch_test20.jsonl"
        reason_rel = "adjudication/manual_reasoning_test20.jsonl"
        queue_rel = "adjudication/p0_adjudication_queue_updates_test20.jsonl"
        command_lines.append(
            "MANUAL_ADJ_LINEAGE "
            f"artifact={batch_rel} sha256={_sha256(batch_path)} "
            "action=manual_row_entry writer=tester ts=2026-02-27T12:01:00+00:00"
        )
        if include_reasoning:
            command_lines.append(
                "MANUAL_ADJ_LINEAGE "
                f"artifact={reason_rel} "
                f"sha256={_sha256(run_dir / reason_rel)} "
                "action=manual_row_reasoning writer=tester ts=2026-02-27T12:01:30+00:00"
            )
        command_lines.append(
            "MANUAL_ADJ_LINEAGE "
            f"artifact={queue_rel} "
            f"sha256={_sha256(run_dir / queue_rel)} "
            "action=queue_update writer=tester ts=2026-02-27T12:02:00+00:00"
        )
        command_lines.append(
            "MANUAL_ADJUDICATION_ATTESTATION batch_id=test20 rows=2 "
            "method=row_by_row_manual_reasoning"
        )
        command_lines.append(
            "python3 scripts/validate_manual_adjudication_log.py --log "
            "run/adjudication/manual_adjudication_batch_test20.jsonl --json"
        )
    command_log_path = run_dir / "command_log.txt"
    command_log_path.write_text(
        "\n".join(command_lines) + "\n",
        encoding="utf-8",
    )
    (run_dir / "cmd_ok.exit_code").write_text("0\n", encoding="utf-8")

    if not synthetic_command and include_reasoning:
        reasoning_path = run_dir / "adjudication" / "manual_reasoning_test20.jsonl"
        _write_json(
            run_dir / "adjudication" / "manual_adjudication_attestation_test20.json",
            {
                "schema_version": "manual-adjudication-attestation-v1",
                "batch_id": "test20",
                "batch_path": "adjudication/manual_adjudication_batch_test20.jsonl",
                "batch_sha256": _sha256(batch_path),
                "reasoning_path": "adjudication/manual_reasoning_test20.jsonl",
                "reasoning_sha256": _sha256(reasoning_path),
                "command_log_path": "command_log.txt",
                "command_log_sha256": _sha256(command_log_path),
                "queue_update_path": "adjudication/p0_adjudication_queue_updates_test20.jsonl",
                "queue_update_sha256": _sha256(
                    run_dir / "adjudication" / "p0_adjudication_queue_updates_test20.jsonl"
                ),
                "attestor_id": "tester",
                "attested_at": "2026-02-27T12:02:00+00:00",
            },
        )

    _write_json(
        run_dir / "adjudication" / "filename_migration_map_round2_to_test20.json",
        {
            "schema_version": "artifact-filename-migration-map-v1",
            "generated_at": "2026-02-27T12:03:00+00:00",
            "mappings": [
                {
                    "old_path": "adjudication/legacy_alias_test20.jsonl",
                    "new_path": "adjudication/manual_adjudication_batch_test20.jsonl",
                    "old_sha256": _sha256(legacy_alias_path),
                    "new_sha256": _sha256(batch_path),
                }
            ],
        },
    )

    unique_index_paths = sorted(
        {
            p.resolve()
            for p in run_dir.rglob("*")
            if p.is_file() and p.name != "artifact_index.json"
        }
    )
    _write_json(
        run_dir / "artifact_index.json",
        {
            "schema_version": "day-artifact-index-v1",
            "artifacts": [
                {
                    "id": path.name,
                    "path": str(path.relative_to(run_dir)),
                    "sha256": _sha256(path),
                }
                for path in unique_index_paths
            ],
        },
    )

    json_out = run_dir / "day_validator_report.json"
    return run_dir, json_out


def _run_validator(run_dir: Path, json_out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-dir",
            str(run_dir),
            "--day-id",
            "day2",
            "--profile",
            str(PROFILE),
            "--strict",
            "--json-out",
            str(json_out),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def test_validator_passes_with_reasoning_and_coverage(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path)
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["failed_check_ids"] == []


def test_validator_fails_when_reasoning_file_missing(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path, include_reasoning=False)
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-ADJ-REASON-001" in report["failed_check_ids"]


def test_validator_fails_on_reasoning_coverage_mismatch(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path, mismatch_reasoning_ids=True)
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-ADJ-REASON-003" in report["failed_check_ids"]


def test_validator_fails_when_reasoning_text_is_too_short(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path)
    reasoning_path = run_dir / "adjudication" / "manual_reasoning_test20.jsonl"
    rows = [
        json.loads(line)
        for line in reasoning_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    rows[0]["witness"] = "short"
    _write_jsonl(reasoning_path, rows)
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-ADJ-REASON-002" in report["failed_check_ids"]


def test_validator_fails_when_reasoning_final_decision_mismatch(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path)
    reasoning_path = run_dir / "adjudication" / "manual_reasoning_test20.jsonl"
    rows = [
        json.loads(line)
        for line in reasoning_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    rows[1]["final_decision"] = "accepted"
    _write_jsonl(reasoning_path, rows)
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-ADJ-REASON-002" in report["failed_check_ids"]


def test_validator_fails_on_synthetic_generation_pattern(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path, synthetic_command=True)
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-ADJ-SYNTH-001" in report["failed_check_ids"]


def test_validator_fails_on_manual_only_script_targeting_protected_artifact(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path)
    command_log = run_dir / "command_log.txt"
    command_log.write_text(
        command_log.read_text(encoding="utf-8")
        + "python3 -c \"print('mutate')\" adjudication/manual_reasoning_test20.jsonl\n",
        encoding="utf-8",
    )
    attestation_path = run_dir / "adjudication" / "manual_adjudication_attestation_test20.json"
    payload = json.loads(attestation_path.read_text(encoding="utf-8"))
    payload["command_log_sha256"] = _sha256(command_log)
    _write_json(attestation_path, payload)
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-ADJ-SYNTH-001" in report["failed_check_ids"]


def test_validator_fails_when_lineage_attestation_missing(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path)
    (run_dir / "command_log.txt").write_text(
        "python3 scripts/validate_manual_adjudication_log.py --log "
        "run/adjudication/manual_adjudication_batch_test20.jsonl --json\n",
        encoding="utf-8",
    )
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-ADJ-SYNTH-001" in report["failed_check_ids"]


def test_validator_fails_when_queue_linkage_missing(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path)
    (run_dir / "adjudication" / "p0_adjudication_queue_updates_test20.jsonl").unlink()
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-ADJ-QUEUE-001" in report["failed_check_ids"]


def test_validator_fails_on_mixed_split_batch(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path)
    batch_path = run_dir / "adjudication" / "manual_adjudication_batch_test20.jsonl"
    rows = [
        json.loads(line)
        for line in batch_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    rows[1]["split"] = "val"
    _write_jsonl(batch_path, rows)
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-ADJ-SPLIT-001" in report["failed_check_ids"]


def test_validator_fails_on_uncertain_training_export_policy(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path)
    batch_path = run_dir / "adjudication" / "manual_adjudication_batch_test20.jsonl"
    rows = [
        json.loads(line)
        for line in batch_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    rows[1]["training_export_eligible"] = True
    _write_jsonl(batch_path, rows)
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-ADJ-EXPORT-001" in report["failed_check_ids"]


def test_validator_requires_red_team_status_enum(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path, red_team_status="started")
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-REDTEAM-001" in report["failed_check_ids"]


def test_validator_requires_adversarial_redteam_artifact_on_complete(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path, red_team_status="complete")
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-REDTEAM-002" in report["failed_check_ids"]


def test_validator_accepts_complete_with_adversarial_redteam_artifact(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(
        tmp_path,
        red_team_status="complete",
        include_adversarial_redteam_artifact=True,
    )
    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-REDTEAM-002" not in report["failed_check_ids"]


def test_validator_fails_when_primary_output_not_in_artifact_index(tmp_path: Path) -> None:
    run_dir, json_out = _build_bundle(tmp_path)
    index_path = run_dir / "artifact_index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["artifacts"] = [
        item
        for item in payload.get("artifacts", [])
        if item.get("path")
        != "canonical/adjudication/manual_adjudication_validation_report.json"
    ]
    _write_json(index_path, payload)

    proc = _run_validator(run_dir, json_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert "VAL-INDEX-002" in report["failed_check_ids"]
