#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installs Sluice with one command, on any distribution:
#
#   curl -fsSL https://raw.githubusercontent.com/Matt-B-007/Sluice/main/get.sh | bash
#
# It downloads the latest release from GitHub, checks it against its .sha256 file, runs its install.sh (which offers
# the system packages Sluice needs and asks before running that command), and deletes everything it downloaded.
# Run it again at any time to update or repair Sluice; your settings are kept.
#
#   ... | bash -s -- --beta           the latest test version instead of the latest stable one
#   ... | bash -s -- --version 0.12.2 a particular version
#   ... | bash -s -- --yes            do not ask before the package command
#   ... | bash -s -- --no-system      skip the system packages (installed already)
#   ... | bash -s -- --no-launch      do not start Sluice at the end
#   ... | bash -s -- --from-source    the newest code on the main branch instead of a release (no checksum to check)
#   ... | bash -s -- --uninstall      remove Sluice (runs its own uninstaller)
#
# Rather read it first? Download it, look, then run it:
#   curl -fsSLO https://raw.githubusercontent.com/Matt-B-007/Sluice/main/get.sh && less get.sh && bash get.sh
#
# Everything is inside main(), called on the last line, so a download cut short runs nothing.

main() {
    set -euo pipefail
    local repo="${SLUICE_REPO:-Matt-B-007/Sluice}"
    local api="${SLUICE_RELEASES_URL:-https://api.github.com/repos/$repo/releases?per_page=20}"
    local channel="stable" want="" pass=() from_source=0 uninstall=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --from-source) from_source=1 ;;
            --uninstall) uninstall=1 ;;
            --beta) channel="beta" ;;
            --stable) channel="stable" ;;
            --version) shift; want="${1:-}" ;;
            --version=*) want="${1#--version=}" ;;
            -h|--help) sed -n '3,21p' "${BASH_SOURCE[0]:-get.sh}" 2>/dev/null | sed 's/^# \{0,1\}//'; return 0 ;;
            *) pass+=("$1") ;;
        esac
        shift
    done

    say() { printf '%s\n' "$*"; }
    fail() { printf 'Sluice could not be installed: %s\n' "$*" >&2; exit 1; }

    if [ "$uninstall" = 1 ]; then  # 0.13.1: the installed Sluice removes itself (it lists what it removes and asks first)
        local installed
        installed="$(command -v sluice || true)"
        [ -n "$installed" ] || [ ! -x "$HOME/.local/bin/sluice" ] || installed="$HOME/.local/bin/sluice"
        if [ -z "$installed" ]; then
            printf 'Sluice is not installed for this user, so there is nothing to remove.\n' >&2
            exit 1
        fi
        if [ -r /dev/tty ]; then
            exec "$installed" --uninstall "${pass[@]}" < /dev/tty
        fi
        exec "$installed" --uninstall --yes "${pass[@]}" < /dev/null
    fi

    [ "$(id -u)" != 0 ] || [ -n "${SLUICE_ALLOW_ROOT:-}" ] || fail "run this as your normal user, not with sudo (Sluice installs for you, in your home folder; it asks for sudo only for the one package command)."
    local py
    py="$(command -v python3 || true)"
    [ -n "$py" ] || fail "python3 is needed. Install it with your package manager (it is called python or python3), then run this again."
    if command -v curl >/dev/null 2>&1; then
        fetch() { curl -fsSL --retry 3 --connect-timeout 15 -o "$2" "$1"; }
    elif command -v wget >/dev/null 2>&1; then
        fetch() { wget -q --tries=3 --timeout=15 -O "$2" "$1"; }
    else
        fail "curl or wget is needed to download Sluice."
    fi

    SLUICE_GET_TMP="$(mktemp -d "${TMPDIR:-/tmp}/sluice-get.XXXXXX")"  # (global: the clean-up runs after main has returned)
    trap 'rm -rf "${SLUICE_GET_TMP:-/nonexistent}"' EXIT
    local tmp="$SLUICE_GET_TMP"

    local tag zip_url sum_url
    if [ "$from_source" = 1 ]; then  # 0.13.1: the main branch, as it is now; there is no published checksum for it
        tag="main (from source)"
        zip_url="https://codeload.github.com/$repo/zip/refs/heads/main"
        say "==> Downloading the newest code from the main branch (not a release: there is no checksum to check it against)"
        fetch "$zip_url" "$tmp/sluice.zip" || fail "the download failed."
    else
    say "==> Finding the ${want:+requested}${want:-latest $channel} Sluice release"
    fetch "$api" "$tmp/releases.json" || fail "could not reach GitHub ($api). Check your internet connection."
    local picked
    picked="$("$py" - "$tmp/releases.json" "$channel" "$want" <<'PY'
