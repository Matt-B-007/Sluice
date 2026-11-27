// SPDX-License-Identifier: GPL-3.0-or-later
//! Sluice's audio engine pieces in Rust. Python (`sluice/spectral.py`) uses these when the module is installed and
//! keeps its own numpy versions as the fallback, so every class here has the same methods as its Python twin.

mod graph;
mod jack_io;
mod mix;
mod native;
mod reducers;
mod room;
mod stft;
mod voice;

use graph::{GraphCore, Proc};
use native::{Effect, Shape, Stereo};
use numpy::{PyArray1, PyArray2, PyArrayMethods, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use reducers::{EchoState, NoiseState};
use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard};
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

/// 0.13.1: a lock that a panic elsewhere cannot poison for good (the audio must go on).
fn locked<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

pub struct NoiseCore {
    stft: Stft,
    st: NoiseState,
}

pub struct EchoCore {
    stft: Stft,
    st: EchoState,
}

#[pyclass]
struct NoiseReducer {
    core: Arc<Mutex<NoiseCore>>,
}

#[pymethods]
impl NoiseReducer {
    #[new]
    #[pyo3(signature = (sample_rate, reduction_db = 12.0))]
    fn new(sample_rate: u32, reduction_db: f64) -> Self {
        NoiseReducer {
            core: Arc::new(Mutex::new(NoiseCore {
                stft: Stft::new(sample_rate),
                st: NoiseState::new(reduction_db),
            })),
        }
    }
    #[getter]
    fn reduction_db(&self) -> f64 {
        locked(&self.core).st.reduction_db
    }
    #[setter]
    fn set_reduction_db(&self, v: f64) {
        locked(&self.core).st.reduction_db = v;
    }
    #[getter]
    fn activity_db(&self) -> f64 {
        locked(&self.core).st.activity_db
    }
    #[getter]
    fn has_profile(&self) -> bool {
        locked(&self.core).st.has_profile()
    }
    #[getter]
    fn sample_rate(&self) -> u32 {
        locked(&self.core).stft.sample_rate
    }
    #[getter]
    fn latency(&self) -> usize {
        stft::N - stft::HOP
    }
    fn reset(&self) {
        let mut c = locked(&self.core);
        c.stft.reset();
        c.st.reset();
    }
    fn wake(&self) {
        let mut c = locked(&self.core);
        c.stft.wake();
        c.st.wake();
    }
    #[pyo3(signature = (power))]
    fn set_profile(&self, power: Option<Vec<f64>>) -> PyResult<()> {
        if let Some(p) = &power {
            if p.len() != K {
                return Err(PyValueError::new_err(format!(
                    "the noise profile needs {K} values"
                )));
            }
        }
        locked(&self.core).st.set_profile(power);
        Ok(())
    }
    fn process(&self, py: Python<'_>, audio: PyReadonlyArray2<f32>) -> PyResult<Py<PyArray2<f32>>> {
        let mut c = locked(&self.core);
        let NoiseCore { stft, st } = &mut *c;
        run(py, stft, &audio, |p, out| st.gain(p, out))
    }
}

#[pyclass]
struct EchoReducer {
    core: Arc<Mutex<EchoCore>>,
}

#[pymethods]
impl EchoReducer {
    #[new]
    #[pyo3(signature = (sample_rate, reverb_time = 0.6, reduction_db = 9.0))]
    fn new(sample_rate: u32, reverb_time: f64, reduction_db: f64) -> Self {
        EchoReducer {
            core: Arc::new(Mutex::new(EchoCore {
                stft: Stft::new(sample_rate),
                st: EchoState::new(sample_rate, reverb_time, reduction_db),
            })),
        }
    }
    #[getter]
    fn reverb_time(&self) -> f64 {
        locked(&self.core).st.reverb_time
    }
    #[setter]
    fn set_reverb_time(&self, v: f64) {
        locked(&self.core).st.reverb_time = v;
    }
    #[getter]
    fn reduction_db(&self) -> f64 {
        locked(&self.core).st.reduction_db
    }
    #[setter]
    fn set_reduction_db(&self, v: f64) {
        locked(&self.core).st.reduction_db = v;
    }
    #[getter]
    fn activity_db(&self) -> f64 {
        locked(&self.core).st.activity_db
    }
    #[getter]
    fn sample_rate(&self) -> u32 {
        locked(&self.core).stft.sample_rate
    }
    #[getter]
    fn latency(&self) -> usize {
        stft::N - stft::HOP
    }
    fn reset(&self) {
        let mut c = locked(&self.core);
        c.stft.reset();
        c.st.reset();
    }
    fn wake(&self) {
        let mut c = locked(&self.core);
        c.stft.wake();
        c.st.wake();
    }
    fn process(&self, py: Python<'_>, audio: PyReadonlyArray2<f32>) -> PyResult<Py<PyArray2<f32>>> {
        let mut c = locked(&self.core);
        let EchoCore { stft, st } = &mut *c;
        run(py, stft, &audio, |p, out| st.gain(p, out))
    }
}

