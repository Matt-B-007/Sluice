// SPDX-License-Identifier: GPL-3.0-or-later
//! 0.13.1: the gate, compressor and ceiling limiter of the built-in voice effects, the same algorithm as `sluice/voicefx.py`
//! (which stays as the reference and the fallback; `tests/test_native_graph.py` checks they agree). They work in steps of
//! about a millisecond: the level of each step (both channels together), the gain for the end of the step, and a gain that
//! glides there sample by sample.

use crate::mix::PeakLimiter;
use crate::native::Stereo;

const STEP_MS: f64 = 1.0;
pub const FLOOR_DB: f64 = -120.0;
const MAX_STEPS: usize = 1024; // room for a block of up to about a second at 48 kHz without allocating

fn step_of(sample_rate: u32) -> usize {
    ((sample_rate as f64 * STEP_MS / 1000.0).round() as usize).max(16)
}

fn coefficient(ms: f64, step_seconds: f64) -> f64 {
    if ms > 0.0 {
        (-step_seconds / (ms / 1000.0)).exp()
    } else {
        0.0
    }
}

/// The level of each step in dB, both channels together: the peak, or the RMS. Written into `out`; returns how many.
fn levels(audio: &Stereo, step: usize, rms: bool, out: &mut Vec<f64>) {
    out.clear();
    let frames = audio[0].len();
    let mut start = 0;
    while start < frames {
        let end = (start + step).min(frames);
        let v = if rms {
            let mut sum = 0.0f64;
            for ch in audio.iter() {
                for &x in &ch[start..end] {
                    sum += (x as f64) * (x as f64);
                }
            }
            (sum / (2 * (end - start)) as f64).sqrt()
        } else {
            let mut peak = 0.0f32;
            for ch in audio.iter() {
                for &x in &ch[start..end] {
                    peak = peak.max(x.abs());
                }
            }
            peak as f64
        };
        out.push(if v > 1e-6 { 20.0 * v.log10() } else { FLOOR_DB });
        start = end;
    }
}

/// `audio` times a gain that glides from `start_db` to each of `ends_db` (one per step), like voicefx._apply (np.interp).
fn apply(audio: &mut Stereo, start_db: f64, ends_db: &[f64], step: usize) {
    let frames = audio[0].len();
    let mut from = 10f64.powf(start_db / 20.0);
    let mut x0 = 0usize;
    for (k, &end_db) in ends_db.iter().enumerate() {
        let to = 10f64.powf(end_db / 20.0);
        let x1 = ((k + 1) * step).min(frames);
        let span = (x1 - x0) as f64;
        let [l, r] = audio;
        for (k, (a, b)) in l[x0..x1].iter_mut().zip(r[x0..x1].iter_mut()).enumerate() {
            let g = (from + (to - from) * (k as f64) / span) as f32;
            *a *= g;
            *b *= g;
        }
        from = to;
        x0 = x1;
    }
}

pub struct VoiceGate {
    pub sample_rate: u32,
    pub threshold_db: f64,
    pub depth_db: f64,
    pub attack_ms: f64,
    pub hold_ms: f64,
    pub release_ms: f64,
    pub activity_db: f64,
    level_db: f64,
    open: bool,
    held: f64,
    gain_db: f64,
    lv: Vec<f64>,
    ends: Vec<f64>,
}

impl VoiceGate {
    const HYSTERESIS: f64 = 4.0;
    const SENSE_MS: f64 = 10.0;

    pub fn new(sample_rate: u32) -> Self {
        VoiceGate {
            sample_rate,
            threshold_db: -40.0,
            depth_db: 24.0,
            attack_ms: 2.0,
            hold_ms: 120.0,
            release_ms: 150.0,
            activity_db: 0.0,
            level_db: FLOOR_DB,
            open: false,
            held: 0.0,
            gain_db: -24.0,
            lv: Vec::with_capacity(MAX_STEPS),
            ends: Vec::with_capacity(MAX_STEPS),
        }
    }

    pub fn wake(&mut self) {
        self.level_db = FLOOR_DB;
    }

    pub fn process(&mut self, audio: &mut Stereo) {
        let step = step_of(self.sample_rate);
        let seconds = step as f64 / self.sample_rate as f64;
        let sense = coefficient(Self::SENSE_MS, seconds);
        let depth = self.depth_db.max(0.0);
        let open_rate = depth / (self.attack_ms / 1000.0).max(seconds) * seconds;
        let close_rate = depth / (self.release_ms / 1000.0).max(seconds) * seconds;
        let start = self.gain_db;
        let mut lv = std::mem::take(&mut self.lv);
        let mut ends = std::mem::take(&mut self.ends);
        levels(audio, step, true, &mut lv);
        ends.clear();
        for &level in &lv {
            let power = 10f64.powf(level / 10.0);
            let smoothed = 10f64.powf(self.level_db / 10.0) * sense + power * (1.0 - sense);
            self.level_db = if smoothed > 1e-12 {
                10.0 * smoothed.log10()
            } else {
                FLOOR_DB
            };
            if self.level_db >= self.threshold_db {
                self.open = true;
                self.held = self.hold_ms / 1000.0;
            } else if self.level_db < self.threshold_db - Self::HYSTERESIS {
                if self.held > 0.0 {
                    self.held -= seconds;
                } else {
                    self.open = false;
                }
            }
            let target = if self.open { 0.0 } else { -depth };
            if self.gain_db < target {
                self.gain_db = target.min(self.gain_db + open_rate);
            } else if self.gain_db > target {
                self.gain_db = target.max(self.gain_db - close_rate);
            }
            ends.push(self.gain_db);
        }
        self.activity_db = self.gain_db;
        apply(audio, start, &ends, step);
        self.lv = lv;
        self.ends = ends;
    }
}

