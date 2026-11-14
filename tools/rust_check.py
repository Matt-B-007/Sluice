#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare the Rust reducers with the Python ones on the same recording: how far apart they are, and how much faster.

Run inside Sluice's environment with the Rust engine installed: python tools/rust_check.py
"""
import sys
import time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sluice_dsp as R
from sluice import spectral as P

rng = np.random.default_rng(1)
sr = 48000
n = sr * 8
t = np.arange(n) / sr
voice = np.sin(2*np.pi*180*t) * (np.sin(2*np.pi*1.5*t) > 0) * 0.3 + 0.1*np.sin(2*np.pi*1200*t)*(np.sin(2*np.pi*1.5*t) > 0)
noise = rng.normal(0, 0.02, n)
x = np.stack([voice + noise, voice*0.9 + rng.normal(0, 0.02, n)]).astype(np.float32)
blocks = [256, 512, 480, 1000]  # includes sizes that are not a multiple of the hop

def run(make, joint=False):
    outs = []
    obj = make()
    pos = 0; i = 0
    while pos < n:
        b = blocks[i % len(blocks)]; i += 1
        outs.append(np.asarray(obj.process(x[:, pos:pos+b])))
        pos += b
    return np.concatenate(outs, axis=1), obj

cases = {
 "noise": (lambda: P.PythonNoiseReducer(sr, 12.0), lambda: R.NoiseReducer(sr, 12.0)),
 "echo": (lambda: P.PythonEchoReducer(sr, 0.8, 9.0), lambda: R.EchoReducer(sr, 0.8, 9.0)),
}
def mk_joint_py():
    return P.PythonJoint([P.PythonEchoReducer(sr, 0.6, 9.0), P.PythonNoiseReducer(sr, 15.0)])
def mk_joint_rs():
    return R.Joint([R.EchoReducer(sr, 0.6, 9.0), R.NoiseReducer(sr, 15.0)])
cases["joint"] = (mk_joint_py, mk_joint_rs)

for name, (mp, mr) in cases.items():
    t0 = time.perf_counter(); yp, op = run(mp); t1 = time.perf_counter()
    yr, orr = run(mr); t2 = time.perf_counter()
    err = np.max(np.abs(yp - yr)); ref = np.max(np.abs(yp))
    rms = np.sqrt(np.mean((yp-yr)**2)) / (np.sqrt(np.mean(yp**2)) + 1e-12)
    print(f"{name:6} shape {yp.shape} max abs diff {err:.2e} (peak {ref:.2f}) rel rms {rms:.2e}  python {t1-t0:.2f}s rust {t2-t1:.2f}s  speedup {(t1-t0)/(t2-t1):.1f}x")
    if name != "joint":
        print("       activity py", round(op.activity_db, 4), "rust", round(orr.activity_db, 4))
