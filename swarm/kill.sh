#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=swarm/common.sh
source "$SCRIPT_DIR/common.sh"
require_tmux

session="$(default_session_name)"
broadcast_first=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      session="${2:?missing session name}"
      shift 2
      ;;
    --no-broadcast)
      broadcast_first=false
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if ! session_exists "$session"; then
  echo "Session not found: $session"
  exit 0
fi

if [[ "$broadcast_first" == "true" ]]; then
  "$SCRIPT_DIR/broadcast.sh" "Please commit WIP and stop. Session shutdown in progress." --session "$session" || true
fi

tmux kill-session -t "$session"
echo "Killed session: $session"
