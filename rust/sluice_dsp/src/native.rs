// SPDX-License-Identifier: GPL-3.0-or-later
//! Sluice's built-in effects, written to behave like the pedalboard (JUCE) ones they replace: same parameters, same
//! maths. Each is checked against pedalboard on real signals in `tests/test_rust_effects.py`.
//!
//! Effects process two channels in place. `prepare` is called whenever the sample rate or a setting changes.

use std::f64::consts::PI;

pub type Stereo = [Vec<f32>; 2];

fn db_to_gain(db: f64) -> f64 {
    10f64.powf(db / 20.0)
}

pub trait Effect: Send {
    fn process(&mut self, audio: &mut Stereo, sample_rate: u32);
}

// ------------------------------------------------------------------------------------------------------- Gain
pub struct Gain {
    pub gain_db: f64,
}

impl Effect for Gain {
    fn process(&mut self, audio: &mut Stereo, _sr: u32) {
        let g = db_to_gain(self.gain_db) as f32;
        for ch in audio.iter_mut() {
            for x in ch.iter_mut() {
                *x *= g;
            }
        }
    }
}

// ----------------------------------------------------------------------------------------------- High-pass (6 dB)
pub struct HighPass {
    pub cutoff_hz: f64,
    s: [f64; 2],
}

impl HighPass {
    pub fn new(cutoff_hz: f64) -> Self {
        HighPass { cutoff_hz, s: [0.0; 2] }
    }
}

impl Effect for HighPass {
    fn process(&mut self, audio: &mut Stereo, sr: u32) {
        // JUCE FirstOrderTPTFilter
        let g = (PI * self.cutoff_hz / sr as f64).tan();
        let gg = g / (1.0 + g);
        for c in 0..2 {
            let mut s = self.s[c];
            for x in audio[c].iter_mut() {
                let xi = *x as f64;
                let v = (xi - s) * gg;
                let lp = v + s;
                s = v + lp;
                *x = (xi - lp) as f32;
            }
            self.s[c] = s;
        }
    }
}

// --------------------------------------------------------------------------------------------- Biquads (the EQ)
#[derive(Clone, Copy, PartialEq)]
pub enum Shape {
    LowShelf,
    HighShelf,
    Peak,
    HighPass, // 0.11.0: a 12 dB/octave Butterworth high-pass (-3 dB at the cutoff; the "q" is 1/sqrt(2))
}

pub struct Biquad {
    pub shape: Shape,
    pub freq: f64,
    pub gain_db: f64,
    pub q: f64,
    s1: [f64; 2],
    s2: [f64; 2],
}

impl Biquad {
    pub fn new(shape: Shape, freq: f64, gain_db: f64, q: f64) -> Self {
        Biquad { shape, freq, gain_db, q, s1: [0.0; 2], s2: [0.0; 2] }
    }

    /// juce::dsp::IIR::Coefficients::makeLowShelf / makeHighShelf / makePeakFilter, normalised by a0.
    fn coefficients(&self, sr: f64) -> [f64; 5] {
        let a_gain = db_to_gain(self.gain_db).max(0.0).sqrt();
        let omega = 2.0 * PI * self.freq.max(2.0) / sr;
        let (b0, b1, b2, a0, a1, a2);
        match self.shape {
            Shape::HighPass => {
                // RBJ cookbook high-pass
                let alpha = omega.sin() / (self.q * 2.0);
                let coso = omega.cos();
                b0 = (1.0 + coso) / 2.0;
                b1 = -(1.0 + coso);
                b2 = (1.0 + coso) / 2.0;
                a0 = 1.0 + alpha;
                a1 = -2.0 * coso;
                a2 = 1.0 - alpha;
            }
            Shape::Peak => {
                let alpha = omega.sin() / (self.q * 2.0);
                let c2 = -2.0 * omega.cos();
                let at = alpha * a_gain;
                let ao = alpha / a_gain;
                b0 = 1.0 + at;
                b1 = c2;
                b2 = 1.0 - at;
                a0 = 1.0 + ao;
                a1 = c2;
                a2 = 1.0 - ao;
            }
            Shape::LowShelf | Shape::HighShelf => {
                let am1 = a_gain - 1.0;
                let ap1 = a_gain + 1.0;
                let coso = omega.cos();
                let beta = omega.sin() * a_gain.sqrt() / self.q;
                let am1c = am1 * coso;
                if self.shape == Shape::LowShelf {
                    b0 = a_gain * (ap1 - am1c + beta);
                    b1 = a_gain * 2.0 * (am1 - ap1 * coso);
                    b2 = a_gain * (ap1 - am1c - beta);
                    a0 = ap1 + am1c + beta;
                    a1 = -2.0 * (am1 + ap1 * coso);
                    a2 = ap1 + am1c - beta;
                } else {
                    b0 = a_gain * (ap1 + am1c + beta);
                    b1 = a_gain * -2.0 * (am1 + ap1 * coso);
                    b2 = a_gain * (ap1 + am1c - beta);
                    a0 = ap1 - am1c + beta;
                    a1 = 2.0 * (am1 - ap1 * coso);
                    a2 = ap1 - am1c - beta;
                }
            }
        }
        [b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0]
    }
}

impl Effect for Biquad {
    fn process(&mut self, audio: &mut Stereo, sr: u32) {
        let [b0, b1, b2, a1, a2] = self.coefficients(sr as f64);
        for c in 0..2 {
            let (mut s1, mut s2) = (self.s1[c], self.s2[c]);
            for x in audio[c].iter_mut() {
                let xi = *x as f64;
                let y = xi * b0 + s1;
                s1 = xi * b1 - y * a1 + s2;
                s2 = xi * b2 - y * a2;
                *x = y as f32;
            }
            self.s1[c] = s1;
            self.s2[c] = s2;
        }
    }
}

