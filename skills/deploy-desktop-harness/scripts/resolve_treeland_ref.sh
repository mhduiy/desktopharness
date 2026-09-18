#!/usr/bin/env bash
# Resolve a user-selected Treeland source/ref to one immutable commit.
set -euo pipefail

: "${TREELAND_SOURCE_URL:=https://github.com/linuxdeepin/treeland.git}"
: "${TREELAND_REF:=HEAD}"

work_dir="$(mktemp -d)"
trap 'rm -rf -- "$work_dir"' EXIT
git clone --quiet --no-checkout "$TREELAND_SOURCE_URL" "$work_dir/source"
git -C "$work_dir/source" fetch --quiet --tags origin "$TREELAND_REF"
commit="$(git -C "$work_dir/source" rev-parse --verify FETCH_HEAD^{commit})"
printf 'TREELAND_SOURCE_URL=%s\nTREELAND_REF=%s\nTREELAND_COMMIT=%s\n' \
  "$TREELAND_SOURCE_URL" "$TREELAND_REF" "$commit"
