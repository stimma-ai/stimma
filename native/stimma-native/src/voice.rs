//! On-device push-to-talk voice transcription.
//!
//! Audio is captured with `cpal`, downsampled to 16 kHz mono, and fed to a
//! locally-loaded int8 Parakeet TDT 0.6B v3 sherpa-onnx export. While the user
//! holds the key, we re-transcribe the whole utterance every ~600 ms and stream
//! interim text over the stdio event channel; on release we run one final pass
//! and return the clean transcript.
//!
//! Moved from src-tauri/src/voice.rs; the capture/decode pipeline is
//! unchanged — only the event transport (Tauri Channel → stdio events) and
//! path resolution (AppHandle → explicit cache dir) differ.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use futures_util::StreamExt;
use serde::Serialize;
use sherpa_onnx::{OfflineRecognizer, OfflineRecognizerConfig, OfflineTransducerModelConfig};

use crate::protocol::EventSink;

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

#[derive(Clone, Copy, Debug)]
struct ModelFile {
    relative_path: &'static str,
    download_url: &'static str,
    fallback_url: Option<&'static str>,
    size: Option<u64>,
}

const MODEL_DIR_NAME: &str = "parakeet-tdt-0.6b-v3-int8";
const PARAKEET_TDT_06B_V3_FILES: &[ModelFile] = &[
    ModelFile {
        relative_path: "parakeet-tdt-0.6b-v3-int8/encoder.int8.onnx",
        download_url:
            "https://models.stimma.ai/parakeet/parakeet-tdt-0.6b-v3-int8/encoder.int8.onnx",
        fallback_url: Some(
            "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/resolve/main/encoder.int8.onnx",
        ),
        size: Some(652_184_281),
    },
    ModelFile {
        relative_path: "parakeet-tdt-0.6b-v3-int8/decoder.int8.onnx",
        download_url:
            "https://models.stimma.ai/parakeet/parakeet-tdt-0.6b-v3-int8/decoder.int8.onnx",
        fallback_url: Some(
            "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/resolve/main/decoder.int8.onnx",
        ),
        size: Some(11_845_275),
    },
    ModelFile {
        relative_path: "parakeet-tdt-0.6b-v3-int8/joiner.int8.onnx",
        download_url:
            "https://models.stimma.ai/parakeet/parakeet-tdt-0.6b-v3-int8/joiner.int8.onnx",
        fallback_url: Some(
            "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/resolve/main/joiner.int8.onnx",
        ),
        size: Some(6_355_277),
    },
    ModelFile {
        relative_path: "parakeet-tdt-0.6b-v3-int8/tokens.txt",
        download_url: "https://models.stimma.ai/parakeet/parakeet-tdt-0.6b-v3-int8/tokens.txt",
        fallback_url: Some(
            "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/resolve/main/tokens.txt",
        ),
        size: Some(93_939),
    },
];

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

pub struct VoiceService {
    /// Root cache directory for this app identity (models live below it).
    cache_dir: PathBuf,
    /// Cached loaded model, kept warm across sessions.
    model: Mutex<Option<Arc<OfflineRecognizer>>>,
    session: Mutex<Option<Session>>,
    /// Fixture WAV mode: bypass cpal and feed this file instead (tests).
    fixture_wav: Option<PathBuf>,
}

impl VoiceService {
    pub fn new(cache_dir: PathBuf, fixture_wav: Option<PathBuf>) -> Self {
        Self {
            cache_dir,
            model: Mutex::new(None),
            session: Mutex::new(None),
            fixture_wav,
        }
    }

    fn models_dir(&self) -> PathBuf {
        self.cache_dir.join("voice-models")
    }

    fn model_file_path(&self, file: &ModelFile) -> PathBuf {
        self.models_dir().join(file.relative_path)
    }

    fn model_dir(&self) -> PathBuf {
        self.models_dir().join(MODEL_DIR_NAME)
    }

    fn model_file_is_downloaded(&self, file: &ModelFile) -> bool {
        let path = self.model_file_path(file);
        path.is_file()
            && path
                .metadata()
                .map(|metadata| match file.size {
                    Some(size) => metadata.len() == size,
                    None => metadata.len() > 0,
                })
                .unwrap_or(false)
    }

    pub fn model_is_downloaded(&self) -> bool {
        PARAKEET_TDT_06B_V3_FILES
            .iter()
            .all(|file| self.model_file_is_downloaded(file))
    }

