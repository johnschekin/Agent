#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=swarm/common.sh
source "$SCRIPT_DIR/common.sh"
require_tmux

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <wave-number> [--session NAME] [--dry-run] [--failed-only] [--include-completed] [--force-restart] [--no-resume] [--max-starts-per-pane N] [--skip-transition-gate] [--transition-scope previous|all-prior] [--completed-statuses CSV] [--waiver-file PATH] [--transition-artifact PATH]" >&2
  exit 1
fi

wave="$1"
shift

session="$(default_session_name)"
dry_run=false
failed_only=false
include_completed=false
force_restart=false
resume_from_checkpoint=true
max_starts_per_pane=1
require_transition_gate=true
transition_scope="previous"
completed_statuses="completed,locked"
waiver_file=""
transition_artifact=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      session="${2:?missing session name}"
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --failed-only)
      failed_only=true
      shift
      ;;
    --include-completed)
      include_completed=true
      shift
      ;;
    --force-restart)
      force_restart=true
      shift
      ;;
    --no-resume)
      resume_from_checkpoint=false
      shift
      ;;
    --max-starts-per-pane)
      max_starts_per_pane="${2:?missing max starts per pane}"
      shift 2
      ;;
    --skip-transition-gate)
      require_transition_gate=false
      shift
      ;;
    --transition-scope)
      transition_scope="${2:?missing transition scope}"
      shift 2
      ;;
    --completed-statuses)
      completed_statuses="${2:?missing completed statuses}"
      shift 2
      ;;
    --waiver-file)
      waiver_file="${2:?missing waiver file path}"
      shift 2
      ;;
    --transition-artifact)
      transition_artifact="${2:?missing transition artifact path}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if ! [[ "$wave" =~ ^[0-9]+$ ]]; then
  echo "Wave number must be an integer: $wave" >&2
  exit 1
fi

if ! [[ "$max_starts_per_pane" =~ ^[0-9]+$ ]] || [[ "$max_starts_per_pane" -lt 1 ]]; then
  echo "--max-starts-per-pane must be a positive integer: $max_starts_per_pane" >&2
  exit 1
fi

if [[ "$require_transition_gate" == "true" && "$wave" -gt 1 ]]; then
  if [[ "$transition_scope" != "previous" && "$transition_scope" != "all-prior" ]]; then
    echo "Invalid --transition-scope: $transition_scope (expected previous|all-prior)" >&2
    exit 1
  fi
  gate_artifact="$transition_artifact"
  if [[ -z "$gate_artifact" ]]; then
    gate_artifact="$(mktemp "/tmp/wave_transition_gate_${wave}_XXXX.json")"
  fi
  gate_cmd=(
    python3 "$ROOT_DIR/scripts/wave_transition_gate.py"
    --conf "$CONF_FILE"
    --workspace-root "$ROOT_DIR/workspaces"
    --target-wave "$wave"
    --scope "$transition_scope"
    --completed-statuses "$completed_statuses"
    --output "$gate_artifact"
    --compact
  )
  if [[ -n "$waiver_file" ]]; then
    gate_cmd+=(--waiver-file "$waiver_file")
  fi
  if ! "${gate_cmd[@]}" >/dev/null 2>&1; then
    gate_reason="$(python3 - "$gate_artifact" <<'PY'
import json
import sys
from pathlib import Path

fp = Path(sys.argv[1])
if not fp.exists():
    print("transition gate failed (artifact missing)")
    raise SystemExit(0)
payload = json.loads(fp.read_text())
decision = payload.get("decision", {})
summary = payload.get("summary", {})
reason = str(decision.get("reason", "transition gate rejected"))
blocked = int(summary.get("blocked_count", 0) or 0)
print(f"{reason} (blocked={blocked})")
PY
)"
    echo "Transition gate failed for wave $wave: $gate_reason" >&2
    echo "Gate artifact: $gate_artifact" >&2
    exit 1
  fi
  echo "Transition gate passed for wave $wave (artifact: $gate_artifact)"
fi

if ! session_exists "$session"; then
  if [[ "$dry_run" == "true" ]]; then
    echo "[dry-run] would launch session: $session"
  else
    "$SCRIPT_DIR/launch.sh" --session "$session" --panes "$(default_panes)"
  fi