/// Echo and noise reduction in ONE pass: the parts' gains are multiplied (see `Joint` in spectral.py).
#[derive(Clone)]
enum PartRef {
    Noise(Arc<Mutex<NoiseCore>>),
    Echo(Arc<Mutex<EchoCore>>),
}

enum PartGuard<'a> {
    Noise(MutexGuard<'a, NoiseCore>),
    Echo(MutexGuard<'a, EchoCore>),
}

pub struct JointCore {
    stft: Stft,
    parts: Vec<PartRef>,
    gain: Vec<f64>,
    part_gain: Vec<f64>,
}

const MAX_PARTS: usize = 4;

impl JointCore {
    fn wake(&mut self) {
        self.stft.wake();
        for p in &self.parts {
            match p {
                PartRef::Noise(n) => locked(n).st.wake(),
                PartRef::Echo(e) => locked(e).st.wake(),
            }
        }
    }
    /// The parts' states locked for one pass (the Joint's own lock is held by the caller, always taken first).
    fn with_parts<R>(
        &mut self,
        f: impl FnOnce(&mut Stft, &mut [f64], &mut [f64], &mut [Option<PartGuard>; MAX_PARTS]) -> R,
    ) -> R {
        let JointCore {
            stft,
            parts,
            gain,
            part_gain,
        } = self;
        let mut guards: [Option<PartGuard>; MAX_PARTS] = [None, None, None, None];
        for (slot, p) in guards.iter_mut().zip(parts.iter()) {
            *slot = Some(match p {
                PartRef::Noise(n) => PartGuard::Noise(locked(n)),
                PartRef::Echo(e) => PartGuard::Echo(locked(e)),
            });
        }
        f(stft, gain, part_gain, &mut guards)
    }
}

fn joint_gains(
    guards: &mut [Option<PartGuard>; MAX_PARTS],
    gain: &mut [f64],
    part_gain: &mut [f64],
    power: &[f64],
    out: &mut [f64],
) {
    let mut first = true;
    for part in guards.iter_mut().flatten() {
        let target: &mut [f64] = if first {
            &mut gain[..]
        } else {
            &mut part_gain[..]
        };
        match part {
            PartGuard::Noise(n) => n.st.gain(power, target),
            PartGuard::Echo(e) => e.st.gain(power, target),
        }
        if !first {
            for k in 0..K {
                gain[k] *= part_gain[k];
            }
        }
        first = false;
    }
    out.copy_from_slice(&gain[..]);
}

#[pyclass]
struct Joint {
    core: Arc<Mutex<JointCore>>,
}

#[pymethods]
impl Joint {
    #[new]
    fn new(py: Python<'_>, parts: Vec<Py<PyAny>>) -> PyResult<Self> {
        if parts.is_empty() {
            return Err(PyValueError::new_err("Joint needs at least one reducer"));
        }
        if parts.len() > MAX_PARTS {
            return Err(PyValueError::new_err("Joint takes at most four reducers"));
        }
        let mut rate = 0;
        let mut refs = Vec::with_capacity(parts.len());
        for (i, p) in parts.iter().enumerate() {
            let b = p.bind(py);
            let (r, part) = if let Ok(n) = b.extract::<PyRef<NoiseReducer>>() {
                (
                    locked(&n.core).stft.sample_rate,
                    PartRef::Noise(n.core.clone()),
                )
            } else if let Ok(e) = b.extract::<PyRef<EchoReducer>>() {
                (
                    locked(&e.core).stft.sample_rate,
                    PartRef::Echo(e.core.clone()),
                )
            } else {
                return Err(PyValueError::new_err(
                    "Joint takes the Rust NoiseReducer and EchoReducer",
                ));
            };
            if i == 0 {
                rate = r;
            }
            refs.push(part);
        }
        Ok(Joint {
            core: Arc::new(Mutex::new(JointCore {
                stft: Stft::new(rate),
                parts: refs,
                gain: vec![1.0; K],
                part_gain: vec![1.0; K],
            })),
        })
    }
    #[getter]
    fn sample_rate(&self) -> u32 {
        locked(&self.core).stft.sample_rate
    }
    #[getter]
    fn latency(&self) -> usize {
        stft::N - stft::HOP
    }
    fn reset(&self) {
        locked(&self.core).stft.reset();
    }
    fn wake(&self) {
        locked(&self.core).wake();
    }
    fn process(&self, py: Python<'_>, audio: PyReadonlyArray2<f32>) -> PyResult<Py<PyArray2<f32>>> {
        let mut c = locked(&self.core);
        c.with_parts(|stft, gain, part_gain, guards| {
            run(py, stft, &audio, |power, out| {
                joint_gains(guards, gain, part_gain, power, out)
            })
        })
    }
}

// ---------------------------------------------------------------------------------------------- built-in effects
fn to_stereo(audio: &PyReadonlyArray2<f32>) -> PyResult<Stereo> {
    if audio.shape()[0] != 2 {
        return Err(PyValueError::new_err("audio must have shape (2, frames)"));
    }
    let view = audio.as_array();
    Ok([
        view.row(0).iter().copied().collect(),
        view.row(1).iter().copied().collect(),
    ])
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
            fx: Arc<Mutex<$ty>>,
        }

        #[pymethods]
        impl $cls {
            #[new]
            #[pyo3(signature = ($($arg),*))]
            fn new($($arg: f64),*) -> Self {
                $cls { fx: Arc::new(Mutex::new($ctor)) }
            }
            #[classattr]
            #[allow(non_snake_case)]
            fn IS_NATIVE() -> bool {
                true
            }
            $(
                #[getter]
                fn $attr(&self) -> f64 {
                    locked(&self.fx).$field
                }
                #[setter]
                fn $set(&self, v: f64) {
                    locked(&self.fx).$field = v;
                }
            )*
            #[pyo3(signature = (audio, sample_rate))]
            fn process(&self, py: Python<'_>, audio: PyReadonlyArray2<f32>, sample_rate: u32) -> PyResult<Py<PyArray2<f32>>> {
                let mut buf = to_stereo(&audio)?;
                locked(&self.fx).process(&mut buf, sample_rate);
                Ok(from_stereo(py, &buf))
            }
        }
    };
}

