// SPDX-License-Identifier: GPL-3.0-or-later
//! Sluice's connection to PipeWire (through its JACK layer): the client, the ports, the block callback, and the
//! measuring of how long each block takes and whose dropouts they are. libjack is loaded when the client is opened, so
//! the module builds and imports without it. The mixing itself is still called in Python for each block (VST3 plugins
//! need Python); everything around that call is Rust.
use jack::{AsyncClient, AudioIn, AudioOut, Client, ClientOptions, ClientStatus, Control, Port, ProcessScope};
use numpy::{PyArray2, PyArrayMethods, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

const SLOW_BLOCK: f64 = 0.7; // a block that used more than this share of its time counts as Sluice running late

type InPair = (Port<AudioIn>, Port<AudioIn>);
type OutPair = (Port<AudioOut>, Port<AudioOut>);

#[derive(Default)]
struct Ports {
    inputs: BTreeMap<String, InPair>,
    outputs: BTreeMap<String, OutPair>,
}

struct Shared {
    ports: Mutex<Ports>,
    callback: Mutex<Option<Py<PyAny>>>,
    error: Mutex<String>,
    epoch: Instant,
    period_ns: u64,
    xruns: AtomicU64,
    xruns_ours: AtomicU64,
    in_block: AtomicBool,
    block_start_ns: AtomicU64,
    last_busy_ns: AtomicU64,
    busy_sum_ns: AtomicU64,
    busy_peak_ns: AtomicU64,
    blocks: AtomicU64,
}

impl Shared {
    fn now_ns(&self) -> u64 {
        self.epoch.elapsed().as_nanos() as u64
    }
    fn set_error(&self, message: String) {
        if let Ok(mut e) = self.error.lock() {
            *e = message;
        }
    }
}

struct Proc {
    shared: Arc<Shared>,
}

impl Proc {
    fn run_python(&self, ports: &mut Ports, ps: &ProcessScope, frames: usize) -> PyResult<()> {
        Python::attach(|py| {
            let cb = {
                let guard = self.shared.callback.lock().map_err(|_| PyRuntimeError::new_err("callback lock poisoned"))?;
                match guard.as_ref() {
                    Some(cb) => cb.clone_ref(py),
                    None => return Err(PyRuntimeError::new_err("no callback")),
                }
            };
            let inputs = PyDict::new(py);
            for (id, (l, r)) in ports.inputs.iter() {
                let arr = PyArray2::<f32>::zeros(py, [2, frames], false);
                {
                    let mut w = unsafe { arr.as_array_mut() };
                    for (c, port) in [l, r].into_iter().enumerate() {
                        let src = port.as_slice(ps);
                        for i in 0..frames.min(src.len()) {
                            w[[c, i]] = src[i];
                        }
                    }
                }
                inputs.set_item(id, arr)?;
            }
            let result = cb.call1(py, (inputs, frames))?;
            let result = result.bind(py).cast::<PyDict>()?.clone();
            for (id, (l, r)) in ports.outputs.iter_mut() {
                let (lo, ro) = (l.as_mut_slice(ps), r.as_mut_slice(ps));
                match result.get_item(id)? {
                    Some(block) => {
                        let a: PyReadonlyArray2<f32> = block.extract()?;
                        if a.shape()[0] != 2 {
                            return Err(PyValueError::new_err("a mix block must have shape (2, frames)"));
                        }
                        let v = a.as_array();
                        let n = v.shape()[1];
                        for i in 0..lo.len() {
                            lo[i] = if i < n { v[[0, i]] } else { 0.0 };
                            ro[i] = if i < n { v[[1, i]] } else { 0.0 };
                        }
                    }
                    None => {
                        lo.fill(0.0);
                        ro.fill(0.0);
                    }
                }
            }
            Ok(())
        })
    }
}

impl jack::ProcessHandler for Proc {
    fn process(&mut self, _: &Client, ps: &ProcessScope) -> Control {
        let s = &self.shared;
        let start = s.now_ns();
        s.block_start_ns.store(start, Ordering::Relaxed);
        s.in_block.store(true, Ordering::Release);
        let frames = ps.n_frames() as usize;
        if let Ok(mut ports) = s.ports.try_lock() {
            if let Err(e) = self.run_python(&mut ports, ps, frames) {
                // never let a failure reach the audio thread: say it, and play silence
                let text = Python::attach(|py| format!("{}: {}", e.get_type(py).name().map(|n| n.to_string()).unwrap_or_default(), e.value(py)));
                s.set_error(text);
                for (l, r) in ports.outputs.values_mut() {
                    l.as_mut_slice(ps).fill(0.0);
                    r.as_mut_slice(ps).fill(0.0);
                }
            }
        }
        let busy = s.now_ns().saturating_sub(start);
        s.in_block.store(false, Ordering::Release);
        s.last_busy_ns.store(busy, Ordering::Relaxed);
        s.busy_sum_ns.fetch_add(busy, Ordering::Relaxed);
        s.blocks.fetch_add(1, Ordering::Relaxed);
        s.busy_peak_ns.fetch_max(busy, Ordering::Relaxed);
        Control::Continue
    }
}

struct Notify {
    shared: Arc<Shared>,
}

impl jack::NotificationHandler for Notify {
    unsafe fn shutdown(&mut self, _status: ClientStatus, reason: &str) {
        self.shared.set_error(format!("Audio server shut down: {reason}"));
    }
    fn xrun(&mut self, _: &Client) -> Control {
        let s = &self.shared;
        s.xruns.fetch_add(1, Ordering::Relaxed);
        // Ours if the block that was running (or had just run) used most of its time: Sluice was the slow one.
        let busy = if s.in_block.load(Ordering::Acquire) {
            s.now_ns().saturating_sub(s.block_start_ns.load(Ordering::Relaxed))
        } else {
            s.last_busy_ns.load(Ordering::Relaxed)
        };
        if busy as f64 > SLOW_BLOCK * s.period_ns as f64 {
            s.xruns_ours.fetch_add(1, Ordering::Relaxed);
        }
        Control::Continue
    }
}

enum State {
    Idle(Client),
    Active(AsyncClient<Notify, Proc>),
    Closed,
}

#[pyclass]
pub struct JackEngine {
    state: Mutex<State>,
    shared: Arc<Shared>,
    #[pyo3(get)]
    sample_rate: u32,
    #[pyo3(get)]
    blocksize: u32,
}

fn client_of(state: &State) -> Option<&Client> {
    match state {
        State::Idle(c) => Some(c),
        State::Active(a) => Some(a.as_client()),
        State::Closed => None,
    }
}

#[pymethods]
impl JackEngine {
    #[new]
    #[pyo3(signature = (client_name = "sluice"))]
    fn new(py: Python<'_>, client_name: &str) -> PyResult<Self> {
        let name = client_name.to_string();
        let opened = py.detach(|| Client::new(&name, ClientOptions::NO_START_SERVER | ClientOptions::USE_EXACT_NAME));
        let (client, status) = opened.map_err(|e| PyRuntimeError::new_err(format!("{e:?}")))?;
        let sample_rate = client.sample_rate() as u32;
        let blocksize = client.buffer_size();
        let period_ns = (blocksize as f64 / sample_rate.max(1) as f64 * 1e9) as u64;
        let _ = status;
        let shared = Arc::new(Shared {
            ports: Mutex::new(Ports::default()),
            callback: Mutex::new(None),
            error: Mutex::new(String::new()),
            epoch: Instant::now(),
            period_ns,
            xruns: AtomicU64::new(0),
            xruns_ours: AtomicU64::new(0),
            in_block: AtomicBool::new(false),
            block_start_ns: AtomicU64::new(0),
            last_busy_ns: AtomicU64::new(0),
            busy_sum_ns: AtomicU64::new(0),
            busy_peak_ns: AtomicU64::new(0),
            blocks: AtomicU64::new(0),
        });
        Ok(JackEngine { state: Mutex::new(State::Idle(client)), shared, sample_rate, blocksize })
    }

    #[getter]
    fn xruns(&self) -> u64 {
        self.shared.xruns.load(Ordering::Relaxed)
    }
    #[getter]
    fn xruns_ours(&self) -> u64 {
        self.shared.xruns_ours.load(Ordering::Relaxed)
    }
    #[getter]
    fn error(&self) -> String {
        self.shared.error.lock().map(|e| e.clone()).unwrap_or_default()
    }
    #[setter]
    fn set_error(&self, value: String) {
        self.shared.set_error(value);
    }

    /// (average, worst) share of a block's time used since the last call.
    fn take_load(&self) -> (f64, f64) {
        let s = &self.shared;
        let blocks = s.blocks.swap(0, Ordering::Relaxed);
        let total = s.busy_sum_ns.swap(0, Ordering::Relaxed);
        let peak = s.busy_peak_ns.swap(0, Ordering::Relaxed);
        if blocks == 0 || s.period_ns == 0 {
            return (0.0, 0.0);
        }
        let p = s.period_ns as f64;
        (total as f64 / blocks as f64 / p, peak as f64 / p)
    }

    fn sync_ports(&self, py: Python<'_>, channel_ids: Vec<String>, mix_ids: Vec<String>) -> PyResult<()> {
        let shared = self.shared.clone();
        let state = &self.state;
        py.detach(move || -> PyResult<()> {
            let guard = state.lock().map_err(|_| PyRuntimeError::new_err("state lock poisoned"))?;
            let client = client_of(&guard).ok_or_else(|| PyRuntimeError::new_err("the audio client is closed"))?;
            let err = |e: jack::Error| PyRuntimeError::new_err(format!("{e:?}"));
            // 1. what is missing, looked up with the lock held only for a moment (the callback keeps the whole old set meanwhile)
            let (missing_in, missing_out): (Vec<String>, Vec<String>) = {
                let ports = shared.ports.lock().map_err(|_| PyRuntimeError::new_err("ports lock poisoned"))?;
                (
                    channel_ids.iter().filter(|id| !ports.inputs.contains_key(*id)).cloned().collect(),
                    mix_ids.iter().filter(|id| !ports.outputs.contains_key(*id)).cloned().collect(),
                )
            };
            // 2. register the new ports without holding the lock: the callback still sees every port it had
            let mut new_in: BTreeMap<String, InPair> = BTreeMap::new();
            let mut new_out: BTreeMap<String, OutPair> = BTreeMap::new();
            for id in &missing_in {
                let l = client.register_port(&format!("in_{id}_L"), AudioIn::default()).map_err(err)?;
                let r = client.register_port(&format!("in_{id}_R"), AudioIn::default()).map_err(err)?;
                new_in.insert(id.clone(), (l, r));
            }
            for id in &missing_out {
                let l = client.register_port(&format!("out_{id}_L"), AudioOut::default()).map_err(err)?;
                let r = client.register_port(&format!("out_{id}_R"), AudioOut::default()).map_err(err)?;
                new_out.insert(id.clone(), (l, r));
            }
            // 3. one short swap under the lock: add the new ports, take out only the ports that are no longer wanted
            let (old_in, old_out) = {
                let mut ports = shared.ports.lock().map_err(|_| PyRuntimeError::new_err("ports lock poisoned"))?;
                ports.inputs.extend(new_in);
                ports.outputs.extend(new_out);
                let stale_in: Vec<String> = ports.inputs.keys().filter(|k| !channel_ids.contains(*k)).cloned().collect();
                let stale_out: Vec<String> = ports.outputs.keys().filter(|k| !mix_ids.contains(*k)).cloned().collect();
                let old_in: Vec<InPair> = stale_in.iter().filter_map(|k| ports.inputs.remove(k)).collect();
                let old_out: Vec<OutPair> = stale_out.iter().filter_map(|k| ports.outputs.remove(k)).collect();
                (old_in, old_out)
            };
            // 4. give the unwanted ports back (the callback no longer uses them)
            for (l, r) in old_in {
                let _ = client.unregister_port(l);
                let _ = client.unregister_port(r);
            }
            for (l, r) in old_out {
                let _ = client.unregister_port(l);
                let _ = client.unregister_port(r);
            }
            Ok(())
        })
    }

    /// Start calling ``callback(inputs, frames)`` (inputs: channel id -> (2, frames) float32; returns mix id -> (2, frames)).
    fn start(&self, py: Python<'_>, callback: Py<PyAny>) -> PyResult<()> {
        *self.shared.callback.lock().map_err(|_| PyRuntimeError::new_err("callback lock poisoned"))? = Some(callback);
        let shared = self.shared.clone();
        let state = &self.state;
        py.detach(move || -> PyResult<()> {
            let mut guard = state.lock().map_err(|_| PyRuntimeError::new_err("state lock poisoned"))?;
            match std::mem::replace(&mut *guard, State::Closed) {
                State::Idle(client) => {
                    match client.activate_async(Notify { shared: shared.clone() }, Proc { shared }) {
                        Ok(active) => {
                            *guard = State::Active(active);
                            Ok(())
                        }
                        Err(e) => Err(PyRuntimeError::new_err(format!("{e:?}"))),
                    }
                }
                other => {
                    *guard = other;
                    Err(PyRuntimeError::new_err("already started or closed"))
                }
            }
        })
    }

    fn stop(&self, py: Python<'_>) -> PyResult<()> {
        let state = &self.state;
        let message = py.detach(move || -> String {
            let mut guard = match state.lock() {
                Ok(g) => g,
                Err(_) => return "state lock poisoned".into(),
            };
            match std::mem::replace(&mut *guard, State::Closed) {
                State::Active(active) => match active.deactivate() {
                    Ok(_) => String::new(), // dropping the client closes it
                    Err(e) => format!("deactivate failed: {e:?}"),
                },
                State::Idle(_) | State::Closed => String::new(),
            }
        });
        *self.shared.callback.lock().map_err(|_| PyRuntimeError::new_err("callback lock poisoned"))? = None;
        if !message.is_empty() {
            self.shared.set_error(message);
        }
        Ok(())
    }
}
