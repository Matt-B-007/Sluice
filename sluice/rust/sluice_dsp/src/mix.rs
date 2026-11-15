// SPDX-License-Identifier: GPL-3.0-or-later
//! The per-block mixing work of `Graph.process` (sluice/dsp.py): measuring a channel, adding it into a mix with a gain
//! ramp, and finishing a mix with its gain, limiter and clip. Same results as the numpy versions, in one pass each.

/// A gain that moves in a straight line from `previous` to `target` over the block (np.linspace, both ends included).
#[inline]
pub fn ramp_value(previous: f64, target: f64, i: usize, frames: usize) -> f32 {
    if frames <= 1 || previous == target {
        return if frames <= 1 { previous as f32 } else { target as f32 };
    }
    (previous + (target - previous) * (i as f64) / ((frames - 1) as f64)) as f32
}

/// Peak over the finite samples, whether anything is non-zero, whether everything is finite.
pub fn stats(l: &[f32], r: &[f32]) -> (f32, bool, bool) {
    let (mut peak, mut nonzero, mut finite) = (0.0f32, false, true);
    for ch in [l, r] {
        for &x in ch {
            if !x.is_finite() {
                finite = false;
                continue;
            }
            let a = x.abs();
            if a > peak {
                peak = a;
            }
            if x != 0.0 {
                nonzero = true;
            }
        }
    }
    (peak, nonzero, finite)
}

pub struct PeakLimiter {
    ceiling: f64,
    decay: f64,
    reduction: f64, // gain reduction (a ratio >= 1) at the end of the previous block
}

impl PeakLimiter {
    pub fn new(sample_rate: u32, ceiling_db: f64, release_ms: f64) -> Self {
        PeakLimiter {
            ceiling: 10f64.powf(ceiling_db / 20.0),
            decay: (-1.0 / (sample_rate as f64 * release_ms / 1000.0)).exp(),
            reduction: 1.0,
        }
    }

    pub fn ceiling(&self) -> f64 {
        self.ceiling
    }

    /// Instant attack, exponential release: the output never exceeds the ceiling.
    pub fn process(&mut self, l: &mut [f32], r: &mut [f32]) {
        let mut red = self.reduction;
        for i in 0..l.len() {
            let need = ((l[i].abs().max(r[i].abs()) as f64) / self.ceiling).max(1.0);
            red = (red * self.decay).max(need).max(1.0);
            let g = red as f32;
            l[i] /= g;
            r[i] /= g;
        }
        self.reduction = red;
    }
}