import json, re, sys
path, channel, want = sys.argv[1], sys.argv[2], sys.argv[3].lstrip("vV")
PRE = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "pre": 1, "rc": 2}
def key(tag):
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)\s*[-.]?\s*(alpha|beta|pre|rc|a|b)?\s*[-.]?\s*(\d*)", tag, re.I)
    if not m:
        return ()
    nums = tuple(int(x) for x in m.group(1).split("."))
    nums += (0,) * (4 - len(nums))
    return nums + ((PRE[m.group(2).lower()], int(m.group(3) or 0)) if m.group(2) else (9, 0))
best = None
for rel in json.load(open(path)):
    tag = str(rel.get("tag_name") or "")
    if rel.get("draft") or not key(tag):
        continue
    if want:
        if tag.lstrip("vV") != want:
            continue
    elif channel != "beta" and (re.search(r"\d\s*[-.]?\s*(alpha|beta|pre|rc|a|b)", tag, re.I)):
        continue
    assets = {a.get("name"): a.get("browser_download_url") for a in rel.get("assets") or [] if isinstance(a, dict)}
    zips = [n for n in assets if n and re.fullmatch(r"sluice-[A-Za-z0-9._-]+\.zip", n) and n + ".sha256" in assets]
    if not zips:
        continue
    if best is None or key(tag) > best[0]:
        best = (key(tag), tag, assets[zips[0]], assets[zips[0] + ".sha256"])
if best is None:
    sys.exit(3)
print(best[1], best[2], best[3])
PY
)" || fail "no ${want:+release $want}${want:-$channel release} with a downloadable zip and checksum was found on GitHub."
    read -r tag zip_url sum_url <<<"$picked"
    case "$zip_url$sum_url" in *[!A-Za-z0-9._~:/?#@%+=\&-]*) fail "the release's download address looks wrong." ;; esac
    case "$zip_url" in https://*) ;; file://*) [ -n "${SLUICE_RELEASES_URL:-}" ] || fail "the release's download address is not https." ;;
        *) fail "the release's download address is not https." ;; esac

    say "==> Downloading Sluice $tag"
    fetch "$zip_url" "$tmp/sluice.zip" || fail "the download failed."
    fetch "$sum_url" "$tmp/sluice.zip.sha256" || fail "the checksum file could not be downloaded."
    local expected actual
    expected="$(tr -s ' \t' ' ' < "$tmp/sluice.zip.sha256" | cut -d' ' -f1 | tr 'A-F' 'a-f')"
    actual="$("$py" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$tmp/sluice.zip")"
    [ -n "$expected" ] && [ "$expected" = "$actual" ] || fail "the download does not match its checksum (it may be damaged). Nothing was installed; try again."
    say "Checked: the download matches its checksum."
    fi

    "$py" - "$tmp/sluice.zip" "$tmp/src" <<'PY' || fail "the zip could not be unpacked."
import os, sys, zipfile
src, dest = sys.argv[1], os.path.realpath(sys.argv[2])
with zipfile.ZipFile(src) as z:
    for member in z.infolist():
        target = os.path.realpath(os.path.join(dest, member.filename))
        if not (target == dest or target.startswith(dest + os.sep)):
            raise SystemExit("unsafe path in the zip: " + member.filename)
    z.extractall(dest)
for root, dirs, files in os.walk(dest):
    for name in files:
        if name in ("install.sh", "uninstall.sh", "get.sh"):
            os.chmod(os.path.join(root, name), 0o755)
PY
    local here
    here="$(dirname "$(find "$tmp/src" -maxdepth 3 -name install.sh -type f | head -n 1)")"
    [ -f "$here/install.sh" ] || fail "the release has no install.sh."

    say "==> Installing (this copies Sluice to ~/.local/share/sluice; the download is deleted afterwards)"
    # The script came in through a pipe, so questions are asked on the terminal itself; with no terminal, nothing is asked.
    if [ -r /dev/tty ] && [ -w /dev/tty ] && { : < /dev/tty; } 2>/dev/null; then
        SLUICE_FROM_GET=1 bash "$here/install.sh" "${pass[@]}" < /dev/tty
    else
        SLUICE_FROM_GET=1 bash "$here/install.sh" --yes "${pass[@]}" < /dev/null
    fi
    say ""
    say "Sluice $tag is installed. Run this same command again at any time to update or repair it."
}

main "$@"