effect_class!(
    "Gain",
    GainFx,
    native::Gain,
    (gain_db),
    native::Gain { gain_db },
    [(gain_db, set_gain_db, gain_db)]
);
effect_class!(
    "HighpassFilter",
    HighpassFx,
    native::HighPass,
    (cutoff_frequency_hz),
    native::HighPass::new(cutoff_frequency_hz),
    [(cutoff_frequency_hz, set_cutoff_frequency_hz, cutoff_hz)]
);
effect_class!(
    "ButterworthHighPass",
    ButterHighPassFx,
    native::Biquad,
    (cutoff_frequency_hz),
    native::Biquad::new(
        Shape::HighPass,
        cutoff_frequency_hz,
        0.0,
        std::f64::consts::FRAC_1_SQRT_2
    ),
    [(cutoff_frequency_hz, set_cutoff_frequency_hz, freq)]
);
effect_class!(
    "LowShelfFilter",
    LowShelfFx,
    native::Biquad,
    (cutoff_frequency_hz, gain_db, q),
    native::Biquad::new(Shape::LowShelf, cutoff_frequency_hz, gain_db, q),
    [
        (cutoff_frequency_hz, set_cutoff_frequency_hz, freq),
        (gain_db, set_gain_db, gain_db),
        (q, set_q, q)
    ]
);
effect_class!(
    "HighShelfFilter",
    HighShelfFx,
    native::Biquad,
    (cutoff_frequency_hz, gain_db, q),
    native::Biquad::new(Shape::HighShelf, cutoff_frequency_hz, gain_db, q),
    [
        (cutoff_frequency_hz, set_cutoff_frequency_hz, freq),
        (gain_db, set_gain_db, gain_db),
        (q, set_q, q)
    ]
);
effect_class!(
    "PeakFilter",
    PeakFx,
    native::Biquad,
    (cutoff_frequency_hz, gain_db, q),
    native::Biquad::new(Shape::Peak, cutoff_frequency_hz, gain_db, q),
    [
        (cutoff_frequency_hz, set_cutoff_frequency_hz, freq),
        (gain_db, set_gain_db, gain_db),
        (q, set_q, q)
    ]
);
effect_class!(
    "Compressor",
    CompressorFx,
    native::Compressor,
    (threshold_db, ratio, attack_ms, release_ms),
    native::Compressor::new(threshold_db, ratio, attack_ms, release_ms),
    [
        (threshold_db, set_threshold_db, threshold_db),
        (ratio, set_ratio, ratio),
        (attack_ms, set_attack_ms, attack_ms),
        (release_ms, set_release_ms, release_ms)
    ]
);
effect_class!(
    "Limiter",
    LimiterFx,
    native::Limiter,
    (threshold_db, release_ms),
    native::Limiter::new(threshold_db, release_ms),
    [
        (threshold_db, set_threshold_db, threshold_db),
        (release_ms, set_release_ms, release_ms)
    ]
);
effect_class!(
    "NoiseGate",
    NoiseGateFx,
    native::NoiseGate,
    (threshold_db, ratio, attack_ms, release_ms),
    native::NoiseGate::new(threshold_db, ratio, attack_ms, release_ms),
    [
        (threshold_db, set_threshold_db, threshold_db),
        (ratio, set_ratio, ratio),
        (attack_ms, set_attack_ms, attack_ms),
        (release_ms, set_release_ms, release_ms)
    ]
);

