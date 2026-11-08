# SPDX-License-Identifier: GPL-3.0-or-later
"""How the default voice chain was chosen: a simulated noisy, echoing room (developer tool, not part of the app).

    python tools/tune_room.py      (needs scipy: pip install scipy)

It builds a voice-like signal (words with soft and loud ones), runs it through a reverb, and adds air-conditioner
rumble, fan hiss and TV noise at several microphone levels. Then it compares the old defaults with the current ones:
how much the noise between words drops, and how much of the quietest words the gate takes away.
It then runs *Measure my room* (sluice/room.py) on the same rooms and reports what its threshold does, and compares
a few compressor settings (how far the voice sits above the noise).
It is a guide, not proof: real voices and rooms differ, and the gate threshold depends on your microphone level.
"""
import sys
from pathlib import Path

import numpy as np
import pedalboard as pb
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sluice import room as measure_room  # noqa: E402

SR = 48000
rng = np.random.default_rng(7)


def db(x):
    return 20 * np.log10(max(float(x), 1e-9))


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def band(noise, lo, hi, order=4):
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos") if lo else signal.butter(order, hi, btype="low", fs=SR, output="sos")
    return signal.sosfilt(sos, noise)


def word(duration, f0, level_db):
    t = np.arange(int(SR * duration)) / SR
    wave = np.zeros_like(t)
    for k in range(1, 40):
        f = f0 * k * (1 + 0.01 * np.sin(2 * np.pi * 5 * t))
        if f.max() > 5000:
            break
        formant = 1.0 + 2.0 * np.exp(-((f.mean() - 600) / 250) ** 2) + 1.5 * np.exp(-((f.mean() - 1700) / 400) ** 2)
        wave += formant / k * np.sin(2 * np.pi * np.cumsum(f) / SR)
    env = np.minimum(1, np.minimum(t / 0.03, (duration - t) / 0.08)) * (0.75 + 0.25 * np.sin(2 * np.pi * 4 * t) ** 2)
    wave *= env
    wave *= 10 ** (level_db / 20) / rms(wave[env > 0.5])
    return wave


def scene(speech_db=-24.0, noise_total_db=-42.0, seconds=24):
    n = SR * seconds
    speech = np.zeros(n)
    marks = []  # (start, end, level) of each word
    pos = SR * 4  # first 4 s: noise only
    levels = [0, 0, -8, 0, 0, -8, 0, -8]
    i = 0
    while pos + SR < n:
        d = rng.uniform(0.25, 0.5)
        lvl = speech_db + levels[i % len(levels)]
        w = word(d, rng.uniform(105, 145), lvl)
        speech[pos:pos + len(w)] += w
        marks.append((pos, pos + len(w), lvl))
        pos += len(w) + int(SR * rng.uniform(0.35, 0.8))
        i += 1
    room = pb.Pedalboard([pb.Reverb(room_size=0.8, damping=0.35, wet_level=0.33, dry_level=0.67, width=1.0)])
    wet = room(speech.astype(np.float32)[None, :], SR)[0].astype(np.float64)
    white = rng.standard_normal(n)
    rumble = band(white, None, 150, 4)          # air conditioner / road
    fan = band(rng.standard_normal(n), 800, 9000, 2)
    tv_src = band(rng.standard_normal(n), 250, 3500, 4)
    tv = tv_src * (0.6 + 0.4 * np.sin(2 * np.pi * 2.3 * np.arange(n) / SR) ** 2)
    parts = [rumble / rms(rumble) * 10 ** (-44 / 20), fan / rms(fan) * 10 ** (-52 / 20), tv / rms(tv) * 10 ** (-47 / 20)]
    noise = sum(parts)
    noise *= 10 ** (noise_total_db / 20) / rms(noise)
    return (wet + noise).astype(np.float32), noise.astype(np.float32), marks


def run(chain, audio):
    return pb.Pedalboard(chain)(audio[None, :], SR)[0]


