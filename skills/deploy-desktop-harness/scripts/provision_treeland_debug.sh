#!/usr/bin/env bash
# Internal helper: build and install matching Debug Treeland binaries on a test machine.
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${SSH_HOST:?}"
: "${SSH_USER:?}"
: "${TREELAND_SOURCE_URL:=https://github.com/linuxdeepin/treeland.git}"
: "${TREELAND_REF:=HEAD}"

# Debug Treeland only matters for a Wayland session; on an X11 session the
# DesktopHarness backend is x11-deepin and never shells out to treeland-debug.
session_type="$("${script_dir}/remote_session_type.sh" 2>/dev/null || printf 'unknown')"
if [[ "$session_type" != "wayland" ]]; then
  printf 'TREELAND_DEBUG_SKIPPED session_type=%s\n' "$session_type"
  exit 0
fi

if "${script_dir}/remote_exec.sh" 'timeout 10 treeland-debug --json tree >/dev/null 2>&1'; then
  printf 'TREELAND_DEBUG_OK reused-existing-build\n'
  exit 0
fi
"${script_dir}/resolve_treeland_ref.sh"
"${script_dir}/remote_exec.sh" "TREELAND_SOURCE_URL=$(printf '%q' "$TREELAND_SOURCE_URL") TREELAND_REF=$(printf '%q' "$TREELAND_REF") bash -se" <<'REMOTE'
set -euo pipefail
src=/var/tmp/treeland-debug-build
sudo rm -rf "$src"
sudo git clone --recursive "$TREELAND_SOURCE_URL" "$src"
sudo git -C "$src" checkout "$TREELAND_REF"
sudo git -C "$src" submodule update --init --recursive
sudo apt-get build-dep -y "$src"
sudo cmake -S "$src" -B "$src/build" -GNinja -DCMAKE_BUILD_TYPE=Debug -DBUILD_TREELAND_DEBUG=ON -DTREELAND_DEBUG_SOURCE=ON -DWITH_SUBMODULE_WAYLIB=ON -DCMAKE_INSTALL_PREFIX=/usr
sudo cmake --build "$src/build" --parallel
sudo cmake --install "$src/build"
if systemctl is-active --quiet treeland.service; then sudo systemctl restart treeland.service; else systemctl --user restart treeland.service; fi
REMOTE
