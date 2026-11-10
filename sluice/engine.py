# SPDX-License-Identifier: GPL-3.0-or-later
"""Engine: keeps audio, links, virtual devices and the model in sync.

Signal path
-----------
  capture devices ----------------\\
                                   >--> sluice:in_<channel>  --> effects --> mixes
  apps --> sluice_ch_<channel> sink /                                          |
        (its .monitor is linked in)                                           v
                      sluice:out_monitor --> headphones      sluice:out_stream --> sluice_stream
                                                                       (apps record "Sluice (Broadcast)")

The data plane (``audio_io`` + ``dsp``) mixes; this class only decides *what is linked
to what*, creates virtual devices, moves apps onto their channel's sink, and pushes
gains and effect chains into the DSP graph.
"""
from __future__ import annotations

import re
import time
import logging
from functools import partial
from pathlib import Path
from typing import Optional

from .audio_io import AudioIO, in_port_names, out_port_names
from .apps import STEAM_PREFIX, Catalog
from .backend import AudioSystem, Stream
from .dsp import Graph
from .effects import EffectInstance, runner_for
from .linker import Linker
from . import reconnect, room
from .model import (MONITOR, PREFIX, STREAM, VOICE_CHAIN, Channel, Effect, Mix, Mixer, canonical_order, linear_to_db,
                    voice_chain_effects)

log = logging.getLogger("sluice.engine")

REFRESH_SECONDS = 2.0
GUARD_STREAK_LOST = 6  # this many failed audio-server calls in a row, with no success between, means the server is gone
RELINK_EVERY = 5  # re-check the connections every 5th device refresh (10 s) unless something changed sooner
XRUN_LOG_SECONDS = 10.0  # dropouts are summed up into one log line per this many seconds
SETTLE_SECONDS = 8.0  # dropouts while starting up or loading effects are expected and are not shown in the status bar
CHANGE_SETTLE_SECONDS = 3.0  # the same quiet time after a change such as adding an effect
RULES_SECONDS = 0.5
MOVE_RETRY_SECONDS = 5.0
FIGHT_MOVES = 3          # this many moves of one app within FIGHT_WINDOW seconds means something moves it back
FIGHT_WINDOW = 10.0
FIGHT_PAUSE = 60.0


def _connect(outs: list, ins: list) -> set:
    """Link two port lists left-to-right. A mono side feeds (or is fed by) both channels."""
    if not outs or not ins:
        return set()
    if len(outs) == 1 and len(ins) >= 2:
        outs = [outs[0], outs[0]]
    if len(ins) == 1 and len(outs) >= 2:
        ins = [ins[0], ins[0]]
    return set(zip(outs, ins))


