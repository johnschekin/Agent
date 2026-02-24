#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=swarm/common.sh
source "$SCRIPT_DIR/common.sh"
require_tmux

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <family-name> [--backend BACKEND] [--pane N] [--session NAME] [--no-resume]" >&2
  exit 1
fi

family="$1"
shift

session="$(default_session_name)"
backend=""
pane=""
resume_from_checkpoint=true
assignment="$(assignment_for_family "$family" || true)"
if [[ -n "$assignment" ]]; then
  IFS='|' read -r _family pane_from_conf _wave backend_from_conf whitelist_from_conf _deps_from_conf <<<"$assignment"
else
  pane_from_conf=""
  backend_from_conf=""
  whitelist_from_conf=""
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend)
      backend="${2:?missing backend}"
      shift 2
      ;;
    --pane)
      pane="${2:?missing pane index}"
      shift 2
      ;;
    --session)
      session="${2:?missing session name}"
      shift 2
      ;;
    --no-resume)
      resume_from_checkpoint=false
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$pane" ]]; then
  pane="${pane_from_conf:-0}"
fi
if [[ -z "$backend" ]]; then
  backend="${backend_from_conf:-$(default_backend)}"
fi
whitelist_csv="${whitelist_from_conf:-}"

if ! session_exists "$session"; then
  echo "Session not found: $session" >&2
  echo "Create it first with: $SCRIPT_DIR/launch.sh --session $session" >&2
  exit 1
fi

target="$(pane_target_for_logical_index "$session" "$pane" || true)"
if [[ -z "$target" ]]; then
  echo "Pane not found for logical index $pane in session $session" >&2
  window_target="$(session_first_window_target "$session" || true)"
  if [[ -n "$window_target" ]]; then
    echo "Available panes in $window_target:" >&2
    tmux list-panes -t "$window_target" -F "  tmux_index=#{pane_index} pane_id=#{pane_id}" >&2 || true
  fi
  exit 1
fi

agent_cmd="$(backend_command "$backend")"
prompt_file="$(mktemp "/tmp/agent_swarm_${family}_XXXXXX.md")"
compose_prompt_file "$family" "$prompt_file"

workspace_dir="$ROOT_DIR/workspaces/$family"
mkdir -p "$workspace_dir"
checkpoint_file="$workspace_dir/checkpoint.json"
if [[ ! -f "$checkpoint_file" ]]; then
  cat >"$checkpoint_file" <<EOF
{"family":"$family","iteration_count":0,"last_strategy_version":0,"last_update":"$(date -u +"%Y-%m-%dT%H:%M:%SZ")","status":"initialized"}
EOF
fi

if [[ "$resume_from_checkpoint" == "true" ]]; then
  resume_summary="$(checkpoint_resume_summary_for_family "$family" || true)"
  if [[ -n "$resume_summary" ]]; then
    {
      echo "## Resume Context"
      echo "You are resuming prior work from checkpoint metadata:"
      echo "- $resume_summary"
      echo "Resume from this state instead of restarting from scratch."
      echo
    } >> "$prompt_file"
  fi
fi

python3 - "$checkpoint_file" "$session" "$pane" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
session = sys.argv[2]
pane = sys.argv[3]

payload = {}
if path.exists():
    try:
        payload = json.loads(path.read_text())
    except Exception:
        payload = {}

payload["status"] = "running"
payload["family"] = str(payload.get("family") or "")
payload["last_session"] = session
payload["last_pane"] = pane
payload["last_start_at"] = datetime.now(timezone.utc).isoformat()
payload["last_update"] = payload["last_start_at"]

path.write_text(json.dumps(payload, indent=2))
PY

tmux send-keys -t "$target" C-c
tmux send-keys -t "$target" "cd '$ROOT_DIR'" C-m
tmux send-keys -t "$target" "unset CLAUDECODE" C-m
tmux send-keys -t "$target" "export AGENT_FAMILY='$family'" C-m
tmux send-keys -t "$target" "export AGENT_CONCEPT_WHITELIST='$whitelist_csv'" C-m
tmux send-keys -t "$target" "export AGENT_PROMPT_FILE='$prompt_file'" C-m
tmux send-keys -t "$target" "$agent_cmd" C-m

sleep "$(startup_wait_seconds)"
tmux load-buffer "$prompt_file"
tmux paste-buffer -t "$target"
tmux send-keys -t "$target" C-m

echo "Started family '$family' on $target using backend '$backend'"
echo "Prompt file: $prompt_file"
