// SPDX-License-Identifier: GPL-3.0-or-later
//! 0.13.1: the whole mixing graph in Rust, for when every effect in every chain is one of Sluice's own Rust effects. The JACK
//! callback then runs a block without Python (no waiting for Python's lock while the window is busy). It does exactly what
//! `Graph.process` in `sluice/dsp.py` does: each channel's chain, the meters, sleeping through silence, the guard against
//! NaN from a misbehaving effect, the "<channel> only" outputs, every mix's gain ramps, the mix fader and its limiter.
//! `dsp.Graph` stays the reference and the fallback (VST3 plugins, the Effects window's live view, "Measure my room").
//!
//! Effects are shared, not copied: the Python object the Effects window changes and the graph's entry hold the same core
//! (an `Arc<Mutex<...>>`), so a turned knob reaches the sound whichever path is running.

use crate::mix::{self, PeakLimiter};
use crate::native::Stereo;
use std::collections::HashMap;

pub const LIMITER_CEILING_DB: f64 = -1.0;
pub const LIMITER_RELEASE_MS: f64 = 100.0;
pub const SILENCE_TAIL_SECONDS: f64 = 6.0;
pub const RECENT_DECAY: f64 = 0.9985;

/// One step of a chain: an effect core shared with its Python object.
pub trait Proc: Send {
    fn run(&mut self, buf: &mut Stereo, sample_rate: u32);
    fn wake(&mut self) {}
}

#[derive(Default)]
pub struct ChannelCore {
    pub id: String,
    pub chain: Vec<Box<dyn Proc>>,
    pub gains: HashMap<String, f64>,
    pub applied: HashMap<String, f64>,
    pub solo_gain: Option<f64>,
    pub solo_applied: f64,
    pub peak: f64,
    pub recent: f64,
    pub input_recent: f64,
    pub input_peak: f64,
    pub asleep: bool,
    pub quiet_frames: u64,
    buf: Stereo,
    pub solo_out: Stereo,
    pub solo_live: bool, // the solo output has sound this block (else it is silence)
}

pub struct MixCore {
    pub id: String,
    pub gain: f64,
    pub applied: f64,
    pub primed: bool,
    pub limiter_on: bool,
    pub limiter: Option<PeakLimiter>,
    pub peak: f64,
    pub out: Stereo,
}

impl MixCore {
    pub fn new(id: &str) -> Self {
        MixCore {
            id: id.to_string(),
            gain: 1.0,
            applied: 1.0,
            primed: false,
            limiter_on: true,
            limiter: None,
            peak: 0.0,
            out: [Vec::new(), Vec::new()],
        }
    }
}

pub struct GraphCore {
    pub sample_rate: u32,
    pub channels: Vec<ChannelCore>,
    pub mixes: Vec<MixCore>,
}

/// Sets a gain reached without allocating once the mix is known (the audio thread runs this every block).
fn set_applied(map: &mut HashMap<String, f64>, id: &str, value: f64) {
    match map.get_mut(id) {
        Some(v) => *v = value,
        None => {
            map.insert(id.to_string(), value);
        }
    }
}

fn fit(buf: &mut Stereo, frames: usize) {
    for ch in buf.iter_mut() {
        if ch.len() != frames {
            ch.resize(frames, 0.0);
        }
    }
}

impl GraphCore {
    pub fn new(sample_rate: u32, mix_ids: &[String]) -> Self {
        GraphCore {
            sample_rate,
            channels: Vec::new(),
            mixes: mix_ids.iter().map(|m| MixCore::new(m)).collect(),
        }
    }

    pub fn channel_mut(&mut self, id: &str) -> Option<&mut ChannelCore> {
        self.channels.iter_mut().find(|c| c.id == id)
    }

    pub fn mix_mut(&mut self, id: &str) -> Option<&mut MixCore> {
        self.mixes.iter_mut().find(|m| m.id == id)
    }

    pub fn set_channels(&mut self, ids: &[String]) {
        self.channels.retain(|c| ids.contains(&c.id));
        for id in ids {
            if !self.channels.iter().any(|c| &c.id == id) {
                self.channels.push(ChannelCore {
                    id: id.clone(),
                    ..Default::default()
                });
            }
        }
    }

