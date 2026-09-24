#!/usr/bin/env bash
# Print the type of the active local graphical session on the remote host:
# "wayland", "x11", or "unknown". Used to gate compositor-specific steps.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec "${script_dir}/remote_exec.sh" bash -s <<'REMOTE'
set -uo pipefail
while read -r id _; do
  [[ -n "$id" ]] || continue
  type="$(loginctl show-session "$id" -p Type --value 2>/dev/null || true)"
  state="$(loginctl show-session "$id" -p State --value 2>/dev/null || true)"
  remote="$(loginctl show-session "$id" -p Remote --value 2>/dev/null || true)"
  if [[ ( "$type" == wayland || "$type" == x11 ) && "$state" == active && "$remote" == no ]]; then
    printf '%s' "$type"
    exit 0
  fi
done < <(loginctl list-sessions --no-legend)
printf 'unknown'
REMOTE
