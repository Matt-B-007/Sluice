# SPDX-License-Identifier: GPL-3.0-or-later
"""Speech corpus (espeak-ng, offline) and realistic room simulation with clean references."""
import ctypes, numpy as np
from scipy import signal
import espeakng_loader

SR = 48000
_lib = None
def _espeak():
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(espeakng_loader.get_library_path())
        lib.espeak_Initialize.restype = ctypes.c_int
        rate = lib.espeak_Initialize(1, 0, espeakng_loader.get_data_path().encode(), 0)
        lib.rate = rate
        _lib = lib
    return _lib

CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)
def synth(text, voice="en-us", rate=150, pitch=50):
    lib = _espeak(); chunks = []
    def cb(wav, n, ev):
        if wav and n > 0: chunks.append(np.ctypeslib.as_array(wav, shape=(n,)).copy())
        return 0
    cbf = CB(cb)
    lib.espeak_SetSynthCallback(cbf)
    lib.espeak_SetVoiceByName(voice.encode())
    lib.espeak_SetParameter(1, rate, 0); lib.espeak_SetParameter(3, pitch, 0)
    b = text.encode() + b"\0"
    lib.espeak_Synth(b, len(b), 0, 1, 0, 1, None, None)
    lib.espeak_Synchronize()
    x = np.concatenate(chunks).astype(np.float64) / 32768.0
    return signal.resample_poly(x, 320, 147)  # 22050 -> 48000

SENTENCES = [
 "Okay, are you guys ready to start the next round?",
 "Watch the left side, I think two of them are pushing through the long hallway.",
 "Thanks for joining the stream today, please remember to follow and share.",
 "She sells sea shells by the sea shore, and the shells she sells are surely seashells.",
 "I can hear you fine, but there is a lot of background noise on my end.",
 "We should rotate to the bomb site now, and I will throw a flash first.",
]
def speech_track(seconds=40, seed=0):
    rng = np.random.default_rng(seed); out = []; t = 0; i = 0
    voices = [("en-us", 140, 45), ("en-us+f3", 150, 60), ("en-us+m3", 130, 40)]
    while t < seconds * SR:
        v, r, p = voices[i % len(voices)]
        w = synth(SENTENCES[i % len(SENTENCES)], v, r, p)
        w = w / np.max(np.abs(w)) * 0.5
        gap = np.zeros(int(SR * rng.uniform(0.6, 1.4)))
        out += [w, gap]; t += len(w) + len(gap); i += 1
    return np.concatenate(out)[: seconds * SR]

def rir(rt60=0.7, drr_db=0.0, seed=1):
    """Synthetic room impulse response: direct path + exponentially decaying diffuse tail (a standard model)."""
    rng = np.random.default_rng(seed); n = int(SR * rt60 * 1.3)
    t = np.arange(n) / SR
    tail = rng.standard_normal(n) * 10 ** (-3 * t / rt60)       # -60 dB at rt60
    tail[: int(0.004 * SR)] = 0
    # frequency-dependent decay: highs die faster (air + absorbent surfaces)
    sos = signal.butter(2, 6000, btype="low", fs=SR, output="sos"); tail = signal.sosfilt(sos, tail)
    direct_e = 1.0
    tail *= np.sqrt(direct_e / (10 ** (drr_db / 10)) / np.sum(tail ** 2))
    h = tail.copy(); h[int(0.002 * SR)] += 1.0
    early = h.copy(); early[int(0.05 * SR):] = 0      # reference: direct sound plus the first 50 ms
    return h, early

def band(noise, lo, hi, order=4):
    sos = signal.butter(order, hi, btype="low", fs=SR, output="sos") if not lo else signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, noise)

def noise_bed(n, kind, rng):
    if kind == "ac":   # steady rumble with a low-frequency hum + broadband hiss
        x = band(rng.standard_normal(n), None, 180) * 1.0 + 0.25 * band(rng.standard_normal(n), 800, 9000, 2)
        t = np.arange(n) / SR; x += 0.15 * np.sin(2 * np.pi * 120 * t)
    elif kind == "fan":
        x = band(rng.standard_normal(n), 100, 6000, 2) * (1 + 0.15 * np.sin(2 * np.pi * 0.7 * np.arange(n) / SR))
    elif kind == "road":
        x = band(rng.standard_normal(n), None, 400, 2) * (1 + 0.5 * np.abs(np.sin(2 * np.pi * 0.12 * np.arange(n) / SR)))
    elif kind == "tv":  # other speech, slowly varying, band-limited, heard from another room
        parts = [synth(SENTENCES[(k * 3 + 1) % len(SENTENCES)], "en-us+f2", 160, 55) for k in range(10)]
        x = np.concatenate(parts); x = np.tile(x, int(np.ceil(n / len(x))))[:n]; x = band(x, 200, 4000)
    else: raise ValueError(kind)
    return x / np.sqrt(np.mean(x ** 2))

def make_scene(noise_kind="ac", snr_db=10.0, rt60=0.7, drr_db=0.0, seconds=36, seed=0, lead=4.0):
    """Returns (observed, reference_early, noise_only_lead). The first `lead` seconds contain only room noise."""
    rng = np.random.default_rng(seed)
    dry = speech_track(seconds - int(lead), seed)
    n = seconds * SR
    dry = np.concatenate([np.zeros(int(lead * SR)), dry])[:n]
    h, early = rir(rt60, drr_db, seed + 1)
    wet = signal.fftconvolve(dry, h)[:n]; ref = signal.fftconvolve(dry, early)[:n]
    noise = noise_bed(n, noise_kind, rng)
    sp = wet[int(lead * SR):]; active = np.abs(sp) > 0.02 * np.max(np.abs(sp))
    p_speech = np.mean(sp[active] ** 2)
    noise *= np.sqrt(p_speech / 10 ** (snr_db / 10))
    obs = wet + noise
    peak = max(np.max(np.abs(obs)), 1e-9); g = 0.5 / peak
    return (obs * g).astype(np.float32), (ref * g).astype(np.float32), noise.astype(np.float32) * g, int(lead * SR)

def si_sdr(est, ref):
    n = min(len(est), len(ref)); est, ref = est[:n] - np.mean(est[:n]), ref[:n] - np.mean(ref[:n])
    a = np.dot(est, ref) / (np.dot(ref, ref) + 1e-12); target = a * ref; noise = est - target
    return 10 * np.log10(np.sum(target ** 2) / (np.sum(noise ** 2) + 1e-12))

def stoi_score(est, ref):
    from pystoi import stoi
    n = min(len(est), len(ref))
    return stoi(ref[:n], est[:n], SR, extended=False)
