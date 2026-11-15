# The Rust engine

Sluice is Python for everything people see and change, and Rust for the audio work that has to be quick and steady.
The Rust part is the `sluice_dsp` extension in [`rust/sluice_dsp`](../rust/sluice_dsp). It is **optional**: without it
Sluice runs the Python versions of everything below, with the same sound and a bit more CPU.

## What runs where

| Part | With Rust installed | Without |
|---|---|---|
| Noise Reducer, Echo Reducer (STFT) | Rust (`stft.rs`, `reducers.rs`), about 6 times faster | Python (`spectral.py`) |
| Built-in effects: Gain, High-pass, EQ (shelves and peak), Compressor, Noise gate, Limiter | Rust (`native.rs`), the same algorithms as the JUCE ones pedalboard uses | pedalboard |
| Mixing: gain ramps, summing, mix fader, peak limiter, meters, NaN guard | Rust (`mix.rs`) | numpy (`dsp.py`) |
| Room, echo and voice measuring: block peaks, noise profile (FFT), echo decay energy, voice levels | Rust (`room.rs`) | numpy (`room.py`) |
| Audio client: JACK/PipeWire ports, the block callback, timing, dropout counting | Rust (`jack_io.rs`, loads libjack when it connects) | python-jack (`audio_io.py`) |
| VST3 plugins | pedalboard (Python) | pedalboard |
| Interface, settings, presets, model, control and MIDI, self-update, logs, bug report, uninstall | Python | Python |

VST3 plugins are loaded by pedalboard, which is Python, so the Rust audio client calls the Python mixing graph once per
block (it takes the GIL for that call) and does everything around the call itself. A channel whose chain has no VST3
plugin still runs all its effects in Rust inside that call.

## Switches

- `SLUICE_NO_RUST=1`: use the Python versions of everything (to compare, or to rule Rust out while hunting a problem).
- `SLUICE_NO_RUST_EFFECTS=1`, `SLUICE_NO_RUST_MIX=1`, `SLUICE_NO_RUST_ROOM=1`, `SLUICE_NO_RUST_IO=1`: one part at a time.
- `sluice --diagnose` has an *Audio engine* line that says which parts are running in Rust.

## How it is checked

`tests/test_rust_*.py` compare every Rust piece with the Python or pedalboard original on the same input (within float
rounding), the whole voice chain with and without Rust, and the audio client against a real JACK server (the dummy
driver) when `jackd` is installed. The full test suite also runs with `SLUICE_NO_RUST=1`. Run `python tools/rust_check.py`
for the comparison numbers.

## Building it

`./install.sh` builds it when `cargo` is found. By hand: `pip install maturin && cd rust/sluice_dsp && maturin develop --release`
inside Sluice's virtual environment. Building needs a Rust toolchain only (no JACK headers: libjack is loaded at run
time, and `vendor/jack-sys` is the published `jack-sys` crate without the build script that insisted on them).

## Real-time notes

The audio thread never waits on a lock for long: ports are swapped under a mutex that the callback only `try_lock`s, a
block that fails is silence, not a stall, and a Python exception in the mixing graph turns into silence plus an error
message, never a crash. Allocation inside the callback is limited to the block's numpy arrays (as it was with python-jack).

## Not done

A fully Rust mixing graph with no Python in the callback at all would need VST3 hosting in Rust. That is a possible
later step, together with a Windows version (WASAPI instead of JACK); neither is part of 0.9.6.
