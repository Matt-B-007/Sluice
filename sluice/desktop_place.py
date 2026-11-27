# SPDX-License-Identifier: GPL-3.0-or-later
"""Where desktop widgets go (0.11.5): snapping to the screen's edges and to each other, a remembered place on each screen, and, on
KDE Plasma under Wayland, real desktop-widget windows through KDE's layer-shell, with a KWin window rule as the fallback.

Wayland does not let an ordinary window place itself, and "keep on top" is only a request there. KDE's layer-shell (the protocol its
own panels and widgets use) does both: a widget window on the top layer, anchored to the top left corner of its screen with margins
that say where it is. Sluice talks to KDE's own LayerShellQt library through ctypes (it has no Python binding), only on KDE under
Wayland, and only if the library and every function it needs are there; anything missing and the widget is an ordinary window, as
before. Elsewhere on KDE, a KWin window rule (written with kwriteconfig and applied with a KWin reconfigure) keeps the widgets on top.

The snapping and the places are pure functions of rectangles, so they are easy to test."""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("sluice.desktop_place")

SNAP = 16  # pixels: an edge this close to a screen edge or another widget's edge snaps to it
GAP = 8  # widgets snapped beside each other keep this gap
MAX_PLACES = 8  # screens a widget remembers a place on


# ----------------------------------------------------------------------------- snapping (pure)
def snap(rect: tuple, screen: tuple, others: list, distance: int = SNAP, gap: int = GAP) -> tuple:
    """Where a widget at ``rect`` (x, y, w, h) settles: its edges snap to the screen's available area ``screen`` (x, y, w, h) and to
    the edges of ``others`` (other widgets' rects, a ``gap`` apart, or lined up with them) when they are within ``distance``. It is
    then kept inside the screen. Returns the new (x, y)."""
    x, y, w, h = rect
    sx, sy, sw, sh = screen
    best_x, best_y = (distance + 1, None), (distance + 1, None)

    def consider(best, value, target):
        d = abs(value - target)
        return (d, target) if d < best[0] else best

    # the screen's edges
    best_x = consider(best_x, x, sx)
    best_x = consider(best_x, x + w, sx + sw)
    best_y = consider(best_y, y, sy)
    best_y = consider(best_y, y + h, sy + sh)
    candidates_x, candidates_y = [], []
    for ox, oy, ow, oh in others:
        overlap_y = y < oy + oh + distance and oy < y + h + distance
        overlap_x = x < ox + ow + distance and ox < x + w + distance
        if overlap_y:  # side by side: beside it with a gap, or lined up with its left or right edge
            candidates_x += [(x, ox + ow + gap, 0), (x + w, ox - gap, w), (x, ox, 0), (x + w, ox + ow, w)]
        if overlap_x:  # one above the other
            candidates_y += [(y, oy + oh + gap, 0), (y + h, oy - gap, h), (y, oy, 0), (y + h, oy + oh, h)]
    snapped_x, snapped_y = x, y
    for edge, target, offset in candidates_x:
        if abs(edge - target) < best_x[0]:
            best_x = (abs(edge - target), target - offset)
    for edge, target, offset in candidates_y:
        if abs(edge - target) < best_y[0]:
            best_y = (abs(edge - target), target - offset)
    if best_x[1] is not None:
        snapped_x = best_x[1] if best_x[1] not in (sx + sw,) else sx + sw - w
    if best_y[1] is not None:
        snapped_y = best_y[1] if best_y[1] not in (sy + sh,) else sy + sh - h
    return clamp((snapped_x, snapped_y, w, h), screen)


def clamp(rect: tuple, screen: tuple) -> tuple:
    """(x, y) of ``rect`` moved just enough to be inside ``screen``."""
    x, y, w, h = rect
    sx, sy, sw, sh = screen
    return (max(sx, min(x, sx + sw - w)), max(sy, min(y, sy + sh - h)))