    /// One block. `input(id)` gives a channel's two input slices (None: no input). Afterwards each mix's `out` and each
    /// channel's `solo_out` (when `solo_gain` is set) hold the block.
    pub fn process<'a, F>(&mut self, frames: usize, input: F)
    where
        F: Fn(&str) -> Option<(&'a [f32], &'a [f32])>,
    {
        let sr = self.sample_rate;
        let tail = (sr as f64 * SILENCE_TAIL_SECONDS) as u64;
        for mix in self.mixes.iter_mut() {
            fit(&mut mix.out, frames);
            for ch in mix.out.iter_mut() {
                ch.fill(0.0);
            }
        }
        let GraphCore {
            channels, mixes, ..
        } = self;
        for channel in channels.iter_mut() {
            fit(&mut channel.buf, frames);
            let mut any = false;
            match input(&channel.id) {
                Some((l, r)) => {
                    for i in 0..frames {
                        let (a, b) = (
                            l.get(i).copied().unwrap_or(0.0),
                            r.get(i).copied().unwrap_or(0.0),
                        );
                        channel.buf[0][i] = a;
                        channel.buf[1][i] = b;
                        // `audio.any()` in numpy: NaN counts as non-zero
                        any |= a != 0.0 || b != 0.0;
                    }
                }
                None => {
                    for ch in channel.buf.iter_mut() {
                        ch.fill(0.0);
                    }
                }
            }
            if any {
                channel.quiet_frames = 0;
            } else {
                channel.quiet_frames = (channel.quiet_frames + frames as u64).min(1 << 30);
            }
            channel.solo_live = false;
            let empty = channel.chain.is_empty();
            if channel.quiet_frames > 0 && frames > 0 && (empty || channel.quiet_frames > tail) {
                // an idle channel costs nothing: no chain, no mixing
                channel.asleep = !empty;
                channel.recent *= RECENT_DECAY;
                for mix in mixes.iter() {
                    let g = channel.gains.get(&mix.id).copied().unwrap_or(0.0);
                    set_applied(&mut channel.applied, &mix.id, g);
                }
                if let Some(g) = channel.solo_gain {
                    fit(&mut channel.solo_out, frames);
                    for ch in channel.solo_out.iter_mut() {
                        ch.fill(0.0);
                    }
                    channel.solo_applied = g;
                }
                continue;
            }
            if frames > 0 {
                let (before, _, _) = mix::stats(&channel.buf[0], &channel.buf[1]);
                // numpy's max(abs) is NaN when a NaN is there; the Python graph then keeps the old value (max(NaN, x) is
                // x in Python), so taking the finite peak here gives the same meters
                let before = before as f64;
                channel.input_recent = before.max(channel.input_recent * RECENT_DECAY);
                channel.input_peak = channel.input_peak.max(before);
            }
            if !empty {
                if channel.asleep {
                    channel.asleep = false;
                    for p in channel.chain.iter_mut() {
                        p.wake();
                    }
                }
                for p in channel.chain.iter_mut() {
                    p.run(&mut channel.buf, sr);
                }
            }
            if frames > 0 {
                let (mut level, _, finite) = mix::stats(&channel.buf[0], &channel.buf[1]);
                if !finite {
                    // a misbehaving effect produced NaN or infinity: replace it with silence
                    for ch in channel.buf.iter_mut() {
                        for x in ch.iter_mut() {
                            if !x.is_finite() {
                                *x = 0.0;
                            }
                        }
                    }
                    level = mix::stats(&channel.buf[0], &channel.buf[1]).0;
                }
                let level = level as f64;
                channel.peak = channel.peak.max(level);
                channel.recent = level.max(channel.recent * RECENT_DECAY);
            }
            for mix in mixes.iter_mut() {
                let target = channel.gains.get(&mix.id).copied().unwrap_or(0.0);
                let previous = channel.applied.get(&mix.id).copied().unwrap_or(target);
                if target == 0.0 && previous == 0.0 {
                    continue;
                }
                for c in 0..2 {
                    let (out, src) = (&mut mix.out[c], &channel.buf[c]);
                    for i in 0..frames {
                        out[i] += src[i] * mix::ramp_value(previous, target, i, frames);
                    }
                }
                set_applied(&mut channel.applied, &mix.id, target);
            }
            if let Some(g) = channel.solo_gain {
                fit(&mut channel.solo_out, frames);
                for c in 0..2 {
                    for i in 0..frames {
                        channel.solo_out[c][i] =
                            channel.buf[c][i] * mix::ramp_value(channel.solo_applied, g, i, frames);
                    }
                }
                channel.solo_applied = g;
                channel.solo_live = true;
            }
        }
        for mix in mixes.iter_mut() {
            if frames == 0 {
                mix.applied = mix.gain;
                mix.primed = true;
                continue;
            }
            let (applied, gain) = (mix.applied, mix.gain);
            for c in 0..2 {
                for i in 0..frames {
                    mix.out[c][i] *= mix::ramp_value(applied, gain, i, frames);
                }
            }
            if mix.limiter_on {
                let limiter = mix.limiter.get_or_insert_with(|| {
                    PeakLimiter::new(sr, LIMITER_CEILING_DB, LIMITER_RELEASE_MS)
                });
                let [l, r] = &mut mix.out;
                limiter.process(l, r);
                for ch in mix.out.iter_mut() {
                    for x in ch.iter_mut() {
                        *x = x.clamp(-1.0, 1.0); // the clip is only a safety net
                    }
                }
            }
            mix.applied = gain;
            mix.primed = true;
            let peak = mix
                .out
                .iter()
                .flat_map(|c| c.iter())
                .fold(0.0f32, |m, &x| m.max(x.abs()));
            mix.peak = mix.peak.max(peak as f64);
        }
    }
}
