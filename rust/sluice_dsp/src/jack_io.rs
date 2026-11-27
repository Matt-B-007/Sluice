// SPDX-License-Identifier: GPL-3.0-or-later
//! Sluice's connection to PipeWire (through its JACK layer): the client, the ports, the block callback, and the
//! measuring of how long each block takes and whose dropouts they are. libjack is loaded when the client is opened, so
//! the module builds and imports without it. 0.13.1: while every channel's chain is one of Sluice's own Rust effects, the
//! block is mixed by the native graph (graph.rs) without Python at all; otherwise (a VST3 plugin, the Effects window's live
//! view, "Measure my room") the mixing is called in Python, as before.
use jack::{
    AsyncClient, AudioIn, AudioOut, Client, ClientOptions, ClientStatus, Control, Port,
    ProcessScope,
};
use numpy::{PyArray2, PyArrayMethods, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use crate::graph::GraphCore;
use crate::NativeGraph;

const SLOW_BLOCK: f64 = 0.7; // a block that used more than this share of its time counts as Sluice running late
const RECENT: usize = 8; // 0.11.1: the last blocks remembered for deciding whose dropout it was

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
    // 0.11.1: the last few blocks (start, busy), because a dropout is reported a moment after the block that caused it, often
    // when a quick block has run since; and how long each block waited for Python's lock before its own work could start
    recent_start_ns: [AtomicU64; RECENT],
    recent_busy_ns: [AtomicU64; RECENT],
    block_index: AtomicU64,
    wait_ns: AtomicU64,
    wait_sum_ns: AtomicU64,
    wait_peak_ns: AtomicU64,
    peak_block_wait_ns: AtomicU64,
    wait_blocks_seen: AtomicU64,
    // 0.13.1: the native graph, and whether it runs the blocks (Python decides; the switch takes effect at the next block)
    native: Mutex<Option<Arc<Mutex<GraphCore>>>>,
    native_on: AtomicBool,
    native_blocks: AtomicU64,
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
    fn run_python(
        &self,
        ports: &mut Ports,
        ps: &ProcessScope,
        frames: usize,
        start: u64,
    ) -> PyResult<()> {
        Python::attach(|py| {
            // the time until Python's lock was ours: spent waiting for another thread (the window), not working
            let s = &self.shared;
            s.wait_ns
                .store(s.now_ns().saturating_sub(start), Ordering::Relaxed);
            let cb = {
                let guard = self
                    .shared
                    .callback
                    .lock()
                    .map_err(|_| PyRuntimeError::new_err("callback lock poisoned"))?;
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
                            return Err(PyValueError::new_err(
                                "a mix block must have shape (2, frames)",
                            ));
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

impl Proc {
    /// 0.13.1: one block mixed by the native graph: no Python, no waiting for Python's lock. False when there is no graph.
    fn run_native(&self, ports: &mut Ports, ps: &ProcessScope, frames: usize) -> bool {
        let core = match self.shared.native.lock() {
            Ok(n) => match n.as_ref() {
                Some(core) => core.clone(),
                None => return false,
            },
            Err(_) => return false,
        };
        // the control side holds this lock only to change a setting (microseconds)
        let mut graph = core.lock().unwrap_or_else(|e| e.into_inner());
        let Ports { inputs, outputs } = ports;
        graph.process(frames, |id| {
            inputs
                .get(id)
                .map(|(l, r)| (l.as_slice(ps), r.as_slice(ps)))
        });
        for (id, (l, r)) in outputs.iter_mut() {
            let (lo, ro) = (l.as_mut_slice(ps), r.as_mut_slice(ps));
            let source = if let Some(mix) = graph.mixes.iter().find(|m| &m.id == id) {
                Some(&mix.out)
            } else if let Some(cid) = id.strip_prefix("solo_") {
                graph
                    .channels
                    .iter()
                    .find(|c| c.id == cid && c.solo_gain.is_some())
                    .map(|c| &c.solo_out)
            } else {
                None
            };
            match source {
                Some(buf) => {
                    for (i, (a, b)) in lo.iter_mut().zip(ro.iter_mut()).enumerate() {
                        *a = buf[0].get(i).copied().unwrap_or(0.0);
                        *b = buf[1].get(i).copied().unwrap_or(0.0);
                    }
                }
                None => {
                    lo.fill(0.0);
                    ro.fill(0.0);
                }
            }
        }
        self.shared.native_blocks.fetch_add(1, Ordering::Relaxed);
        true
    }
}

impl jack::ProcessHandler for Proc {
    fn process(&mut self, _: &Client, ps: &ProcessScope) -> Control {
        let s = &self.shared;
        let start = s.now_ns();
        s.block_start_ns.store(start, Ordering::Relaxed);
        s.in_block.store(true, Ordering::Release);
        s.wait_ns.store(0, Ordering::Relaxed);
        let frames = ps.n_frames() as usize;
        if let Ok(mut ports) = s.ports.try_lock() {
            if s.native_on.load(Ordering::Acquire) && self.run_native(&mut ports, ps, frames) {
                // mixed in Rust
            } else if let Err(e) = self.run_python(&mut ports, ps, frames, start) {
                // never let a failure reach the audio thread: say it, and play silence
                let text = Python::attach(|py| {
                    format!(
                        "{}: {}",
                        e.get_type(py)
                            .name()
                            .map(|n| n.to_string())
                            .unwrap_or_default(),
                        e.value(py)
                    )
                });
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
        let wait = s.wait_ns.load(Ordering::Relaxed);
        s.wait_sum_ns.fetch_add(wait, Ordering::Relaxed);
        s.wait_peak_ns.fetch_max(wait, Ordering::Relaxed);
        if s.busy_peak_ns.fetch_max(busy, Ordering::Relaxed) < busy {
            s.peak_block_wait_ns.store(wait, Ordering::Relaxed); // how much of the slowest block was waiting
        }
        let slot = (s.block_index.fetch_add(1, Ordering::Relaxed) as usize) % RECENT;
        s.recent_start_ns[slot].store(start, Ordering::Relaxed);
        s.recent_busy_ns[slot].store(busy, Ordering::Relaxed);
        Control::Continue
    }
}

struct Notify {
    shared: Arc<Shared>,
}

impl jack::NotificationHandler for Notify {
    unsafe fn shutdown(&mut self, _status: ClientStatus, reason: &str) {
        self.shared
            .set_error(format!("Audio server shut down: {reason}"));
    }
    fn xrun(&mut self, _: &Client) -> Control {
        let s = &self.shared;
        s.xruns.fetch_add(1, Ordering::Relaxed);
        // Ours if a block of Sluice's used most of its time just before: the one running now, or one of the last few (0.11.1:
        // only the last one was looked at, and by the time the dropout was reported a quick block had often run since).
        let now = s.now_ns();
        let mut busy = if s.in_block.load(Ordering::Acquire) {
            now.saturating_sub(s.block_start_ns.load(Ordering::Relaxed))
        } else {
            s.last_busy_ns.load(Ordering::Relaxed)
        };
        let window = s.period_ns.saturating_mul(RECENT as u64);
        for (start, took) in s.recent_start_ns.iter().zip(&s.recent_busy_ns) {
            if now.saturating_sub(start.load(Ordering::Relaxed)) <= window {
                busy = busy.max(took.load(Ordering::Relaxed));
            }
        }
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
        let opened = py.detach(|| {
            Client::new(
                &name,
                ClientOptions::NO_START_SERVER | ClientOptions::USE_EXACT_NAME,
            )
        });
        let (client, status) = opened.map_err(|e| PyRuntimeError::new_err(format!("{e:?}")))?;
        let sample_rate = client.sample_rate();
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
            recent_start_ns: std::array::from_fn(|_| AtomicU64::new(0)),
            recent_busy_ns: std::array::from_fn(|_| AtomicU64::new(0)),
            block_index: AtomicU64::new(0),
            wait_ns: AtomicU64::new(0),
            wait_sum_ns: AtomicU64::new(0),
            wait_peak_ns: AtomicU64::new(0),
            peak_block_wait_ns: AtomicU64::new(0),
            wait_blocks_seen: AtomicU64::new(0),
            native: Mutex::new(None),
            native_on: AtomicBool::new(false),
            native_blocks: AtomicU64::new(0),
        });
        Ok(JackEngine {
            state: Mutex::new(State::Idle(client)),
            shared,
            sample_rate,
            blocksize,
        })
    }

    /// 0.13.1: the native graph the blocks can be mixed by (None: always Python).
    #[pyo3(signature = (graph))]
    fn set_native(&self, graph: Option<PyRef<NativeGraph>>) {
        if graph.is_none() {
            self.shared.native_on.store(false, Ordering::Release);
        }
        if let Ok(mut n) = self.shared.native.lock() {
            *n = graph.map(|g| g.core.clone());
        }
    }
    /// 0.13.1: mix the next blocks in the native graph (true) or in Python (false).
    fn use_native(&self, on: bool) {
        self.shared.native_on.store(on, Ordering::Release);
    }
    #[getter]
    fn native_on(&self) -> bool {
        self.shared.native_on.load(Ordering::Acquire)
    }
    /// How many blocks the native graph has mixed so far (for the bug report).
    #[getter]
    fn native_blocks(&self) -> u64 {
        self.shared.native_blocks.load(Ordering::Relaxed)
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
        self.shared
            .error
            .lock()
            .map(|e| e.clone())
            .unwrap_or_default()
    }
    #[setter]
    fn set_error(&self, value: String) {
        self.shared.set_error(value);
    }

    /// 0.11.1: (average, worst, in the slowest block) share of a block's time spent waiting for Python's lock before the
    /// block's own work could start, since the last call. Call it right after take_load.
    fn take_wait(&self) -> (f64, f64, f64) {
        let s = &self.shared;
        let total = s.wait_sum_ns.swap(0, Ordering::Relaxed);
        let peak = s.wait_peak_ns.swap(0, Ordering::Relaxed);
        let in_slowest = s.peak_block_wait_ns.swap(0, Ordering::Relaxed);
        let blocks = s.block_index.load(Ordering::Relaxed).max(1);
        let counted = s.wait_blocks_seen.swap(blocks, Ordering::Relaxed);
        let n = blocks.saturating_sub(counted).max(1);
        if s.period_ns == 0 {
            return (0.0, 0.0, 0.0);
        }
        let p = s.period_ns as f64;
        (
            total as f64 / n as f64 / p,
            peak as f64 / p,
            in_slowest as f64 / p,
        )
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

    fn sync_ports(
        &self,
        py: Python<'_>,
        channel_ids: Vec<String>,
        mix_ids: Vec<String>,
    ) -> PyResult<()> {
        let shared = self.shared.clone();
        let state = &self.state;
        py.detach(move || -> PyResult<()> {
            let guard = state
                .lock()
                .map_err(|_| PyRuntimeError::new_err("state lock poisoned"))?;
            let client = client_of(&guard)
                .ok_or_else(|| PyRuntimeError::new_err("the audio client is closed"))?;
            let err = |e: jack::Error| PyRuntimeError::new_err(format!("{e:?}"));
            // 1. what is missing, looked up with the lock held only for a moment (the callback keeps the whole old set meanwhile)
            let (missing_in, missing_out): (Vec<String>, Vec<String>) = {
                let ports = shared
                    .ports
                    .lock()
                    .map_err(|_| PyRuntimeError::new_err("ports lock poisoned"))?;
                (
                    channel_ids
                        .iter()
                        .filter(|id| !ports.inputs.contains_key(*id))
                        .cloned()
                        .collect(),
                    mix_ids
                        .iter()
                        .filter(|id| !ports.outputs.contains_key(*id))
                        .cloned()
                        .collect(),
                )
            };
            // 2. register the new ports without holding the lock: the callback still sees every port it had
            let mut new_in: BTreeMap<String, InPair> = BTreeMap::new();
            let mut new_out: BTreeMap<String, OutPair> = BTreeMap::new();
            for id in &missing_in {
                let l = client
                    .register_port(&format!("in_{id}_L"), AudioIn::default())
                    .map_err(err)?;
                let r = client
                    .register_port(&format!("in_{id}_R"), AudioIn::default())
                    .map_err(err)?;
                new_in.insert(id.clone(), (l, r));
            }
            for id in &missing_out {
                let l = client
                    .register_port(&format!("out_{id}_L"), AudioOut::default())
                    .map_err(err)?;
                let r = client
                    .register_port(&format!("out_{id}_R"), AudioOut::default())
                    .map_err(err)?;
                new_out.insert(id.clone(), (l, r));
            }
            // 3. one short swap under the lock: add the new ports, take out only the ports that are no longer wanted
            let (old_in, old_out) = {
                let mut ports = shared
                    .ports
                    .lock()
                    .map_err(|_| PyRuntimeError::new_err("ports lock poisoned"))?;
                ports.inputs.extend(new_in);
                ports.outputs.extend(new_out);
                let stale_in: Vec<String> = ports
                    .inputs
                    .keys()
                    .filter(|k| !channel_ids.contains(*k))
                    .cloned()
                    .collect();
                let stale_out: Vec<String> = ports
                    .outputs
                    .keys()
                    .filter(|k| !mix_ids.contains(*k))
                    .cloned()
                    .collect();
                let old_in: Vec<InPair> = stale_in
                    .iter()
                    .filter_map(|k| ports.inputs.remove(k))
                    .collect();
                let old_out: Vec<OutPair> = stale_out
                    .iter()
                    .filter_map(|k| ports.outputs.remove(k))
                    .collect();
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
        *self
            .shared
            .callback
            .lock()
            .map_err(|_| PyRuntimeError::new_err("callback lock poisoned"))? = Some(callback);
        let shared = self.shared.clone();
        let state = &self.state;
        py.detach(move || -> PyResult<()> {
            let mut guard = state
                .lock()
                .map_err(|_| PyRuntimeError::new_err("state lock poisoned"))?;
            match std::mem::replace(&mut *guard, State::Closed) {
                State::Idle(client) => {
                    match client.activate_async(
                        Notify {
                            shared: shared.clone(),
                        },
                        Proc { shared },
                    ) {
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
        *self
            .shared
            .callback
            .lock()
            .map_err(|_| PyRuntimeError::new_err("callback lock poisoned"))? = None;
        // The ports keep the JACK client alive. Let go of them now, while the server is still there, so the client is closed here and
        // not whenever Python finally frees this object (which can be after the server has gone, and libjack then crashes).
        let ports = std::mem::take(
            &mut *self
                .shared
                .ports
                .lock()
                .map_err(|_| PyRuntimeError::new_err("ports lock poisoned"))?,
        );
        py.detach(move || drop(ports));
        if !message.is_empty() {
            self.shared.set_error(message);
        }
        Ok(())
    }
}
