#!/usr/bin/env bash
# Execute a remote command without accepting, storing, or emitting credentials.
set -euo pipefail

: "${SSH_HOST:?Set SSH_HOST to the user-supplied hostname or IP.}"
: "${SSH_USER:?Set SSH_USER to the user-supplied SSH username.}"

port="${SSH_PORT:-22}"
identity_args=()
if [[ -n "${SSH_IDENTITY_FILE:-}" ]]; then
  identity_args=(-i "${SSH_IDENTITY_FILE}")
fi

# Password authentication, if selected by the user, remains an SSH interactive prompt.
# Never add a password option, environment variable, or stdin wrapper here.
exec ssh \
  -o ConnectTimeout=15 \
  -o ConnectionAttempts=1 \
  -o ServerAliveInterval=10 \
  -o ServerAliveCountMax=2 \
  -o StrictHostKeyChecking=ask \
  -p "$port" \
  "${identity_args[@]}" \
  "${SSH_USER}@${SSH_HOST}" "$@"
