#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Removes Sluice: shows what it will remove, asks, then removes it. Same as `sluice --uninstall`, for when the
# installed copy no longer starts. Only your own folders are touched; nothing needs root.
#
#   ./uninstall.sh                  show the list, ask, remove
#   ./uninstall.sh --keep-settings  keep your settings, presets and controller bindings
#   ./uninstall.sh --dry-run        only show the list
#   ./uninstall.sh --yes            do not ask
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$here/.venv/bin/python" ] && "$here/.venv/bin/python" -c 'import sluice' 2>/dev/null; then
    exec "$here/.venv/bin/python" -m sluice --uninstall "$@"
fi
# The environment is gone or broken: the uninstaller itself needs only the standard library.
PYTHONPATH="$here" exec "${PYTHON:-python3}" -m sluice --uninstall "$@"