class Engine:
    def __init__(self, mixer: Mixer, system: AudioSystem, io: AudioIO, linker: Linker, catalog: Optional[Catalog] = None) -> None:
        self.mixer = mixer
        self.catalog = catalog if catalog is not None else Catalog()
        self.system = system
        self.io = io
        self.linker = linker
        self.graph: Optional[Graph] = None

        self.sources: list = []
        self.sinks: list = []
        self.default_source: Optional[str] = None
        self.default_sink: Optional[str] = None
        self.streams: list = []
        self.errors: list = []

        self._instances: dict = {}
        self._applied_gains: dict = {}
        self._signature: Optional[tuple] = None
        self._stream_signature: Optional[tuple] = None
        self._last_refresh = 0.0
        self._refreshes_since_link = 0
        self._last_rules = 0.0
        self._link_retry = False
        self._move_backoff: dict = {}
        self._move_history: dict = {}
        self._warned_default = False
        self._loop_warned: set = set()
        self.server_lost = False  # the audio server (PipeWire) went away: the window then restarts Sluice (see reconnect.py)
        self._guard_streak = 0
        self.mic_muted = False  # not saved either: Sluice always starts with the microphone live
        self.hear_broadcast = False  # not saved: it always starts off, so nobody is surprised by the wrong mix
        self._started = False
        self._last_links: set = set()
        self._last_failed: set = set()
        self._logged_xruns = 0
        self._xrun_base = 0
        self._ours_base = 0
        self._pending_xruns = 0           # dropouts not yet written to the log (they are summed up, not logged one by one)
        self._pending_since = 0.0
        self._last_xrun_log = float("-inf")
        self._xrun_hint_given = False
        self._load = (0.0, 0.0)           # (average, worst) share of a block that Sluice's own work uses, recently
        self._known_inputs: Optional[set] = None
        self._notices: list = []
        self._quiet_until = 0.0
        self._last_io_error = ""

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.graph = Graph(self.io.sample_rate, [m.id for m in self.mixer.mixes])
        log.info("starting: channels %s, mixes %s, %d Hz, %d frames per block",
                 [c.id for c in self.mixer.channels], [m.id for m in self.mixer.mixes],
                 self.io.sample_rate, self.io.blocksize)
        self._settling(SETTLE_SECONDS)
        for mix in self.mixer.mixes:
            if mix.sink_name:
                self._guard(self.system.ensure_null_sink, mix.sink_name, mix.description, True, mix.source_description)
        for channel in self.mixer.channels:
            self._guard(self.system.ensure_null_sink, channel.sink_name, channel.description)
            if channel.separate:
                self._guard(self.system.ensure_null_sink, channel.solo_sink_name, channel.solo_sink_description, True, channel.solo_description)
            self._load_effects(channel)
        self._sync_graph()
        self._push_gains(force=True)
        self.io.start(self.graph)
        self._started = True
        self.refresh_devices()
        self.apply_links()
        self.apply_rules(time.monotonic())
        log.info("started")

    def shutdown(self, save_to: Optional[Path] = None) -> None:
        """Stop audio, optionally save the settings (plugin state is read once audio has stopped), clean up."""
        log.info("shutting down")
        if self._pending_xruns:
            self._log_dropouts(time.monotonic())
        self._started = False
        self.io.stop()
        if save_to is not None:
            try:
                self.save_config(save_to, backups=True)
            except OSError as exc:
                self._error(f"Could not save settings: {exc}")
        self._guard(self._release_apps)
        self._guard(self.linker.shutdown)
        self._guard(self.system.cleanup)
        self._instances.clear()
        log.info("shut down cleanly")

    def _release_apps(self) -> None:
        """Before our devices vanish, put every app that is on one back on the normal output."""
        default = self.default_sink
        if not default or default.startswith(PREFIX):
            return
        for stream in self.system.list_streams():
            if stream.sink.startswith(f"{PREFIX}ch_"):
                try:
                    self.system.move_stream(stream.index, default)
                    log.info("released %s back to %s", stream.name, default)
                except Exception as exc:
                    log.warning("could not release %s: %s", stream.name, exc)

    def save_config(self, path: Optional[Path] = None, backups: bool = False) -> None:
        for instance in self._instances.values():
            instance.capture_state()
        self.mixer.save(path, backups=backups)

    def take_errors(self) -> list:
        errors, self.errors = self.errors, []
        if self.graph is not None:
            for message in self.graph.take_errors():
                log.warning("%s", message)
                errors.append(message)
        if self.io.error:
            message, self.io.error = self.io.error, ""
            if reconnect.is_lost_message(message):
                self.server_lost = True
            if message != self._last_io_error:  # a failing callback repeats every block: log it once
                log.error("audio: %s", message)
            self._last_io_error = message
            errors.append(message)
        return errors

    def _error(self, message: str) -> None:
        shape = re.sub(r"\d+", "#", message)  # ids inside messages change every time: compare the shape
        if not self.errors or re.sub(r"\d+", "#", self.errors[-1]) != shape:
            log.warning("%s", message)
            self.errors.append(message)

    def _guard(self, fn, *args):
        try:
            result = fn(*args)
            self._guard_streak = 0
            return result
        except Exception as exc:  # an audio-server hiccup must never kill the UI
            self._guard_streak += 1
            if self._guard_streak >= GUARD_STREAK_LOST and hasattr(self.io, "client"):
                self.server_lost = True  # the same call failing again and again: the server is gone
            self._error(f"{type(exc).__name__}: {exc}")
            return None

    def take_notices(self) -> list:
        """Short messages worth showing once (a new microphone appeared)."""
        notices, self._notices = self._notices, []
        return notices

    def dropout_counts(self) -> tuple:
        """(dropouts shown in the status bar, how many of them came while Sluice itself was running late)."""
        total = max(0, self.io.xruns - self._xrun_base)
        return total, min(total, max(0, self.io.xruns_ours - self._ours_base))

    def status_text(self) -> str:
        io = self.io
        total, ours = self.dropout_counts()
        text = f"{io.sample_rate} Hz · {io.blocksize} frames · {total} {'dropout' if total == 1 else 'dropouts'}"
        if total >= 3:  # one or two say nothing about who is to blame
            if ours * 2 >= total:
                text += " · mostly Sluice"
            elif ours * 4 <= total:
                text += " · mostly elsewhere"
        return text

    def dropout_tooltip(self) -> str:
        total, ours = self.dropout_counts()
        text = ("A dropout is a moment the audio could not keep up: you may hear a click or a gap. It can come from Sluice or "
                "from any other program or device in the audio system. Dropouts while starting or changing effects are not "
                "counted.")
        average, worst = self._load
        if average > 0:
            text += f"\n\nSluice's own audio work is using about {average * 100:.0f}% of each block (worst recently: {worst * 100:.0f}%)."
        if total:
            text += (f"\n\nOf the {total}, {ours} came while Sluice was running late and {total - ours} while it was keeping up, "
                     "which points at something else: another program, a busy USB device, or the system itself.")
            text += ("\n\nTo find the cause, run  pw-top  in a terminal and watch the ERR column. To give everything more room, "
                     "choose a larger size in Settings > Audio buffer, or remove heavy effects.")
        return text

    # ----------------------------------------------------------------- devices
    def refresh_devices(self) -> bool:
        """Re-read devices and defaults. Returns True if anything changed."""
        # if the audio server hiccups, keep what we knew instead of treating every device as unplugged
        sources = self._guard(self.system.list_sources)
        sinks = self._guard(self.system.list_sinks)
        if sources is not None and sinks is not None:
            self.sources, self.sinks = sources, sinks
            self.default_source = self._guard(self.system.default_source)
            self.default_sink = self._guard(self.system.default_sink)
        if self.default_sink and self.default_sink.startswith(PREFIX) and not self._warned_default:
            self._warned_default = True
            log.warning("the default output is a Sluice device (%s); the Listen mix cannot use 'Default'. "
                        "Pick your headphones in the Listen device list.", self.default_sink)
            self._error("The system default output is a Sluice device: pick your headphones in the Listen list.")
        signature = (
            tuple(d.name for d in self.sources),
            tuple(d.name for d in self.sinks),
            self.default_source,
            self.default_sink,
        )
        changed = signature != self._signature
        self._signature = signature
        inputs = {d.name: d.description for d in self.sources if not d.monitor}
        if self._known_inputs is not None:  # not the first look: anything new was plugged in (or switched on) just now
            for name in inputs.keys() - self._known_inputs:
                self._notices.append(f"New microphone found: {inputs[name]}. Choose it in a channel's input list to use it.")
        self._known_inputs = set(inputs)
        self._last_refresh = time.monotonic()
        if changed:
            log.info("devices: %d inputs, %d outputs, default output %s, default input %s",
                     sum(not d.monitor for d in self.sources), len(self.sinks), self.default_sink, self.default_source)
            log.debug("inputs: %s", [d.name for d in self.sources if not d.monitor])
            log.debug("outputs: %s", [d.name for d in self.sinks])
        return changed

    @staticmethod
    def _resolve(device: Optional[str], available: list, default: Optional[str]) -> Optional[str]:
        if device is None:
            return None
        name = default if device == "" else device
        if not name or name.startswith(PREFIX):  # never feed sluice back into itself
            return None
        return name if any(d.name == name for d in available) else None

    def resolve_source(self, device: str) -> Optional[str]:
        return self._resolve(device, self.sources, self.default_source)

    def resolve_mix_sink(self, mix: Mix) -> Optional[str]:
        if mix.sink_name:
            return mix.sink_name
        found = self._resolve(mix.device, self.sinks, self.default_sink)
        if found is None and mix.device and self.default_sink and not self.default_sink.startswith(PREFIX):
            # The chosen output is not here (unplugged, or settings copied from another computer): play on the system
            # default instead of going silent. It is not saved, so the choice returns when the device does.
            if mix.id not in self._loop_warned:
                self._loop_warned.add(mix.id)
                log.warning("output %s for mix '%s' is not available; using the system default %s", mix.device, mix.id, self.default_sink)
            return self._resolve("", self.sinks, self.default_sink)
        return found

    # ------------------------------------------------------------------- links
    def desired_links(self) -> tuple:
        """(links that should exist, True if some port was not found yet)."""
        snap = self.linker.snapshot()
        links: set = set()
        missing = False

        output_nodes = {self.resolve_mix_sink(m) for m in self.mixer.mixes} - {None}
        output_nodes |= {c.solo_sink_name for c in self.mixer.channels if c.separate}
        for channel in self.mixer.channels:
            in_ports = list(in_port_names(channel.id))
            sources = [channel.sink_name]  # apps assigned to the channel play into this sink
            for device in channel.devices:
                name = self.resolve_source(device)
                if not name:
                    continue
                if name.endswith(".monitor"):  # "what this output is playing": the sink node's own output ports
                    name = name[: -len(".monitor")]
                    if name in output_nodes:
                        if name not in self._loop_warned:
                            self._loop_warned.add(name)
                            log.warning("not using the monitor of %s on channel '%s': a mix plays into it, which would loop", name, channel.id)
                            self._error("A channel cannot take what your own output is playing: that would be a feedback loop.")
                        continue
                sources.append(name)
            for node in sources:
                outs = snap.outputs(node)
                if outs:
                    links |= _connect(outs, in_ports)
                elif node == channel.sink_name:
                    missing = True

        for mix in self.mixer.mixes:
            node = self.resolve_mix_sink(mix)
            if node is None:
                continue
            ins = snap.inputs(node)
            if ins:
                # while "hear broadcast" is on, the Listen output plays the Broadcast mix instead of the Listen mix
                source_mix = STREAM if (mix.kind == MONITOR and self.hear_broadcast) else mix.id
                links |= _connect(list(out_port_names(source_mix)), ins)
            else:
                missing = True

        for channel in self.mixer.channels:  # a channel's own recording device carries just that channel
            if channel.separate:
                ins = snap.inputs(channel.solo_sink_name)
                if ins:
                    links |= _connect(list(out_port_names(f"solo_{channel.id}")), ins)
                else:
                    missing = True
        return links, missing

    def apply_links(self) -> None:
        self._refreshes_since_link = 0
        desired, missing = self.desired_links()
        failed = self._guard(self.linker.sync, desired)
        self._link_retry = missing or bool(failed)
        added, removed = desired - self._last_links, self._last_links - desired
        if added or removed:
            log.info("links: %d wanted (+%d, -%d)", len(desired), len(added), len(removed))
            for out_port, in_port in sorted(added):
                log.debug("link + %s -> %s", out_port, in_port)
            for out_port, in_port in sorted(removed):
                log.debug("link - %s -> %s", out_port, in_port)
        self._last_links = set(desired)
        failed = set(failed or ())
        if failed and failed != self._last_failed:
            log.warning("could not create %d link(s), will retry: %s", len(failed), sorted(failed)[:6])
        elif self._last_failed and not failed:
            log.info("all links are in place now")
        self._last_failed = failed
        if missing:
            log.debug("some ports do not exist yet; will retry")

    # ------------------------------------------------------------------- apps
    def apply_rules(self, now: float) -> bool:
        """Move apps onto their channel's sink. True if the list of playing apps changed."""
        self._last_rules = now
        streams = self._guard(self.system.list_streams) or []
        signature = tuple((s.index, s.key, s.sink) for s in streams)
        changed = signature != self._stream_signature
        self._stream_signature = signature
        self.streams = streams

        live = {(s.index, s.sink) for s in streams}
        for key in [k for k in self._move_backoff if (k[0], k[2]) not in live and self._move_backoff[k] < now]:
            del self._move_backoff[key]

        for stream in streams:
            target = self._target_sink(stream)
            if target is None or stream.sink == target:
                continue
            key = (stream.index, stream.sink, target)
            if self._move_backoff.get(key, 0.0) > now:
                continue
            history = [t for t in self._move_history.get(stream.index, []) if now - t < FIGHT_WINDOW]
            if len(history) >= FIGHT_MOVES:
                self._move_backoff[key] = now + FIGHT_PAUSE
                self._move_history[stream.index] = []
                self._error(f"{stream.name} keeps being moved back by something else; Sluice will leave it alone for a minute.")
                continue
            try:
                self.system.move_stream(stream.index, target)
                history.append(now)
                self._move_history[stream.index] = history
                log.info("moved %s (stream %d) from %s to %s", stream.name, stream.index, stream.sink, target)
            except Exception as exc:
                self._move_backoff[key] = now + MOVE_RETRY_SECONDS
                self._error(f"Could not move {stream.name}: {exc}")
        return changed

    def channel_for_stream(self, stream: Stream) -> Optional[Channel]:
        return self.mixer.channel_for_stream(stream, self.catalog.expand)

    def app_label(self, key: str) -> str:
        """A readable name for something a channel remembers (a binary, a Steam game id...)."""
        label = self.catalog.label(key)
        if label:
            return label
        wanted = self.catalog.expand(key)
        for stream in self.streams:
            if key in stream.names or not stream.names.isdisjoint(wanted):
                return stream.name
        if key.startswith(STEAM_PREFIX):
            return f"Steam game {key[len(STEAM_PREFIX):]}"
        return key

    def _target_sink(self, stream: Stream) -> Optional[str]:
        channel = self.channel_for_stream(stream)
        if channel is not None:
            return channel.sink_name
        if stream.sink.startswith(f"{PREFIX}ch_"):  # was on a channel it no longer belongs to
            default = self.default_sink
            if default and not default.startswith(PREFIX):
                return default
        return None

    def tick(self, now: Optional[float] = None) -> set:
        """Call a few times a second. Returns what changed: {'devices', 'streams'}."""
        now = time.monotonic() if now is None else now
        changed: set = set()
        relink = False
        if now - self._last_refresh >= REFRESH_SECONDS:
            if self.refresh_devices():
                changed.add("devices")
                relink = True
            self._refreshes_since_link += 1
            if self._refreshes_since_link >= RELINK_EVERY:
                relink = True  # ports can also appear or vanish without the device list changing; checking costs a few
                #                small processes (pw-link), so it is done every few seconds, not every tick
        if now - self._last_rules >= RULES_SECONDS:
            if self.apply_rules(now):
                changed.add("streams")
        if relink or self._link_retry:
            self.apply_links()
        xruns = self.io.xruns
        average, worst = self.io.take_load()
        if average or worst:
            self._load = (0.7 * self._load[0] + 0.3 * average if self._load[0] else average, max(worst, self._load[1] * 0.9))
        if now < self._quiet_until:
            self._xrun_base = xruns
            self._ours_base = self.io.xruns_ours
        if xruns > self._logged_xruns:
            if not self._pending_xruns:
                self._pending_since = now
            self._pending_xruns += xruns - self._logged_xruns
            self._logged_xruns = xruns
        if self._pending_xruns and now - self._last_xrun_log >= XRUN_LOG_SECONDS:
            self._log_dropouts(now)
        return changed

    def _log_dropouts(self, now: float) -> None:
        """One line for every stretch of dropouts, not one per half second: a long burst used to fill the whole log."""
        total, ours = self.io.xruns, self.io.xruns_ours
        average, worst = self._load
        log.warning("audio dropouts: %d in the last %.0f s (%d since Sluice started; %d of those while Sluice itself was running "
                    "late). Sluice's own work uses about %.0f%% of a block, worst %.0f%%.",
                    self._pending_xruns, max(1.0, now - self._pending_since), total, ours, average * 100, worst * 100)
        if not self._xrun_hint_given:
            self._xrun_hint_given = True
            log.warning("if dropouts keep coming: run pw-top and look at the ERR column to see which program is behind them, or "
                        "use Settings > Audio buffer > Large")
        self._pending_xruns = 0
        self._last_xrun_log = now

    # ------------------------------------------------------------- graph sync
    def _settling(self, seconds: float) -> None:
        self._quiet_until = max(self._quiet_until, time.monotonic() + seconds)

    def _sync_graph(self) -> None:
        self._settling(CHANGE_SETTLE_SECONDS)
        channel_ids = [c.id for c in self.mixer.channels]
        self.io.sync_ports(channel_ids, self._output_ids())
        self.graph.set_channels(channel_ids)
        for channel in self.mixer.channels:
            self._rebuild_chain(channel.id)

    def _output_ids(self) -> list:
        """Every stereo output the audio client has: one per mix, plus one per channel with its own output."""
        return [m.id for m in self.mixer.mixes] + [f"solo_{c.id}" for c in self.mixer.channels if c.separate]

    def _push_gains(self, force: bool = False) -> None:
        if force:
            self._applied_gains.clear()
        for channel in self.mixer.channels:
            muted = self.mic_muted and bool(channel.devices)  # "Mute my microphone" silences every microphone channel, own outputs too
            solo = (0.0 if muted else 1.0) if channel.separate else None  # otherwise own outputs ignore faders and mutes
            if self._applied_gains.get((channel.id, "solo"), "unset") != solo:
                self._applied_gains[(channel.id, "solo")] = solo
                self.graph.set_solo(channel.id, solo)
        for channel in self.mixer.channels:
            for mix in self.mixer.mixes:
                gain = 0.0 if (self.mic_muted and channel.devices) else self.mixer.route_gain(channel, mix)
                if self._applied_gains.get((channel.id, mix.id)) != gain:
                    self._applied_gains[(channel.id, mix.id)] = gain
                    self.graph.set_gain(channel.id, mix.id, gain)
        for mix in self.mixer.mixes:
            value = (self.mixer.master_gain(mix), mix.limiter)
            if self._applied_gains.get(("mix", mix.id)) != value:
                self._applied_gains[("mix", mix.id)] = value
                self.graph.set_mix(mix.id, *value)

    # --------------------------------------------------------------- effects
    def _load_effects(self, channel: Channel) -> None:
        self._settling(CHANGE_SETTLE_SECONDS)
        for effect in channel.effects:
            instance = EffectInstance(effect)
            self._instances[effect.id] = instance
            if instance.error:
                log.warning("effect '%s' on channel '%s' is not active: %s", effect.name, channel.id, instance.error)

    def effect_instance(self, effect_id: str) -> Optional[EffectInstance]:
        return self._instances.get(effect_id)

    def _rebuild_chain(self, channel_id: str) -> None:
        channel = self.mixer.channel(channel_id)
        live = []
        for effect in channel.effects:
            instance = self._instances.get(effect.id)
            if instance is not None and instance.usable and not effect.bypass:
                live.append(instance)
        self.graph.set_chain(channel_id, live)

    def add_effect(self, channel_id: str, effect: Effect) -> EffectInstance:
        channel = self.mixer.channel(channel_id)
        channel.effects.append(effect)
        channel.effects = canonical_order(channel.effects)  # built-in effects always run in the best order
        instance = EffectInstance(effect)
        self._instances[effect.id] = instance
        self._rebuild_chain(channel_id)
        if instance.error:
            log.warning("effect '%s' added to '%s' but could not load: %s", effect.name, channel_id, instance.error)
        else:
            log.info("effect '%s' (%s) added to '%s'", effect.name, effect.kind, channel_id)
        return instance

    def remove_effect(self, channel_id: str, effect_id: str) -> None:
        channel = self.mixer.channel(channel_id)
        channel.effects = [e for e in channel.effects if e.id != effect_id]
        self._instances.pop(effect_id, None)
        log.info("effect %s removed from '%s'", effect_id, channel_id)
        self._rebuild_chain(channel_id)

    def move_effect(self, channel_id: str, effect_id: str, delta: int) -> None:
        """Move a VST3 plugin in the chain. Built-in effects cannot be moved: they keep the best order themselves."""
        channel = self.mixer.channel(channel_id)
        effects = channel.effects
        for i, effect in enumerate(effects):
            if effect.id == effect_id:
                if effect.kind == "builtin":
                    self._error("Built-in effects are kept in the best order automatically; only VST3 plugins can be moved.")
                    return
                j = max(0, min(len(effects) - 1, i + delta))
                effects.insert(j, effects.pop(i))
                break
        channel.effects = canonical_order(effects)
        self._rebuild_chain(channel_id)

    def apply_voice_chain(self, channel_id: str) -> None:
        """Replace the channel's built-in voice effects with the recommended chain. VST3 plugins and Gain stay."""
        channel = self.mixer.channel(channel_id)
        for effect in [e for e in channel.effects if e.kind == "builtin" and e.type in VOICE_CHAIN]:
            self._instances.pop(effect.id, None)
            channel.effects.remove(effect)
        for effect in voice_chain_effects():
            channel.effects.append(effect)
            self._instances[effect.id] = EffectInstance(effect)
        channel.effects = canonical_order(channel.effects)
        log.info("recommended voice chain applied to '%s'", channel_id)
        self._rebuild_chain(channel_id)

    def set_effect_bypass(self, channel_id: str, effect_id: str, bypass: bool) -> None:
        for effect in self.mixer.channel(channel_id).effects:
            if effect.id == effect_id:
                effect.bypass = bypass
        self._rebuild_chain(channel_id)

    def set_effect_param(self, effect_id: str, key: str, value: float) -> None:
        instance = self._instances.get(effect_id)
        if instance is not None:
            instance.record_param(key, value)  # saved settings update at once
            self.graph.submit(partial(instance.apply_param, key, value))  # the live plugin on the audio thread

    # ------------------------------------------------------------ measure my room
    def measure_room_start(self, channel_id: str, seconds: float = room.LISTEN_SECONDS) -> None:
        """Start listening to a channel's input (before its effects) for ``measure_room_finish``."""
        self.mixer.channel(channel_id)  # raises for an unknown channel
        if self.graph is None:
            raise RuntimeError("audio is not running")
        self.graph.start_capture(channel_id, seconds)

    def measure_room_progress(self, channel_id: str) -> float:
        return self.graph.capture_progress(channel_id) if self.graph is not None else 0.0

    def measure_room_cancel(self, channel_id: str) -> None:
        if self.graph is not None:
            self.graph.cancel_capture(channel_id)

    def measure_room_finish(self, channel_id: str, gate_effect_id: str) -> Optional[room.RoomResult]:
        """None while still listening; then what the room sounded like and the gate threshold that suits it."""
        if self.graph is None:
            return None
        audio = self.graph.take_capture(channel_id)
        if audio is None:
            return None
        channel = self.mixer.channel(channel_id)
        ahead = []
        for effect in channel.effects:
            if effect.id == gate_effect_id:
                break
            if effect.type not in ("echo_reducer", "noise_reducer"):  # they adapt over the first seconds, which would
                ahead.append(effect)                                  # look like a disturbance; the gate is set above the raw noise
        return room.analyse(audio, self.io.sample_rate, runner_for(ahead, self.io.sample_rate))

    def measure_echo_finish(self, channel_id: str) -> Optional[room.EchoResult]:
        """None while still listening; then how long the room's echo lasts (from a clap)."""
        if self.graph is None:
            return None
        audio = self.graph.take_capture(channel_id)
        if audio is None:
            return None
        return room.analyse_echo(audio, self.io.sample_rate)

    def measure_voice_finish(self, channel_id: str) -> Optional[room.VoiceResult]:
        """None while still listening; then how loud the person's talking was and how far to move the microphone's level."""
        if self.graph is None:
            return None
        audio = self.graph.take_capture(channel_id)
        if audio is None:
            return None
        return room.analyse_voice(audio, self.io.sample_rate)

    def channel_recent_peak_db(self, channel_id: str) -> Optional[float]:
        """The channel's peak after its effects over the last couple of seconds, in dB (None when it is not running)."""
        channel = self.graph.channels.get(channel_id) if self.graph is not None else None
        return None if channel is None else linear_to_db(channel.recent)

    def apply_noise_profile(self, channel_id: str, profile) -> None:
        """Start this channel's Noise Reducers from the noise spectrum that Measure my room heard."""
        if self.graph is None or profile is None:
            return
        for effect in self.mixer.channel(channel_id).effects:
            instance = self._instances.get(effect.id)
            if effect.type == "noise_reducer" and instance is not None and instance.stage is not None:
                self.graph.submit(partial(instance.stage.set_profile, profile))

    # -------------------------------------------------------------- UI setters
    def set_level(self, channel_id: str, mix_id: str, db: float) -> None:
        self.mixer.set_level(channel_id, mix_id, db)
        self._push_gains()

    def set_mute(self, channel_id: str, mix_id: str, mute: bool) -> None:
        self.mixer.channel(channel_id).mutes[mix_id] = mute
        self._push_gains()

    def set_mic_muted(self, muted: bool) -> None:
        """Silence (or restore) every channel that has a microphone: in all mixes and in its own "Sluice (Mic)" output."""
        self.mic_muted = bool(muted)
        self._push_gains()

    def set_linked(self, channel_id: str, linked: bool) -> None:
        channel = self.mixer.channel(channel_id)
        channel.linked = linked
        if linked:  # snap the other fader to the monitor level
            self.mixer.set_level(channel_id, MONITOR, channel.levels.get(MONITOR, 0.0))
            self._push_gains()

    def set_master(self, mix_id: str, db: float) -> None:
        from .model import clamp_db

        self.mixer.mix(mix_id).gain_db = clamp_db(db)
        self._push_gains()

    def set_master_mute(self, mix_id: str, mute: bool) -> None:
        self.mixer.mix(mix_id).mute = mute
        self._push_gains()

    def set_limiter(self, mix_id: str, on: bool) -> None:
        self.mixer.mix(mix_id).limiter = on
        self._push_gains()

    def set_mix_device(self, mix_id: str, device: Optional[str]) -> None:
        mix = self.mixer.mix(mix_id)
        mix.device = device
        shown = "nothing" if device is None else ("the system default" if device == "" else device)
        log.info("%s output set to %s (plays into %s)", mix.label, shown, self.resolve_mix_sink(mix) or "no device")
        picked = next((d for d in self.sinks if d.name == device), None)
        if picked is not None and picked.channels > 2:
            log.warning("%s has %d channels: Sluice plays into the first two, which may not be your headphones. "
                        "A stereo entry for the same hardware is usually the right choice.", picked.name, picked.channels)
        self.apply_links()

    def set_hear_broadcast(self, on: bool) -> None:
        """Play the Broadcast mix in your own output, to check what the audience hears."""
        self.hear_broadcast = bool(on)
        log.info("hear broadcast: %s", "on (the Listen output plays the Broadcast mix)" if on else "off")
        self.apply_links()

    def add_device(self, channel_id: str, device: str) -> None:
        channel = self.mixer.channel(channel_id)
        if device not in channel.devices:
            channel.devices.append(device)
        self.apply_links()

    def remove_device(self, channel_id: str, device: str) -> None:
        channel = self.mixer.channel(channel_id)
        if device in channel.devices:
            channel.devices.remove(device)
        self.apply_links()

    def assign_app(self, app_key: str, channel_id: Optional[str]) -> None:
        self.mixer.assign_app(app_key, channel_id)
        log.info("app '%s' assigned to %s", app_key, f"channel '{channel_id}'" if channel_id else "no channel (plays directly)")
        self.apply_rules(time.monotonic())

    def add_channel(self, label: str) -> Channel:
        channel = self.mixer.add_channel(label)
        log.info("channel '%s' added", channel.id)
        self._guard(self.system.ensure_null_sink, channel.sink_name, channel.description)
        self._sync_graph()
        self._push_gains()
        self.apply_links()
        return channel

    def remove_channel(self, channel_id: str) -> None:
        channel = self.mixer.channel(channel_id)
        for effect in channel.effects:
            self._instances.pop(effect.id, None)
        sink_name = channel.sink_name
        solo_sink = channel.solo_sink_name if channel.separate else None
        log.info("channel '%s' removed", channel_id)
        self.mixer.remove_channel(channel_id)
        self.apply_rules(time.monotonic())  # apps on the channel's sink go back to the default device first
        self._guard(self.system.remove_null_sink, sink_name)
        if solo_sink:
            self._guard(self.system.remove_null_sink, solo_sink)
        self._sync_graph()
        for key in [k for k in self._applied_gains if k[0] == channel_id]:
            del self._applied_gains[key]
        self.apply_links()

    def rename_channel(self, channel_id: str, label: str) -> None:
        label = label.strip()[:24]
        if not label:
            return
        channel = self.mixer.channel(channel_id)
        log.info("channel '%s' renamed to '%s'", channel_id, label)
        channel.label = label
        # The device name apps see comes from the virtual sink, so re-create it with the new name.
        self.apply_rules(time.monotonic())
        self._guard(self.system.remove_null_sink, channel.sink_name)
        self._guard(self.system.ensure_null_sink, channel.sink_name, channel.description)
        if channel.separate:  # its recording device carries the name too
            self._guard(self.system.remove_null_sink, channel.solo_sink_name)
            self._guard(self.system.ensure_null_sink, channel.solo_sink_name, channel.solo_sink_description, True, channel.solo_description)
        self.apply_links()

    def set_separate(self, channel_id: str, on: bool) -> None:
        """Offer (or stop offering) the channel as its own recording device, for example "Sluice (Mic)"."""
        channel = self.mixer.channel(channel_id)
        if channel.separate == on:
            return
        channel.separate = on
        if on:
            self._guard(self.system.ensure_null_sink, channel.solo_sink_name, channel.solo_sink_description, True, channel.solo_description)
            log.info("channel '%s' now has its own recording device: %s", channel_id, channel.solo_description)
        else:
            self._guard(self.system.remove_null_sink, channel.solo_sink_name)
            log.info("channel '%s' no longer has its own recording device", channel_id)
        self._sync_graph()
        self._push_gains()
        self.apply_links()

    # ------------------------------------------------------------------ meters
    def levels(self) -> dict:
        """Peak levels since the last call. 'ch:<id>:<mix>' is after effects and fader; 'mix:<id>' is the output."""
        peaks = self.graph.take_peaks() if self.graph else {}
        result: dict = {}
        for channel in self.mixer.channels:
            raw = peaks.get(f"ch:{channel.id}", 0.0)
            for mix in self.mixer.mixes:
                result[f"ch:{channel.id}:{mix.id}"] = min(1.0, raw * self.mixer.route_gain(channel, mix))
        for mix in self.mixer.mixes:
            result[f"mix:{mix.id}"] = min(1.0, peaks.get(f"mix:{mix.id}", 0.0))
        return result
