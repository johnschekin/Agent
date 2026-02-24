#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SWARM_DIR="$ROOT_DIR/swarm"
CONF_FILE="${SWARM_CONF:-$SWARM_DIR/swarm.conf}"

require_tmux() {
  if ! command -v tmux >/dev/null 2>&1; then
    echo "Error: tmux is required but not found in PATH." >&2
    exit 1
  fi
}

_conf_value() {
  local key="$1"
  if [[ ! -f "$CONF_FILE" ]]; then
    return 0
  fi
  awk -F= -v k="$key" '
    $0 ~ "^[[:space:]]*" k "=" {
      sub(/^[[:space:]]*/, "", $2);
      sub(/[[:space:]]*$/, "", $2);
      print $2;
      exit
    }
  ' "$CONF_FILE"
}

default_session_name() {
  local v
  v="$(_conf_value "SESSION_NAME")"
  echo "${v:-agent-swarm}"
}

default_backend() {
  local v
  v="$(_conf_value "DEFAULT_BACKEND")"
  echo "${v:-opus46}"
}

default_panes() {
  local v
  v="$(_conf_value "DEFAULT_PANES")"
  if [[ -n "$v" ]]; then
    echo "$v"
  else
    echo "4"
  fi
}

startup_wait_seconds() {
  local v
  v="$(_conf_value "STARTUP_WAIT_SECONDS")"
  if [[ -n "$v" ]]; then
    echo "$v"
  else
    echo "2"
  fi
}

config_assignments() {
  if [[ ! -f "$CONF_FILE" ]]; then
    return 0
  fi
  awk '
    /^[[:space:]]*#/ {next}
    /^[[:space:]]*$/ {next}
    index($0, "=") > 0 {next}
    index($0, "|") > 0 {print $0}
  ' "$CONF_FILE"
}

assignment_for_family() {
  local family="$1"
  config_assignments | awk -F'|' -v fam="$family" '$1 == fam {print $0; exit}'
}

checkpoint_file_for_family() {
  local family="$1"
  echo "$ROOT_DIR/workspaces/$family/checkpoint.json"
}

checkpoint_status_for_family() {
  local family="$1"
  local checkpoint
  checkpoint="$(checkpoint_file_for_family "$family")"
  if [[ ! -f "$checkpoint" ]]; then
    echo "missing"
    return 0
  fi
  python3 - "$checkpoint" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text())
except Exception:
    print("invalid")
    raise SystemExit(0)
status = str(payload.get("status", "")).strip().lower()
print(status or "initialized")
PY
}

checkpoint_resume_summary_for_family() {
  local family="$1"
  local checkpoint
  checkpoint="$(checkpoint_file_for_family "$family")"
  if [[ ! -f "$checkpoint" ]]; then
    return 0
  fi
  python3 - "$checkpoint" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text())
except Exception:
    raise SystemExit(0)

status = str(payload.get("status", "")).strip() or "initialized"
iteration = payload.get("iteration_count", 0)
concept = str(
    payload.get("current_concept_id")
    or payload.get("last_concept_id")
    or ""
).strip()
version = payload.get("last_strategy_version", 0)
coverage = payload.get("last_coverage_hit_rate", None)
last_update = str(payload.get("last_update", "")).strip()

parts = [f"status={status}", f"iteration={iteration}", f"strategy_v={version}"]
if concept:
    parts.append(f"concept={concept}")
if coverage is not None:
    parts.append(f"coverage={coverage}")
if last_update:
    parts.append(f"updated={last_update}")
print(", ".join(parts))
PY
}

dependency_list_for_assignment() {
  local line="$1"
  IFS='|' read -r _family _pane _wave _backend _whitelist deps <<<"$line"
  echo "${deps:-}"
}

dependency_ready_for_family() {
  local family="$1"
  local assignment
  assignment="$(assignment_for_family "$family" || true)"
  if [[ -z "$assignment" ]]; then
    echo "missing_assignment"
    return 0
  fi
  local deps
  deps="$(dependency_list_for_assignment "$assignment")"
  if [[ -z "$deps" ]]; then
    echo "ready"
    return 0
  fi
  IFS=',' read -r -a dep_arr <<<"$deps"
  for dep in "${dep_arr[@]}"; do
    dep="$(echo "$dep" | xargs)"
    if [[ -z "$dep" ]]; then
      continue
    fi
    dep_status="$(checkpoint_status_for_family "$dep")"
    case "$dep_status" in
      completed|locked)
        ;;
      *)
        echo "blocked:$dep:$dep_status"
        return 0
        ;;
    esac
  done
  echo "ready"
}

session_exists() {
  local session="$1"
  tmux has-session -t "$session" >/dev/null 2>&1
}

session_first_window_index() {
  local session="$1"
  tmux list-windows -t "$session" -F "#{window_index}" | head -n 1
}

session_first_window_target() {
  local session="$1"
  local win
  win="$(session_first_window_index "$session" 2>/dev/null || true)"
  if [[ -z "$win" ]]; then
    return 1
  fi
  echo "$session:$win"
}

pane_target_for_logical_index() {
  local session="$1"
  local logical_index="$2"
  local window_target
  window_target="$(session_first_window_target "$session" 2>/dev/null || true)"
  if [[ -z "$window_target" ]]; then
    return 1
  fi
  if [[ "$logical_index" -lt 0 ]]; then
    return 1
  fi
  mapfile -t pane_ids < <(tmux list-panes -t "$window_target" -F "#{pane_id}")
  if [[ "$logical_index" -ge "${#pane_ids[@]}" ]]; then
    return 1
  fi
  echo "${pane_ids[$logical_index]}"
}

pane_exists() {
  local target="$1"
  tmux list-panes -t "$target" >/dev/null 2>&1
}

backend_command() {
  local backend="$1"
  case "$backend" in
    opus46)
      echo "claude --model opus-4.6 --dangerously-skip-permissions"
      ;;
    claude)
      echo "claude --dangerously-skip-permissions"
      ;;
    codex)
      echo "codex"
      ;;
    gemini)
      echo "gemini"
      ;;
    *)
      echo "$backend"
      ;;
  esac
}

compose_prompt_file() {
  local family="$1"
  local out_file="$2"
  local pieces=(
    "$SWARM_DIR/prompts/common-rules.md"
    "$SWARM_DIR/prompts/platform-conventions.md"
    "$SWARM_DIR/prompts/family_agent_base.md"
    "$SWARM_DIR/prompts/enrichment/${family}.md"
    "$SWARM_DIR/prompts/${family}.md"
  )

  : > "$out_file"
  for fp in "${pieces[@]}"; do
    if [[ -f "$fp" ]]; then
      cat "$fp" >> "$out_file"
      printf "\n\n" >> "$out_file"
    fi
  done
}
