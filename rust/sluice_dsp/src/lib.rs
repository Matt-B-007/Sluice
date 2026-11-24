// SPDX-License-Identifier: GPL-3.0-or-later
//! Sluice's audio engine pieces in Rust. Python (`sluice/spectral.py`) uses these when the module is installed and
//! keeps its own numpy versions as the fallback, so every class here has the same methods as its Python twin.

mod jack_io;
mod mix;
mod room;
mod native;
mod reducers;
mod stft;

use numpy::{PyArray1, PyArray2, PyArrayMethods, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use native::{Effect, Shape, Stereo};
use reducers::{EchoState, NoiseState};
use stft::{Stft, K};

fn run<F: FnMut(&[f64], &mut [f64])>(
    py: Python<'_>,
    stft: &mut Stft,
    audio: &PyReadonlyArray2<f32>,
    gain: F,
) -> PyResult<Py<PyArray2<f32>>> {
    let shape = audio.shape();
    if shape[0] != 2 {
        return Err(PyValueError::new_err("audio must have shape (2, frames)"));
    }
    let arr = PyArray2::<f32>::zeros(py, [2, shape[1]], false);
    {
        let out = unsafe { arr.as_array_mut() };
        stft.process(audio.as_array(), out, gain);
    }
    Ok(arr.unbind())
}

#[pyclass]
struct NoiseReducer {
    stft: Stft,
    st: NoiseState,
}

#[pymethods]
impl NoiseReducer {
    #[new]
    #[pyo3(signature = (sample_rate, reduction_db = 12.0))]
    fn new(sample_rate: u32, reduction_db: f64) -> Self {
        NoiseReducer { stft: Stft::new(sample_rate), st: NoiseState::new(reduction_db) }
    }
    #[getter]
    fn reduction_db(&self) -> f64 {
        self.st.reduction_db
    }
    #[setter]
    fn set_reduction_db(&mut self, v: f64) {
        self.st.reduction_db = v;
    }
    #[getter]
    fn activity_db(&self) -> f64 {
        self.st.activity_db
    }
    #[getter]
    fn has_profile(&self) -> bool {
        self.st.has_profile()
    }
    #[getter]
    fn sample_rate(&self) -> u32 {
        self.stft.sample_rate
    }
    #[getter]
    fn latency(&self) -> usize {
        stft::N - stft::HOP
    }
    fn reset(&mut self) {
        self.stft.reset();
        self.st.reset();
    }
    fn wake(&mut self) {
        self.stft.wake();
        self.st.wake();
    }
    #[pyo3(signature = (power))]
    fn set_profile(&mut self, power: Option<Vec<f64>>) -> PyResult<()> {
        if let Some(p) = &power {
            if p.len() != K {
                return Err(PyValueError::new_err(format!("the noise profile needs {K} values")));
            }
        }
        self.st.set_profile(power);
        Ok(())
    }
    fn process(&mut self, py: Python<'_>, audio: PyReadonlyArray2<f32>) -> PyResult<Py<PyArray2<f32>>> {
        let st = &mut self.st;
        run(py, &mut self.stft, &audio, |p, out| st.gain(p, out))
    }
}

#[pyclass]
struct EchoReducer {
    stft: Stft,
    st: EchoState,
}

#[pymethods]
impl EchoReducer {
    #[new]
    #[pyo3(signature = (sample_rate, reverb_time = 0.6, reduction_db = 9.0))]
    fn new(sample_rate: u32, reverb_time: f64, reduction_db: f64) -> Self {
        EchoReducer { stft: Stft::new(sample_rate), st: EchoState::new(sample_rate, reverb_time, reduction_db) }
    }
    #[getter]
    fn reverb_time(&self) -> f64 {
        self.st.reverb_time
    }
    #[setter]
    fn set_reverb_time(&mut self, v: f64) {
        self.st.reverb_time = v;
    }
    #[getter]
    fn reduction_db(&self) -> f64 {
        self.st.reduction_db
    }
    #[setter]
    fn set_reduction_db(&mut self, v: f64) {
        self.st.reduction_db = v;
    }
    #[getter]
    fn activity_db(&self) -> f64 {
        self.st.activity_db
    }
    #[getter]
    fn sample_rate(&self) -> u32 {
        self.stft.sample_rate
    }
    #[getter]
    fn latency(&self) -> usize {
        stft::N - stft::HOP
    }
    fn reset(&mut self) {
        self.stft.reset();
        self.st.reset();
    }
    fn wake(&mut self) {
        self.stft.wake();
        self.st.wake();
    }
    fn process(&mut self, py: Python<'_>, audio: PyReadonlyArray2<f32>) -> PyResult<Py<PyArray2<f32>>> {
        let st = &mut self.st;
        run(py, &mut self.stft, &audio, |p, out| st.gain(p, out))
    }
}

/// Echo and noise reduction in ONE pass: the parts' gains are multiplied (see `Joint` in spectral.py).
#[pyclass]
struct Joint {
    stft: Stft,
    parts: Vec<Py<PyAny>>,
    gain: Vec<f64>,
    part_gain: Vec<f64>,
}

const MAX_PARTS: usize = 4;

enum Part<'a, 'py> {
    Noise(PyRefMut<'py, NoiseReducer>, std::marker::PhantomData<&'a ()>),
    Echo(PyRefMut<'py, EchoReducer>, std::marker::PhantomData<&'a ()>),
}

#[pymethods]
impl Joint {
    #[new]
    fn new(py: Python<'_>, parts: Vec<Py<PyAny>>) -> PyResult<Self> {
        if parts.is_empty() {
            return Err(PyValueError::new_err("Joint needs at least one reducer"));
        }
        let mut rate = 0;
        for (i, p) in parts.iter().enumerate() {
            let b = p.bind(py);
            let r = if let Ok(n) = b.extract::<PyRef<NoiseReducer>>() {
                n.stft.sample_rate
            } else if let Ok(e) = b.extract::<PyRef<EchoReducer>>() {
                e.stft.sample_rate
            } else {
                return Err(PyValueError::new_err("Joint takes the Rust NoiseReducer and EchoReducer"));
            };
            if i == 0 {
                rate = r;
            }
        }
        if parts.len() > MAX_PARTS {
            return Err(PyValueError::new_err("Joint takes at most four reducers"));
        }
        Ok(Joint { stft: Stft::new(rate), parts, gain: vec![1.0; K], part_gain: vec![1.0; K] })
    }
    #[getter]
    fn sample_rate(&self) -> u32 {
        self.stft.sample_rate
    }
    #[getter]
    fn latency(&self) -> usize {
        stft::N - stft::HOP
    }
    fn reset(&mut self) {
        self.stft.reset();
    }
    fn wake(&mut self, py: Python<'_>) {
        self.stft.wake();
        for p in &self.parts {
            let b = p.bind(py);
            if let Ok(mut n) = b.extract::<PyRefMut<NoiseReducer>>() {
                n.st.wake();
            } else if let Ok(mut e) = b.extract::<PyRefMut<EchoReducer>>() {
                e.st.wake();
            }
        }
    }
    fn process(&mut self, py: Python<'_>, audio: PyReadonlyArray2<f32>) -> PyResult<Py<PyArray2<f32>>> {
        let mut parts: [Option<Part>; MAX_PARTS] = [None, None, None, None];
        for (slot, p) in parts.iter_mut().zip(self.parts.iter()) {
            let b = p.bind(py);
            if let Ok(n) = b.extract::<PyRefMut<NoiseReducer>>() {
                *slot = Some(Part::Noise(n, Default::default()));
            } else if let Ok(e) = b.extract::<PyRefMut<EchoReducer>>() {
                *slot = Some(Part::Echo(e, Default::default()));
            }
        }
        let Joint { stft, gain, part_gain, .. } = self;
        run(py, stft, &audio, |power, out| {
            let mut first = true;
            for part in parts.iter_mut().flatten() {
                let target: &mut [f64] = if first { &mut gain[..] } else { &mut part_gain[..] };
                match part {
                    Part::Noise(n, _) => n.st.gain(power, target),
                    Part::Echo(e, _) => e.st.gain(power, target),
                }
                if !first {
                    for k in 0..K {
                        gain[k] *= part_gain[k];
                    }
                }
                first = false;
            }
            out.copy_from_slice(&gain[..]);
        })
    }
}


// ---------------------------------------------------------------------------------------------- built-in effects
fn to_stereo(audio: &PyReadonlyArray2<f32>) -> PyResult<Stereo> {
    if audio.shape()[0] != 2 {
        return Err(PyValueError::new_err("audio must have shape (2, frames)"));
    }
    let view = audio.as_array();
    Ok([view.row(0).iter().copied().collect(), view.row(1).iter().copied().collect()])
}

fn from_stereo(py: Python<'_>, audio: &Stereo) -> Py<PyArray2<f32>> {
    let frames = audio[0].len();
    let arr = PyArray2::<f32>::zeros(py, [2, frames], false);
    {
        let mut w = unsafe { arr.as_array_mut() };
        for c in 0..2 {
            for (i, v) in audio[c].iter().enumerate() {
                w[[c, i]] = *v;
            }
        }
    }
    arr.unbind()
}

/// Defines a Python class with settable attributes (named like pedalboard's) around one effect.
macro_rules! effect_class {
    ($py_name:literal, $cls:ident, $ty:ty, ($($arg:ident),*), $ctor:expr, [$(($attr:ident, $set:ident, $field:ident)),*]) => {
        #[pyclass(name = $py_name)]
        struct $cls {
            fx: $ty,
        }

        #[pymethods]
        impl $cls {
            #[new]
            #[pyo3(signature = ($($arg),*))]
            fn new($($arg: f64),*) -> Self {
                $cls { fx: $ctor }
            }
            #[classattr]
            #[allow(non_snake_case)]
            fn IS_NATIVE() -> bool {
                true
            }
            $(
                #[getter]
                fn $attr(&self) -> f64 {
                    self.fx.$field
                }
                #[setter]
                fn $set(&mut self, v: f64) {
                    self.fx.$field = v;
                }
            )*
            #[pyo3(signature = (audio, sample_rate))]
            fn process(&mut self, py: Python<'_>, audio: PyReadonlyArray2<f32>, sample_rate: u32) -> PyResult<Py<PyArray2<f32>>> {
                let mut buf = to_stereo(&audio)?;
                self.fx.process(&mut buf, sample_rate);
                Ok(from_stereo(py, &buf))
            }
        }
    };
}

effect_class!("Gain", GainFx, native::Gain, (gain_db), native::Gain { gain_db }, [(gain_db, set_gain_db, gain_db)]);
effect_class!("HighpassFilter", HighpassFx, native::HighPass, (cutoff_frequency_hz), native::HighPass::new(cutoff_frequency_hz),
    [(cutoff_frequency_hz, set_cutoff_frequency_hz, cutoff_hz)]);
effect_class!("ButterworthHighPass", ButterHighPassFx, native::Biquad, (cutoff_frequency_hz),
    native::Biquad::new(Shape::HighPass, cutoff_frequency_hz, 0.0, std::f64::consts::FRAC_1_SQRT_2),
    [(cutoff_frequency_hz, set_cutoff_frequency_hz, freq)]);
effect_class!("LowShelfFilter", LowShelfFx, native::Biquad, (cutoff_frequency_hz, gain_db, q),
    native::Biquad::new(Shape::LowShelf, cutoff_frequency_hz, gain_db, q),
    [(cutoff_frequency_hz, set_cutoff_frequency_hz, freq), (gain_db, set_gain_db, gain_db), (q, set_q, q)]);
effect_class!("HighShelfFilter", HighShelfFx, native::Biquad, (cutoff_frequency_hz, gain_db, q),
    native::Biquad::new(Shape::HighShelf, cutoff_frequency_hz, gain_db, q),
    [(cutoff_frequency_hz, set_cutoff_frequency_hz, freq), (gain_db, set_gain_db, gain_db), (q, set_q, q)]);
effect_class!("PeakFilter", PeakFx, native::Biquad, (cutoff_frequency_hz, gain_db, q),
    native::Biquad::new(Shape::Peak, cutoff_frequency_hz, gain_db, q),
    [(cutoff_frequency_hz, set_cutoff_frequency_hz, freq), (gain_db, set_gain_db, gain_db), (q, set_q, q)]);
effect_class!("Compressor", CompressorFx, native::Compressor, (threshold_db, ratio, attack_ms, release_ms),
    native::Compressor::new(threshold_db, ratio, attack_ms, release_ms),
    [(threshold_db, set_threshold_db, threshold_db), (ratio, set_ratio, ratio), (attack_ms, set_attack_ms, attack_ms),
     (release_ms, set_release_ms, release_ms)]);
effect_class!("Limiter", LimiterFx, native::Limiter, (threshold_db, release_ms),
    native::Limiter::new(threshold_db, release_ms),
    [(threshold_db, set_threshold_db, threshold_db), (release_ms, set_release_ms, release_ms)]);
effect_class!("NoiseGate", NoiseGateFx, native::NoiseGate, (threshold_db, ratio, attack_ms, release_ms),
    native::NoiseGate::new(threshold_db, ratio, attack_ms, release_ms),
    [(threshold_db, set_threshold_db, threshold_db), (ratio, set_ratio, ratio), (attack_ms, set_attack_ms, attack_ms),
     (release_ms, set_release_ms, release_ms)]);

/// Runs a list of the effects above, in order, in one call (one trip across the Python/Rust border for the group).
#[pyclass]
struct Run {
    plugins: Vec<Py<PyAny>>,
}

#[pymethods]
impl Run {
    #[new]
    fn new(py: Python<'_>, plugins: Vec<Py<PyAny>>) -> PyResult<Self> {
        for p in &plugins {
            let b = p.bind(py);
            let ok = b.extract::<PyRef<GainFx>>().is_ok()
                || b.extract::<PyRef<HighpassFx>>().is_ok()
                || b.extract::<PyRef<ButterHighPassFx>>().is_ok()
                || b.extract::<PyRef<LowShelfFx>>().is_ok()
                || b.extract::<PyRef<HighShelfFx>>().is_ok()
                || b.extract::<PyRef<PeakFx>>().is_ok()
                || b.extract::<PyRef<CompressorFx>>().is_ok()
                || b.extract::<PyRef<NoiseGateFx>>().is_ok()
                || b.extract::<PyRef<LimiterFx>>().is_ok();
            if !ok {
                return Err(PyValueError::new_err("Run takes only sluice_dsp effects"));
            }
        }
        Ok(Run { plugins })
    }
    #[pyo3(signature = (audio, sample_rate))]
    fn process(&mut self, py: Python<'_>, audio: PyReadonlyArray2<f32>, sample_rate: u32) -> PyResult<Py<PyArray2<f32>>> {
        let mut buf = to_stereo(&audio)?;
        for p in &self.plugins {
            let b = p.bind(py);
            macro_rules! try_run {
                ($($t:ty),*) => {$(
                    if let Ok(mut fx) = b.extract::<PyRefMut<$t>>() {
                        fx.fx.process(&mut buf, sample_rate);
                        continue;
                    }
                )*};
            }
            try_run!(GainFx, HighpassFx, ButterHighPassFx, LowShelfFx, HighShelfFx, PeakFx, CompressorFx, NoiseGateFx, LimiterFx);
        }
        Ok(from_stereo(py, &buf))
    }
}

// -------------------------------------------------------------------------------------------------- mixing kernels
#[pyclass]
struct PeakLimiter {
    inner: mix::PeakLimiter,
}

#[pymethods]
impl PeakLimiter {
    #[new]
    #[pyo3(signature = (sample_rate, ceiling_db = -1.0, release_ms = 100.0))]
    fn new(sample_rate: u32, ceiling_db: f64, release_ms: f64) -> Self {
        PeakLimiter { inner: mix::PeakLimiter::new(sample_rate, ceiling_db, release_ms) }
    }
    #[getter]
    fn ceiling(&self) -> f64 {
        self.inner.ceiling()
    }
    fn process(&mut self, py: Python<'_>, audio: PyReadonlyArray2<f32>) -> PyResult<Py<PyArray2<f32>>> {
        let mut buf = to_stereo(&audio)?;
        let [l, r] = &mut buf;
        self.inner.process(l, r);
        Ok(from_stereo(py, &buf))
    }
}

/// (peak over the finite samples, any non-zero sample, all samples finite) of a (2, frames) block.
#[pyfunction]
fn block_stats(audio: PyReadonlyArray2<f32>) -> PyResult<(f32, bool, bool)> {
    let buf = to_stereo(&audio)?;
    Ok(mix::stats(&buf[0], &buf[1]))
}

/// ``out += audio * gain`` where the gain glides from ``previous`` to ``target`` over the block. Changes ``out`` in place.
#[pyfunction]
fn accumulate(out: &Bound<'_, PyArray2<f32>>, audio: PyReadonlyArray2<f32>, previous: f64, target: f64) -> PyResult<()> {
    let a = audio.as_array();
    let mut o = unsafe { out.as_array_mut() };
    if a.shape() != o.shape() {
        return Err(PyValueError::new_err("out and audio must have the same shape"));
    }
    let frames = a.shape()[1];
    for c in 0..2 {
        for i in 0..frames {
            o[[c, i]] += a[[c, i]] * mix::ramp_value(previous, target, i, frames);
        }
    }
    Ok(())
}

/// A mix's last step: its fader (gliding from ``applied`` to ``gain``), the limiter if there is one, a safety clip.
/// Changes ``out`` in place and returns the block's peak.
#[pyfunction]
#[pyo3(signature = (out, applied, gain, limiter=None))]
fn finish_mix(out: &Bound<'_, PyArray2<f32>>, applied: f64, gain: f64, limiter: Option<Py<PeakLimiter>>) -> PyResult<f32> {
    let py = out.py();
    let mut buf: Stereo = {
        let o = unsafe { out.as_array() };
        if o.shape()[0] != 2 {
            return Err(PyValueError::new_err("out must have shape (2, frames)"));
        }
        let frames = o.shape()[1];
        let mut l = Vec::with_capacity(frames);
        let mut r = Vec::with_capacity(frames);
        for i in 0..frames {
            let g = mix::ramp_value(applied, gain, i, frames);
            l.push(o[[0, i]] * g);
            r.push(o[[1, i]] * g);
        }
        [l, r]
    };
    if let Some(lim) = limiter {
        let mut lim = lim.bind(py).borrow_mut();
        let [l, r] = &mut buf;
        lim.inner.process(l, r);
        for ch in buf.iter_mut() {
            for x in ch.iter_mut() {
                *x = x.clamp(-1.0, 1.0); // the clip is only a safety net
            }
        }
    }
    let peak = buf.iter().flat_map(|ch| ch.iter()).fold(0.0f32, |m, &x| if x.abs() > m { x.abs() } else { m });
    let mut o = unsafe { out.as_array_mut() };
    for c in 0..2 {
        for (i, v) in buf[c].iter().enumerate() {
            o[[c, i]] = *v;
        }
    }
    Ok(peak)
}

// ------------------------------------------------------------------------------------------ room measurements
#[pyfunction]
fn block_peaks_db(py: Python<'_>, audio: PyReadonlyArray2<f32>, size: usize) -> PyResult<Py<PyArray1<f64>>> {
    let b = to_stereo(&audio)?;
    Ok(PyArray1::from_vec(py, room::block_peaks_db(&b[0], &b[1], size)).unbind())
}

#[pyfunction]
fn block_power(py: Python<'_>, audio: PyReadonlyArray2<f32>, size: usize) -> PyResult<Py<PyArray1<f64>>> {
    let b = to_stereo(&audio)?;
    Ok(PyArray1::from_vec(py, room::block_power(&b[0], &b[1], size)).unbind())
}

#[pyfunction]
fn noise_profile(py: Python<'_>, audio: PyReadonlyArray2<f32>, n: usize, hop: usize) -> PyResult<Py<PyArray1<f64>>> {
    let b = to_stereo(&audio)?;
    Ok(PyArray1::from_vec(py, room::noise_profile(&b[0], &b[1], n, hop.max(1))).unbind())
}

#[pyfunction]
fn echo_energy(py: Python<'_>, audio: PyReadonlyArray2<f64>, sample_rate: f64, block: usize) -> PyResult<Py<PyArray1<f64>>> {
    if audio.shape()[0] != 2 {
        return Err(PyValueError::new_err("audio must have shape (2, frames)"));
    }
    let v = audio.as_array();
    let l: Vec<f64> = v.row(0).iter().copied().collect();
    let r: Vec<f64> = v.row(1).iter().copied().collect();
    Ok(PyArray1::from_vec(py, room::echo_energy(&l, &r, sample_rate, block)).unbind())
}

#[pymodule]
fn sluice_dsp(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<NoiseReducer>()?;
    m.add_class::<EchoReducer>()?;
    m.add_class::<Joint>()?;
    m.add_class::<GainFx>()?;
    m.add_class::<HighpassFx>()?;
    m.add_class::<LowShelfFx>()?;
    m.add_class::<HighShelfFx>()?;
    m.add_class::<PeakFx>()?;
    m.add_class::<ButterHighPassFx>()?;
    m.add_class::<CompressorFx>()?;
    m.add_class::<NoiseGateFx>()?;
    m.add_class::<LimiterFx>()?;
    m.add_class::<Run>()?;
    m.add_class::<PeakLimiter>()?;
    m.add_class::<jack_io::JackEngine>()?;
    m.add_function(wrap_pyfunction!(block_stats, m)?)?;
    m.add_function(wrap_pyfunction!(block_peaks_db, m)?)?;
    m.add_function(wrap_pyfunction!(block_power, m)?)?;
    m.add_function(wrap_pyfunction!(noise_profile, m)?)?;
    m.add_function(wrap_pyfunction!(echo_energy, m)?)?;
    m.add_function(wrap_pyfunction!(accumulate, m)?)?;
    m.add_function(wrap_pyfunction!(finish_mix, m)?)?;
    m.add("VERSION", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
