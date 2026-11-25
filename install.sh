#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Installs Sluice for your user, nothing system-wide: the program goes in ~/.local/share/sluice/program (with its own
# virtual environment), the `sluice` command in ~/.local/bin, and Sluice in the applications menu. Nothing it needs
# stays in the folder you downloaded, and at the end it offers to delete that folder.
# It can also install the system packages Sluice needs, but only if you say yes, and it never removes any.
#
#   ./install.sh                  check, offer the system packages, install, check again
#   ./install.sh --yes            do not ask before running the package command (the download folder is then kept)
#   ./install.sh --no-system      skip the system packages (you installed them yourself)
#   ./install.sh --dry-run        show what would be done and change nothing
#   ./install.sh --no-desktop     leave the applications menu alone
#   ./install.sh --in-place       install in this folder instead (for working on Sluice's code)
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here" || exit 1

assume_yes=0; system=1; dry=0; desktop=1; in_place=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y) assume_yes=1 ;;
        --no-system) system=0 ;;
        --dry-run) dry=1 ;;
        --desktop) desktop=1 ;;   # (the default since 0.12.0)
        --no-desktop) desktop=0 ;;
        --in-place) in_place=1 ;;
        -h|--help) sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
run()  { if [ "$dry" = 1 ]; then say "   (dry run) $*"; else "$@"; fi; }

if [ "$(id -u)" = 0 ] && [ -z "${SLUICE_ALLOW_ROOT:-}" ]; then
    say "Please run this as your normal user, not as root: Sluice installs into your own folders." >&2
    exit 1
fi

py="${PYTHON:-python3}"
if ! command -v "$py" >/dev/null 2>&1; then
    say "Python 3 was not found. Install it first (for example: sudo apt install python3 python3-venv)." >&2
    exit 1
fi
if ! "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    say "Sluice needs Python 3.10 or newer; this is $("$py" -V 2>&1). Install a newer Python, or run:" >&2
    say "  PYTHON=python3.12 ./install.sh" >&2
    exit 1
fi

osr="${SLUICE_OS_RELEASE:-/etc/os-release}"
distro() { PYTHONPATH="$here" "$py" -m sluice.distro --os-release "$osr" "$@"; }

step "Your system"
say "Distribution family: $(distro name)"
say "Python: $("$py" -V 2>&1)"
if command -v pactl >/dev/null 2>&1 && pactl info 2>/dev/null | grep -qi pipewire; then
    say "Sound server: PipeWire (good)"
else
    say "Sound server: PipeWire was not detected. Sluice needs PipeWire with its PulseAudio and JACK parts."
fi

if [ "$system" = 1 ]; then
    step "System packages"
    cmd="$(distro command)"
    case "$(distro family)" in
        unknown)
            say "This distribution is not one I know the package names for. Sluice needs: PipeWire (with pipewire-pulse,"
            say "WirePlumber and the PipeWire JACK library), the pw-link tool, libpulse, and python venv support."
            say "See the README, section 'Other distributions'." ;;
        *)
            say "Sluice needs these system packages. This is the command that installs whatever is missing:"
            say ""
            say "    $cmd"
            say ""
            if command -v pacman >/dev/null 2>&1 && pacman -Qq jack2 >/dev/null 2>&1 && ! pacman -Qq pipewire-jack >/dev/null 2>&1; then
                say "NOTE: jack2 is installed. If pacman offers to REMOVE jack2 to install pipewire-jack, answer N and stop:"
                say "that means you use a real JACK server, and Sluice would need a different setup."
                say ""
            fi
            if [ "$dry" = 1 ]; then
                say "   (dry run) not running it"
            else
                reply="n"
                if [ "$assume_yes" = 1 ]; then reply="y"; else read -r -p "Run it now? [y/N] " reply; fi
                case "$reply" in
                    y|Y|yes) $cmd || { say "The package command failed or was cancelled. Fix that and run ./install.sh again." >&2; exit 1; } ;;
                    *) say "Skipped. Run the command above yourself before starting Sluice." ;;
                esac
            fi ;;
    esac
fi

# 0.12.0: the program lives in its own folder, not in the download.
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
target="$data_home/sluice/program"
bin_dir="${XDG_BIN_HOME:-$HOME/.local/bin}"
download="$here"
if [ "$in_place" = 1 ]; then
    target="$here"
