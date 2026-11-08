# SPDX-License-Identifier: GPL-3.0-or-later
"""Check whether a newer sluice exists. Only ever runs when the user asks (Help > Check for updates).

sluice has no download page of its own yet, so ``RELEASE_URL`` is empty. When one exists, put its address here
(or set ``SLUICE_UPDATE_URL``). The address must answer with JSON in one of two shapes::

    {"tag_name": "v0.4.0", "html_url": "https://..."}      (what GitHub's "latest release" API returns)
    [{"tag_name": "v0.4.0", "html_url": "https://..."}]    (GitHub's list of releases, newest first: use this one
                                                            while releases are marked "pre-release", because the
                                                            "latest" address skips those)
    {"version": "0.4.0",   "url": "https://..."}
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

RELEASE_URL = "https://api.github.com/repos/Matt-B-007/Sluice/releases?per_page=5"
MAX_BYTES = 1024 * 1024


@dataclass
class UpdateResult:
    status: str      # "not_configured", "up_to_date", "available" or "error"
    current: str
    latest: str = ""
    page: str = ""   # where to download it
    message: str = ""


def parse_version(text: str) -> tuple:
    """'v0.3.10-beta' -> (0, 3, 10). Anything unreadable gives (), which is never newer."""
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)", str(text))
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    width = max(len(a), len(b))
    return bool(a) and a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def _fetch(url: str, timeout: float):
    if not url.lower().startswith("https://"):
        raise ValueError("the update address must start with https://")
    from . import __version__

    request = urllib.request.Request(url, headers={"User-Agent": f"sluice/{__version__}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https only, checked above)
        data = json.loads(response.read(MAX_BYTES).decode("utf-8"))
    if not isinstance(data, (dict, list)):
        raise ValueError("unexpected answer")
    return data


def check(current: str, url: Optional[str] = None, fetch: Optional[Callable[[str, float], dict]] = None,
          timeout: float = 6.0) -> UpdateResult:
    url = url if url is not None else (os.environ.get("SLUICE_UPDATE_URL") or RELEASE_URL)
    if not url:
        return UpdateResult("not_configured", current)
    try:
        data = (fetch or _fetch)(url, timeout)
        if isinstance(data, list):  # GitHub's list of releases (newest first); "latest" would skip pre-releases such as betas
            data = next((item for item in data if isinstance(item, dict) and not item.get("draft") and item.get("tag_name")), None)
            if data is None:
                raise ValueError("no releases found")
        latest = str(data.get("tag_name") or data.get("version") or "").strip()
        page = str(data.get("html_url") or data.get("url") or "")
    except Exception as exc:  # offline, bad address, bad JSON: all just "could not check"
        return UpdateResult("error", current, message=str(exc) or type(exc).__name__)
    if not parse_version(latest):
        return UpdateResult("error", current, message="the answer did not contain a version number")
    if not page.lower().startswith("https://"):
        page = ""
    status = "available" if is_newer(latest, current) else "up_to_date"
    return UpdateResult(status, current, latest.lstrip("vV"), page)
