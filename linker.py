# SPDX-License-Identifier: GPL-3.0-or-later
"""Connects ports in the PipeWire graph using the ``pw-link`` command line tool.

sluice decides *which* ports should be linked; this module makes it so, and only ever
removes links that sluice itself created.
"""
from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from typing import Callable, Iterable, Optional


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

    def snapshot(self) -> PortSnapshot:
        return PortSnapshot(fabricate=True)

    def sync(self, desired: set) -> set:
        self.links = set(desired)
        return set()

    def shutdown(self) -> None:
        self.links = set()


class PwLinker(Linker):
    def __init__(self, run: Optional[Callable] = None, binary: str = "pw-link") -> None:
        self._binary = binary
        self._run = run or self._subprocess_run
        self._owned: set = set()

    def _subprocess_run(self, args: list) -> tuple:
        try:
            done = subprocess.run([self._binary, *args], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("%s %s could not run: %s", self._binary, args, exc)
            return 127, ""
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
        existing = self.current_links()
        for pair in sorted(self._owned):
            if pair in existing:
                self._run(["-d", pair[0], pair[1]])
        self._owned.clear()
