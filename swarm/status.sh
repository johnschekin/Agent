#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=swarm/common.sh
source "$SCRIPT_DIR/common.sh"
require_tmux

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
  echo "Session not found: $session"
  exit 0
fi

window_target="$(session_first_window_target "$session" || true)"
if [[ -z "$window_target" ]]; then
  echo "No windows found in session: $session" >&2
  exit 1
fi

echo "Session: $session"
echo "Window: $window_target"
echo "PaneStatus:"
printf "%-8s %-8s %-16s %-16s %-8s %s\n" "logical" "tmux" "title" "command" "pid" "last_line"
logical=0
while IFS='|' read -r pane_id pane_index title cmd pid; do
  last_line="$(tmux capture-pane -p -t "$pane_id" | tail -n 1 | tr -d '\r')"
  printf "%-8s %-8s %-16s %-16s %-8s %s\n" "$logical" "$pane_index" "$title" "$cmd" "$pid" "$last_line"
  logical=$((logical + 1))
done < <(tmux list-panes -t "$window_target" -F "#{pane_id}|#{pane_index}|#{pane_title}|#{pane_current_command}|#{pane_pid}")

echo
echo "FamilyAssignments:"
printf "%-24s %-6s %-6s %-10s %-12s %-36s %s\n" "family" "pane" "wave" "backend" "checkpoint" "whitelist" "depends_on"
while IFS='|' read -r family pane wave backend whitelist deps; do
  checkpoint_status="$(checkpoint_status_for_family "$family")"
  printf "%-24s %-6s %-6s %-10s %-12s %-36s %s\n" "$family" "$pane" "$wave" "$backend" "$checkpoint_status" "$whitelist" "${deps:-}"
done < <(config_assignments)