fi

count=0
skipped=0
declare -A pane_start_count=()
declare -A pane_running_family=()

if [[ "$force_restart" != "true" ]]; then
  while IFS='|' read -r running_family running_pane running_wave _running_backend _running_whitelist _running_deps; do
    if [[ "$running_wave" != "$wave" ]]; then
      continue
    fi
    running_status="$(checkpoint_status_for_family "$running_family")"
    if [[ "$running_status" == "running" ]] && [[ -z "${pane_running_family[$running_pane]:-}" ]]; then
      pane_running_family["$running_pane"]="$running_family"
    fi
  done < <(config_assignments)
fi

while IFS='|' read -r family pane line_wave backend _whitelist _deps; do
  if [[ "$line_wave" != "$wave" ]]; then
    continue
  fi

  checkpoint_status="$(checkpoint_status_for_family "$family")"
  if [[ "$failed_only" == "true" ]]; then
    case "$checkpoint_status" in
      failed|error|stalled)
        ;;
      *)
        skipped=$((skipped + 1))
        if [[ "$dry_run" == "true" ]]; then
          echo "[dry-run] skip $family (failed-only, status=$checkpoint_status)"
        fi
        continue
        ;;
    esac
  fi

  if [[ "$force_restart" != "true" && "$include_completed" != "true" ]]; then
    case "$checkpoint_status" in
      running)
        skipped=$((skipped + 1))
        if [[ "$dry_run" == "true" ]]; then
          echo "[dry-run] skip $family (status=running)"
        fi
        continue
        ;;
      completed|locked)
        skipped=$((skipped + 1))
        if [[ "$dry_run" == "true" ]]; then
          echo "[dry-run] skip $family (status=$checkpoint_status)"
        fi
        continue
        ;;
      *)
        ;;
    esac
  fi

  if [[ "$force_restart" != "true" ]]; then
    running_on_pane="${pane_running_family[$pane]:-}"
    if [[ -n "$running_on_pane" && "$running_on_pane" != "$family" ]]; then
      skipped=$((skipped + 1))
      if [[ "$dry_run" == "true" ]]; then
        echo "[dry-run] skip $family (pane=$pane busy by running family=$running_on_pane)"
      fi
      continue
    fi
  fi

  started_for_pane="${pane_start_count[$pane]:-0}"
  if [[ "$started_for_pane" -ge "$max_starts_per_pane" ]]; then
    skipped=$((skipped + 1))
    if [[ "$dry_run" == "true" ]]; then
      echo "[dry-run] skip $family (pane=$pane reached max-starts-per-pane=$max_starts_per_pane)"
    fi
    continue
  fi

  dep_state="$(dependency_ready_for_family "$family")"
  if [[ "$dep_state" != "ready" ]]; then
    skipped=$((skipped + 1))
    if [[ "$dry_run" == "true" ]]; then
      echo "[dry-run] skip $family ($dep_state)"
    fi
    continue
  fi

  count=$((count + 1))
  pane_start_count["$pane"]=$((started_for_pane + 1))
  resume_summary="$(checkpoint_resume_summary_for_family "$family" || true)"
  if [[ "$dry_run" == "true" ]]; then
    if [[ -n "$resume_summary" && "$resume_from_checkpoint" == "true" ]]; then
      echo "[dry-run] start $family on pane=$pane backend=${backend:-$(default_backend)} (resume: $resume_summary)"
    else
      echo "[dry-run] start $family on pane=$pane backend=${backend:-$(default_backend)}"
    fi
  else
    if [[ "$resume_from_checkpoint" == "true" ]]; then
      "$SCRIPT_DIR/start-agent.sh" "$family" --session "$session" --pane "$pane" --backend "${backend:-$(default_backend)}"
    else
      "$SCRIPT_DIR/start-agent.sh" "$family" --session "$session" --pane "$pane" --backend "${backend:-$(default_backend)}" --no-resume
    fi
  fi
done < <(config_assignments)

if [[ "$count" -eq 0 ]]; then
  echo "No assignments eligible for wave $wave (skipped=$skipped)."
  exit 1
fi

echo "Dispatched wave $wave with $count family agent(s); skipped=$skipped."
