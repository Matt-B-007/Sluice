#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Fills in your GitHub address everywhere it is needed, once, before the first push:
#
#   tools/set-github-repo.sh YOURNAME            (repository called "sluice")
#   tools/set-github-repo.sh YOURNAME my-repo    (repository with another name)
#
# It changes: the project links in pyproject.toml, the links in README.md and docs/PUBLISHING.md, and the
# address "Help > Check for updates" asks (sluice/updates.py). Run it again with other names to change them.
set -eu
cd "$(dirname "${BASH_SOURCE[0]}")/.."

owner="${1:-}"; repo="${2:-sluice}"
if [ -z "$owner" ] || ! printf '%s' "$owner/$repo" | grep -Eq '^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$'; then
    echo "usage: tools/set-github-repo.sh GITHUB_USERNAME [REPOSITORY_NAME]" >&2
    exit 2
fi

# links: whatever owner/repo is there now (the YOURNAME/sluice placeholder, or an earlier run) becomes the new one
current="$(grep -o 'github.com/[A-Za-z0-9-]*/[A-Za-z0-9._-]*' pyproject.toml | head -1 | sed 's#github.com/##')"
for file in pyproject.toml README.md docs/PUBLISHING.md CONTRIBUTING.md; do
    [ -f "$file" ] && sed -i "s#${current}#${owner}/${repo}#g; s#YOURNAME#${owner}#g" "$file"
done

# the update check: GitHub's list of releases (the "latest" address would skip pre-releases such as betas)
url="https://api.github.com/repos/${owner}/${repo}/releases?per_page=5"
sed -i -E "s#^RELEASE_URL = \".*\"#RELEASE_URL = \"${url}\"#" sluice/updates.py

echo "Set to ${owner}/${repo}:"
grep -n "github.com" pyproject.toml | sed 's/^/  /'
grep -n '^RELEASE_URL' sluice/updates.py | sed 's/^/  /'