def metrics(chain, mix, noise, marks, gate_index=None):
    out = run(chain, mix)
    idle = db(rms(out[SR:SR * 4]))                                   # noise only, nobody talking
    speech_rms, tails, quiet = [], [], []
    for s, e, lvl in marks:
        core = out[s + int(0.08 * SR): e - int(0.05 * SR)]
        speech_rms.append(rms(core))
        if lvl < marks[0][2] - 4:
            quiet.append(rms(core) / max(rms(mix[s + int(0.08 * SR): e - int(0.05 * SR)]), 1e-9))
        a, b = e + int(0.12 * SR), e + int(0.30 * SR)               # the echo after the word ends
        if b < len(out):
            tails.append(rms(out[a:b]))
    # noise that stays on top of the voice while talking = the chain with the gate held open
    open_chain = [p for i, p in enumerate(chain) if i != gate_index] if gate_index is not None else chain
    talking_noise = rms(run(open_chain, noise)[SR:])
    speech_level = db(np.mean(speech_rms))
    return {
        "idle noise dB": idle,
        "echo after word dB": db(np.mean(tails)),
        "speech dB": speech_level,
        "quiet words kept": float(np.mean(quiet)) if quiet else float("nan"),
        "voice over noise dB (open gate)": speech_level - db(talking_noise),
    }


def show(title, rows):
    keys = list(rows[0][1].keys())
    print(f"\n{title}")
    print(f"{'':34}" + "".join(f"{k[:22]:>24}" for k in keys))
    for name, m in rows:
        print(f"{name:34}" + "".join(f"{m[k]:24.1f}" if k != 'quiet words kept' else f"{m[k]:24.2f}" for k in keys))


def chain(old: bool, gate: bool = True):
    if old:
        c = [pb.HighpassFilter(80)]
        if gate:
            c.append(pb.NoiseGate(threshold_db=-45, ratio=10, attack_ms=5, release_ms=150))
        c += [pb.LowShelfFilter(120, 0), pb.PeakFilter(300, -3, 1), pb.HighShelfFilter(10000, 2)]
    else:
        c = [pb.HighpassFilter(100), pb.HighpassFilter(100)]
        if gate:
            c.append(pb.NoiseGate(threshold_db=-30, ratio=4, attack_ms=3, release_ms=100))
        c += [pb.LowShelfFilter(120, -2), pb.PeakFilter(250, -4, 1), pb.HighShelfFilter(10000, 1)]
    return c + [pb.Compressor(threshold_db=-18, ratio=3, attack_ms=10, release_ms=100), pb.Gain(2),
                pb.Limiter(threshold_db=-2, release_ms=60)]


def measured_rooms(scenes):
    """What *Measure my room* does: listen to the first 4.5 s (noise only), set the gate, then see what that gate does."""
    print(f"\n{'Measure my room':26}" + "".join(f"{n:>13}" for n, _, _ in scenes))
    cut_line, quiet_line, thr_line, status_line = [f"{'  noise cut (dB)':26}"], [f"{'  quiet words (dB)':26}"], [f"{'  threshold set (dB)':26}"], [f"{'  verdict':26}"]
    for _, speech_db, noise_db in scenes:
        mix, _noise, marks = scene(speech_db=speech_db, noise_total_db=noise_db)
        highpass = lambda a: pb.Pedalboard([pb.HighpassFilter(100), pb.HighpassFilter(100)])(a.astype(np.float32), SR)  # noqa: E731
        quiet_part = mix[:SR * 4]  # the first four seconds of every simulated room are noise only
        result = measure_room.analyse(np.stack([quiet_part, quiet_part]), SR, highpass)
        chain_open = [pb.HighpassFilter(100), pb.HighpassFilter(100)]
        chain_gate = chain_open + [pb.NoiseGate(threshold_db=result.threshold_db, ratio=4, attack_ms=3, release_ms=100)]
        gated, opened = run(chain_gate, mix), run(chain_open, mix)
        top = max(m[2] for m in marks)
        quiet = [(s_, e_) for s_, e_, lvl in marks if lvl < top - 4]
        g = np.mean([rms(gated[s_ + int(.08 * SR):e_ - int(.05 * SR)]) for s_, e_ in quiet])
        o = np.mean([rms(opened[s_ + int(.08 * SR):e_ - int(.05 * SR)]) for s_, e_ in quiet])
        cut_line.append(f"{db(rms(gated[SR:4 * SR]) / rms(opened[SR:4 * SR])):13.0f}")
        quiet_line.append(f"{db(g / o):13.1f}")
        thr_line.append(f"{result.threshold_db:13.1f}")
        status_line.append(f"{result.status:>13}")
    for line in (thr_line, cut_line, quiet_line, status_line):
        print("".join(line))


