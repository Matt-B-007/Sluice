# SPDX-License-Identifier: GPL-3.0-or-later
"""The old name of ``update_check`` (renamed in 0.11.6), kept so the updater in Sluice 0.11.5 and earlier accepts newer versions:
before installing a download it imports ``sluice.updates`` from the downloaded files, and refuses the update if that fails.
Nothing in Sluice imports this module."""
from .update_check import UpdateResult, check, find_assets

__all__ = ["UpdateResult", "check", "find_assets"]