/// One of Sluice's built-in effects, shared with its Python object.
struct EffectProc<T: Effect>(Arc<Mutex<T>>);

impl<T: Effect + 'static> Proc for EffectProc<T> {
    fn run(&mut self, buf: &mut Stereo, sample_rate: u32) {
        locked(&self.0).process(buf, sample_rate);
    }
}

struct NoiseProc(Arc<Mutex<NoiseCore>>);
impl Proc for NoiseProc {
    fn run(&mut self, buf: &mut Stereo, _sr: u32) {
        let mut c = locked(&self.0);
        let NoiseCore { stft, st } = &mut *c;
        stft.process_buf(buf, |p, out| st.gain(p, out));
    }
    fn wake(&mut self) {
        let mut c = locked(&self.0);
        c.stft.wake();
        c.st.wake();
    }
}

struct EchoProc(Arc<Mutex<EchoCore>>);
impl Proc for EchoProc {
    fn run(&mut self, buf: &mut Stereo, _sr: u32) {
        let mut c = locked(&self.0);
        let EchoCore { stft, st } = &mut *c;
        stft.process_buf(buf, |p, out| st.gain(p, out));
    }
    fn wake(&mut self) {
        let mut c = locked(&self.0);
        c.stft.wake();
        c.st.wake();
    }
}

struct JointProc(Arc<Mutex<JointCore>>);
impl Proc for JointProc {
    fn run(&mut self, buf: &mut Stereo, _sr: u32) {
        let mut c = locked(&self.0);
        c.with_parts(|stft, gain, part_gain, guards| {
            stft.process_buf(buf, |power, out| {
                joint_gains(guards, gain, part_gain, power, out)
            })
        });
    }
    fn wake(&mut self) {
        locked(&self.0).wake();
    }
}

struct GateProc(Arc<Mutex<voice::VoiceGate>>);
impl Proc for GateProc {
    fn run(&mut self, buf: &mut Stereo, _sr: u32) {
        locked(&self.0).process(buf);
    }
    fn wake(&mut self) {
        locked(&self.0).wake();
    }
}

struct CompProc(Arc<Mutex<voice::LinkedCompressor>>);
impl Proc for CompProc {
    fn run(&mut self, buf: &mut Stereo, _sr: u32) {
        locked(&self.0).process(buf);
    }
    fn wake(&mut self) {
        locked(&self.0).wake();
    }
}

struct CeilingProc(Arc<Mutex<voice::CeilingLimiter>>);
impl Proc for CeilingProc {
    fn run(&mut self, buf: &mut Stereo, _sr: u32) {
        locked(&self.0).process(buf);
    }
}

/// The graph's entry for a Python object, sharing its core; None when it is not one of Sluice's Rust effects.
fn proc_of(b: &Bound<'_, PyAny>) -> Option<Box<dyn Proc>> {
    macro_rules! effects {
        ($($t:ty => $inner:ty),*) => {$(
            if let Ok(fx) = b.extract::<PyRef<$t>>() {
                return Some(Box::new(EffectProc::<$inner>(fx.fx.clone())));
            }
        )*};
    }
    effects!(
        GainFx => native::Gain,
        HighpassFx => native::HighPass,
        ButterHighPassFx => native::Biquad,
        LowShelfFx => native::Biquad,
        HighShelfFx => native::Biquad,
        PeakFx => native::Biquad,
        CompressorFx => native::Compressor,
        NoiseGateFx => native::NoiseGate,
        LimiterFx => native::Limiter
    );
    if let Ok(n) = b.extract::<PyRef<NoiseReducer>>() {
        return Some(Box::new(NoiseProc(n.core.clone())));
    }
    if let Ok(e) = b.extract::<PyRef<EchoReducer>>() {
        return Some(Box::new(EchoProc(e.core.clone())));
    }
    if let Ok(j) = b.extract::<PyRef<Joint>>() {
        return Some(Box::new(JointProc(j.core.clone())));
    }
    if let Ok(g) = b.extract::<PyRef<VoiceGate>>() {
        return Some(Box::new(GateProc(g.core.clone())));
    }
    if let Ok(c) = b.extract::<PyRef<LinkedCompressor>>() {
        return Some(Box::new(CompProc(c.core.clone())));
    }
    if let Ok(c) = b.extract::<PyRef<CeilingLimiter>>() {
        return Some(Box::new(CeilingProc(c.core.clone())));
    }
    if let Ok(r) = b.extract::<PyRef<Run>>() {
        return Some(Box::new(RunProc(
            r.procs.iter().map(|p| p.clone_box()).collect(),
        )));
    }
    None
}

