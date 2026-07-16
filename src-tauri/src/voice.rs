//! On-device push-to-talk voice transcription.
//!
//! Audio is captured with `cpal`, downsampled to 16 kHz mono, and fed to a
//! locally-loaded ASR model. Whisper uses whisper.cpp via `whisper-rs`
//! (Metal-accelerated on macOS); Parakeet uses an int8 sherpa-onnx export. While
//! the user holds the key, we re-transcribe the whole utterance every ~600 ms and
//! stream interim text to the frontend over a Tauri `Channel`; on release we run
//! one final pass and return the clean transcript.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use futures_util::StreamExt;
use serde::Serialize;
use sherpa_onnx::{OfflineRecognizer, OfflineRecognizerConfig, OfflineTransducerModelConfig};
use tauri::ipc::Channel;
use whisper_rs::{FullParams, SamplingStrategy, WhisperContext, WhisperContextParameters};

const SAMPLE_RATE: u32 = 16_000;
/// Minimum audio (in samples at 16 kHz) before we bother running ASR.
const MIN_SAMPLES: usize = SAMPLE_RATE as usize / 2; // 0.5s
/// How long to wait between interim transcription passes.
const INTERIM_INTERVAL_MS: u64 = 600;
/// How long the capture loop will run without a frontend keepalive before it
/// gives up and stops itself. The frontend pings `voice_keepalive` every ~1s
/// while the recording indicator is on screen, so if the webview that owns the
/// session goes away (HMR swap, page refresh, crash, lost focus) the loop
/// self-terminates within this window instead of spinning forever. This is a
/// liveness lease, NOT a cap on utterance length — an active dictation refreshes
/// it continuously and can run as long as the user holds the key.
const LEASE_TIMEOUT: Duration = Duration::from_secs(4);
/// Peak amplitude below which a buffer is treated as silence (no speech).
const SILENCE_PEAK: f32 = 0.01;

// ---------------------------------------------------------------------------
// Model registry
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ModelKind {
    Whisper,
    SherpaParakeetTdt,
}

#[derive(Clone, Copy, Debug)]
struct ModelFile {
    relative_path: &'static str,
    download_url: &'static str,
    fallback_url: Option<&'static str>,
    size: Option<u64>,
}

#[derive(Clone, Copy, Debug)]
struct ModelInfo {
    kind: ModelKind,
    files: &'static [ModelFile],
}

const WHISPER_BASE_FILES: &[ModelFile] = &[ModelFile {
    relative_path: "ggml-base.bin",
    download_url: "https://models.stimma.ai/whisper/ggml-base.bin",
    fallback_url: Some("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"),
    size: Some(147_951_465),
}];

const WHISPER_SMALL_FILES: &[ModelFile] = &[ModelFile {
    relative_path: "ggml-small.bin",
    download_url: "https://models.stimma.ai/whisper/ggml-small.bin",
    fallback_url: Some("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"),
    size: Some(487_601_967),
}];

const PARAKEET_TDT_06B_V2_FILES: &[ModelFile] = &[
    ModelFile {
        relative_path: "parakeet-tdt-0.6b-v2-int8/encoder.int8.onnx",
        download_url:
            "https://models.stimma.ai/parakeet/parakeet-tdt-0.6b-v2-int8/encoder.int8.onnx",
        fallback_url: Some(
            "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/encoder.int8.onnx",
        ),
        size: Some(652_184_296),
    },
    ModelFile {
        relative_path: "parakeet-tdt-0.6b-v2-int8/decoder.int8.onnx",
        download_url:
            "https://models.stimma.ai/parakeet/parakeet-tdt-0.6b-v2-int8/decoder.int8.onnx",
        fallback_url: Some(
            "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/decoder.int8.onnx",
        ),
        size: Some(7_257_753),
    },
    ModelFile {
        relative_path: "parakeet-tdt-0.6b-v2-int8/joiner.int8.onnx",
        download_url:
            "https://models.stimma.ai/parakeet/parakeet-tdt-0.6b-v2-int8/joiner.int8.onnx",
        fallback_url: Some(
            "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/joiner.int8.onnx",
        ),
        size: Some(1_739_080),
    },
    ModelFile {
        relative_path: "parakeet-tdt-0.6b-v2-int8/tokens.txt",
        download_url: "https://models.stimma.ai/parakeet/parakeet-tdt-0.6b-v2-int8/tokens.txt",
        fallback_url: Some(
            "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/tokens.txt",
        ),
        size: Some(9_384),
    },
];