    /// Loads Parakeet v3, reusing the cached recognizer across sessions.
    fn ensure_model(&self) -> Result<Arc<OfflineRecognizer>, String> {
        let mut guard = self.model.lock().unwrap();
        if let Some(model) = guard.as_ref() {
            return Ok(model.clone());
        }

        if !self.model_is_downloaded() {
            return Err("voice model not downloaded".into());
        }

        let model = Arc::new(create_recognizer(&self.model_dir())?);
        *guard = Some(model.clone());
        Ok(model)
    }

    // -----------------------------------------------------------------------
    // Requests
    // -----------------------------------------------------------------------

    pub async fn download_model(&self, events: &EventSink) -> Result<(), String> {
        let result = self.download_model_inner(events).await;
        if let Err(e) = &result {
            events.send(&DownloadEvent::Error { message: e.clone() });
        }
        result
    }

    async fn download_model_inner(&self, events: &EventSink) -> Result<(), String> {
        use std::io::Write;

        let dir = self.models_dir();
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;

        if self.model_is_downloaded() {
            events.send(&DownloadEvent::Done);
            return Ok(());
        }

        // Already-downloaded models resolve above; only new downloads are blocked,
        // mirroring the backend's model_cache lockdown behavior.
        if privacy_lockdown_enabled() {
            return Err("Privacy Lockdown is on; voice model downloads are disabled".to_string());
        }

        let known_total = PARAKEET_TDT_06B_V3_FILES
            .iter()
            .try_fold(0u64, |acc, file| file.size.map(|size| acc + size));
        let mut downloaded: u64 = PARAKEET_TDT_06B_V3_FILES
            .iter()
            .filter(|file| self.model_file_is_downloaded(file))
            .filter_map(|file| file.size)
            .sum();
        let mut last_emit: u64 = 0;

        for model_file in PARAKEET_TDT_06B_V3_FILES {
            let final_path = self.model_file_path(model_file);
            if self.model_file_is_downloaded(model_file) {
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
                    events.send(&DownloadEvent::Progress { downloaded, total });
                }
            }
            file.flush().map_err(|e| e.to_string())?;
            drop(file);

            if let Some(expected_size) = model_file.size {
                let actual_size = tmp_path.metadata().map_err(|e| e.to_string())?.len();
                if actual_size != expected_size {
                    return Err(format!(
                        "downloaded {} bytes for {}, expected {}",
                        actual_size, model_file.relative_path, expected_size
                    ));
                }
            }

            if final_path.exists() {
                std::fs::remove_file(&final_path).map_err(|e| e.to_string())?;
            }
            std::fs::rename(&tmp_path, &final_path).map_err(|e| e.to_string())?;
        }

        events.send(&DownloadEvent::Done);
        Ok(())
    }

    pub fn start(&self, events: EventSink) -> Result<(), String> {
        // Tear down any previous session first.
        if let Some(prev) = self.session.lock().unwrap().take() {
            prev.stop.store(true, Ordering::SeqCst);
        }

        let model = self.ensure_model()?;

        let stop = Arc::new(AtomicBool::new(false));
        let finished = Arc::new(AtomicBool::new(false));
        let result = Arc::new(Mutex::new(String::new()));
        let last_seen = Arc::new(Mutex::new(Instant::now()));

        {
            let mut s = self.session.lock().unwrap();
            *s = Some(Session {
                stop: stop.clone(),
                finished: finished.clone(),
                result: result.clone(),
                last_seen: last_seen.clone(),
            });
        }

        let fixture = self.fixture_wav.clone();
        // The cpal stream is `!Send`, so it must be built and dropped on the same
        // thread. We own the whole capture+decode loop here.
        std::thread::spawn(move || match fixture {
            Some(path) => transcribe_fixture(model, path, stop, finished, result, events),
            None => capture_and_transcribe(model, stop, finished, result, last_seen, events),
        });

        Ok(())
    }

    pub async fn stop(&self) -> Result<String, String> {
        let session = self.session.lock().unwrap().take();
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

    pub fn cancel(&self) {
        if let Some(session) = self.session.lock().unwrap().take() {
            session.stop.store(true, Ordering::SeqCst);
        }
    }

    /// Renew the liveness lease on the active session. See `LEASE_TIMEOUT`.
    pub fn keepalive(&self) {
        if let Some(session) = self.session.lock().unwrap().as_ref() {
            *session.last_seen.lock().unwrap() = Instant::now();
        }
    }

    /// Stop any active capture (used on shutdown / owner loss).
    pub fn shutdown(&self) {
        self.cancel();
    }
}

