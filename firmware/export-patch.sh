#!/usr/bin/env bash
# Regenerates stackzeta-firmware.patch from a working firmware tree after
# firmware changes: the diff from the pinned upstream commit to the tree's
# committed HEAD. Commit your firmware changes in that tree first.
#
#   firmware/export-patch.sh [firmware-tree]   (default: upstream/StackChan)
set -euo pipefail

UPSTREAM_COMMIT="$(sed -n 's/^UPSTREAM_COMMIT="\(.*\)"$/\1/p' "$(dirname "$0")/setup.sh")"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tree="${1:-$(dirname "$here")/upstream/StackChan}"

if [ -n "$(git -C "$tree" status --porcelain)" ]; then
    echo "error: $tree has uncommitted changes; commit them first" >&2
    exit 1
fi
# Edits to the fetched xiaozhi-esp32 tree only survive via its patch file.
xiaozhi="$tree/firmware/xiaozhi-esp32"
if [ -d "$xiaozhi/.git" ] &&
   ! git -c safe.directory='*' -C "$xiaozhi" diff | cmp -s - "$tree/firmware/patches/xiaozhi-esp32.patch"; then
    echo "warning: firmware/xiaozhi-esp32 differs from firmware/patches/xiaozhi-esp32.patch;" >&2
    echo "         regenerate it: git -C firmware/xiaozhi-esp32 diff > firmware/patches/xiaozhi-esp32.patch" >&2
fi

git -C "$tree" diff --binary "$UPSTREAM_COMMIT" HEAD > "$here/stackzeta-firmware.patch"

# Deployment addresses and secrets belong in git-ignored files only.
if grep -aqE "sk-(proj-)?[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}" "$here/stackzeta-firmware.patch"; then
    echo "error: the patch appears to contain an API key or token; not safe to commit" >&2
    exit 1
fi
echo "Wrote $here/stackzeta-firmware.patch ($(wc -c < "$here/stackzeta-firmware.patch") bytes)"