// ---------------------------------------------------------------------------- JUCE BallisticsFilter + Compressor
fn cte(ms: f64, sr: f64) -> f64 {
    if ms < 1.0e-3 {
        0.0
    } else {
        (-2.0 * PI * 1000.0 / (ms * sr)).exp()
    }
}

#[derive(Clone, Copy, PartialEq)]
enum Level {
    Peak,
    Rms,
}

struct Ballistics {
    y: [f64; 2],
}

impl Ballistics {
    fn new() -> Self {
        Ballistics { y: [0.0; 2] }
    }
    #[inline]
    fn step(&mut self, c: usize, x: f64, level: Level, cte_attack: f64, cte_release: f64) -> f64 {
        let v = if level == Level::Rms { x * x } else { x.abs() };
        let k = if v > self.y[c] { cte_attack } else { cte_release };
        let r = v + k * (self.y[c] - v);
        self.y[c] = r;
        if level == Level::Rms {
            r.sqrt()
        } else {
            r
        }
    }
}

pub struct Compressor {
    pub threshold_db: f64,
    pub ratio: f64,
    pub attack_ms: f64,
    pub release_ms: f64,
    env: Ballistics,
}

impl Compressor {
    pub fn new(threshold_db: f64, ratio: f64, attack_ms: f64, release_ms: f64) -> Self {
        Compressor { threshold_db, ratio, attack_ms, release_ms, env: Ballistics::new() }
    }
}

impl Effect for Compressor {
    fn process(&mut self, audio: &mut Stereo, sr: u32) {
        let sr = sr as f64;
        let threshold = db_to_gain(self.threshold_db.max(-200.0));
        let threshold_inv = 1.0 / threshold;
        let ratio_inv = 1.0 / self.ratio;
        let (ca, cr) = (cte(self.attack_ms, sr), cte(self.release_ms, sr));
        for c in 0..2 {
            for x in audio[c].iter_mut() {
                let xi = *x as f64;
                let env = self.env.step(c, xi, Level::Peak, ca, cr);
                let gain = if env < threshold { 1.0 } else { (env * threshold_inv).powf(ratio_inv - 1.0) };
                *x = (gain * xi) as f32;
            }
        }
    }
}

pub struct NoiseGate {
    pub threshold_db: f64,
    pub ratio: f64,
    pub attack_ms: f64,
    pub release_ms: f64,
    rms: Ballistics,
    env: Ballistics,
}

impl NoiseGate {
    pub fn new(threshold_db: f64, ratio: f64, attack_ms: f64, release_ms: f64) -> Self {
        NoiseGate { threshold_db, ratio, attack_ms, release_ms, rms: Ballistics::new(), env: Ballistics::new() }
    }
}

impl Effect for NoiseGate {
    fn process(&mut self, audio: &mut Stereo, sr: u32) {
        let sr = sr as f64;
        let threshold = db_to_gain(self.threshold_db.max(-200.0));
        let threshold_inv = 1.0 / threshold;
        // juce::dsp::NoiseGate: an RMS detector (instant attack, 50 ms release), then a peak ballistics stage with
        // the attack and release you set, then the gain from the ratio below the threshold
        let c_rms = cte(50.0, sr);
        let (ca, cr) = (cte(self.attack_ms, sr), cte(self.release_ms, sr));
        for c in 0..2 {
            for x in audio[c].iter_mut() {
                let xi = *x as f64;
                let level = self.rms.step(c, xi, Level::Rms, 0.0, c_rms);
                let env = self.env.step(c, level, Level::Peak, ca, cr);
                let gain = if env > threshold { 1.0 } else { (env * threshold_inv).powf(self.ratio - 1.0) };
                *x = (gain * xi) as f32;
            }
        }
    }
}

// ------------------------------------------------------------------------------------------------ Limiter
/// pedalboard's Limiter (juce::dsp::Limiter): a 4:1 compressor at -10 dB (2 ms / 200 ms), a 1000:1 compressor at the
/// threshold (instant attack, your release), then a make-up gain, then a hard clip at full scale. The gain is applied
/// AFTER the second compressor, which is why this limiter does not hold its threshold (see PeakLimiter in dsp.py).
pub struct Limiter {
    pub threshold_db: f64,
    pub release_ms: f64,
    first: Compressor,
    second: Compressor,
    gain: Option<f64>,   // the make-up gain reached so far (it glides to a new value over 1 ms)
}

impl Limiter {
    pub fn new(threshold_db: f64, release_ms: f64) -> Self {
        Limiter {
            threshold_db,
            release_ms,
            first: Compressor::new(-10.0, 4.0, 2.0, 200.0),
            second: Compressor::new(threshold_db, 1000.0, 0.001, release_ms),
            gain: None,
        }
    }
}

impl Effect for Limiter {
    fn process(&mut self, audio: &mut Stereo, sr: u32) {
        self.second.threshold_db = self.threshold_db;
        self.second.release_ms = self.release_ms;
        self.first.process(audio, sr);
        self.second.process(audio, sr);
        let target = 10f64.powf(10.0 * (1.0 - 0.25) / 40.0) * db_to_gain(-self.threshold_db.max(-100.0));
        let mut g = self.gain.unwrap_or(target);
        let step = (target - g) / (sr as f64 * 0.001).max(1.0);
        let frames = audio[0].len();
        for i in 0..frames {
            if (target - g).abs() > step.abs() {
                g += step;
            } else {
                g = target;
            }
            for c in 0..2 {
                audio[c][i] = ((audio[c][i] as f64 * g) as f32).clamp(-1.0, 1.0);
            }
        }
        self.gain = Some(g);
    }
}
