# SPDX-License-Identifier: GPL-3.0-or-later
"""Scores the Noise Reducer and Echo Reducer on simulated noisy, echoing rooms with synthetic speech.
Needs: pip install pystoi espeakng-loader scipy. Prints SI-SDR / STOI of the raw, noise-reduced, echo-reduced and both orders."""
import sys, time, os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
import reducer_corpus as C
from sluice.spectral import NoiseReducer, EchoReducer, Joint

def run(fx, x, block=512):
    x2 = np.stack([x, x]).astype(np.float32)
    n = x2.shape[1] // block * block
    out = np.concatenate([fx.process(x2[:, i:i+block]) for i in range(0, n, block)], axis=1)[0]
    d = fx.latency
    out = np.concatenate([out[d:], np.zeros(d)])
    return out[: n]

def score(est, ref, lead):
    n = len(est); s = slice(lead + 48000, n)
    return C.si_sdr(est[s], ref[:n][s]), C.stoi_score(est[s], ref[:n][s])

def main():
    for kind in ["ac", "fan", "road", "tv"]:
        for snr in [5, 10, 15]:
            obs, ref, noise, lead = C.make_scene(kind, snr, 0.7, 0.0, seconds=24)
            base = score(obs, ref, lead)
            nr = run(NoiseReducer(48000, 12), obs); a = score(nr, ref, lead)
            er = run(EchoReducer(48000, 0.7, 9), obs); b = score(er, ref, lead)
            both = run(EchoReducer(48000, 0.7, 9), run(NoiseReducer(48000, 12), obs)); c = score(both, ref, lead)
            both2 = run(NoiseReducer(48000, 12), run(EchoReducer(48000, 0.7, 9), obs)); d = score(both2, ref, lead)
            joint = run(Joint([EchoReducer(48000, 0.7, 9), NoiseReducer(48000, 12)]), obs); e = score(joint, ref, lead)
            print(f"{kind:5}{snr:3}  obs {base[0]:5.1f}/{base[1]:.2f}  noise {a[0]:5.1f}/{a[1]:.2f}  echo {b[0]:5.1f}/{b[1]:.2f}  N>E {c[0]:5.1f}/{c[1]:.2f}  E>N {d[0]:5.1f}/{d[1]:.2f}  JOINT {e[0]:5.1f}/{e[1]:.2f}", flush=True)
    x = np.random.randn(2, 512).astype(np.float32) * .1
    for name, fx in (("echo then noise, two passes", None), ("joint, one pass", Joint([EchoReducer(48000), NoiseReducer(48000)]))):
        a, b = (EchoReducer(48000), NoiseReducer(48000)) if fx is None else (fx, None)
        for _ in range(100): (b.process(a.process(x)) if b else a.process(x))
        best = 1e9
        for _ in range(5):
            t = time.perf_counter()
            for _ in range(300): (b.process(a.process(x)) if b else a.process(x))
            best = min(best, (time.perf_counter() - t) / 300 * 1e6)
        print(f"{name}: {best:.0f} us per 512-frame block (budget 10667)")


if __name__ == "__main__":
    main()
