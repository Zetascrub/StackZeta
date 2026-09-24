#!/usr/bin/env bash
# Recreates the StackZeta firmware tree: clones m5stack/StackChan at the
# pinned commit and applies stackzeta-firmware.patch on a local branch.
#
#   firmware/setup.sh [target-dir]     (default: upstream/StackChan)
#
# Then build as described in docs/toolchain.md.
set -euo pipefail

UPSTREAM_URL="https://github.com/m5stack/StackChan.git"
UPSTREAM_COMMIT="1b5765599fba8aaad1811d9a79358ccc7051f5f3"
BRANCH="stackzeta"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(dirname "$here")"
target="${1:-$repo_root/upstream/StackChan}"
patch="$here/stackzeta-firmware.patch"

if [ -e "$target" ]; then
    echo "error: $target already exists; remove it or pass another directory" >&2
    exit 1
fi

git clone "$UPSTREAM_URL" "$target"
git -C "$target" checkout -q -b "$BRANCH" "$UPSTREAM_COMMIT"
git -C "$target" apply --binary --whitespace=nowarn "$patch"
git -C "$target" add -A
git -C "$target" -c user.name="StackZeta setup" -c user.email="setup@stackzeta.invalid" \
    commit -q -m "Apply StackZeta firmware patch"

local_cfg="$target/firmware/sdkconfig.defaults.local"
if [ ! -e "$local_cfg" ]; then
    cp "$here/sdkconfig.defaults.local.example" "$local_cfg"
    echo "Created $local_cfg: set your Docker host's LAN IP in it before building."
fi

echo "StackZeta firmware ready in $target (branch $BRANCH)."
