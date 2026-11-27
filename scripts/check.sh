#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Every check CI runs, in the same order and with the same flags. CI calls this script and nothing else for its checks, so a
# check run here and one run on GitHub cannot differ (House Standard). StowLock runs it before pushing; run it in full before
# making a release zip.
#
#   bash scripts/check.sh                       all sections, in this order: shell, python, rust, tests
#   bash scripts/check.sh shell python          only those sections
#   TAG=v1.2.3 bash scripts/check.sh release    the release workflow's extra check: the tag matches the version files
#
# First it looks for every tool the chosen sections need, and lists each missing one with the command that installs it.
# Exit codes: 0 every check passed · 1 a check failed · 3 only tools are missing (nothing was checked).
set -Eeuo pipefail
trap 'exit 1' ERR  # any failing check exits with 1, whatever code the tool itself used

cd "$(dirname "$0")/.."
# shellcheck source=scripts/tool-versions
. scripts/tool-versions

PY="${PYTHON:-python3}"
on_ci=false
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    on_ci=true
fi
RUST_DIR=rust/sluice_dsp
RUST_VERSION="$(sed -n 's/^channel = "\(.*\)"/\1/p' "$RUST_DIR/rust-toolchain.toml")"
advisory=()

step() {
    printf '\n== %s\n' "$1"
}

# ------------------------------------------------------------------------------------------------- tools, checked first
pacman_pkgs=()
aur_pkgs=()
missing=()

need() {  # need WHAT PACKAGES [aur]: note a missing tool and the Arch package(s) that provide it
    local package
    missing+=("$1")
    for package in $2; do
        if [ "${3:-}" = "aur" ]; then
            aur_pkgs+=("$package")
        else
            pacman_pkgs+=("$package")
        fi
    done
}

has_module() {
    "$PY" -c "import $1" >/dev/null 2>&1
}

find_tools() {
    local section have_python=true libs
    if ! command -v "$PY" >/dev/null 2>&1; then
        need "$PY (Python 3)" python
        have_python=false
    fi
    for section in "$@"; do
        case "$section" in
            shell)
                if ! command -v shellcheck >/dev/null 2>&1; then
                    need "shellcheck $SHELLCHECK_VERSION (or: pip install shellcheck-py==$SHELLCHECK_PY)" shellcheck
                fi
                ;;
            python)
                if [ "$have_python" = true ] && ! has_module pyflakes; then
                    need "pyflakes for $PY (or: pip install pyflakes)" python-pyflakes
                fi
                if ! command -v ruff >/dev/null 2>&1; then
                    need "ruff, the Python formatter (or: pip install ruff==$RUFF_VERSION)" ruff
                fi
                ;;
            rust)
                if ! command -v cargo >/dev/null 2>&1; then
                    need "Rust $RUST_VERSION with rustfmt and clippy (rustup installs the pinned version by itself)" rustup
                elif ! (cd "$RUST_DIR" && cargo fmt --version >/dev/null 2>&1 && cargo clippy --version >/dev/null 2>&1); then
                    need "rustfmt and clippy (with rustup: rustup component add rustfmt clippy)" rustup
                fi
                ;;
            tests)
                if [ "$have_python" = true ]; then
                    if ! has_module pytest; then need "pytest for $PY (or: pip install -e \".[dev]\")" python-pytest; fi
                    if ! has_module numpy; then need "numpy for $PY" python-numpy; fi
                    if ! has_module cryptography; then need "cryptography for $PY (checks signed updates)" python-cryptography; fi
                    if ! has_module PySide6; then need "PySide6 for $PY" pyside6; fi
                    if ! has_module pulsectl; then
                        need "pulsectl for $PY (it is in the AUR; or: pip install pulsectl)" python-pulsectl aur
                    fi
                    if ! "$PY" tools/check-qt-libs.py >/dev/null 2>&1; then
                        libs="$("$PY" tools/check-qt-libs.py | sed -n 's/.*cannot load \(.*\), which.*/\1/p')"
                        need "Qt's system libraries ($libs)" "libglvnd libxkbcommon fontconfig"
                    fi
                fi
                ;;
            release)
                if ! command -v git >/dev/null 2>&1; then need "git" git; fi
                ;;
        esac
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        return
    fi
    echo "Some tools these checks need are missing, so nothing was checked. On Arch or CachyOS:"
    if [ "${#pacman_pkgs[@]}" -gt 0 ]; then
        echo "  sudo pacman -S --needed $(printf '%s\n' "${pacman_pkgs[@]}" | sort -u | tr '\n' ' ')"
    fi
    if [ "${#aur_pkgs[@]}" -gt 0 ]; then
        echo "  paru -S --needed $(printf '%s\n' "${aur_pkgs[@]}" | sort -u | tr '\n' ' ')  (from the AUR)"
    fi
    echo "Missing:"
    printf '  - %s\n' "${missing[@]}"
    if [ "$on_ci" = true ]; then
        echo "::error::Tools are missing on the test machine: ${missing[*]}"
    fi
    exit 3
}