fi
target_real="$(cd "$target" 2>/dev/null && pwd || echo "$target")"
if [ "$target_real" != "$here" ]; then
    step "Copying Sluice to $target"
    if [ "$dry" = 1 ]; then
        say "   (dry run) copy the program files from $here to $target (not .venv, .git, caches or build folders)"
    else
        mkdir -p "$target" || { say "Could not create $target." >&2; exit 1; }
        # replace the program files a copy there has (so modules an older version had do not linger); keep its .venv
        # (reused, faster) and the Rust build cache
        for entry in "$here"/* "$here"/.[!.]*; do
            [ -e "$entry" ] || continue
            name="$(basename "$entry")"
            case "$name" in .venv|.git|.update|.previous|.pytest_cache|*.egg-info|__pycache__) continue ;; esac
            if [ "$name" = rust ] && [ -d "$target/rust/sluice_dsp/target" ]; then
                find "$target/rust" -mindepth 1 -maxdepth 1 ! -name sluice_dsp -exec rm -rf {} +
                find "$target/rust/sluice_dsp" -mindepth 1 -maxdepth 1 ! -name target -exec rm -rf {} +
            else
                rm -rf "${target:?}/$name"
            fi
        done
        rm -rf "$target/.update" "$target/.previous"
        tar -C "$here" --exclude=./.venv --exclude=./.git --exclude=./.update --exclude=./.previous \
            --exclude=./rust/sluice_dsp/target --exclude=__pycache__ --exclude=.pytest_cache --exclude='*.egg-info' \
            -cf - . | tar -C "$target" -xf - || { say "Could not copy Sluice to $target." >&2; exit 1; }
        say "Copied."
    fi
    here="$target"
    if [ "$dry" = 1 ]; then cd /; else cd "$here" || exit 1; fi
fi

step "Installing Sluice (virtual environment in $here/.venv)"
run "$py" -m venv .venv || { say "Could not create the virtual environment. On Debian/Ubuntu install python3-venv." >&2; exit 1; }
run .venv/bin/python -m pip install --upgrade pip >/dev/null
if [ "$dry" = 1 ]; then
    say "   (dry run) pip install -e ."
else
    # the long package download and build chatter is kept in a file and only shown when something fails
    pip_log="$(mktemp)"
    if .venv/bin/python -m pip install --quiet --disable-pip-version-check -e . >"$pip_log" 2>&1; then
        rm -f "$pip_log"
        say "Sluice and its Python packages are installed."
    else
        cat "$pip_log" >&2
        say "pip could not install Sluice. Read the error above (also saved in $pip_log)." >&2
        exit 1
    fi
fi

step "Faster audio engine (optional, needs Rust)"
if [ "${SLUICE_NO_RUST:-}" = 1 ]; then
    say "Skipped (SLUICE_NO_RUST=1). Sluice will use its Python engine."
elif command -v cargo >/dev/null 2>&1 && [ -d rust/sluice_dsp ]; then
    say "Building the Rust engine (a minute or two the first time)..."
    if [ "$dry" = 1 ]; then
        say "   (dry run) pip install maturin; maturin develop --release"
    elif .venv/bin/python -m pip install maturin >/dev/null && (cd rust/sluice_dsp && VIRTUAL_ENV="$here/.venv" "$here/.venv/bin/maturin" develop --release >/dev/null 2>&1); then
        say "Rust engine installed."
    else
        say "The Rust engine did not build, so Sluice will use its Python engine (same sound, a bit more CPU)."
    fi
else
    say "Rust (cargo) was not found, so Sluice will use its Python engine (same sound, a bit more CPU)."
    say "For the faster engine install Rust (https://rustup.rs, or your package manager's 'rust') and run ./install.sh again."
fi

step "Checking"
if [ "$dry" = 1 ]; then
    say "   (dry run) .venv/bin/sluice --version; .venv/bin/sluice --diagnose"
else
    .venv/bin/sluice --version
    .venv/bin/sluice --diagnose || say "Something above needs attention. Each line says what to install or start."
    extras="$(.venv/bin/python -m sluice.setup_check optional 2>/dev/null || true)"
    if [ -n "$extras" ]; then
        say ""
        say "Optional extras Sluice can use (it works without them; Settings > Setup check lists them too):"
        say "$extras"
    fi
fi

step "The sluice command"
command_file="$bin_dir/sluice"
command="sluice"
if [ -e "$command_file" ] && ! grep -q "Written by Sluice's install.sh" "$command_file" 2>/dev/null; then
    say "$command_file exists and is not Sluice's, so it was left alone. Start Sluice with: $here/.venv/bin/sluice"
    command="$here/.venv/bin/sluice"
elif [ "$dry" = 1 ]; then
    say "   (dry run) write $command_file"
else
    mkdir -p "$bin_dir"
    {
        printf '#!/bin/sh\n'
        printf "# Written by Sluice's install.sh: starts Sluice from where it is installed. (Uninstalling removes it.)\n"
        printf 'exec %s "$@"\n' "'$here/.venv/bin/sluice'"
    } > "$command_file"
    chmod 755 "$command_file"
    say "Written: $command_file"
    case ":$PATH:" in
        *":$bin_dir:"*) ;;
        *) say "($bin_dir is not in your PATH, so in a terminal type the whole path: $command_file)"; command="$command_file" ;;
    esac
fi

if [ "$desktop" = 1 ]; then
    step "Applications menu"
    run .venv/bin/sluice --install-desktop
fi

step "Done"
say "Sluice is installed in $here."
[ "$desktop" = 1 ] && say "Start it from your applications menu, or in a terminal:  $command"
[ "$desktop" = 1 ] || say "Start it:                     $command"
say "Try the interface only:       $command --demo"
say "Something wrong?              $command --report"

# 0.12.0: the download is no longer needed. Offer to delete it, only when it is plainly a Sluice download: not a git
# clone (it may hold your own changes), not the installed copy, not your home folder.
if [ "$download" != "$here" ] && [ -z "${SLUICE_FROM_GET:-}" ]; then  # (get.sh deletes its own download)
    safe=1
    [ -e "$download/.git" ] && safe=0
    case "$download" in "$HOME"|"/"|"$data_home"*) safe=0 ;; esac
    for f in pyproject.toml install.sh sluice/__init__.py; do [ -e "$download/$f" ] || safe=0; done
    if [ "$safe" = 1 ]; then
        say ""
        if [ "$dry" = 1 ]; then
            say "   (dry run) would offer to delete the download folder $download"
        elif [ "$assume_yes" = 1 ]; then
            say "The folder you downloaded ($download) is no longer needed; you can delete it, and the zip too."
        else
            reply="n"
            read -r -p "Sluice no longer needs the folder you downloaded ($download). Delete it now? [y/N] " reply
            case "$reply" in
                y|Y|yes)
                    cd / && rm -rf -- "$download" && say "Deleted $download. (The zip you downloaded can go too.)" ;;
                *) say "Kept. You can delete $download yourself at any time." ;;
            esac
        fi
    elif [ -e "$download/.git" ]; then
        say ""
        say "($download is a git clone, so it was left as it is. Sluice runs from $here, not from it.)"
    fi
fi
