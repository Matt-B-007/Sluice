# SPDX-License-Identifier: GPL-3.0-or-later
"""Install a newer Sluice release in place, without downloading and unpacking a zip by hand.

How it works, and what it will never do:

* It only runs when you ask (Help > Check for updates > Update now) or when you switched on *Update automatically*.
* It downloads the release zip and its ``.sha256`` file from the release page, over https, and refuses to go on unless
  the zip matches the checksum. (That catches a damaged or cut-off download. It cannot catch a release that was
  tampered with on GitHub itself: the checksum comes from the same place.)
* It unpacks into ``.update/`` inside the Sluice folder, never outside it, and refuses archives with absolute paths,
  ``..``, links, or an unreasonable size.
* Before touching anything it starts the new code once in a separate process to see that it imports, and that its
  version is the one the release promised.
* It swaps the program files (the folders and files that the release contains) and keeps the old ones in ``.previous/``.
  Your ``.venv``, your settings and everything else in the folder are not touched.
* The swap is done when Sluice closes or restarts, never while it runs, so a running Sluice never loads half of each
  version. *Go back to the previous version* (or ``sluice --rollback``) puts the old files back.

A copy of Sluice that is a git checkout, or that sits in a folder you cannot write to, is never changed: it is
updated with ``git pull`` or the way you installed it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("sluice.selfupdate")

WORK = ".update"          # where a downloaded release waits (inside the Sluice folder: same disk, so renames are instant)
PREVIOUS = ".previous"    # the files of the version before the last update
READY = "ready.json"
PROTECTED = {".venv", ".git", WORK, PREVIOUS, "sluice.egg-info"}  # never replaced, never removed
MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_UNPACKED_BYTES = 300 * 1024 * 1024
MAX_FILES = 5000
TRUSTED_HOST = "github.com"
CHECK_SECONDS = 180

# What the new code must be able to do before it is allowed to replace the old: import its main parts from its own folder.
_CHECK = (
    "import sys\n"
    "tree = sys.argv[1]\n"
    "sys.path.insert(0, tree)\n"
    "import sluice, sluice.engine, sluice.model, sluice.updates, sluice.ui\n"
    "assert sluice.__file__.startswith(tree), sluice.__file__\n"
    "print(sluice.__version__)\n"
)


class UpdateError(Exception):
    """Something went wrong; the message is meant to be shown to the user. Sluice itself is left as it was."""


# ----------------------------------------------------------------------------------------------- where and whether
def install_root(package_file: Optional[str] = None) -> Optional[Path]:
    """The Sluice folder (the one with pyproject.toml and install.sh), or None if this is not such an install."""
    package = Path(package_file or __file__).resolve().parent
    root = package.parent
    if package.name != "sluice" or not (root / "pyproject.toml").is_file() or not (root / "install.sh").is_file():
        return None
    return root


def unavailable_reason(root: Optional[Path]) -> str:
    """Why this copy cannot update itself, or '' when it can."""
    if root is None:
        return ("This copy of Sluice was not installed from the release zip (there is no Sluice folder next to its code), "
                "so it cannot replace itself. Update it the way you installed it.")
    if (root / ".git").exists():
        return "This copy is a git checkout. Update it with: git pull"
    if not os.access(root, os.W_OK):
        return f"Sluice cannot write to its own folder ({root}), so it cannot update itself there."
    return ""


def offer_problem(root: Optional[Path], result) -> str:
    """Why this release cannot be installed automatically, or '' when it can (``result`` is an updates.UpdateResult)."""
    reason = unavailable_reason(root)
    if reason:
        return reason
    if not (getattr(result, "zip_url", "") and getattr(result, "checksum_url", "")):
        return "This release does not include the zip and its checksum file, so it has to be downloaded by hand."
    return ""


def disk_version(folder: Path) -> str:
    """The version written in ``folder/sluice/__init__.py``, read as text (nothing is imported)."""
    try:
        text = (folder / "sluice" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else ""


def _newer(a: str, b: str) -> bool:
    from .updates import is_newer

    return is_newer(a, b)


# -------------------------------------------------------------------------------------------------------- downloading
class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError("the download was redirected to an address that is not https")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, timeout: float):
    if not url.lower().startswith("https://"):
        raise UpdateError("The download address must start with https://")
    from . import __version__

    opener = urllib.request.build_opener(_HttpsOnly)
    return opener.open(urllib.request.Request(url, headers={"User-Agent": f"sluice/{__version__}"}), timeout=timeout)


def fetch_text(url: str, timeout: float = 20.0) -> str:
    with _open(url, timeout) as response:
        return response.read(4096).decode("utf-8", "replace")


def download(url: str, dest: Path, progress: Optional[Callable[[int, int], None]] = None, timeout: float = 20.0) -> None:
    """Save ``url`` to ``dest``; ``progress(done, total)`` is called as it goes (total is 0 when unknown)."""
    with _open(url, timeout) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        if total > MAX_ZIP_BYTES:
            raise UpdateError("The download is larger than a Sluice release should ever be, so it was not fetched.")
        done = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            done += len(chunk)
            if done > MAX_ZIP_BYTES:
                raise UpdateError("The download is larger than a Sluice release should ever be, so it was stopped.")
            out.write(chunk)
            if progress:
                progress(done, total)


def sha256_of(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_checksum(text: str, filename: str) -> str:
    """The hash from a ``sha256sum`` file (``<hash>  <name>``), or a bare hash. '' when it cannot be trusted."""
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if not parts or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            continue
        if len(parts) == 2 and os.path.basename(parts[1].strip().lstrip("*")) != filename:
            continue  # a line for another file
        return parts[0].lower()
    return ""


def _check_url(url: str) -> None:
    if not url.lower().startswith("https://"):
        raise UpdateError("The download address must start with https://")
    host = url.split("/", 3)[2].lower()
    if host != TRUSTED_HOST and not os.environ.get("SLUICE_UPDATE_URL"):
        raise UpdateError(f"Updates are only downloaded from {TRUSTED_HOST}; this release points to {host}.")


# --------------------------------------------------------------------------------------------------------- unpacking
def extract(zip_path: Path, dest: Path) -> Path:
    """Unpack the release zip safely into ``dest`` and return the folder that holds ``pyproject.toml``."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UpdateError("The downloaded file is not a valid zip.") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_FILES:
            raise UpdateError("The downloaded zip is empty or has an unreasonable number of files.")
        if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
            raise UpdateError("The downloaded zip would unpack to an unreasonable size.")
        names = []
        for info in infos:
            name = info.filename
            parts = name.split("/")
            if name.startswith("/") or "\\" in name or ".." in parts or re.match(r"^[A-Za-z]:", name):
                raise UpdateError(f"The downloaded zip contains an unsafe path ({name!r}).")
            if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                raise UpdateError(f"The downloaded zip contains a link ({name!r}), which a release never does.")
            names.append(name)
        tops = {n.split("/", 1)[0] for n in names}
        strip = len(tops) == 1 and all("/" in n for n in names)  # one folder around everything (git archive --prefix)
        dest.mkdir(parents=True, exist_ok=True)
        base = dest.resolve()
        for info in infos:
            relative = info.filename.split("/", 1)[1] if strip else info.filename
            if not relative:
                continue
            target = (base / relative).resolve()
            if base not in target.parents and target != base:
                raise UpdateError(f"The downloaded zip tries to write outside its folder ({info.filename!r}).")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            mode = (info.external_attr >> 16) & 0o777
            os.chmod(target, 0o755 if mode & 0o111 else 0o644)
    return dest


