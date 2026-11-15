# SPDX-License-Identifier: GPL-3.0-or-later
"""Spotting an app that listens to the raw microphone while a Sluice channel has effects on it.

OBS, Discord or a browser that is set to the microphone itself, not to "Sluice (Mic)" or "Sluice (Broadcast)", hears the
voice without the Noise Reducer, the EQ and the rest. Nothing is wrong with Sluice then, but nobody would guess, so
Sluice says so.
"""
from __future__ import annotations

from typing import Callable, Iterable

CHECK_SECONDS = 5.0  # how often the connections are looked at (one small pw-link call)
SECONDS = 8.0  # an app must hold the raw microphone this long before it is reported (level meters flick on and off)

# Programs that only watch the level of a microphone (volume meters, session managers, audio tools): not a recording.
IGNORED = ("sluice", "pavucontrol", "pulseaudio volume control", "volume control", "plasmashell", "kmix", "peak detect",
           "wireplumber", "pipewire", "easyeffects", "kded", "gnome-shell", "gnome-control-center", "cinnamon",
           "pwvucontrol", "helvum", "qpwgraph", "carla", "catia", "patchance", "ardour-peak")


def node_of(port: str) -> str:
    return port.rsplit(":", 1)[0]


def ignorable(node: str) -> bool:
    lowered = node.lower()
    return any(word in lowered for word in IGNORED)


def processed(channel) -> bool:
    """A channel changes the sound when at least one of its effects is on."""
    return any(not effect.bypass for effect in channel.effects)


def find(links: Iterable, channels: Iterable, resolve_source: Callable) -> dict:
    """{app: [channel, ...]}: apps whose input is linked straight from a microphone that a processing channel uses."""
    mics: dict = {}  # source node -> channels with effects that use it
    for channel in channels:
        if not channel.devices or not processed(channel):
            continue
        for device in channel.devices:
            name = resolve_source(device)
            if not name or name.endswith(".monitor"):  # "what an output plays" is not a microphone
                continue
            mics.setdefault(name, []).append(channel)
    found: dict = {}
    for out_port, in_port in links:
        out_node, app = node_of(out_port), node_of(in_port)
        if out_node in mics and app != out_node and not ignorable(app):
            for channel in mics[out_node]:
                if channel not in found.setdefault(app, []):
                    found[app].append(channel)
    return found


def message(app: str, channels: list) -> str:
    labels = " and ".join(c.label for c in channels)
    separate = next((c for c in channels if getattr(c, "separate", False)), None)
    use = f"Sluice ({separate.label})" if separate is not None else "Sluice (Broadcast)"
    return (f"{app} is listening to your raw microphone, so the effects on {labels} (noise reduction, EQ and the rest) "
            f"do not reach it. In {app}, choose “{use}” as its microphone to use them.")


def short(app: str) -> str:
    return f"⚠ {app} hears your raw mic (no effects)"
