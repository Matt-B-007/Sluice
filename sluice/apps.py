# SPDX-License-Identifier: GPL-3.0-or-later
"""A list of the programs and games installed on this computer, so they can be picked instead of typed.

Sources: the desktop-entry files (``*.desktop``) that every Linux app menu uses, Steam's game manifests, and the
game lists of Lutris, Heroic/Epic (legendary) and Bottles. Nothing here touches audio. A running program is recognised by any of several names
(its binary, its window/app name, a Steam game id), so ``Catalog.expand`` turns the one name a
channel remembers into all the names that mean the same program.
"""
from __future__ import annotations

import logging
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("sluice.apps")

STEAM_PREFIX = "steam:"
_SKIP_STEAM = ("proton", "steam linux runtime", "steamworks common", "steam runtime")
_STEAM_URL = re.compile(r"steam://(?:rungameid|run)/(\d+)")


@dataclass(frozen=True)
class AppEntry:
    name: str            # shown to the user
    key: str             # what a channel remembers (lower case)
    kind: str            # "app" or "game"
    aliases: frozenset   # every lower-case name that identifies this program, including the key


class Catalog:
    def __init__(self, entries: Iterable[AppEntry] = ()) -> None:
        self.entries = sorted(entries, key=lambda e: e.name.casefold())
        self._by_key = {e.key: e for e in self.entries}

    def __len__(self) -> int:
        return len(self.entries)

    def label(self, key: str) -> Optional[str]:
        entry = self._by_key.get(key)
        return entry.name if entry else None

    def expand(self, key: str) -> frozenset:
        """All names that mean the same program as ``key`` (at least ``key`` itself)."""
        entry = self._by_key.get(key)
        return (entry.aliases | {key}) if entry else frozenset({key})

    # --------------------------------------------------------------------- scanning
    @classmethod
    def scan(cls, desktop_dirs: Optional[list] = None, steam_roots: Optional[list] = None,
             home: Optional[Path] = None) -> "Catalog":
        entries: dict = {}
        try:
            for path in desktop_files(desktop_dirs if desktop_dirs is not None else default_desktop_dirs()):
                entry = parse_desktop_file(path)
                if entry is not None:
                    entries.setdefault(entry.key, entry)
            for entry in steam_games(steam_roots if steam_roots is not None else default_steam_roots()):
                entries[entry.key] = entry  # the manifest's name is the better one
            for entry in launcher_games(home if home is not None else Path.home()):
                entries.setdefault(entry.key, entry)
        except Exception as exc:  # a strange file must never stop the app: an empty list is fine
            log.warning("could not list installed programs: %s", exc)
        catalog = cls(entries.values())
        log.info("installed programs found: %d (%d games)", len(catalog), sum(e.kind == "game" for e in catalog.entries))
        return catalog


# ------------------------------------------------------------------------- desktop entries
def default_desktop_dirs() -> list:
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    dirs = [home / "applications", home / "flatpak" / "exports" / "share" / "applications"]
    for base in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"):
        if base:
            dirs.append(Path(base) / "applications")
    dirs.append(Path("/var/lib/flatpak/exports/share/applications"))
    seen, unique = set(), []
    for d in dirs:
        if str(d) not in seen:
            seen.add(str(d))
            unique.append(d)
    return unique


def desktop_files(directories: list) -> Iterable[Path]:
    for directory in directories:
        try:
            yield from sorted(Path(directory).glob("*.desktop"))
        except OSError:
            continue


def _read_entry(path: Path) -> dict:
    values: dict = {}
    in_section = False
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_section = line == "[Desktop Entry]"
            continue
        if in_section and "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values.setdefault(key.strip(), value.strip())  # first one wins; Name[de] etc. are different keys
    return values