def check_tree(tree: Path, expected: str) -> None:
    """The unpacked release must look like Sluice and carry the version the release page promised."""
    for needed in ("pyproject.toml", "install.sh", "sluice/__init__.py"):
        if not (tree / needed).is_file():
            raise UpdateError(f"The downloaded release is missing {needed}, so it was not installed.")
    found = disk_version(tree)
    if found != expected.lstrip("vV"):
        raise UpdateError(f"The download says it is version {found or 'unknown'}, not {expected}, so it was not installed.")


def dependencies(pyproject_text: str) -> list:
    """The ``dependencies = [...]`` of a pyproject.toml (the runtime ones, not the optional ones)."""
    match = re.search(r"^dependencies\s*=\s*\[(.*?)\]", pyproject_text, re.S | re.M)
    return re.findall(r'"([^"]+)"', match.group(1)) if match else []


def _install_dependencies(root: Path, tree: Path, run: Callable) -> None:
    def read(folder: Path) -> list:
        try:
            return dependencies((folder / "pyproject.toml").read_text(encoding="utf-8"))
        except OSError:
            return []

    wanted, have = read(tree), read(root)
    if not wanted or set(wanted) == set(have):
        return
    log.info("the new version needs other packages: %s", wanted)
    try:
        done = run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *wanted],
                   capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"The new version needs packages that could not be installed ({exc}). Sluice is unchanged.") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
        raise UpdateError("The new version needs packages that could not be installed. Sluice is unchanged.\n" + "\n".join(tail))


