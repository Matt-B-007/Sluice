// SPDX-License-Identifier: GPL-3.0-or-later
//! The heavy numbers of the room, echo and voice measurements (sluice/room.py): the same arithmetic as the numpy
//! versions. The wording and the decisions stay in Python.
use rustfft::num_complex::Complex64;
use rustfft::FftPlanner;
use std::f64::consts::PI;

/// Loudest absolute sample (both channels) of every `size` samples, as dB (20·log10, floor 1e-9). Whole blocks only.
pub fn block_peaks_db(l: &[f32], r: &[f32], size: usize) -> Vec<f64> {
    let size = size.max(1);
    let blocks = l.len() / size;
    (0..blocks)
        .map(|b| {
            let mut peak = 0.0f32;
            for i in b * size..(b + 1) * size {
                peak = peak.max(l[i].abs()).max(r[i].abs());
            }
            20.0 * (peak.max(1e-9f32) as f64).log10()
        })
        .collect()
}

/// Mean power over both channels of every `size` samples (whole blocks only).
pub fn block_power(l: &[f32], r: &[f32], size: usize) -> Vec<f64> {
    let size = size.max(1);
    let blocks = l.len() / size;
    (0..blocks)
        .map(|b| {
            let mut sum = 0.0f64;
            for i in b * size..(b + 1) * size {
                sum += (l[i] as f64).powi(2) + (r[i] as f64).powi(2);
            }
            sum / (2 * size) as f64
        })
        .collect()
}

/// Mean power of every frequency (n/2+1 of them) over the n-sample frames starting every `hop` samples: sqrt-Hann
/// window, both channels averaged before the power is taken (as the noise reducer measures it).
pub fn noise_profile(l: &[f32], r: &[f32], n: usize, hop: usize) -> Vec<f64> {
    let bins = n / 2 + 1;
    let window: Vec<f32> = (0..n)
        .map(|i| (0.5 - 0.5 * (2.0 * PI * i as f64 / n as f64).cos()).sqrt() as f32)
        .collect();
    let mut planner = FftPlanner::<f64>::new();
    let fft = planner.plan_fft_forward(n);
    let mut total = vec![0.0f64; bins];
    let mut count = 0usize;
    let mut buf = vec![Complex64::new(0.0, 0.0); n];
    let mut mixed = vec![Complex64::new(0.0, 0.0); n];
    let mut start = 0usize;
    while start + n <= l.len() {
        for (ch, out) in [(l, &mut buf), (r, &mut mixed)] {
            for i in 0..n {
                // the product is rounded to f32 as numpy does for a float32 frame times a float32 window
                out[i] = Complex64::new((ch[start + i] * window[i]) as f64, 0.0);
            }
        }
        fft.process(&mut buf);
        fft.process(&mut mixed);
        for k in 0..bins {
            let m = (buf[k] + mixed[k]) * 0.5;
            total[k] += m.re * m.re + m.im * m.im;
        }
        count += 1;
        start += hop;
    }
    let c = count.max(1) as f64;
    total.iter().map(|v| v / c).collect()
}

/// The echo measurement's first half: the mean of both channels with everything under 100 Hz removed (a ramp up to
/// 200 Hz), then the power of every `block` samples (+1e-18). Same as the numpy code in `analyse_echo`.
pub fn echo_energy(l: &[f64], r: &[f64], sample_rate: f64, block: usize) -> Vec<f64> {
    let n = l.len();
    let mut data: Vec<Complex64> = (0..n)
        .map(|i| Complex64::new((l[i] + r[i]) / 2.0, 0.0))
        .collect();
    let mut planner = FftPlanner::<f64>::new();
    let fwd = planner.plan_fft_forward(n);
    let inv = planner.plan_fft_inverse(n);
    fwd.process(&mut data);
    // rfft keeps bins 0..=n/2; the mirror half is rebuilt from them, so scale both halves the same way
    for (k, bin) in data.iter_mut().enumerate().take(n) {
        let kk = if k <= n / 2 { k } else { n - k };
        let f = kk as f64 * sample_rate / n as f64;
        *bin *= ((f - 100.0) / 100.0).clamp(0.0, 1.0);
    }
    inv.process(&mut data);
    let scale = 1.0 / n as f64;
    let block = block.max(1);
    let blocks = n / block;
    (0..blocks)
        .map(|b| {
            let mut s = 0.0;
            for value in &data[b * block..(b + 1) * block] {
                let v = value.re * scale;
                s += v * v;
            }
            s / block as f64 + 1e-18
        })
        .collect()
}
