#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Installs Sluice for your user: a virtual environment inside this folder, nothing system-wide.
# It can also install the system packages Sluice needs, but only if you say yes, and it never removes anything.
#
#   ./install.sh                  check, offer the system packages, install, check again
#   ./install.sh --yes            do not ask before running the package command
#   ./install.sh --no-system      skip the system packages (you installed them yourself)
#   ./install.sh --dry-run        show what would be done and change nothing
#   ./install.sh --desktop        also add Sluice to the applications menu
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here" || exit 1

assume_yes=0; system=1; dry=0; desktop=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y) assume_yes=1 ;;
        --no-system) system=0 ;;
        --dry-run) dry=1 ;;
        --desktop) desktop=1 ;;
        -h|--help) sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

step "Installing Sluice (virtual environment in $here/.venv)"
run "$py" -m venv .venv || { say "Could not create the virtual environment. On Debian/Ubuntu install python3-venv." >&2; exit 1; }
run .venv/bin/python -m pip install --upgrade pip >/dev/null
run .venv/bin/python -m pip install -e . || { say "pip could not install Sluice. Read the error above." >&2; exit 1; }

step "Checking"
if [ "$dry" = 1 ]; then
    say "   (dry run) .venv/bin/sluice --version; .venv/bin/sluice --diagnose"
else
    .venv/bin/sluice --version
    .venv/bin/sluice --diagnose || say "Something above needs attention. Each line says what to install or start."
fi

if [ "$desktop" = 1 ]; then
    step "Applications menu"
    run .venv/bin/sluice --install-desktop
fi

step "Done"
say "Start it:                     $here/.venv/bin/sluice"
say "Try the interface only:       $here/.venv/bin/sluice --demo"
say "Add it to the apps menu:      $here/.venv/bin/sluice --install-desktop"
say "Something wrong?              $here/.venv/bin/sluice --report"