def binary_from_exec(command: str) -> tuple:
    """(binary name, extra identifiers) from a desktop entry's Exec line, or ("", set())."""
    try:
        tokens = shlex.split(re.sub(r"%[a-zA-Z%]", "", command))
    except ValueError:
        return "", set()
    while tokens and (tokens[0] == "env" or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0])):
        tokens.pop(0)
    if not tokens:
        return "", set()
    first = os.path.basename(tokens[0]).lower()
    extra: set = set()
    if first == "flatpak" and "run" in tokens:
        rest = tokens[tokens.index("run") + 1:]
        command_option = next((t.split("=", 1)[1] for t in rest if t.startswith("--command=")), "")
        app_id = next((t for t in rest if not t.startswith("-")), "")
        if app_id:
            extra.add(app_id.lower())
        binary = os.path.basename(command_option).lower() or app_id.split(".")[-1].lower()
        return binary, extra
    return first, extra


def parse_desktop_file(path: Path) -> Optional[AppEntry]:
    values = _read_entry(path)
    if values.get("Type", "Application") != "Application":
        return None
    if values.get("NoDisplay", "").lower() == "true" or values.get("Hidden", "").lower() == "true":
        return None
    name, command = values.get("Name", ""), values.get("Exec", "")
    if not name or not command:
        return None
    steam = _STEAM_URL.search(command)
    categories = {c for c in values.get("Categories", "").split(";") if c}
    if steam:
        key = f"{STEAM_PREFIX}{steam.group(1)}"
        return AppEntry(name, key, "game", frozenset({key, name.lower()}))
    binary, extra = binary_from_exec(command)
    if not binary or binary in ("steam", "sh", "bash", "env"):
        return None  # the Steam launcher itself and shell wrappers cannot be recognised by their binary
    aliases = {binary, name.lower(), Path(path).stem.lower()} | extra
    wm_class = values.get("StartupWMClass", "").lower()
    if wm_class:
        aliases.add(wm_class)
    return AppEntry(name, binary, "game" if "Game" in categories else "app", frozenset(aliases))


# ------------------------------------------------------------------------------------ Steam
def default_steam_roots() -> list:
    home = Path.home()
    return [
        home / ".local" / "share" / "Steam",
        home / ".steam" / "steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    ]


def steam_libraries(roots: list) -> list:
    libraries: list = []
    for root in roots:
        root = Path(root)
        candidates = [root]
        try:
            text = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
            candidates += [Path(p) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
        except OSError:
            pass
        for path in candidates:
            try:
                real = path.resolve()
            except OSError:
                continue
            if real not in libraries and (real / "steamapps").is_dir():
                libraries.append(real)
    return libraries


def steam_games(roots: list) -> Iterable[AppEntry]:
    for library in steam_libraries(roots):
        try:
            manifests = sorted((library / "steamapps").glob("appmanifest_*.acf"))
        except OSError:
            continue
        for manifest in manifests:
            try:
                text = manifest.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            app_id = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]*)"', text)
            if not app_id or not name or not name.group(1).strip():
                continue
            title = name.group(1).strip()
            if title.lower().startswith(_SKIP_STEAM):
                continue  # tools, not games
            key = f"{STEAM_PREFIX}{app_id.group(1)}"
            yield AppEntry(title, key, "game", frozenset({key, title.lower()}))


def steam_id_of_process(pid: int) -> Optional[str]:
    """The Steam game id a running program was started with, if any (read from its environment)."""
    try:
        data = Path(f"/proc/{int(pid)}/environ").read_bytes()
    except (OSError, ValueError):
        return None
    found = {}
    for item in data.split(b"\0"):
        for var in (b"SteamGameId=", b"SteamAppId="):
            if item.startswith(var):
                value = item[len(var):].decode("ascii", "ignore")
                if value.isdigit() and value != "0":
                    found[var] = value
    value = found.get(b"SteamGameId=") or found.get(b"SteamAppId=")
    return f"{STEAM_PREFIX}{value}" if value else None