# ---------------------------------------------------------------------------------------------------------- staging
def staged(root: Path) -> Optional[dict]:
    """The downloaded and verified release waiting to be installed, or None."""
    try:
        data = json.loads((root / WORK / READY).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("version"), str) or not (root / WORK / "tree").is_dir():
        return None
    return data


def discard_staged(root: Path) -> None:
    shutil.rmtree(root / WORK, ignore_errors=True)


def stage(result, root: Path, progress: Optional[Callable[[int, int], None]] = None,
          fetch_text: Callable = fetch_text, download: Callable = download, run: Optional[Callable] = None) -> str:
    """Download, verify and unpack the release in ``result`` (an updates.UpdateResult) into ``root/.update``.

    Nothing of the running Sluice is changed. Returns the version. Raises UpdateError with a readable message."""
    run = run or subprocess.run
    problem = offer_problem(root, result)
    if problem:
        raise UpdateError(problem)
    version = result.latest.lstrip("vV")
    current = disk_version(root)
    if current and not _newer(version, current):
        raise UpdateError(f"Sluice {current} is already installed here.")
    waiting = staged(root)
    if waiting and waiting["version"] == version:
        return version  # downloaded earlier (for example by the automatic update); nothing more to fetch
    _check_url(result.zip_url)
    _check_url(result.checksum_url)
    name = os.path.basename(result.zip_url.split("?", 1)[0])
    work = root / WORK
    shutil.rmtree(work, ignore_errors=True)
    try:
        work.mkdir()
        try:
            text = fetch_text(result.checksum_url)
        except UpdateError:
            raise
        except Exception as exc:
            raise UpdateError(f"Could not download the checksum file: {exc}") from exc
        wanted = parse_checksum(text, name)
        if not wanted:
            raise UpdateError("The checksum file for this release could not be read, so it was not downloaded.")
        archive = work / name
        try:
            download(result.zip_url, archive, progress)
        except UpdateError:
            raise
        except Exception as exc:
            raise UpdateError(f"Could not download the update: {exc}") from exc
        if sha256_of(archive) != wanted:
            raise UpdateError("The downloaded file does not match its checksum (it is damaged or incomplete). Nothing was installed.")
        tree = extract(archive, work / "tree")
        archive.unlink()
        check_tree(tree, version)
        _install_dependencies(root, tree, run)
        (work / READY).write_text(json.dumps({"version": version, "sha256": wanted, "name": name}), encoding="utf-8")
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    log.info("update %s downloaded and verified", version)
    return version