# ----------------------------------------------------------------------------- a place on each screen (pure)
def remember(spec: dict, screen_name: str, x: int, y: int) -> None:
    """Keep where the widget is on this screen (and that this is the screen it was last on)."""
    places = spec.get("places") if isinstance(spec.get("places"), dict) else {}
    places = dict(places)
    places[screen_name] = [int(x), int(y)]
    if len(places) > MAX_PLACES:  # forget the oldest screens first (dicts keep their order)
        for old in list(places)[:-MAX_PLACES]:
            if old != screen_name:
                places.pop(old, None)
    spec["places"] = places
    spec["screen"] = screen_name
    spec["x"], spec["y"] = int(x), int(y)


def place_for(spec: dict, screens: dict, primary: str, size: tuple) -> Optional[tuple]:
    """Where to show a widget: its place on the screen it was last on if that screen is here, else its place on any screen that is
    here, else its saved x and y if they are on a screen, else None (the caller picks a spot). ``screens`` maps names to their
    available areas (x, y, w, h); the result is kept inside that screen."""
    places = spec.get("places") if isinstance(spec.get("places"), dict) else {}
    order = [spec.get("screen")] + [name for name in places if name != spec.get("screen")]
    for name in order:
        if name in screens and name in places:
            x, y = places[name]
            return clamp((x, y) + tuple(size), screens[name])
    x, y = spec.get("x"), spec.get("y")
    if isinstance(x, int) and isinstance(y, int):
        for area in screens.values():
            ax, ay, aw, ah = area
            if ax <= x < ax + aw and ay <= y < ay + ah:
                return clamp((x, y) + tuple(size), area)
        if primary in screens:  # its screen is gone: the same spot on the main screen, kept on it
            return clamp((x, y) + tuple(size), screens[primary])
    return None


def clean_places(value) -> dict:
    """Saved places made safe: at most a few screens, each a short name and two whole numbers in range."""
    out = {}
    if isinstance(value, dict):
        for name, pair in list(value.items())[:MAX_PLACES]:
            if (
                isinstance(name, str)
                and 0 < len(name) <= 60
                and isinstance(pair, list)
                and len(pair) == 2
                and all(isinstance(n, int) and not isinstance(n, bool) and -5000 <= n <= 20000 for n in pair)
            ):
                out[name] = [pair[0], pair[1]]
    return out


# ----------------------------------------------------------------------------- KDE layer-shell
def kde_wayland(env=None, platform: str = "") -> bool:
    env = os.environ if env is None else env
    desktop = (env.get("XDG_CURRENT_DESKTOP", "") + ":" + env.get("XDG_SESSION_DESKTOP", "")).upper()
    wayland = platform == "wayland" or (not platform and env.get("XDG_SESSION_TYPE") == "wayland")
    return wayland and "KDE" in desktop


def mangle(method: str, arguments: str) -> str:
    """The C++ (Itanium) name of ``LayerShellQt::Window::method``, as the library exports it. Built here from the method's name and
    its arguments' codes, so a name can never carry a miscounted length again (0.11.5 asked for one with a 24 where 21 belonged)."""
    return f"_ZN12LayerShellQt6Window{len(method)}{method}E{arguments}"


def nested(name: str) -> str:
    """The code for a type declared inside LayerShellQt::Window (an enum such as Layer or KeyboardInteractivity)."""
    return f"NS0_{len(name)}{name}E"