# pinned TOOL INSTALLED PINNED COMMAND...: runs a check whose findings can depend on the tool's version. With the pinned
# version (always on GitHub) a finding fails the run. With another version a finding is shown and listed at the end but does
# not fail: GitHub runs the pinned version, and a newer tool may know rules the pinned one does not.
pinned() {
    local tool="$1" installed="$2" wanted="$3"
    shift 3
    if [ "$installed" = "$wanted" ]; then
        "$@"
        return
    fi
    if [ "$on_ci" = true ]; then
        echo "::error::$tool $installed is installed but $wanted is pinned"
        exit 1
    fi
    echo "NOTE: $tool $installed is installed here, $wanted is pinned (GitHub runs $wanted)"
    if ! "$@"; then
        echo "DIFFERS: '$*' found something with $tool $installed; GitHub's $tool $wanted decides"
        advisory+=("$* (with $tool $installed, not the pinned $wanted)")
    fi
}

# ------------------------------------------------------------------------------------------------------------ shell
check_shell() {
    step "Shell scripts: bash -n or sh -n, then shellcheck at default severity"
    local installed script first dialect
    installed="$(shellcheck --version | sed -n 's/^version: //p')"
    for script in install.sh uninstall.sh get.sh scripts/*.sh tools/*.sh; do
        [ -f "$script" ] || continue
        first="$(head -n 1 "$script")"
        case "$first" in
            *bash*) dialect="bash" ;;
            *) dialect="sh" ;;
        esac
        echo "$script ($dialect)"
        "$dialect" -n "$script"
        pinned shellcheck "$installed" "$SHELLCHECK_VERSION" shellcheck -x -s "$dialect" "$script"
    done
    bash install.sh --help >/dev/null
}

# ------------------------------------------------------------------------------------------------------------ python
check_python() {
    step "Python: pyflakes (any finding fails), then ruff format --check"
    "$PY" -m pyflakes sluice tests tools
    # 0.13.1: one layout for all Python (pyproject.toml [tool.ruff]); "ruff format" fixes what this finds
    pinned ruff "$(ruff --version | sed -n 's/^ruff //p')" "$RUFF_VERSION" ruff format --check sluice tests tools
    step "The version files and the changelogs agree"
    "$PY" tools/check-version.py
}

# ------------------------------------------------------------------------------------------------------------ rust
check_rust() {
    step "Rust engine: cargo fmt --check, then cargo clippy -D warnings"
    local installed
    cd "$RUST_DIR"
    installed="$(cargo --version | awk '{print $2}')"  # with rustup: the version in rust-toolchain.toml
    pinned Rust "$installed" "$RUST_VERSION" cargo fmt --check
    pinned Rust "$installed" "$RUST_VERSION" cargo clippy --all-targets --quiet -- -D warnings
    cd - >/dev/null
}

# ------------------------------------------------------------------------------------------------------------ tests
check_tests() {
    step "Qt's system libraries can be loaded"
    "$PY" tools/check-qt-libs.py
    if has_module sluice_dsp; then
        step "Tests with the Rust engine"
        "$PY" -c "import sluice.spectral as s; assert s.BACKEND == 'rust', s.RUST_ERROR; import sluice_dsp; print('Rust engine', sluice_dsp.VERSION)"
        QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q
        step "Tests with the Rust engine switched off (Python and Rust must agree)"
        SLUICE_NO_RUST=1 QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q
    else
        if [ "${SLUICE_EXPECT_RUST:-}" = "1" ]; then
            echo "::error::The Rust engine was expected (SLUICE_EXPECT_RUST=1) but sluice_dsp cannot be imported"
            exit 1
        fi
        step "Tests (Python engine; the Rust engine is not installed for $PY)"
        QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q
    fi
}

# ------------------------------------------------------------------------------------------------------------ release
check_release() {
    step "The tag, the version files and the changelogs agree, and the version is newer than every release"
    if [ -z "${TAG:-}" ]; then
        echo "::error::TAG is not set (TAG=v1.2.3 bash scripts/check.sh release)"
        exit 1
    fi
    "$PY" tools/check-version.py --tag "$TAG" --new
}

sections=("$@")
if [ "${#sections[@]}" -eq 0 ]; then
    sections=(shell python rust tests)
fi
for section in "${sections[@]}"; do
    case "$section" in
        shell | python | rust | tests | release) ;;
        *)
            echo "Unknown section '$section' (use: shell python rust tests release)" >&2
            exit 1
            ;;
    esac
done

find_tools "${sections[@]}"
for section in "${sections[@]}"; do
    "check_$section"
done

echo
if [ "${#advisory[@]}" -gt 0 ]; then
    echo "Found only with a tool version other than the pinned one (GitHub uses the pinned versions; look at these):"
    printf '  - %s\n' "${advisory[@]}"
fi
echo "All checks passed: ${sections[*]}"
