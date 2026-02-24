#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=swarm/common.sh
source "$SCRIPT_DIR/common.sh"
require_tmux

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 \"<message>\" [--session NAME]" >&2
  exit 1
fi

message="$1"
shift
session="$(default_session_name)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      session="${2:?missing session name}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if ! session_exists "$session"; then
  echo "Session not found: $session" >&2
  exit 1
fi

tmp="$(mktemp "/tmp/agent_broadcast_XXXXXX.txt")"
printf "%s" "$message" >"$tmp"

while IFS='|' read -r family pane _wave _backend _whitelist _deps; do
  target="$(pane_target_for_logical_index "$session" "$pane" || true)"
  if [[ -n "$target" ]] && pane_exists "$target"; then
    tmux load-buffer "$tmp"
    tmux paste-buffer -t "$target"
    tmux send-keys -t "$target" C-m
    echo "Broadcast sent to $family ($target)"
  fi
done < <(config_assignments)

rm -f "$tmp"