# ------------------------------------------------------------------------- other game launchers
def _exe_aliases(title: str, key: str, exe: str) -> frozenset:
    """Names a running Wine/Proton game may appear under: the title and the program file's name, with and without .exe."""
    names = {key, title.lower()}
    base = re.split(r"[\\/]", exe.strip().strip("\"'"))[-1].lower() if exe else ""
    if base:
        names.add(base)
        if base.endswith(".exe"):
            names.add(base[:-4])
    return frozenset(n for n in names if n)


def lutris_games(home: Path) -> Iterable[AppEntry]:
    """Installed Lutris games (its ``pga.db`` lists them; each game's ``.yml`` names the program file)."""
    import sqlite3

    for data, config in ((home / ".local" / "share" / "lutris", home / ".config" / "lutris"),
                         (home / ".var" / "app" / "net.lutris.Lutris" / "data" / "lutris",
                          home / ".var" / "app" / "net.lutris.Lutris" / "config" / "lutris")):
        db = data / "pga.db"
        if not db.is_file():
            continue
        try:
            connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
            try:
                rows = connection.execute("SELECT name, slug, configpath FROM games WHERE installed = 1").fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            log.debug("lutris database not readable: %s", exc)
            continue
        for name, slug, configpath in rows:
            if not name or not slug:
                continue
            exe = ""
            if configpath:
                try:
                    text = (config / "games" / f"{configpath}.yml").read_text(encoding="utf-8", errors="replace")
                    found = re.search(r"^\s*exe:\s*(.+?)\s*$", text, re.M)
                    exe = found.group(1) if found else ""
                except OSError:
                    pass
            key = f"lutris:{slug}"
            yield AppEntry(str(name), key, "game", _exe_aliases(str(name), key, exe))


def legendary_games(home: Path) -> Iterable[AppEntry]:
    """Installed Epic games, from the ``installed.json`` of legendary and of Heroic."""
    import json

    for path in (home / ".config" / "legendary" / "installed.json",
                 home / ".config" / "heroic" / "legendaryConfig" / "legendary" / "installed.json",
                 home / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic" / "legendaryConfig" / "legendary" / "installed.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for app_name, item in data.items():
            if not isinstance(item, dict) or not item.get("title"):
                continue
            key = f"epic:{app_name}".lower()
            yield AppEntry(str(item["title"]), key, "game",
                           _exe_aliases(str(item["title"]), key, str(item.get("executable") or "")))


def bottles_programs(home: Path) -> Iterable[AppEntry]:
    """Programs added to Bottles bottles (each bottle's ``bottle.yml`` lists them with a name and a program file)."""
    for root in (home / ".local" / "share" / "bottles" / "bottles",
                 home / ".var" / "app" / "com.usebottles.bottles" / "data" / "bottles" / "bottles"):
        try:
            files = sorted(root.glob("*/bottle.yml"))
        except OSError:
            continue
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            name = exe = ""
            for line in lines + [""]:
                found = re.match(r"^\s+(name|executable|path):\s*(.+?)\s*$", line)
                if found:
                    field, value = found.group(1), found.group(2).strip("\"'")
                    if field == "name":
                        if name and exe:
                            yield _bottle_entry(path.parent.name, name, exe)
                        name, exe = value, ""
                    elif field == "executable" or (field == "path" and not exe):
                        exe = value
                elif not line.strip() and name and exe:
                    yield _bottle_entry(path.parent.name, name, exe)
                    name = exe = ""
            if name and exe:
                yield _bottle_entry(path.parent.name, name, exe)


def _bottle_entry(bottle: str, name: str, exe: str) -> AppEntry:
    key = f"bottles:{bottle}:{name}".lower()
    return AppEntry(name, key, "app", _exe_aliases(name, key, exe))


def launcher_games(home: Path) -> Iterable[AppEntry]:
    for source in (lutris_games, legendary_games, bottles_programs):
        try:
            yield from source(home)
        except Exception as exc:  # one launcher's odd file must not hide the others
            log.debug("%s failed: %s", source.__name__, exc)