# The LayerShellQt functions Sluice uses. The first four are needed; the rest are used when the library has them.
SYMBOLS = {
    "get": mangle("get", "P7QWindow"),
    "setLayer": mangle("setLayer", nested("Layer")),
    "setAnchors": mangle("setAnchors", "6QFlagsI" + nested("Anchor") + "E"),
    "setMargins": mangle("setMargins", "RK8QMargins"),
    "setKeyboardInteractivity": mangle("setKeyboardInteractivity", nested("KeyboardInteractivity")),
    "setExclusiveZone": mangle("setExclusiveZone", "i"),
    "setScope": mangle("setScope", "RK7QString"),
    "setScreen": mangle("setScreen", "P7QScreen"),
    "setWantsToBeOnActiveScreen": mangle("setWantsToBeOnActiveScreen", "b"),
    "setActivateOnShow": mangle("setActivateOnShow", "b"),
}
REQUIRED = ("get", "setLayer", "setAnchors", "setMargins")
ARGUMENTS = {  # ctypes argument types after the window pointer
    "setLayer": [ctypes.c_int],
    "setAnchors": [ctypes.c_int],
    "setKeyboardInteractivity": [ctypes.c_int],
    "setExclusiveZone": [ctypes.c_int],
    "setScreen": [ctypes.c_void_p],
    "setWantsToBeOnActiveScreen": [ctypes.c_bool],
    "setActivateOnShow": [ctypes.c_bool],
}
LAYER_TOP = 2  # LayerShellQt::Window::LayerTop
ANCHOR_TOP, ANCHOR_LEFT = 1, 4
KEYBOARD_NONE = 0
LIBRARIES = ("libLayerShellQtInterface.so.6", "libLayerShellQtInterface.so.5", "libLayerShellQtInterface.so")


class _Margins(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("top", ctypes.c_int), ("right", ctypes.c_int), ("bottom", ctypes.c_int)]


class LayerShell:
    """KDE's LayerShellQt, if it can be used: ``available`` says so. ``attach(window)`` makes a not-yet-shown QWindow a top-layer
    surface anchored to the top left; ``place(window, x, y)`` moves it (its margins from that corner)."""

    def __init__(self, loader=None, env=None, platform: str = "") -> None:
        self.lib = None
        self.functions: dict = {}
        self.attached: dict = {}  # id(window) -> the LayerShellQt::Window pointer
        self.reason = ""
        if not kde_wayland(env, platform):
            self.reason = "not KDE Plasma on Wayland"
            return
        load = loader or self._load
        lib = load()
        if lib is None:
            self.reason = "KDE's layer-shell library (LayerShellQt) is not installed"
            return
        missing = []
        for key, name in SYMBOLS.items():
            function = getattr(lib, name, None)
            if function is None:
                if key in REQUIRED:
                    missing.append(name)
                continue
            self.functions[key] = function
        if missing:
            self.reason = f"LayerShellQt is missing a function Sluice needs ({', '.join(missing)})"
            self.functions = {}
            return
        self.lib = lib
        f = self.functions
        f["get"].restype = ctypes.c_void_p
        f["get"].argtypes = [ctypes.c_void_p]
        f["setMargins"].argtypes = [ctypes.c_void_p, ctypes.POINTER(_Margins)]
        for key, types in ARGUMENTS.items():
            if key in f:
                f[key].argtypes = [ctypes.c_void_p] + types

    def missing_optional(self) -> list:
        return [key for key in SYMBOLS if key not in REQUIRED and key not in self.functions]

    @staticmethod
    def _load():
        for name in LIBRARIES + tuple(filter(None, [ctypes.util.find_library("LayerShellQtInterface")])):
            try:
                return ctypes.CDLL(name)
            except OSError:
                continue
        return None

    @property
    def available(self) -> bool:
        return self.lib is not None

    def attach(self, window, pointer: Optional[int] = None, screen=None) -> bool:
        """Make ``window`` (a QWindow that has not been shown yet) a widget on the top layer of ``screen`` (a QScreen, or a C++
        address). ``pointer`` is the window's C++ address (found with shiboken when not given). Returns whether it worked; on any
        failure the window stays an ordinary one."""
        if not self.available:
            return False
        try:
            if pointer is None:
                pointer = _address(window)
            handle = self.functions["get"](ctypes.c_void_p(pointer))
            if not handle:
                return False
            f = self.functions
            f["setLayer"](handle, LAYER_TOP)
            f["setAnchors"](handle, ANCHOR_TOP | ANCHOR_LEFT)
            if "setKeyboardInteractivity" in f:
                f["setKeyboardInteractivity"](handle, KEYBOARD_NONE)
            if "setExclusiveZone" in f:
                f["setExclusiveZone"](handle, -1)  # never pushes panels or other windows aside
            if "setWantsToBeOnActiveScreen" in f:
                f["setWantsToBeOnActiveScreen"](handle, False)  # stays on its own screen, not the one you are working on
            if "setActivateOnShow" in f:
                f["setActivateOnShow"](handle, False)  # appearing does not take the keyboard from your game or browser
            self.attached[id(window)] = [handle, None]
            if screen is not None:
                self.set_screen(window, screen)
            return True
        except Exception as exc:  # a library from another version: stay an ordinary window
            log.info("layer-shell not used for a desktop widget: %s", exc)
            return False

    def set_screen(self, window, screen) -> bool:
        """Put a layer-shell widget on ``screen`` (a QScreen or its C++ address); without it, KDE picks a screen itself."""
        entry = self.attached.get(id(window))
        if entry is None or "setScreen" not in self.functions or screen is None:
            return False
        try:
            address = screen if isinstance(screen, int) else _address(screen)
            if entry[1] != address:
                self.functions["setScreen"](entry[0], ctypes.c_void_p(address))
                entry[1] = address
            return True
        except Exception as exc:
            log.info("could not put a layer-shell widget on its screen: %s", exc)
            return False

    def place(self, window, x: int, y: int, screen_origin: tuple = (0, 0), screen=None) -> bool:
        entry = self.attached.get(id(window))
        if entry is None:
            return False
        if screen is not None:
            self.set_screen(window, screen)
        margins = _Margins(max(0, int(x - screen_origin[0])), max(0, int(y - screen_origin[1])), 0, 0)
        try:
            self.functions["setMargins"](entry[0], ctypes.byref(margins))
            return True
        except Exception as exc:
            log.info("could not move a layer-shell widget: %s", exc)
            return False

    def is_attached(self, window) -> bool:
        return id(window) in self.attached

    def forget(self, window) -> None:
        self.attached.pop(id(window), None)


