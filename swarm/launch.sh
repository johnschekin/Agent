#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=swarm/common.sh
source "$SCRIPT_DIR/common.sh"
require_tmux

session="$(default_session_name)"
panes="$(default_panes)"
workdir="$ROOT_DIR"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      session="${2:?missing session name}"
      shift 2
      ;;
    --panes)
      panes="${2:?missing pane count}"
      shift 2
      ;;
    --workdir)
      workdir="${2:?missing workdir path}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--session NAME] [--panes N] [--workdir PATH]" >&2
      exit 1
      ;;
  esac
done

if [[ "$panes" -lt 1 ]]; then
  echo "Error: --panes must be >= 1" >&2
  exit 1
fi

if session_exists "$session"; then
  echo "Session already exists: $session" >&2
  exit 0
fi

tmux new-session -d -s "$session" -n swarm -c "$workdir"
window_target="$(session_first_window_target "$session")"
for ((i = 1; i < panes; i++)); do
  tmux split-window -t "$window_target" -c "$workdir"
  tmux select-layout -t "$window_target" tiled >/dev/null
done

i=0
while IFS='|' read -r pane_id _pane_index; do
  tmux select-pane -t "$pane_id" -T "agent-$i"
  i=$((i + 1))
done < <(tmux list-panes -t "$window_target" -F "#{pane_id}|#{pane_index}")

if [[ "$i" -ne "$panes" ]]; then
  echo "Warning: expected $panes panes but found $i in $window_target" >&2
fi

echo "Launched tmux session '$session' with $panes pane(s) in $workdir"
echo "Attach with: tmux attach -t $session"
