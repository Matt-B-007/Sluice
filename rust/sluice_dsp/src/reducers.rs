// SPDX-License-Identifier: GPL-3.0-or-later
//! The noise and echo reducers' gain rules: line for line the same as `NoiseReducer.gain` and `EchoReducer.gain`
//! in `sluice/spectral.py`, so the two can be compared sample by sample.

use crate::stft::{HOP, K};

const VOICE_LO: usize = 2;
const VOICE_HI: usize = 170;

fn db(g: &[f64]) -> f64 {
    let sum: f64 = g[VOICE_LO..VOICE_HI]
        .iter()
        .map(|&x| x.max(1e-4).log10())
        .sum();
    20.0 * sum / (VOICE_HI - VOICE_LO) as f64
}

/// Average each frequency with its neighbours; the first and last repeat themselves. Writes into `out`.
fn smooth(g: &[f64], out: &mut [f64]) {
    let n = g.len();
    for i in 0..n {
        let a = g[if i == 0 { 0 } else { i - 1 }];
        let c = g[if i + 1 == n { n - 1 } else { i + 1 }];
        out[i] = 0.25 * a + 0.5 * g[i] + 0.25 * c;
    }
}

// Every buffer below is made once, when the reducer is built or reset, so the audio thread allocates nothing.
pub struct NoiseState {
    pub reduction_db: f64,
    pub activity_db: f64,
    profile: Option<Vec<f64>>,
    noise: Vec<f64>,
    noise_ready: bool,
    ps: Vec<f64>,
    ps_ready: bool,
    slices: Vec<Vec<f64>>,
    slice_min: Vec<f64>,
    at: usize,
    slice_frames: usize,
    speech: Vec<f64>,
    prev_gain: Vec<f64>,
    prev_snr_post: Vec<f64>, // kept across reset(), as in the Python version
    prev_snr_ready: bool,
    // scratch
    power: Vec<f64>,
    quiet: Vec<f64>,
    ratio: Vec<f64>,
    g: Vec<f64>,
    g2: Vec<f64>,
}

const ALPHA_P: f64 = 0.85;
const WINDOW_FRAMES: usize = 280;
const SUBWINDOWS: usize = 8;
const SPEECH_RATIO: f64 = 4.0;
const BETA: f64 = 0.97;

impl NoiseState {
    pub fn new(reduction_db: f64) -> Self {
        let mut s = NoiseState {
            reduction_db,
            activity_db: 0.0,
            profile: None,
            noise: vec![0.0; K],
            noise_ready: false,
            ps: vec![0.0; K],
            ps_ready: false,
            slices: vec![vec![f64::INFINITY; K]; SUBWINDOWS],
            slice_min: vec![f64::INFINITY; K],
            at: 0,
            slice_frames: 0,
            speech: vec![0.0; K],
            prev_gain: vec![1.0; K],
            prev_snr_post: vec![0.0; K],
            prev_snr_ready: false,
            power: vec![0.0; K],
            quiet: vec![0.0; K],
            ratio: vec![0.0; K],
            g: vec![0.0; K],
            g2: vec![0.0; K],
        };
        s.reset();
        s
    }

    pub fn reset(&mut self) {
        self.noise_ready = false;
        self.ps_ready = false;
        for s in self.slices.iter_mut() {
            s.iter_mut().for_each(|x| *x = f64::INFINITY);
        }
        self.slice_min.iter_mut().for_each(|x| *x = f64::INFINITY);
        self.at = 0;
        self.slice_frames = 0;
        self.speech.iter_mut().for_each(|x| *x = 0.0);
        self.prev_gain.iter_mut().for_each(|x| *x = 1.0);
        if let Some(p) = &self.profile {
            self.noise.copy_from_slice(p);
            self.noise_ready = true;
        }
    }

    pub fn has_profile(&self) -> bool {
        self.profile.is_some()
    }

    pub fn set_profile(&mut self, power: Option<Vec<f64>>) {
        self.profile = power;
        match &self.profile {
            Some(p) => {
                self.noise.copy_from_slice(p);
                self.noise_ready = true;
            }
            None => self.noise_ready = false,
        }
    }