def _address(qt_object) -> int:
    import shiboken6

    return shiboken6.getCppPointer(qt_object)[0]


_shell: Optional[LayerShell] = None


def status() -> str:
    """One line for the bug report: whether desktop widgets use KDE's layer-shell, and why not if they do not."""
    shell = layer_shell()
    if shell.available:
        extra = shell.missing_optional()
        line = "KDE layer-shell (they place themselves and stay on top)" + (
            f"; this version lacks {', '.join(extra)}" if extra else ""
        )
    else:
        line = f"ordinary windows ({shell.reason})"
    if kde():
        glass = blur()
        line += "; Glass blur: " + ("KWin" if glass.available else f"none ({glass.reason})")
    return line


def layer_shell() -> LayerShell:
    """The one LayerShell for this run (looked for once)."""
    global _shell
    if _shell is None:
        platform = ""
        try:
            from PySide6.QtGui import QGuiApplication

            platform = QGuiApplication.platformName() or ""
        except Exception:  # no Qt application yet: the platform is unknown, so the environment decides
            pass
        _shell = LayerShell(platform=platform)
        if not _shell.available and kde_wayland(platform=platform):
            log.info("desktop widgets: %s", _shell.reason)
        elif _shell.available:
            log.info(
                "desktop widgets: KDE layer-shell in use%s",
                (" (without " + ", ".join(_shell.missing_optional()) + ")") if _shell.missing_optional() else "",
            )
    return _shell


# ----------------------------------------------------------------------------- KDE blur behind (0.11.6)
def kde(env=None) -> bool:
    env = os.environ if env is None else env
    return "KDE" in (env.get("XDG_CURRENT_DESKTOP", "") + ":" + env.get("XDG_SESSION_DESKTOP", "")).upper()