/// Runs a list of the effects above, in order, in one call (one trip across the Python/Rust border for the group).
#[pyclass]
struct Run {
    procs: Vec<SharedEffect>,
}

/// A built-in effect's core, of whichever kind (for Run, which the graph can also take whole).
#[derive(Clone)]
enum SharedEffect {
    Gain(Arc<Mutex<native::Gain>>),
    HighPass(Arc<Mutex<native::HighPass>>),
    Biquad(Arc<Mutex<native::Biquad>>),
    Compressor(Arc<Mutex<native::Compressor>>),
    NoiseGate(Arc<Mutex<native::NoiseGate>>),
    Limiter(Arc<Mutex<native::Limiter>>),
}

impl SharedEffect {
    fn process(&self, buf: &mut Stereo, sr: u32) {
        match self {
            SharedEffect::Gain(f) => locked(f).process(buf, sr),
            SharedEffect::HighPass(f) => locked(f).process(buf, sr),
            SharedEffect::Biquad(f) => locked(f).process(buf, sr),
            SharedEffect::Compressor(f) => locked(f).process(buf, sr),
            SharedEffect::NoiseGate(f) => locked(f).process(buf, sr),
            SharedEffect::Limiter(f) => locked(f).process(buf, sr),
        }
    }
    fn clone_box(&self) -> SharedEffect {
        self.clone()
    }
}

struct RunProc(Vec<SharedEffect>);
impl Proc for RunProc {
    fn run(&mut self, buf: &mut Stereo, sr: u32) {
        for p in &self.0 {
            p.process(buf, sr);
        }
    }
}

#[pymethods]
impl Run {
    #[new]
    fn new(py: Python<'_>, plugins: Vec<Py<PyAny>>) -> PyResult<Self> {
        let mut procs = Vec::with_capacity(plugins.len());
        for p in &plugins {
            let b = p.bind(py);
            let shared = if let Ok(f) = b.extract::<PyRef<GainFx>>() {
                SharedEffect::Gain(f.fx.clone())
            } else if let Ok(f) = b.extract::<PyRef<HighpassFx>>() {
                SharedEffect::HighPass(f.fx.clone())
            } else if let Ok(f) = b.extract::<PyRef<ButterHighPassFx>>() {
                SharedEffect::Biquad(f.fx.clone())
            } else if let Ok(f) = b.extract::<PyRef<LowShelfFx>>() {
                SharedEffect::Biquad(f.fx.clone())
            } else if let Ok(f) = b.extract::<PyRef<HighShelfFx>>() {
                SharedEffect::Biquad(f.fx.clone())
            } else if let Ok(f) = b.extract::<PyRef<PeakFx>>() {
                SharedEffect::Biquad(f.fx.clone())
            } else if let Ok(f) = b.extract::<PyRef<CompressorFx>>() {
                SharedEffect::Compressor(f.fx.clone())
            } else if let Ok(f) = b.extract::<PyRef<NoiseGateFx>>() {
                SharedEffect::NoiseGate(f.fx.clone())
            } else if let Ok(f) = b.extract::<PyRef<LimiterFx>>() {
                SharedEffect::Limiter(f.fx.clone())
            } else {
                return Err(PyValueError::new_err("Run takes only sluice_dsp effects"));
            };
            procs.push(shared);
        }
        Ok(Run { procs })
    }
    #[pyo3(signature = (audio, sample_rate))]
    fn process(
        &self,
        py: Python<'_>,
        audio: PyReadonlyArray2<f32>,
        sample_rate: u32,
    ) -> PyResult<Py<PyArray2<f32>>> {
        let mut buf = to_stereo(&audio)?;
        for p in &self.procs {
            p.process(&mut buf, sample_rate);
        }
        Ok(from_stereo(py, &buf))
    }
}

// ------------------------------------------------------------------------------------------------ voice effects
#[pyclass]
struct VoiceGate {
    core: Arc<Mutex<voice::VoiceGate>>,
}

