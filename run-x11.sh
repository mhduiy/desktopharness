#!/bin/bash
# Start the AutoUI MCP server inside the live graphical session.
#
# The model key is read from .env.local (0600) instead of being passed on the
# command line, so it never shows up in `ps` output.
set -euo pipefail
cd "$(dirname "$0")"

pid="$(pgrep -u "$(id -un)" -x kwin_x11 | head -1)"
if [ -z "$pid" ]; then
  echo "no kwin_x11 session for $(id -un); is the graphical session up?" >&2
  exit 1
fi
mapfile -t envs < <(tr '\0' '\n' < "/proc/$pid/environ" \
  | grep -E '^(DISPLAY|XAUTHORITY|XDG_RUNTIME_DIR|DBUS_SESSION_BUS_ADDRESS)=')

if [ -f .env.local ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.local
  set +a
fi

pkill -f 'treeland-autogui-mcp.*--config' 2>/dev/null || true
sleep 1
nohup env "${envs[@]}" .venv/bin/treeland-autogui-mcp --config config/mcp-autoui-x11.json \
  >>"$HOME/dh-mcp-x11.log" 2>&1 &
sleep 5
ss -ltn 'sport = :8651' | tail -1