# ----------------------------------------------------------------------------------------------------- the swap itself
def _verify_new_code(tree: Path, expected: str, run: Callable) -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        done = run([sys.executable, "-I", "-c", _CHECK, str(tree.resolve())], capture_output=True, text=True,
                   timeout=CHECK_SECONDS, env=env, cwd=str(tree))
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"The new version could not be tried out ({exc}), so it was not installed.") from exc
    if done.returncode != 0 or done.stdout.strip().splitlines()[-1:] != [expected]:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
        raise UpdateError("The new version did not start properly when tried, so it was not installed. Sluice is unchanged.\n"
                          + "\n".join(tail))


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _restore(root: Path, previous: Path, moved: list, added: list) -> None:
    for name in added:
        if (root / name).exists() or (root / name).is_symlink():
            _remove(root / name)
    for name in moved:
        saved = previous / name
        if saved.exists() or saved.is_symlink():
            if (root / name).exists() or (root / name).is_symlink():
                _remove(root / name)
            os.replace(saved, root / name)


def apply_staged(root: Path, run: Optional[Callable] = None) -> Optional[str]:
    """Install the release waiting in ``root/.update`` and keep the old files in ``root/.previous``.

    Returns the new version, or None when nothing was waiting. Raises UpdateError (and leaves the old files in place)
    when it cannot. Call it only when Sluice is closing or about to restart."""
    run = run or subprocess.run
    waiting = staged(root)
    if waiting is None:
        return None
    tree = root / WORK / "tree"
    version = waiting["version"]
    current = disk_version(root)
    if disk_version(tree) != version or (current and not _newer(version, current)):
        discard_staged(root)  # stale: already installed, or not what it claims
        return None
    try:
        _verify_new_code(tree, version, run)
    except UpdateError:
        discard_staged(root)
        raise
    names = sorted(n for n in os.listdir(tree) if n not in PROTECTED)
    moved = [n for n in names if (root / n).exists() or (root / n).is_symlink()]
    added = [n for n in names if n not in moved]
    previous = root / PREVIOUS
    shutil.rmtree(previous, ignore_errors=True)
    previous.mkdir()
    (previous / "manifest.json").write_text(
        json.dumps({"version": current, "moved": moved, "added": added, "installed": version}), encoding="utf-8")
    try:
        for name in names:
            if name in moved:
                os.replace(root / name, previous / name)
            os.replace(tree / name, root / name)
    except Exception as exc:
        log.warning("the update failed half-way (%s); putting the old files back", exc)
        try:
            _restore(root, previous, moved, added)
        except Exception:
            log.exception("could not put the old files back")
            raise UpdateError(f"The update failed and the old files could not be fully restored ({exc}). "
                              f"Unpack the release zip by hand; your settings are not affected.") from exc
        raise UpdateError(f"The update could not be installed ({exc}). Sluice is as it was.") from exc
    discard_staged(root)
    log.info("updated %s -> %s", current, version)
    return version


def apply_staged_quietly() -> Optional[str]:
    """Used when Sluice closes: install a waiting update if there is one; log, never raise."""
    try:
        root = install_root()
        if root is None or unavailable_reason(root):
            return None
        return apply_staged(root)
    except Exception as exc:
        log.warning("could not install the waiting update: %s", exc)
        return None


# ------------------------------------------------------------------------------------------------------ going back
def previous_version(root: Optional[Path]) -> str:
    """The version that *Go back* would restore, or '' when there is nothing to go back to."""
    if root is None:
        return ""
    try:
        data = json.loads((root / PREVIOUS / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict) or not data.get("moved"):
        return ""
    return str(data.get("version") or "an earlier version")


def rollback(root: Path) -> str:
    """Put the files of the version before the last update back. Returns that version."""
    version = previous_version(root)
    if not version:
        raise UpdateError("There is no earlier version to go back to.")
    reason = unavailable_reason(root)
    if reason:
        raise UpdateError(reason)
    previous = root / PREVIOUS
    data = json.loads((previous / "manifest.json").read_text(encoding="utf-8"))
    try:
        _restore(root, previous, list(data.get("moved", [])), list(data.get("added", [])))
    except Exception as exc:
        raise UpdateError(f"Could not go back to the earlier version ({exc}).") from exc
    shutil.rmtree(previous, ignore_errors=True)
    discard_staged(root)
    log.info("went back to %s", version)
    return version