/// Remove caches created by builds that offered Whisper and Parakeet v2.
/// These are disposable model weights and can be downloaded again by an older
/// build from its upstream fallback if the user rolls back.
pub fn cleanup_legacy_models(cache_dir: &Path) {
    let legacy_dir = cache_dir.join("whisper-models");
    if !legacy_dir.exists() {
        return;
    }
    match std::fs::remove_dir_all(&legacy_dir) {
        Ok(()) => log::info!("[voice] removed legacy voice model cache"),
        Err(error) => log::warn!("[voice] failed to remove legacy voice model cache: {error}"),
    }
}

fn create_recognizer(dir: &Path) -> Result<OfflineRecognizer, String> {
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

    OfflineRecognizer::create(&config).ok_or_else(|| "failed to load Parakeet model".to_string())
}

// ---------------------------------------------------------------------------
// Events streamed to the frontend (wire format identical to the Tauri shell)
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

// ---------------------------------------------------------------------------
// Capture + transcription worker (runs on its own thread)
// ---------------------------------------------------------------------------

fn capture_and_transcribe(
    model: Arc<OfflineRecognizer>,
    stop: Arc<AtomicBool>,
    finished: Arc<AtomicBool>,
    result: Arc<Mutex<String>>,
    last_seen: Arc<Mutex<Instant>>,
    on_event: EventSink,
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
        on_event.send(&TranscriptEvent::Error { message: msg });
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
    on_event.send(&TranscriptEvent::Started);

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

        // Skip near-silent buffers rather than feeding background noise to ASR.
        let speech = samples.len() >= MIN_SAMPLES && peak >= SILENCE_PEAK;

        if speech {
            match run_parakeet(&model, &samples) {
                Ok(text) => {
                    let cleaned = collapse_whitespace(&text);
                    if stopping {
                        *result.lock().unwrap() = cleaned;
                    } else if !cleaned.is_empty() {
                        on_event.send(&TranscriptEvent::Partial { text: cleaned });
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

/// Fixture mode: transcribe a WAV file instead of capturing the mic. Used by
/// the protocol tests so the full start → partial → stop → final flow can run
/// headless. Emits one partial, waits for stop, then commits the final text.
fn transcribe_fixture(
    model: Arc<OfflineRecognizer>,
    wav_path: PathBuf,
    stop: Arc<AtomicBool>,
    finished: Arc<AtomicBool>,
    result: Arc<Mutex<String>>,
    on_event: EventSink,
) {
    struct FinishGuard(Arc<AtomicBool>);
    impl Drop for FinishGuard {
        fn drop(&mut self) {
            self.0.store(true, Ordering::SeqCst);
        }
    }
    let _guard = FinishGuard(finished);

    let wave = match sherpa_onnx::Wave::read(&wav_path.to_string_lossy()) {
        Some(w) => w,
        None => {
            on_event.send(&TranscriptEvent::Error {
                message: format!("failed to read fixture wav: {}", wav_path.display()),
            });
            return;
        }
    };
    on_event.send(&TranscriptEvent::Started);

    match run_parakeet(&model, wave.samples()) {
        Ok(text) => {
            let cleaned = collapse_whitespace(&text);
            on_event.send(&TranscriptEvent::Partial {
                text: cleaned.clone(),
            });
            *result.lock().unwrap() = cleaned;
        }
        Err(e) => {
            on_event.send(&TranscriptEvent::Error { message: e });
            return;
        }
    }

    // Hold the "recording" open until the caller stops, like a live session.
    while !stop.load(Ordering::SeqCst) {
        std::thread::sleep(Duration::from_millis(50));
    }
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

fn run_parakeet(recognizer: &OfflineRecognizer, samples: &[f32]) -> Result<String, String> {
    let stream = recognizer.create_stream();
    stream.accept_waveform(SAMPLE_RATE as i32, samples);
    recognizer.decode(&stream);
    let result = stream
        .get_result()
        .ok_or_else(|| "failed to decode Parakeet transcript".to_string())?;
    Ok(result.text.trim().to_string())
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

#[cfg(test)]
mod tests {
    use super::cleanup_legacy_models;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn legacy_model_cache_is_removed() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock is after epoch")
            .as_nanos();
        let cache_dir = std::env::temp_dir().join(format!(
            "stimma-voice-cleanup-{}-{nonce}",
            std::process::id()
        ));
        let legacy_dir = cache_dir.join("whisper-models/parakeet-tdt-0.6b-v2-int8");
        std::fs::create_dir_all(&legacy_dir).expect("create legacy cache fixture");
        std::fs::write(legacy_dir.join("encoder.int8.onnx"), b"old model")
            .expect("write legacy cache fixture");

        cleanup_legacy_models(&cache_dir);

        assert!(!cache_dir.join("whisper-models").exists());
        std::fs::remove_dir(cache_dir).expect("remove empty test cache");
    }
}