BLUR_LIBRARIES = ("libKF6WindowSystem.so.6", "libKF5WindowSystem.so.5")
# void KWindowEffects::enableBlurBehind(QWindow *window, bool enable, const QRegion &region)
BLUR_SYMBOL = "_ZN14KWindowEffects16enableBlurBehindEP7QWindowbRK7QRegion"


LIB_DIRS = ("/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu")


def system_qt(lib_dirs=LIB_DIRS) -> tuple:
    """(the system's Qt version, its plugin folder) when KDE's window-system plugins are installed there, else ("", None).
    Sluice runs PySide6's own Qt, so KDE's library looks for its plugins in PySide6's folder unless told where the system keeps
    them: then it finds none, prints "Could not find any platform plugin" and blurs nothing (0.11.6 on Plasma)."""
    import glob

    for folder in lib_dirs:
        plugins = Path(folder) / "qt6" / "plugins"
        if not (plugins / "kf6" / "kwindowsystem").is_dir():
            continue
        cores = sorted(glob.glob(os.path.join(folder, "libQt6Core.so.6.*")))
        version = cores[-1].rsplit(".so.", 1)[-1] if cores else ""
        return version, plugins
    return "", None


def same_minor(a: str, b: str) -> bool:
    return bool(a) and bool(b) and a.split(".")[:2] == b.split(".")[:2]


class Blur:
    """KDE's KWindowEffects, if it can be used: ``available`` says so. ``set(window, on, region)`` asks KWin to blur what is behind
    ``window`` inside ``region`` (the Glass skin). Elsewhere, or when it cannot work in this Qt, nothing is blurred and ``reason``
    says why (the bug report shows it)."""

    def __init__(
        self,
        loader=None,
        env=None,
        qt_version: Optional[str] = None,
        system: Optional[tuple] = None,
        add_path: Optional[Callable] = None,
    ) -> None:
        self.function = None
        self.reason = ""
        if not kde(env):
            self.reason = "not KDE Plasma"
            return
        version, plugins = system if system is not None else system_qt()
        if plugins is None:
            self.reason = "KDE's window-system plugins were not found"
            return
        if qt_version is None:
            from PySide6.QtCore import qVersion

            qt_version = qVersion()
        if version and not same_minor(version, qt_version):  # a plugin built for another Qt would not load (or worse)
            self.reason = f"the system's Qt is {version} and Sluice's is {qt_version}; KDE's blur only works in the same version"
            return
        if add_path is None:
            from PySide6.QtCore import QCoreApplication

            add_path = QCoreApplication.addLibraryPath
        add_path(str(plugins))  # before KWindowSystem looks for its platform plugin (on its first call)
        lib = (loader or self._load)()
        if lib is None:
            self.reason = "KDE's window system library (KWindowSystem) is not installed"
            return
        function = getattr(lib, BLUR_SYMBOL, None)
        if function is None:
            self.reason = "KWindowSystem has no blur function"
            return
        function.restype = None
        function.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p]
        self.function = function

    @staticmethod
    def _load():
        for name in BLUR_LIBRARIES + tuple(filter(None, [ctypes.util.find_library("KF6WindowSystem")])):
            try:
                return ctypes.CDLL(name)
            except OSError:
                continue
        return None

    @property
    def available(self) -> bool:
        return self.function is not None

    def set(self, window, on: bool, region=None, pointers=None) -> bool:
        """Blur behind ``window`` (a shown QWindow) inside ``region`` (a QRegion in its coordinates; None: all of it), or stop.
        ``pointers`` is (window address, region address), found with shiboken when not given. Returns whether it was asked."""
        if not self.available or window is None:
            return False
        try:
            if pointers is None:
                from PySide6.QtGui import QRegion

                region = region if region is not None else QRegion()
                pointers = (_address(window), _address(region))
            self.function(ctypes.c_void_p(pointers[0]), bool(on), ctypes.c_void_p(pointers[1]))
            return True
        except Exception as error:  # a crash-free failure: the widget is simply not blurred
            log.info("blur behind failed: %s", error)
            return False