/// Returns metadata for a known model id, or `None`.
fn model_info(model_id: &str) -> Option<ModelInfo> {
    // Weights are primarily served from our R2 bucket (free, unmetered egress).
    // Whisper comes from "ggerganov/whisper.cpp"; Parakeet v2 int8 comes from
    // the sherpa-onnx export of NVIDIA's English-only Parakeet TDT 0.6B v2 model.
    match model_id {
        "base" => Some(ModelInfo {
            kind: ModelKind::Whisper,
            files: WHISPER_BASE_FILES,
        }),
        "small" => Some(ModelInfo {
            kind: ModelKind::Whisper,
            files: WHISPER_SMALL_FILES,
        }),
        "parakeet-tdt-0.6b-v2" => Some(ModelInfo {
            kind: ModelKind::SherpaParakeetTdt,
            files: PARAKEET_TDT_06B_V2_FILES,
        }),
        _ => None,
    }
}

// Mirrors backend/privacy_lockdown.py: truthy values of STIMMA_PRIVACY_LOCKDOWN.
fn privacy_lockdown_enabled() -> bool {
    std::env::var("STIMMA_PRIVACY_LOCKDOWN")
        .map(|v| {
            matches!(
                v.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false)
}

fn models_dir(app: &tauri::AppHandle) -> PathBuf {
    let bundle_id = app.config().identifier.clone();
    let (_data, cache) = crate::get_app_dirs(&bundle_id);
    cache.join("whisper-models")
}

fn model_file_path(app: &tauri::AppHandle, file: &ModelFile) -> PathBuf {
    models_dir(app).join(file.relative_path)
}

fn model_primary_path(app: &tauri::AppHandle, model_id: &str) -> Result<PathBuf, String> {
    let info = model_info(model_id).ok_or_else(|| format!("unknown model: {model_id}"))?;
    let file = info
        .files
        .first()
        .ok_or_else(|| format!("model {model_id} has no files"))?;
    Ok(model_file_path(app, file))
}

fn model_dir(app: &tauri::AppHandle, model_id: &str) -> Result<PathBuf, String> {
    Ok(model_primary_path(app, model_id)?
        .parent()
        .ok_or_else(|| format!("model {model_id} has no parent directory"))?
        .to_path_buf())
}

fn model_is_downloaded(app: &tauri::AppHandle, model_id: &str) -> Result<bool, String> {
    let info = model_info(model_id).ok_or_else(|| format!("unknown model: {model_id}"))?;
    Ok(info.files.iter().all(|file| {
        let path = model_file_path(app, file);
        path.is_file() && path.metadata().map(|m| m.len() > 0).unwrap_or(false)
    }))
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/// A live capture/transcription session. The worker thread owns the cpal
/// stream (which is `!Send`); we communicate with it through these shared
/// flags and the result slot.
struct Session {
    stop: Arc<AtomicBool>,
    finished: Arc<AtomicBool>,
    result: Arc<Mutex<String>>,
    /// Last time the frontend confirmed it's still alive (see `LEASE_TIMEOUT`).
    last_seen: Arc<Mutex<Instant>>,
}

pub struct VoiceState {
    /// Cached loaded model, keyed by model id, kept warm across sessions.
    model: Mutex<Option<(String, LoadedModel)>>,
    session: Mutex<Option<Session>>,
}

impl VoiceState {
    pub fn new() -> Self {
        Self {
            model: Mutex::new(None),
            session: Mutex::new(None),
        }
    }
}

#[derive(Clone)]
enum LoadedModel {
    Whisper(Arc<WhisperContext>),
    SherpaParakeetTdt(Arc<OfflineRecognizer>),
}

/// Loads the requested model, reusing the cached context when the id matches.
fn ensure_model(
    state: &VoiceState,
    app: &tauri::AppHandle,
    model_id: &str,
) -> Result<LoadedModel, String> {
    let mut guard = state.model.lock().unwrap();
    if let Some((id, model)) = guard.as_ref() {
        if id == model_id {
            return Ok(model.clone());
        }
    }

    if !model_is_downloaded(app, model_id)? {
        return Err(format!("model {model_id} not downloaded"));
    }

    let info = model_info(model_id).ok_or_else(|| format!("unknown model: {model_id}"))?;
    let model = match info.kind {
        ModelKind::Whisper => {
            let path = model_primary_path(app, model_id)?;
            let path_str = path.to_str().ok_or("model path is not valid UTF-8")?;
            let ctx =
                WhisperContext::new_with_params(path_str, WhisperContextParameters::default())
                    .map_err(|e| format!("failed to load model: {e}"))?;
            LoadedModel::Whisper(Arc::new(ctx))
        }
        ModelKind::SherpaParakeetTdt => {
            let dir = model_dir(app, model_id)?;
            let path = |name: &str| -> Result<String, String> {
                dir.join(name)
                    .to_str()
                    .map(|s| s.to_string())
                    .ok_or_else(|| format!("{name} path is not valid UTF-8"))
            };

            let mut config = OfflineRecognizerConfig::default();
            config.model_config.transducer = OfflineTransducerModelConfig {
                encoder: Some(path("encoder.int8.onnx")?),
                decoder: Some(path("decoder.int8.onnx")?),
                joiner: Some(path("joiner.int8.onnx")?),
            };
            config.model_config.tokens = Some(path("tokens.txt")?);
            config.model_config.model_type = Some("nemo_transducer".into());
            config.model_config.provider = Some("cpu".into());
            config.model_config.num_threads = 4;
            config.decoding_method = Some("greedy_search".into());

            let recognizer = OfflineRecognizer::create(&config)
                .ok_or_else(|| "failed to load Parakeet model".to_string())?;
            LoadedModel::SherpaParakeetTdt(Arc::new(recognizer))
        }
    };

    *guard = Some((model_id.to_string(), model.clone()));
    Ok(model)
}

// ---------------------------------------------------------------------------
// Events streamed to the frontend
// ---------------------------------------------------------------------------

#[derive(Clone, Serialize)]
#[serde(tag = "type", rename_all = "camelCase")]
pub enum DownloadEvent {
    Progress { downloaded: u64, total: Option<u64> },
    Done,
    Error { message: String },
}

#[derive(Clone, Serialize)]
#[serde(tag = "type", rename_all = "camelCase")]
pub enum TranscriptEvent {
    /// Capture started successfully (mic is live).
    Started,
    /// Interim transcript of the utterance so far.
    Partial {
        text: String,
    },
    Error {
        message: String,
    },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ModelStatus {
    base: bool,
    small: bool,
    parakeet_tdt_06b_v2: bool,
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn voice_model_status(app: tauri::AppHandle) -> Result<ModelStatus, String> {
    Ok(ModelStatus {
        base: model_is_downloaded(&app, "base")?,
        small: model_is_downloaded(&app, "small")?,
        parakeet_tdt_06b_v2: model_is_downloaded(&app, "parakeet-tdt-0.6b-v2")?,
    })
}

#[tauri::command]
pub async fn voice_download_model(
    app: tauri::AppHandle,
    model_id: String,
    on_event: Channel<DownloadEvent>,
) -> Result<(), String> {
    let result = download_model_inner(&app, &model_id, &on_event).await;
    if let Err(e) = &result {
        let _ = on_event.send(DownloadEvent::Error { message: e.clone() });
    }
    result
}

async fn download_model_inner(
    app: &tauri::AppHandle,
    model_id: &str,
    on_event: &Channel<DownloadEvent>,
) -> Result<(), String> {
    use std::io::Write;

    let info = model_info(model_id).ok_or_else(|| format!("unknown model: {model_id}"))?;
    let dir = models_dir(app);
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;

    if model_is_downloaded(app, model_id)? {
        let _ = on_event.send(DownloadEvent::Done);
        return Ok(());
    }

    // Already-downloaded models resolve above; only new downloads are blocked,
    // mirroring the backend's model_cache lockdown behavior.
    if privacy_lockdown_enabled() {
        return Err("Privacy Lockdown is on; voice model downloads are disabled".to_string());
    }

    let known_total = info
        .files
        .iter()
        .try_fold(0u64, |acc, file| file.size.map(|size| acc + size));
    let mut downloaded: u64 = info
        .files
        .iter()
        .map(|file| {
            let path = model_file_path(app, file);
            path.metadata().map(|m| m.len()).unwrap_or(0)
        })
        .sum();
    let mut last_emit: u64 = 0;

    for model_file in info.files {
        let final_path = model_file_path(app, model_file);
        if final_path.is_file() && final_path.metadata().map(|m| m.len() > 0).unwrap_or(false) {
            continue;
        }

        if let Some(parent) = final_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }

        let tmp_path = final_path.with_extension(format!(
            "{}part",
            final_path
                .extension()
                .and_then(|e| e.to_str())
                .map(|e| format!("{e}."))
                .unwrap_or_default()
        ));
        let mut resp = None;
        let mut errors = Vec::new();
        for url in [Some(model_file.download_url), model_file.fallback_url]
            .into_iter()
            .flatten()
        {
            match reqwest::get(url).await {
                Ok(candidate) if candidate.status().is_success() => {
                    resp = Some(candidate);
                    break;
                }
                Ok(candidate) => {
                    errors.push(format!("{url} returned {}", candidate.status()));
                }
                Err(e) => {
                    errors.push(format!("{url} failed: {e}"));
                }
            }
        }
        let resp = resp.ok_or_else(|| {
            format!(
                "download failed for {}: {}",
                model_file.relative_path,
                errors.join("; ")
            )
        })?;
        let fallback_total = resp.content_length().map(|total| downloaded + total);
        let total = known_total.or(fallback_total);

        let mut file = std::fs::File::create(&tmp_path).map_err(|e| e.to_string())?;
        let mut stream = resp.bytes_stream();

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| e.to_string())?;
            file.write_all(&chunk).map_err(|e| e.to_string())?;
            downloaded += chunk.len() as u64;
            // Throttle progress events to ~1 per MB.
            if downloaded - last_emit >= 1_000_000 {
                last_emit = downloaded;
                let _ = on_event.send(DownloadEvent::Progress { downloaded, total });
            }
        }
        file.flush().map_err(|e| e.to_string())?;
        drop(file);

        std::fs::rename(&tmp_path, &final_path).map_err(|e| e.to_string())?;
    }

    let _ = on_event.send(DownloadEvent::Done);
    Ok(())
}

#[tauri::command]
pub async fn voice_start(
    app: tauri::AppHandle,
    state: tauri::State<'_, Arc<VoiceState>>,
    model_id: String,
    on_event: Channel<TranscriptEvent>,
) -> Result<(), String> {
    // Tear down any previous session first.
    if let Some(prev) = state.session.lock().unwrap().take() {
        prev.stop.store(true, Ordering::SeqCst);
    }

    let model = ensure_model(&state, &app, &model_id)?;

    let stop = Arc::new(AtomicBool::new(false));
    let finished = Arc::new(AtomicBool::new(false));
    let result = Arc::new(Mutex::new(String::new()));
    let last_seen = Arc::new(Mutex::new(Instant::now()));

    {
        let mut s = state.session.lock().unwrap();
        *s = Some(Session {
            stop: stop.clone(),
            finished: finished.clone(),
            result: result.clone(),
            last_seen: last_seen.clone(),
        });
    }

    // The cpal stream is `!Send`, so it must be built and dropped on the same
    // thread. We own the whole capture+decode loop here.
    std::thread::spawn(move || {
        capture_and_transcribe(model, stop, finished, result, last_seen, on_event);
    });

    Ok(())
}

#[tauri::command]
pub async fn voice_stop(state: tauri::State<'_, Arc<VoiceState>>) -> Result<String, String> {
    let session = state.session.lock().unwrap().take();
    let session = match session {
        Some(s) => s,
        None => return Ok(String::new()),
    };

    session.stop.store(true, Ordering::SeqCst);

    // Wait for the worker to run its final pass (bounded so we never hang).
    for _ in 0..200 {
        if session.finished.load(Ordering::SeqCst) {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }

    let text = session.result.lock().unwrap().clone();
    Ok(text)
}

#[tauri::command]
pub async fn voice_cancel(state: tauri::State<'_, Arc<VoiceState>>) -> Result<(), String> {
    if let Some(session) = state.session.lock().unwrap().take() {
        session.stop.store(true, Ordering::SeqCst);
    }
    Ok(())
}

/// Renew the liveness lease on the active session. The frontend calls this on a
/// timer while the recording indicator is visible; if it stops (because the
/// owning webview reloaded, crashed, or lost focus), the capture loop notices
/// the stale lease and stops itself. See `LEASE_TIMEOUT`.
#[tauri::command]
pub async fn voice_keepalive(state: tauri::State<'_, Arc<VoiceState>>) -> Result<(), String> {
    if let Some(session) = state.session.lock().unwrap().as_ref() {
        *session.last_seen.lock().unwrap() = Instant::now();
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Capture + transcription worker (runs on its own thread)
// ---------------------------------------------------------------------------

fn capture_and_transcribe(
    model: LoadedModel,
    stop: Arc<AtomicBool>,
    finished: Arc<AtomicBool>,
    result: Arc<Mutex<String>>,
    last_seen: Arc<Mutex<Instant>>,
    on_event: Channel<TranscriptEvent>,
) {
    // Ensure `finished` is always set, even on early return, so voice_stop
    // never waits the full timeout.
    struct FinishGuard(Arc<AtomicBool>);
    impl Drop for FinishGuard {
        fn drop(&mut self) {
            self.0.store(true, Ordering::SeqCst);
        }
    }
    let _guard = FinishGuard(finished.clone());

    let fail = |msg: String| {
        log::error!("[voice] {msg}");
        let _ = on_event.send(TranscriptEvent::Error { message: msg });
    };

    let host = cpal::default_host();
    let device = match host.default_input_device() {
        Some(d) => d,
        None => return fail("No microphone found".into()),
    };
    let config = match device.default_input_config() {
        Ok(c) => c,
        Err(e) => return fail(format!("Could not open microphone: {e}")),
    };

    let in_rate = config.sample_rate().0;
    let channels = config.channels() as usize;
    let sample_format = config.sample_format();
    let stream_cfg: cpal::StreamConfig = config.into();

    // Raw mono samples at the device's native rate.
    let raw: Arc<Mutex<Vec<f32>>> = Arc::new(Mutex::new(Vec::new()));
    let err_fn = |e| log::error!("[voice] stream error: {e}");

    let stream = match sample_format {
        cpal::SampleFormat::F32 => {
            let raw_cb = raw.clone();
            device.build_input_stream(
                &stream_cfg,
                move |data: &[f32], _: &_| push_mono(&raw_cb, data, channels, |s| s),
                err_fn,
                None,
            )
        }
        cpal::SampleFormat::I16 => {
            let raw_cb = raw.clone();
            device.build_input_stream(
                &stream_cfg,
                move |data: &[i16], _: &_| {
                    push_mono(&raw_cb, data, channels, |s| s as f32 / 32768.0)
                },
                err_fn,
                None,
            )
        }
        cpal::SampleFormat::U16 => {
            let raw_cb = raw.clone();
            device.build_input_stream(
                &stream_cfg,
                move |data: &[u16], _: &_| {
                    push_mono(&raw_cb, data, channels, |s| (s as f32 - 32768.0) / 32768.0)
                },
                err_fn,
                None,
            )
        }
        other => return fail(format!("Unsupported audio sample format: {other:?}")),
    };

    let stream = match stream {
        Ok(s) => s,
        Err(e) => return fail(format!("Could not start microphone: {e}")),
    };
    if let Err(e) = stream.play() {
        return fail(format!("Could not start microphone: {e}"));
    }

    log::info!(
        "[voice] capturing from '{}' @ {} Hz, {} ch, {:?}",
        device.name().unwrap_or_else(|_| "unknown".into()),
        in_rate,
        channels,
        sample_format
    );
    let _ = on_event.send(TranscriptEvent::Started);

    loop {
        // Sleep up to the interim interval, but wake promptly on stop.
        let mut waited = 0u64;
        while waited < INTERIM_INTERVAL_MS && !stop.load(Ordering::SeqCst) {
            std::thread::sleep(Duration::from_millis(50));
            waited += 50;
        }
        let stopping = stop.load(Ordering::SeqCst);

        // Liveness lease: if the frontend that owns this session has stopped
        // renewing it, the recording indicator is no longer on screen, so this
        // capture is orphaned (webview reloaded/crashed, key release lost, etc).
        // Abandon it without committing rather than transcribe into the void.
        if !stopping && last_seen.lock().unwrap().elapsed() > LEASE_TIMEOUT {
            log::warn!(
                "[voice] frontend lease expired (>{}s without keepalive) — stopping orphaned capture",
                LEASE_TIMEOUT.as_secs()
            );
            break;
        }

        let samples = {
            let buf = raw.lock().unwrap();
            resample_to_16k(&buf, in_rate)
        };
        let peak = samples.iter().fold(0.0f32, |m, &s| m.max(s.abs()));

        // Skip near-silent buffers: Whisper otherwise hallucinates non-speech
        // annotations like "[BLANK_AUDIO]" on silence.
        let speech = samples.len() >= MIN_SAMPLES && peak >= SILENCE_PEAK;

        if speech {
            match run_transcription(&model, &samples) {
                Ok(text) => {
                    let cleaned = clean_transcript(&model, &text);
                    if stopping {
                        *result.lock().unwrap() = cleaned;
                    } else if !cleaned.is_empty() {
                        let _ = on_event.send(TranscriptEvent::Partial { text: cleaned });
                    }
                }
                Err(e) => log::error!("[voice] transcription failed: {e}"),
            }
        } else if stopping {
            log::info!(
                "[voice] no speech captured (samples={}, peak={:.4})",
                samples.len(),
                peak
            );
        }

        if stopping {
            break;
        }
    }

    drop(stream);
    // `_guard` sets `finished` on drop here.
}

/// Downmix interleaved frames to mono and append to the shared buffer.
fn push_mono<T: Copy>(
    buf: &Arc<Mutex<Vec<f32>>>,
    data: &[T],
    channels: usize,
    to_f32: impl Fn(T) -> f32,
) {
    if channels == 0 {
        return;
    }
    let mut b = buf.lock().unwrap();
    for frame in data.chunks(channels) {
        let sum: f32 = frame.iter().map(|&s| to_f32(s)).sum();
        b.push(sum / channels as f32);
    }
}

fn run_transcription(model: &LoadedModel, samples: &[f32]) -> Result<String, String> {
    match model {
        LoadedModel::Whisper(ctx) => run_whisper(ctx, samples),
        LoadedModel::SherpaParakeetTdt(recognizer) => run_parakeet(recognizer, samples),
    }
}

fn run_whisper(ctx: &WhisperContext, samples: &[f32]) -> Result<String, String> {
    let mut state = ctx.create_state().map_err(|e| e.to_string())?;

    let mut params = FullParams::new(SamplingStrategy::Greedy { best_of: 1 });
    params.set_n_threads(4);
    params.set_translate(false);
    // Let multilingual Whisper detect the spoken language.
    params.set_language(None);
    params.set_print_special(false);
    params.set_print_progress(false);
    params.set_print_realtime(false);
    params.set_print_timestamps(false);
    params.set_suppress_blank(true);

    state.full(params, samples).map_err(|e| e.to_string())?;

    let n = state.full_n_segments().map_err(|e| e.to_string())?;
    let mut out = String::new();
    for i in 0..n {
        let seg = state.full_get_segment_text(i).map_err(|e| e.to_string())?;
        out.push_str(&seg);
    }
    Ok(out.trim().to_string())
}

fn run_parakeet(recognizer: &OfflineRecognizer, samples: &[f32]) -> Result<String, String> {
    let stream = recognizer.create_stream();
    stream.accept_waveform(SAMPLE_RATE as i32, samples);
    recognizer.decode(&stream);
    let result = stream
        .get_result()
        .ok_or_else(|| "failed to decode Parakeet transcript".to_string())?;
    Ok(result.text.trim().to_string())
}

fn clean_transcript(model: &LoadedModel, text: &str) -> String {
    match model {
        LoadedModel::Whisper(_) => clean_whisper_transcript(text),
        LoadedModel::SherpaParakeetTdt(_) => collapse_whitespace(text),
    }
}

/// Strips Whisper's non-speech annotations, e.g. `[BLANK_AUDIO]`, `(music)`,
/// `*laughs*`, which it emits during silence or background noise.
fn clean_whisper_transcript(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut depth: i32 = 0;
    for ch in text.chars() {
        match ch {
            '[' | '(' => depth += 1,
            ']' | ')' => depth = (depth - 1).max(0),
            '*' => {}
            _ if depth == 0 => out.push(ch),
            _ => {}
        }
    }
    // Collapse whitespace left behind by removed annotations.
    collapse_whitespace(&out)
}

fn collapse_whitespace(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

// ---------------------------------------------------------------------------
// Resampling (device rate -> 16 kHz mono)
// ---------------------------------------------------------------------------

fn resample_to_16k(input: &[f32], in_rate: u32) -> Vec<f32> {
    if input.is_empty() {
        return Vec::new();
    }
    if in_rate == SAMPLE_RATE {
        return input.to_vec();
    }
    let ratio = SAMPLE_RATE as f64 / in_rate as f64;
    if ratio < 1.0 {
        // Downsampling: box-filter low-pass before decimation to curb aliasing.
        let width = (in_rate as f64 / SAMPLE_RATE as f64).round().max(1.0) as usize;
        let filtered = box_lowpass(input, width);
        linear_resample(&filtered, ratio)
    } else {
        linear_resample(input, ratio)
    }
}

/// Causal moving-average low-pass.
fn box_lowpass(input: &[f32], width: usize) -> Vec<f32> {
    if width <= 1 {
        return input.to_vec();
    }
    let mut out = Vec::with_capacity(input.len());
    let mut acc = 0.0f32;
    for i in 0..input.len() {
        acc += input[i];
        if i >= width {
            acc -= input[i - width];
        }
        let denom = if i + 1 < width { i + 1 } else { width } as f32;
        out.push(acc / denom);
    }
    out
}

fn linear_resample(input: &[f32], ratio: f64) -> Vec<f32> {
    let out_len = ((input.len() as f64) * ratio).round() as usize;
    let mut out = Vec::with_capacity(out_len);
    for i in 0..out_len {
        let src = i as f64 / ratio;
        let idx = src.floor() as usize;
        let frac = (src - idx as f64) as f32;
        let a = input.get(idx).copied().unwrap_or(0.0);
        let b = input.get(idx + 1).copied().unwrap_or(a);
        out.push(a + (b - a) * frac);
    }
    out
}
