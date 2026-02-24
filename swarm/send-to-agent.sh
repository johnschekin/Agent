#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=swarm/common.sh
source "$SCRIPT_DIR/common.sh"
require_tmux

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <family-name> \"<message>\" [--session NAME]" >&2
  exit 1
fi

family="$1"
message="$2"
shift 2

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

assignment="$(assignment_for_family "$family" || true)"
if [[ -z "$assignment" ]]; then
  echo "Family not configured in swarm.conf: $family" >&2
  exit 1
fi
IFS='|' read -r _family pane _wave _backend _whitelist _deps <<<"$assignment"
target="$(pane_target_for_logical_index "$session" "$pane" || true)"

if [[ -z "$target" ]] || ! pane_exists "$target"; then
  echo "Pane not found for logical index $pane in session $session" >&2
  exit 1
fi

tmp="$(mktemp "/tmp/agent_send_${family}_XXXXXX.txt")"
printf "%s" "$message" >"$tmp"
tmux load-buffer "$tmp"
tmux paste-buffer -t "$target"
tmux send-keys -t "$target" C-m
rm -f "$tmp"

echo "Message sent to '$family' ($target)"