def compressors(scenes):
    """Does more or less compression change how far the voice sits above the noise? (Gate held open; higher is better.)"""
    variants = [("current: -18 dB, 3:1, makeup 2", dict(threshold_db=-18, ratio=3, attack_ms=10, release_ms=100, gain=2)),
                ("gentler: -24 dB, 2:1, makeup 0", dict(threshold_db=-24, ratio=2, attack_ms=20, release_ms=200, gain=0)),
                ("harder: -16 dB, 4:1, makeup 3", dict(threshold_db=-16, ratio=4, attack_ms=5, release_ms=80, gain=3))]
    print(f"\n{'voice over noise (dB)':34}" + "".join(f"{n:>13}" for n, _, _ in scenes[:4]))
    data = [scene(speech_db=sp, noise_total_db=nz) for _, sp, nz in scenes[:4]]
    for label, c in variants:
        line = f"{label:34}"
        for mix, noise, marks in data:
            chain = [pb.HighpassFilter(100), pb.HighpassFilter(100), pb.Compressor(threshold_db=c["threshold_db"], ratio=c["ratio"], attack_ms=c["attack_ms"], release_ms=c["release_ms"]), pb.Gain(c["gain"])]
            speech = np.mean([rms(run(chain, mix)[s_ + int(.08 * SR):e_ - int(.05 * SR)]) for s_, e_, _ in marks])
            line += f"{db(speech / rms(run(chain, noise)[SR:])):13.1f}"
        print(line)


if __name__ == "__main__":
    scenes = [("hot mic", -20, -38), ("typical", -24, -42), ("noisy", -24, -36), ("loud TV", -24, -33),
              ("quiet mic", -30, -46), ("very quiet", -36, -52)]
    print(f"{'(dB change vs gate open)':26}" + "".join(f"{n:>13}" for n, _, _ in scenes))
    for label, old in (("old defaults: noise", True), ("new defaults: noise", False)):
        for what in ("noise", "quiet words"):
            if what == "quiet words":
                label = label.replace(": noise", ": quiet words")
            line = f"{label:26}"
            for _, speech_db, noise_db in scenes:
                mix, _noise, marks = scene(speech_db=speech_db, noise_total_db=noise_db)
                gated, opened = run(chain(old), mix), run(chain(old, gate=False), mix)
                if what == "noise":
                    line += f"{db(rms(gated[SR:SR * 4]) / rms(opened[SR:SR * 4])):13.0f}"
                else:
                    top = max(m[2] for m in marks)
                    quiet = [(s, e) for s, e, lvl in marks if lvl < top - 4]
                    g = np.mean([rms(gated[s + int(.08 * SR):e - int(.05 * SR)]) for s, e in quiet])
                    o = np.mean([rms(opened[s + int(.08 * SR):e - int(.05 * SR)]) for s, e in quiet])
                    line += f"{db(g / o):13.1f}"
            print(line)
            label = label.replace(": quiet words", ": noise")
    measured_rooms(scenes)
    compressors(scenes)
