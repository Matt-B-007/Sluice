#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Releases the version that is in the code, so the tag can never disagree with it.
#
#   tools/release.sh --set 0.13.0   # 1. set a new version in sluice/__init__.py and pyproject.toml, and start its changelog section
#                                   #    (then write the changelog section, run the tests and commit)
#   tools/release.sh                # 2. check everything, then tag v<version> and push the tag; GitHub builds the release
#
# Instead of step 2 you can also use GitHub: Actions > Release > Run workflow. It does the same checks and makes the tag itself.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"

if [ "${1:-}" = "--set" ]; then
    new="${2:?usage: tools/release.sh --set 0.13.0}"
    new="${new#v}"
    python3 - "$new" <<'EOF'
import re, sys
from pathlib import Path
new = sys.argv[1]
if not re.match(r"^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$", new):
    sys.exit(f"{new} is not a version like 0.13.0 or 0.13.0-beta.1")
for path, pattern, line in (("sluice/__init__.py", r'^__version__ = ".*"$', f'__version__ = "{new}"'),
                            ("pyproject.toml", r'^version = ".*"$', f'version = "{new}"')):
    p = Path(path)
    p.write_text(re.sub(pattern, line, p.read_text(), count=1, flags=re.M))
for path in ("CHANGELOG.md", "sluice/data/CHANGELOG.md"):
    p = Path(path)
    text = p.read_text()
    if not re.search(rf"^## {re.escape(new)}$", text, re.M):
        text = text.replace("# Changelog\n\n", f"# Changelog\n\n## {new}\n- (say what changed)\n\n", 1)
        p.write_text(text)
print(f"Version set to {new}. Now write its section at the top of CHANGELOG.md, copy CHANGELOG.md to sluice/data/CHANGELOG.md,")
print("run the tests, commit and push. Then run tools/release.sh to release it.")
EOF
    exit 0
fi

python3 tools/check-version.py
version="$(python3 tools/check-version.py --print)"
tag="v$version"
if grep -q "(say what changed)" CHANGELOG.md; then
    echo "Problem: CHANGELOG.md still has the '(say what changed)' placeholder. Write what changed first." >&2; exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "Problem: there are changes that are not committed. Commit them (or set them aside) first:" >&2
    git status --short >&2; exit 1
fi
git fetch --quiet origin --tags
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    echo "Problem: $tag already exists. To make a new release, set a new version: tools/release.sh --set <next version>" >&2; exit 1
fi
branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$branch" 2>/dev/null || echo none)" ]; then
    echo "Problem: this commit is not on GitHub yet. Push it first: git push origin $branch" >&2; exit 1
fi
case "$version" in *-*) kind="a test version (only the Beta channel gets it)";; *) kind="a stable version";; esac
echo "Releasing Sluice $version, $kind, from $(git rev-parse --short HEAD) on $branch."
git tag -a "$tag" -m "Sluice $version"
git push origin "$tag"
echo "Pushed $tag. GitHub is building the release now: see the Actions tab, then Releases."