#[pymethods]
impl VoiceGate {
    #[new]
    fn new(sample_rate: u32) -> Self {
        VoiceGate {
            core: Arc::new(Mutex::new(voice::VoiceGate::new(sample_rate))),
        }
    }
    #[getter]
    fn sample_rate(&self) -> u32 {
        locked(&self.core).sample_rate
    }
    #[getter]
    fn threshold_db(&self) -> f64 {
        locked(&self.core).threshold_db
    }
    #[setter]
    fn set_threshold_db(&self, v: f64) {
        locked(&self.core).threshold_db = v;
    }
    #[getter]
    fn depth_db(&self) -> f64 {
        locked(&self.core).depth_db
    }
    #[setter]
    fn set_depth_db(&self, v: f64) {
        locked(&self.core).depth_db = v;
    }
    #[getter]
    fn attack_ms(&self) -> f64 {
        locked(&self.core).attack_ms
    }
    #[setter]
    fn set_attack_ms(&self, v: f64) {
        locked(&self.core).attack_ms = v;
    }
    #[getter]
    fn hold_ms(&self) -> f64 {
        locked(&self.core).hold_ms
    }
    #[setter]
    fn set_hold_ms(&self, v: f64) {
        locked(&self.core).hold_ms = v;
    }
    #[getter]
    fn release_ms(&self) -> f64 {
        locked(&self.core).release_ms
    }
    #[setter]
    fn set_release_ms(&self, v: f64) {
        locked(&self.core).release_ms = v;
    }
    #[getter]
    fn activity_db(&self) -> f64 {
        locked(&self.core).activity_db
    }
    fn wake(&self) {
        locked(&self.core).wake();
    }
    fn process(&self, py: Python<'_>, audio: PyReadonlyArray2<f32>) -> PyResult<Py<PyArray2<f32>>> {
        let mut buf = to_stereo(&audio)?;
        locked(&self.core).process(&mut buf);
        Ok(from_stereo(py, &buf))
    }
}

#[pyclass]
struct LinkedCompressor {
    core: Arc<Mutex<voice::LinkedCompressor>>,
}

#[pymethods]
impl LinkedCompressor {
    #[new]
    fn new(sample_rate: u32) -> Self {
        LinkedCompressor {
            core: Arc::new(Mutex::new(voice::LinkedCompressor::new(sample_rate))),
        }
    }
    #[getter]
    fn sample_rate(&self) -> u32 {
        locked(&self.core).sample_rate
    }
    #[getter]
    fn threshold_db(&self) -> f64 {
        locked(&self.core).threshold_db
    }
    #[setter]
    fn set_threshold_db(&self, v: f64) {
        locked(&self.core).threshold_db = v;
    }
    #[getter]
    fn ratio(&self) -> f64 {
        locked(&self.core).ratio
    }
    #[setter]
    fn set_ratio(&self, v: f64) {
        locked(&self.core).ratio = v;
    }
    #[getter]
    fn attack_ms(&self) -> f64 {
        locked(&self.core).attack_ms
    }
    #[setter]
    fn set_attack_ms(&self, v: f64) {
        locked(&self.core).attack_ms = v;
    }
    #[getter]
    fn release_ms(&self) -> f64 {
        locked(&self.core).release_ms
    }
    #[setter]
    fn set_release_ms(&self, v: f64) {
        locked(&self.core).release_ms = v;
    }
    #[getter]
    fn makeup_db(&self) -> f64 {
        locked(&self.core).makeup_db
    }
    #[setter]
    fn set_makeup_db(&self, v: f64) {
        locked(&self.core).makeup_db = v;
    }
    #[getter]
    fn activity_db(&self) -> f64 {
        locked(&self.core).activity_db
    }
    fn reduction(&self, level_db: f64) -> f64 {
        locked(&self.core).reduction(level_db)
    }
    fn wake(&self) {
        locked(&self.core).wake();
    }
    fn process(&self, py: Python<'_>, audio: PyReadonlyArray2<f32>) -> PyResult<Py<PyArray2<f32>>> {
        let mut buf = to_stereo(&audio)?;
        locked(&self.core).process(&mut buf);
        Ok(from_stereo(py, &buf))
    }
}

#[pyclass]
struct CeilingLimiter {
    core: Arc<Mutex<voice::CeilingLimiter>>,
}