    /// Fills `out` (K values) with the gain for every frequency of this frame.
    pub fn gain(&mut self, power_in: &[f64], out: &mut [f64]) {
        let floor = 10f64.powf(-self.reduction_db.max(0.0) / 20.0);
        if floor >= 0.999 {
            out.iter_mut().for_each(|x| *x = 1.0);
            return;
        }
        for (power, input) in self.power.iter_mut().zip(&power_in[..K]) {
            *power = input + 1e-12;
        }
        if !self.ps_ready {
            self.ps.copy_from_slice(&self.power);
            self.ps_ready = true;
        }
        for k in 0..K {
            self.ps[k] = ALPHA_P * self.ps[k] + (1.0 - ALPHA_P) * self.power[k];
            if self.ps[k] < self.slice_min[k] {
                self.slice_min[k] = self.ps[k];
            }
        }
        self.slice_frames += 1;
        if self.slice_frames >= WINDOW_FRAMES / SUBWINDOWS {
            self.slices[self.at].copy_from_slice(&self.slice_min);
            self.at = (self.at + 1) % SUBWINDOWS;
            self.slice_min.copy_from_slice(&self.ps);
            self.slice_frames = 0;
        }
        for k in 0..K {
            let mut m = self.slice_min[k];
            for s in &self.slices {
                if s[k] < m {
                    m = s[k];
                }
            }
            self.quiet[k] = m * 1.6;
        }
        if !self.noise_ready {
            self.noise.copy_from_slice(&self.quiet);
            self.noise_ready = true;
        }
        for k in 0..K {
            let voice = if self.ps[k] / self.quiet[k].max(1e-12) > SPEECH_RATIO {
                1.0
            } else {
                0.0
            };
            self.speech[k] = 0.9 * self.speech[k] + 0.1 * voice;
            let rate = 0.92 + 0.08 * self.speech[k];
            self.noise[k] =
                rate * self.noise[k] + (1.0 - rate) * self.power[k].min(self.quiet[k] * 3.0);
            self.ratio[k] = self.power[k] / self.noise[k].max(1e-12);
        }
        for k in 0..K {
            let post = (self.ratio[k] - 1.0).max(0.0);
            let snr = if self.prev_snr_ready {
                BETA * self.prev_gain[k] * self.prev_gain[k] * self.prev_snr_post[k]
                    + (1.0 - BETA) * post
            } else {
                post
            };
            self.g[k] = snr / (1.0 + snr);
        }
        std::mem::swap(&mut self.prev_snr_post, &mut self.ratio);
        self.prev_snr_ready = true;
        smooth(&self.g, &mut self.g2);
        for x in self.g2.iter_mut() {
            *x = x.max(floor).min(1.0);
        }
        self.prev_gain.copy_from_slice(&self.g2);
        self.activity_db += 0.1 * (db(&self.g2) - self.activity_db);
        out.copy_from_slice(&self.g2);
    }

    pub fn wake(&mut self) {}
}

pub struct EchoState {
    pub reverb_time: f64,
    pub reduction_db: f64,
    pub activity_db: f64,
    ring: Vec<Vec<f64>>,
    at: usize,
    ps: Vec<f64>,
    ps_ready: bool,
    prev: Vec<f64>,
    // scratch
    power: Vec<f64>,
    late: Vec<f64>,
    g: Vec<f64>,
    g2: Vec<f64>,
}

const LATE_SECONDS: f64 = 0.05;
const ALPHA: f64 = 0.7;

impl EchoState {
    pub fn new(sample_rate: u32, reverb_time: f64, reduction_db: f64) -> Self {
        // Python's round() rounds halves to even
        let delay =
            ((LATE_SECONDS * sample_rate as f64 / HOP as f64).round_ties_even() as usize).max(1);
        EchoState {
            reverb_time,
            reduction_db,
            activity_db: 0.0,

            ring: vec![vec![0.0; K]; delay + 1],
            at: 0,
            ps: vec![0.0; K],
            ps_ready: false,
            prev: vec![1.0; K],
            power: vec![0.0; K],
            late: vec![0.0; K],
            g: vec![0.0; K],
            g2: vec![0.0; K],
        }
    }

    pub fn reset(&mut self) {
        for r in self.ring.iter_mut() {
            r.iter_mut().for_each(|x| *x = 0.0);
        }
        self.at = 0;
        self.ps_ready = false;
        self.prev.iter_mut().for_each(|x| *x = 1.0);
    }

    /// Fills `out` (K values) with the gain for every frequency of this frame.
    pub fn gain(&mut self, power_in: &[f64], out: &mut [f64]) {
        let floor = 10f64.powf(-self.reduction_db.max(0.0) / 20.0);
        for (power, input) in self.power.iter_mut().zip(&power_in[..K]) {
            *power = input + 1e-12;
        }
        if self.ps_ready {
            for k in 0..K {
                self.ps[k] = ALPHA * self.ps[k] + (1.0 - ALPHA) * self.power[k];
            }
        } else {
            self.ps.copy_from_slice(&self.power);
            self.ps_ready = true;
        }
        self.late.copy_from_slice(&self.ring[self.at]);
        self.ring[self.at].copy_from_slice(&self.ps);
        self.at = (self.at + 1) % self.ring.len();
        let decay = 10f64.powf(-6.0 * LATE_SECONDS / self.reverb_time.max(0.1));
        for k in 0..K {
            // max/min rather than clamp on purpose: a NaN (from a broken input) becomes 0, silence, instead of spreading
            #[allow(clippy::manual_clamp)]
            let g = (1.0 - decay * self.late[k] / self.power[k])
                .max(0.0)
                .min(1.0);
            self.g[k] = g.sqrt();
        }
        smooth(&self.g, &mut self.g2);
        for k in 0..K {
            let v = self.g2[k].max(floor).min(1.0);
            self.g2[k] = if v < self.prev[k] {
                0.5 * self.prev[k] + 0.5 * v
            } else {
                v
            };
        }
        self.prev.copy_from_slice(&self.g2);
        self.activity_db += 0.1 * (db(&self.g2) - self.activity_db);
        out.copy_from_slice(&self.g2);
    }

    pub fn wake(&mut self) {
        self.reset_buffers();
    }

    fn reset_buffers(&mut self) {
        for r in self.ring.iter_mut() {
            r.iter_mut().for_each(|x| *x = 0.0);
        }
        self.ps_ready = false;
        self.prev.iter_mut().for_each(|x| *x = 1.0);
    }
}
