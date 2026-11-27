// SPDX-License-Identifier: GPL-3.0-or-later
//! Overlap-add framework shared by the reducers: the same algorithm as `StftEffect` in `sluice/spectral.py`.

use numpy::ndarray::{ArrayView2, ArrayViewMut2};
use realfft::num_complex::Complex32;
use realfft::{ComplexToReal, RealFftPlanner, RealToComplex};
use std::collections::VecDeque;
use std::sync::Arc;

pub const N: usize = 1024;
pub const HOP: usize = 256;
pub const K: usize = N / 2 + 1;

pub struct Stft {
    window: Vec<f32>,
    frame: [Vec<f32>; 2],
    ola: [Vec<f32>; 2],
    inb: [VecDeque<f32>; 2],
    outb: [VecDeque<f32>; 2],
    fwd: Arc<dyn RealToComplex<f32>>,
    inv: Arc<dyn ComplexToReal<f32>>,
    spec: [Vec<Complex32>; 2],
    buf: Vec<f32>,
    // Everything the audio thread needs is made here, once: after the first blocks nothing is allocated.
    scratch_fwd: Vec<Complex32>,
    scratch_inv: Vec<Complex32>,
    hop_in: [Vec<f32>; 2],
    power: Vec<f64>,
    gains: Vec<f64>,
    pub sample_rate: u32,
}

const QUEUE: usize = 8192; // room for the longest audio block seen in practice plus a hop: the queues never grow

impl Stft {
    pub fn new(sample_rate: u32) -> Self {
        let mut planner = RealFftPlanner::<f32>::new();
        let fwd = planner.plan_fft_forward(N);
        let inv = planner.plan_fft_inverse(N);
        // sqrt of the periodic Hann window, like np.sqrt(np.hanning(N + 1)[:-1])
        let window = (0..N)
            .map(|k| {
                let h = 0.5 - 0.5 * (2.0 * std::f64::consts::PI * k as f64 / N as f64).cos();
                h.sqrt() as f32
            })
            .collect();
        Stft {
            window,
            frame: [vec![0.0; N], vec![0.0; N]],
            ola: [vec![0.0; N], vec![0.0; N]],
            inb: [
                VecDeque::with_capacity(QUEUE),
                VecDeque::with_capacity(QUEUE),
            ],
            outb: [
                VecDeque::with_capacity(QUEUE),
                VecDeque::with_capacity(QUEUE),
            ],
            scratch_fwd: fwd.make_scratch_vec(),
            scratch_inv: inv.make_scratch_vec(),
            hop_in: [vec![0.0; HOP], vec![0.0; HOP]],
            power: vec![0.0; K],
            gains: vec![1.0; K],
            fwd,
            inv,
            spec: [
                vec![Complex32::new(0.0, 0.0); K],
                vec![Complex32::new(0.0, 0.0); K],
            ],
            buf: vec![0.0; N],
            sample_rate,
        }
    }

    pub fn reset(&mut self) {
        for c in 0..2 {
            self.frame[c].iter_mut().for_each(|x| *x = 0.0);
            self.ola[c].iter_mut().for_each(|x| *x = 0.0);
            self.inb[c].clear();
            self.outb[c].clear();
        }
    }

    /// Sound returned after the channel was skipped for silence: forget the half-processed audio.
    pub fn wake(&mut self) {
        self.reset();
    }

    /// `input` and `output` are (2, frames). `gain` gets the mixed power spectrum of one frame and fills in the gain for
    /// every bin. The output has the same length (the first blocks are delayed by up to 16 ms of silence).
    pub fn process<F: FnMut(&[f64], &mut [f64])>(
        &mut self,
        input: ArrayView2<f32>,
        mut output: ArrayViewMut2<f32>,
        mut gain: F,
    ) {
        let frames = input.shape()[1];
        for c in 0..2 {
            self.inb[c].extend(input.row(c).iter().copied());
        }
        while self.inb[0].len() >= HOP {
            for c in 0..2 {
                for (i, v) in self.inb[c].drain(..HOP).enumerate() {
                    self.hop_in[c][i] = v;
                }
            }
            self.hop(&mut gain);
        }
        if self.outb[0].len() < frames {
            let missing = frames - self.outb[0].len();
            for c in 0..2 {
                for _ in 0..missing {
                    self.outb[c].push_front(0.0);
                }
            }
        }
        for c in 0..2 {
            for (i, v) in self.outb[c].drain(..frames).enumerate() {
                output[[c, i]] = v;
            }
        }
    }

    fn hop<F: FnMut(&[f64], &mut [f64])>(&mut self, gain: &mut F) {
        for c in 0..2 {
            self.frame[c].copy_within(HOP.., 0);
            self.frame[c][N - HOP..].copy_from_slice(&self.hop_in[c]);
            for i in 0..N {
                self.buf[i] = self.frame[c][i] * self.window[i];
            }
            self.fwd
                .process_with_scratch(&mut self.buf, &mut self.spec[c], &mut self.scratch_fwd)
                .unwrap();
        }
        for k in 0..K {
            let re = 0.5 * (self.spec[0][k].re + self.spec[1][k].re);
            let im = 0.5 * (self.spec[0][k].im + self.spec[1][k].im);
            self.power[k] = (re * re + im * im) as f64;
        }
        gain(&self.power, &mut self.gains);
        for c in 0..2 {
            for k in 0..K {
                self.spec[c][k] *= self.gains[k] as f32;
            }
            // the DC and Nyquist bins of a real signal are real
            self.spec[c][0].im = 0.0;
            self.spec[c][K - 1].im = 0.0;
            self.inv
                .process_with_scratch(&mut self.spec[c], &mut self.buf, &mut self.scratch_inv)
                .unwrap();
            for i in 0..N {
                // realfft's inverse is unnormalised: divide by N (numpy's irfft does), then window, then the overlap scale 1/2
                self.ola[c][i] += (self.buf[i] / N as f32) * self.window[i] * 0.5;
            }
            self.outb[c].extend(self.ola[c][..HOP].iter().copied());
            self.ola[c].copy_within(HOP.., 0);
            self.ola[c][N - HOP..].iter_mut().for_each(|x| *x = 0.0);
        }
    }
}
