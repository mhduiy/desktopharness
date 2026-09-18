#!/usr/bin/env bash
# Sole public entry point for DesktopHarness deployment.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
while (($#)); do
  case "$1" in
    --host) SSH_HOST="$2"; shift 2 ;;
    --user) SSH_USER="$2"; shift 2 ;;
    --treeland-source) TREELAND_SOURCE_URL="$2"; shift 2 ;;
    --treeland-ref) TREELAND_REF="$2"; shift 2 ;;
    *) echo "usage: $0 --host HOST --user USER [--treeland-source URL] [--treeland-ref REF]" >&2; exit 2 ;;
  esac
done
: "${SSH_HOST:?--host is required}"
: "${SSH_USER:?--user is required}"
: "${CUA_MODEL_API_KEY:?CUA_MODEL_API_KEY must be injected by the controller}"
export SSH_HOST SSH_USER TREELAND_SOURCE_URL TREELAND_REF CUA_MODEL_API_KEY

"${root}/provision_treeland_debug.sh"
exec "${root}/provision_remote.sh"