pub struct LinkedCompressor {
    pub sample_rate: u32,
    pub threshold_db: f64,
    pub ratio: f64,
    pub attack_ms: f64,
    pub release_ms: f64,
    pub makeup_db: f64,
    pub activity_db: f64,
    env_db: f64,
    gain_db: Option<f64>,
    lv: Vec<f64>,
    ends: Vec<f64>,
}

impl LinkedCompressor {
    const KNEE: f64 = 6.0;

    pub fn new(sample_rate: u32) -> Self {
        LinkedCompressor {
            sample_rate,
            threshold_db: -18.0,
            ratio: 3.0,
            attack_ms: 10.0,
            release_ms: 100.0,
            makeup_db: 2.0,
            activity_db: 0.0,
            env_db: FLOOR_DB,
            gain_db: None,
            lv: Vec::with_capacity(MAX_STEPS),
            ends: Vec::with_capacity(MAX_STEPS),
        }
    }

    pub fn wake(&mut self) {
        self.env_db = FLOOR_DB;
    }

    pub fn reduction(&self, level_db: f64) -> f64 {
        let over = level_db - self.threshold_db;
        let slope = 1.0 / self.ratio.max(1.0) - 1.0;
        let half = Self::KNEE / 2.0;
        if over <= -half {
            0.0
        } else if over < half {
            slope * (over + half).powi(2) / (2.0 * Self::KNEE)
        } else {
            slope * over
        }
    }

    pub fn process(&mut self, audio: &mut Stereo) {
        let step = step_of(self.sample_rate);
        let seconds = step as f64 / self.sample_rate as f64;
        let (attack, release) = (
            coefficient(self.attack_ms, seconds),
            coefficient(self.release_ms, seconds),
        );
        let start = self.gain_db.unwrap_or(self.makeup_db);
        let mut lv = std::mem::take(&mut self.lv);
        let mut ends = std::mem::take(&mut self.ends);
        levels(audio, step, false, &mut lv);
        ends.clear();
        for &level in &lv {
            let keep = if level > self.env_db { attack } else { release };
            self.env_db = level + keep * (self.env_db - level);
            let cut = self.reduction(self.env_db);
            self.activity_db = cut;
            ends.push(cut + self.makeup_db);
        }
        self.gain_db = Some(ends.last().copied().unwrap_or(start));
        apply(audio, start, &ends, step);
        self.lv = lv;
        self.ends = ends;
    }
}

pub struct CeilingLimiter {
    pub sample_rate: u32,
    threshold_db: f64,
    release_ms: f64,
    limiter: Option<PeakLimiter>,
    pub activity_db: f64,
}

impl CeilingLimiter {
    pub fn new(sample_rate: u32) -> Self {
        CeilingLimiter {
            sample_rate,
            threshold_db: -2.0,
            release_ms: 60.0,
            limiter: None,
            activity_db: 0.0,
        }
    }
    pub fn threshold_db(&self) -> f64 {
        self.threshold_db
    }
    pub fn set_threshold_db(&mut self, v: f64) {
        if v != self.threshold_db {
            self.threshold_db = v;
            self.limiter = None;
        }
    }
    pub fn release_ms(&self) -> f64 {
        self.release_ms
    }
    pub fn set_release_ms(&mut self, v: f64) {
        if v != self.release_ms {
            self.release_ms = v;
            self.limiter = None;
        }
    }
    pub fn process(&mut self, audio: &mut Stereo) {
        let (sr, t, r) = (self.sample_rate, self.threshold_db, self.release_ms);
        let limiter = self
            .limiter
            .get_or_insert_with(|| PeakLimiter::new(sr, t, r));
        let peak = |a: &Stereo| {
            a.iter()
                .flat_map(|c| c.iter())
                .fold(0.0f32, |m, &x| m.max(x.abs())) as f64
        };
        let before = peak(audio);
        let [l, rr] = audio;
        limiter.process(l, rr);
        let after = peak(audio);
        self.activity_db = if before > 1e-6 && after > 0.0 {
            20.0 * (after / before).log10()
        } else {
            0.0
        };
    }
}