_blur: Optional[Blur] = None


def blur() -> Blur:
    """The one Blur for this run (looked for once)."""
    global _blur
    if _blur is None:
        _blur = Blur()
        if kde() and not _blur.available:
            log.info("Glass widgets: no blur behind (%s)", _blur.reason)
    return _blur


# ----------------------------------------------------------------------------- the KWin rule fallback
RULE_GROUP = "sluice-desktop-widgets"
RULE_TITLE = "Sluice widget"  # every widget window's title starts with this


def kwin_rule_commands(writer: str) -> list:
    """The kwriteconfig commands that add a KWin rule keeping Sluice's widget windows above other windows and (0.11.7) out of the
    taskbar, the pager and Alt-Tab, in KWin's own rules file. ("2": force the setting.)"""
    base = [writer, "--file", "kwinrulesrc", "--group", RULE_GROUP, "--key"]
    entries = [
        ("Description", "Sluice desktop widgets"),
        ("title", RULE_TITLE),
        ("titlematch", "2"),
        ("above", "true"),
        ("aboverule", "2"),
        ("skiptaskbar", "true"),
        ("skiptaskbarrule", "2"),
        ("skippager", "true"),
        ("skippagerrule", "2"),
        ("skipswitcher", "true"),
        ("skipswitcherrule", "2"),
    ]
    commands = [base + [key, value] for key, value in entries]
    return commands


def kwin_rule_present(reader: Optional[str] = None) -> bool:
    reader = reader or shutil.which("kreadconfig6") or shutil.which("kreadconfig5")
    if not reader:
        return False
    try:

        def read(key):
            return subprocess.run(
                [reader, "--file", "kwinrulesrc", "--group", RULE_GROUP, "--key", key], capture_output=True, text=True, timeout=5
            ).stdout.strip()

        # a rule from before 0.11.7 only kept them above: it counts as missing, so Sluice offers it again (and writes the rest)
        return read("title") == RULE_TITLE and read("skiptaskbar") == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def add_kwin_rule(run=subprocess.run) -> str:
    """Add the rule and ask KWin to read its rules again. Returns "" when done, else what went wrong in plain words."""
    writer = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    if not writer:
        return "KDE's kwriteconfig was not found, so the rule could not be added."
    try:
        for command in kwin_rule_commands(writer):
            run(command, check=True, capture_output=True, timeout=5)
        listed = run(
            [writer.replace("kwriteconfig", "kreadconfig"), "--file", "kwinrulesrc", "--group", "General", "--key", "rules"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        names = [n for n in (getattr(listed, "stdout", "") or "").strip().split(",") if n]
        if RULE_GROUP not in names:
            names.append(RULE_GROUP)
        run(
            [writer, "--file", "kwinrulesrc", "--group", "General", "--key", "rules", ",".join(names)],
            check=True,
            capture_output=True,
            timeout=5,
        )
        run(
            [writer, "--file", "kwinrulesrc", "--group", "General", "--key", "count", str(len(names))],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"The rule could not be written: {exc}"
    for tool in ("qdbus6", "qdbus", "qdbus-qt6", "qdbus-qt5"):
        if shutil.which(tool):
            try:
                run([tool, "org.kde.KWin", "/KWin", "reconfigure"], capture_output=True, timeout=5)
                return ""
            except (OSError, subprocess.SubprocessError):
                break
    if shutil.which("dbus-send"):
        try:
            run(
                ["dbus-send", "--session", "--type=method_call", "--dest=org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure"],
                capture_output=True,
                timeout=5,
            )
            return ""
        except (OSError, subprocess.SubprocessError):
            pass
    return "The rule was added. Log out and back in (or restart KWin) for it to take effect."