#[pymethods]
impl CeilingLimiter {
    #[new]
    fn new(sample_rate: u32) -> Self {
        CeilingLimiter {
            core: Arc::new(Mutex::new(voice::CeilingLimiter::new(sample_rate))),
        }
    }
    #[getter]
    fn sample_rate(&self) -> u32 {
        locked(&self.core).sample_rate
    }
    #[getter]
    fn threshold_db(&self) -> f64 {
        locked(&self.core).threshold_db()
    }
    #[setter]
    fn set_threshold_db(&self, v: f64) {
        locked(&self.core).set_threshold_db(v);
    }
    #[getter]
    fn release_ms(&self) -> f64 {
        locked(&self.core).release_ms()
    }
    #[setter]
    fn set_release_ms(&self, v: f64) {
        locked(&self.core).set_release_ms(v);
    }
    #[getter]
    fn activity_db(&self) -> f64 {
        locked(&self.core).activity_db
    }
    fn wake(&self) {}
    fn process(&self, py: Python<'_>, audio: PyReadonlyArray2<f32>) -> PyResult<Py<PyArray2<f32>>> {
        let mut buf = to_stereo(&audio)?;
        locked(&self.core).process(&mut buf);
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
        PeakLimiter {
            inner: mix::PeakLimiter::new(sample_rate, ceiling_db, release_ms),
        }
    }
    #[getter]
    fn ceiling(&self) -> f64 {
        self.inner.ceiling()
    }
    fn process(
        &mut self,
        py: Python<'_>,
        audio: PyReadonlyArray2<f32>,
    ) -> PyResult<Py<PyArray2<f32>>> {
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
fn accumulate(
    out: &Bound<'_, PyArray2<f32>>,
    audio: PyReadonlyArray2<f32>,
    previous: f64,
    target: f64,
) -> PyResult<()> {
    let a = audio.as_array();
    let mut o = unsafe { out.as_array_mut() };
    if a.shape() != o.shape() {
        return Err(PyValueError::new_err(
            "out and audio must have the same shape",
        ));
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
fn finish_mix(
    out: &Bound<'_, PyArray2<f32>>,
    applied: f64,
    gain: f64,
    limiter: Option<Py<PeakLimiter>>,
) -> PyResult<f32> {
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
    let peak =
        buf.iter()
            .flat_map(|ch| ch.iter())
            .fold(0.0f32, |m, &x| if x.abs() > m { x.abs() } else { m });
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
fn block_peaks_db(
    py: Python<'_>,
    audio: PyReadonlyArray2<f32>,
    size: usize,
) -> PyResult<Py<PyArray1<f64>>> {
    let b = to_stereo(&audio)?;
    Ok(PyArray1::from_vec(py, room::block_peaks_db(&b[0], &b[1], size)).unbind())
}

#[pyfunction]
fn block_power(
    py: Python<'_>,
    audio: PyReadonlyArray2<f32>,
    size: usize,
) -> PyResult<Py<PyArray1<f64>>> {
    let b = to_stereo(&audio)?;
    Ok(PyArray1::from_vec(py, room::block_power(&b[0], &b[1], size)).unbind())
}

#[pyfunction]
fn noise_profile(
    py: Python<'_>,
    audio: PyReadonlyArray2<f32>,
    n: usize,
    hop: usize,
) -> PyResult<Py<PyArray1<f64>>> {
    let b = to_stereo(&audio)?;
    Ok(PyArray1::from_vec(py, room::noise_profile(&b[0], &b[1], n, hop.max(1))).unbind())
}

#[pyfunction]
fn echo_energy(
    py: Python<'_>,
    audio: PyReadonlyArray2<f64>,
    sample_rate: f64,
    block: usize,
) -> PyResult<Py<PyArray1<f64>>> {
    if audio.shape()[0] != 2 {
        return Err(PyValueError::new_err("audio must have shape (2, frames)"));
    }
    let v = audio.as_array();
    let l: Vec<f64> = v.row(0).iter().copied().collect();
    let r: Vec<f64> = v.row(1).iter().copied().collect();
    Ok(PyArray1::from_vec(py, room::echo_energy(&l, &r, sample_rate, block)).unbind())
}

// --------------------------------------------------------------------------------------------- the native graph
/// 0.13.1: the mixing graph in Rust (see graph.rs). `dsp.Graph` gives it the same settings it keeps itself, and the JACK
/// engine runs it instead of calling Python while every chain is native.
#[pyclass]
pub struct NativeGraph {
    pub(crate) core: Arc<Mutex<GraphCore>>,
}

type ChannelState = (HashMap<String, f64>, f64, f64, f64, u64, bool);

#[pymethods]
impl NativeGraph {
    #[new]
    fn new(sample_rate: u32, mix_ids: Vec<String>) -> Self {
        NativeGraph {
            core: Arc::new(Mutex::new(GraphCore::new(sample_rate, &mix_ids))),
        }
    }
    #[getter]
    fn sample_rate(&self) -> u32 {
        locked(&self.core).sample_rate
    }
    fn set_channels(&self, ids: Vec<String>) {
        locked(&self.core).set_channels(&ids);
    }
    fn set_mixes(&self, ids: Vec<String>) {
        let mut g = locked(&self.core);
        g.mixes.retain(|m| ids.contains(&m.id));
        for id in &ids {
            if !g.mixes.iter().any(|m| &m.id == id) {
                g.mixes.push(graph::MixCore::new(id));
            }
        }
    }
    /// The channel's chain from Python effect objects (sharing their cores). A TypeError, and nothing changed, when one of
    /// them is not a Sluice Rust effect: the Python graph must run that channel.
    fn set_chain(&self, py: Python<'_>, channel_id: &str, items: Vec<Py<PyAny>>) -> PyResult<()> {
        let mut procs: Vec<Box<dyn Proc>> = Vec::with_capacity(items.len());
        for item in &items {
            let b = item.bind(py);
            match proc_of(b) {
                Some(p) => procs.push(p),
                None => {
                    let name = b
                        .get_type()
                        .name()
                        .map(|n| n.to_string())
                        .unwrap_or_default();
                    return Err(PyTypeError::new_err(format!(
                        "{name} is not a native effect"
                    )));
                }
            }
        }
        if let Some(c) = locked(&self.core).channel_mut(channel_id) {
            c.chain = procs;
        }
        Ok(())
    }
    #[pyo3(signature = (channel_id, gains, solo))]
    fn set_channel(&self, channel_id: &str, gains: HashMap<String, f64>, solo: Option<f64>) {
        if let Some(c) = locked(&self.core).channel_mut(channel_id) {
            if c.solo_gain.is_none() {
                if let Some(g) = solo {
                    c.solo_applied = g;
                }
            }
            c.gains = gains;
            c.solo_gain = solo;
        }
    }
    fn set_mix(&self, mix_id: &str, gain: f64, limiter: bool) {
        if let Some(m) = locked(&self.core).mix_mut(mix_id) {
            m.gain = gain;
            m.limiter_on = limiter;
            if !m.primed {
                m.applied = gain;
            }
        }
    }
    /// Hand over where a channel was (when the Rust graph takes over from the Python one, or back): gains reached,
    /// meters, and how long it has been quiet.
    fn put_channel_state(&self, channel_id: &str, state: ChannelState) {
        if let Some(c) = locked(&self.core).channel_mut(channel_id) {
            (
                c.applied,
                c.solo_applied,
                c.recent,
                c.input_recent,
                c.quiet_frames,
                c.asleep,
            ) = state;
        }
    }
    fn channel_state(&self, channel_id: &str) -> Option<ChannelState> {
        let mut g = locked(&self.core);
        g.channel_mut(channel_id).map(|c| {
            (
                c.applied.clone(),
                c.solo_applied,
                c.recent,
                c.input_recent,
                c.quiet_frames,
                c.asleep,
            )
        })
    }
    fn put_mix_state(&self, mix_id: &str, applied: f64, primed: bool) {
        if let Some(m) = locked(&self.core).mix_mut(mix_id) {
            m.applied = applied;
            m.primed = primed;
        }
    }
    fn mix_state(&self, mix_id: &str) -> Option<(f64, bool)> {
        locked(&self.core)
            .mix_mut(mix_id)
            .map(|m| (m.applied, m.primed))
    }
    /// Peaks since the last call, keyed like dsp.Graph.take_peaks ('ch:<id>', 'in:<id>', 'mix:<id>').
    fn take_peaks(&self) -> HashMap<String, f64> {
        let mut g = locked(&self.core);
        let mut out = HashMap::new();
        for c in g.channels.iter_mut() {
            out.insert(format!("ch:{}", c.id), std::mem::take(&mut c.peak));
            out.insert(format!("in:{}", c.id), std::mem::take(&mut c.input_peak));
        }
        for m in g.mixes.iter_mut() {
            out.insert(format!("mix:{}", m.id), std::mem::take(&mut m.peak));
        }
        out
    }
    /// channel id -> (recent peak after the effects, recent peak before them, asleep)
    fn levels(&self) -> HashMap<String, (f64, f64, bool)> {
        locked(&self.core)
            .channels
            .iter()
            .map(|c| (c.id.clone(), (c.recent, c.input_recent, c.asleep)))
            .collect()
    }
    /// One block, for tests and the parity check: channel id -> (2, frames) float32, as dsp.Graph.process.
    fn process<'py>(
        &self,
        py: Python<'py>,
        inputs: HashMap<String, PyReadonlyArray2<'py, f32>>,
        frames: usize,
    ) -> PyResult<HashMap<String, Py<PyArray2<f32>>>> {
        let mut owned: HashMap<String, Stereo> = HashMap::new();
        for (id, a) in &inputs {
            owned.insert(id.clone(), to_stereo(a)?);
        }
        let mut g = locked(&self.core);
        g.process(frames, |id| owned.get(id).map(|s| (&s[0][..], &s[1][..])));
        let mut out = HashMap::new();
        for m in &g.mixes {
            out.insert(m.id.clone(), from_stereo(py, &m.out));
        }
        for c in &g.channels {
            if c.solo_gain.is_some() {
                out.insert(format!("solo_{}", c.id), from_stereo(py, &c.solo_out));
            }
        }
        Ok(out)
    }
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
    m.add_class::<VoiceGate>()?;
    m.add_class::<LinkedCompressor>()?;
    m.add_class::<CeilingLimiter>()?;
    m.add_class::<NativeGraph>()?;
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
