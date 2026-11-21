# SPDX-License-Identifier: GPL-3.0-or-later
"""Connects ports in the PipeWire graph using the ``pw-link`` command line tool.

sluice decides *which* ports should be linked; this module makes it so, and only ever
removes links that sluice itself created.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Iterable, Optional

from . import efficiency

log = logging.getLogger("sluice.linker")


def _rank(port: str) -> int:
    name = port.rsplit(":", 1)[-1].lower()
    if name.endswith(("_fl", "_l", "_1")):
        return 0
    if name.endswith(("_fr", "_r", "_2")):
        return 1
    return 2


def stereo_pair(ports: Iterable) -> list:
    """Up to two ports ordered left, right."""
    return sorted(ports, key=_rank)[:2]


class PortSnapshot:
    """What ports exist right now. ``fabricate=True`` invents stereo ports for any node (demo/tests)."""

    def __init__(self, outputs: Iterable = (), inputs: Iterable = (), fabricate: bool = False) -> None:
        self._outputs = list(outputs)
        self._inputs = list(inputs)
        self._fabricate = fabricate

    @staticmethod
    def _of_node(ports: list, node: str) -> list:
        return stereo_pair(p for p in ports if p.rsplit(":", 1)[0] == node)

    def outputs(self, node: str) -> list:
        if self._fabricate:
            return [f"{node}:out_L", f"{node}:out_R"]
        return self._of_node(self._outputs, node)

    def inputs(self, node: str) -> list:
        if self._fabricate:
            return [f"{node}:in_L", f"{node}:in_R"]
        return self._of_node(self._inputs, node)


def parse_ports(text: str) -> list:
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_links(text: str) -> set:
    """Parse ``pw-link -l`` into {(output port, input port)}."""
    links = set()
    current: Optional[str] = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw[0] in " \t":
            line = raw.strip()
            if current is None:
                continue
            if line.startswith("|->"):
                links.add((current, line[3:].strip()))
            elif line.startswith("|<-"):
                links.add((line[3:].strip(), current))
        else:
            current = raw.strip()
    return links


class Linker(ABC):
    @abstractmethod
    def snapshot(self) -> PortSnapshot: ...

    @abstractmethod
    def sync(self, desired: set) -> set:
        """Make the graph contain ``desired`` links. Returns the ones that could not be made yet."""

    @abstractmethod
    def shutdown(self) -> None: ...


class NullLinker(Linker):
    """Records what would be linked. Used by demo mode and tests."""

    def __init__(self) -> None:
        self.links: set = set()
        self.others: set = set()  # tests: links made by other programs

    def snapshot(self) -> PortSnapshot:
        return PortSnapshot(fabricate=True)

    def current_links(self) -> set:
        return self.links | self.others

    def sync(self, desired: set) -> set:
        self.links = set(desired)
        return set()

    def shutdown(self) -> None:
        self.links = set()


class GraphWatcher:
    """Tells Sluice when the PipeWire graph changed (0.11.5), so the connections are checked then instead of on a clock.

    One long-running ``pw-link --monitor`` prints every port and link that comes or goes; a thread reads it and raises a flag. Before,
    Sluice ran three short ``pw-link`` processes about every six seconds just to look (some 28 a minute) whether anything had changed.
    If the monitor cannot start, or stops, ``running()`` says so and the engine goes back to looking on a clock."""

    COMMANDS = (["--monitor", "--links"], ["--monitor", "--output", "--input"])

    def __init__(self, binary: str = "pw-link", popen: Optional[Callable] = None) -> None:
        self._binary = binary
        self._popen = popen or subprocess.Popen
        self._processes: list = []
        self._changed = threading.Event()
        self._changed.set()  # the first look is always done
        self._stop = False

    def start(self) -> bool:
        for args in self.COMMANDS:
            try:
                process = self._popen([self._binary, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            except (OSError, ValueError) as exc:
                log.info("cannot watch the PipeWire graph (%s); connections are checked every few seconds instead", exc)
                self.stop()
                return False
            self._processes.append(process)
            threading.Thread(target=self._read, args=(process,), name="sluice-graph-watch", daemon=True).start()
        efficiency.helper_launched(0.0)
        return True

    def _read(self, process) -> None:
        try:
            for _line in process.stdout:
                if self._stop:
                    break
                self._changed.set()
        except (OSError, ValueError):
            pass

    def running(self) -> bool:
        return bool(self._processes) and all(process.poll() is None for process in self._processes)

    def take_changed(self) -> bool:
        """True (once) if the graph changed since the last call."""
        if self._changed.is_set():
            self._changed.clear()
            return True
        return False

    def stop(self) -> None:
        self._stop = True
        for process in self._processes:
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except OSError:
                    pass
        self._processes = []


class PwLinker(Linker):
    def __init__(self, run: Optional[Callable] = None, binary: str = "pw-link", watch: bool = False) -> None:
        self._binary = binary
        self._run = run or self._subprocess_run
        self._owned: set = set()
        self.watcher: Optional[GraphWatcher] = None
        if watch:  # the running app watches the graph; the tests and the bug report's checks do not
            watcher = GraphWatcher(binary)
            if watcher.start():
                self.watcher = watcher

    def _subprocess_run(self, args: list) -> tuple:
        started = time.perf_counter()
        try:
            done = subprocess.run([self._binary, *args], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("%s %s could not run: %s", self._binary, args, exc)
            efficiency.helper_launched(time.perf_counter() - started)
            return 127, ""
        efficiency.helper_launched(time.perf_counter() - started)  # for the bug report: how often, and how long
        if done.returncode != 0:
            log.debug("%s %s exited with %d: %s", self._binary, args, done.returncode, done.stderr.strip()[:200])
        return done.returncode, done.stdout

    def available(self) -> bool:
        return self._run(["-o"])[0] == 0

    def snapshot(self) -> PortSnapshot:
        _, outputs = self._run(["-o"])
        _, inputs = self._run(["-i"])
        return PortSnapshot(parse_ports(outputs), parse_ports(inputs))

    def current_links(self) -> set:
        return parse_links(self._run(["-l"])[1])

    def sync(self, desired: set) -> set:
        existing = self.current_links()
        failed = set()
        for out_port, in_port in sorted(desired - existing):
            if self._run([out_port, in_port])[0] == 0:
                self._owned.add((out_port, in_port))
            else:
                failed.add((out_port, in_port))
        self._owned |= desired & existing
        for pair in sorted(self._owned - desired):
            if pair in existing:
                self._run(["-d", pair[0], pair[1]])
        self._owned &= desired
        return failed

    def shutdown(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None
        existing = self.current_links()
        for pair in sorted(self._owned):
            if pair in existing:
                self._run(["-d", pair[0], pair[1]])
        self._owned.clear()
