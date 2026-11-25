#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Makes the two files a GitHub release needs, so that get.sh (the one-line installer) and Sluice's own updater can install it:
#
#   dist/sluice-v<version>.zip          the program (no caches, no build folders, no .git)
#   dist/sluice-v<version>.zip.sha256   its checksum
#
#   tools/make-release.sh
#
# Then attach both to the release on GitHub. A version with "-beta" in it (0.13.0-beta.1) is a beta: also tick
# "Set as a pre-release", so only people on the Beta channel get it.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
version="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$here/sluice/__init__.py")"
[ -n "$version" ] || { echo "no version in sluice/__init__.py" >&2; exit 1; }
name="sluice-v$version.zip"
mkdir -p "$here/dist"
rm -f "$here/dist/$name" "$here/dist/$name.sha256"
cd "$(dirname "$here")"
base="$(basename "$here")"
zip -qr "$here/dist/$name" "$base" -x "$base/.git/*" "$base/dist/*" "*/__pycache__/*" "*/.pytest_cache/*" \
    "$base/rust/sluice_dsp/target/*" "*.egg-info/*" "$base/.venv/*" "$base/.update/*" "$base/.previous/*"
cd "$here/dist"
sha256sum "$name" > "$name.sha256"
echo "Made dist/$name and dist/$name.sha256"
case "$version" in
    *[ab]*|*rc*|*pre*) echo "This is a test version: on GitHub, tick \"Set as a pre-release\"." ;;
    *) echo "This is a stable version." ;;
esac
echo "With the GitHub command line:  gh release create v$version dist/$name dist/$name.sha256$(case "$version" in *[ab]*|*rc*|*pre*) echo ' --prerelease';; esac) --notes-file <(sed -n '/^## $version/,/^## /p' CHANGELOG.md)"
