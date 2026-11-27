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


# ----------------------------------------------------------------------------- 0.12.4: recording around Sluice's faders
MONITOR = " · monitor"  # warning keys: "OBS · monitor" (the plain app name is the raw-microphone warning)
LOOP = " · loop"


def find_monitors(links: Iterable, channels: Iterable) -> dict:
    """{app: [channel, ...]}: apps recording "Monitor of Sluice (<channel>) output", the raw copy of what apps send into a
    channel, from before its effects, faders and mutes (PipeWire makes one for every output, so it is easy to pick in OBS)."""
    sinks = {channel.sink_name: channel for channel in channels}
    found: dict = {}
    for out_port, in_port in links:
        out_node, app = node_of(out_port), node_of(in_port)
        channel = sinks.get(out_node)
        if channel is None or ":monitor_" not in out_port or app.startswith("sluice") or ignorable(app):
            continue
        if channel not in found.setdefault(app, []):
            found[app].append(channel)
    return found


def monitor_message(app: str, channels: list) -> str:
    names = " and ".join(f"“Monitor of Sluice ({c.label}) output”" for c in channels)
    labels = " and ".join(c.label for c in channels)
    own = " and ".join(f"“Sluice ({c.label})”" for c in channels)
    return (f"{app} is recording {names}: a copy of the sound from before Sluice's faders and mutes, so Broadcast cannot "
            f"change or mute it. In {app}, use “Sluice (Broadcast)” instead, or turn on {labels} under the channel's menu > "
            f"Recording devices for OBS and use {own}, which follow your Broadcast faders and mutes.")


def monitor_short(app: str) -> str:
    return f"⚠ {app} records around your faders"


BROADCAST_NODES = ("sluice_stream_mic", "sluice_stream")  # what "Sluice (Broadcast)" is made of


def find_loops(links: Iterable, streams: Iterable, channel_for_stream: Callable, in_broadcast: Callable) -> dict:
    """{app: channel}: apps that record Sluice's Broadcast (or a recording device) while their own sound plays into a channel
    that goes to Broadcast: what they play comes back in what they record (OBS monitoring into an "OBS" channel, say)."""
    recorders = set()
    for out_port, in_port in links:
        out_node, app = node_of(out_port), node_of(in_port)
        if (out_node in BROADCAST_NODES or out_node.startswith("sluice_solo_")) and not app.startswith("sluice") \
                and not ignorable(app):
            recorders.add(app)
    found: dict = {}
    for app in recorders:
        lowered = app.lower()
        for stream in streams:
            if lowered not in stream.names and not any(lowered.startswith(name) for name in stream.names if len(name) > 2):
                continue
            channel = channel_for_stream(stream)
            if channel is not None and in_broadcast(channel):
                found[app] = channel
                break
    return found


def loop_message(app: str, channel) -> str:
    return (f"{app} records your Broadcast, and {app}'s own sound plays into the {channel.label} channel, which goes to "
            f"Broadcast too: what {app} plays comes back into what it records, so your stream can echo or hear things "
            f"twice. Mute {channel.label} in Broadcast, or in {app} set its audio monitoring to your headphones.")


def loop_short(app: str) -> str:
    return f"⚠ {app} can hear itself on Broadcast"


def short_for(key: str) -> str:
    """The status-bar line for a warning key."""
    if key.endswith(MONITOR):
        return monitor_short(key[:-len(MONITOR)])
    if key.endswith(LOOP):
        return loop_short(key[:-len(LOOP)])
    return short(key)
