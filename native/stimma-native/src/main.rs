//! stimma-native: dictation + drag-out metadata embedding helper.
//!
//! Spawned once per app instance by the desktop shell:
//!   stimma-native --cache-dir <app cache dir> [--fixture-wav <wav>]
//!
//! Speaks the JSON-lines protocol in protocol.rs over stdio. Logs to stderr.
//! Exits when stdin closes (parent death) after cancelling any live capture.

mod embed;
mod protocol;
mod voice;

use std::io::BufRead;
use std::path::PathBuf;
use std::sync::Arc;

use protocol::{EventSink, Writer, MAX_LINE_BYTES};
use voice::VoiceService;

fn arg_value(args: &[String], flag: &str) -> Option<String> {
    args.iter()
        .position(|a| a == flag)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .target(env_logger::Target::Stderr)
        .init();

    let args: Vec<String> = std::env::args().collect();
    let cache_dir = match arg_value(&args, "--cache-dir") {
        Some(dir) => PathBuf::from(dir),
        None => {
            eprintln!("stimma-native: --cache-dir is required");
            std::process::exit(2);
        }
    };
    let fixture_wav = arg_value(&args, "--fixture-wav").map(PathBuf::from);

    voice::cleanup_legacy_models(&cache_dir);

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("build tokio runtime");

    let writer = Writer::new();
    let voice_service = Arc::new(VoiceService::new(cache_dir.clone(), fixture_wav));

    let stdin = std::io::stdin();
    let mut line = String::new();
    let mut reader = stdin.lock();

    loop {
        line.clear();
        // Bounded read: take_line semantics with a hard cap.
        let mut limited = std::io::Read::take(&mut reader, (MAX_LINE_BYTES + 1) as u64);
        let read = match limited.read_line(&mut line) {
            Ok(0) => break, // EOF: parent is gone.
            Ok(n) => n,
            Err(e) => {
                log::error!("stdin read error: {e}");
                break;
            }
        };
        if read > MAX_LINE_BYTES {
            log::error!("request line exceeds {MAX_LINE_BYTES} bytes; dropping");
            continue;
        }
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let parsed: serde_json::Value = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(e) => {
                log::error!("bad request line: {e}");
                continue;
            }
        };
        let Some(id) = parsed.get("id").and_then(|v| v.as_u64()) else {
            log::error!("request missing id");
            continue;
        };
        let method = parsed.get("method").and_then(|v| v.as_str()).unwrap_or("");
        let params = parsed.get("params").cloned().unwrap_or(serde_json::Value::Null);

        handle_request(&runtime, &writer, &voice_service, &cache_dir, id, method, params);
    }

    voice_service.shutdown();
}

fn handle_request(
    runtime: &tokio::runtime::Runtime,
    writer: &Writer,
    voice_service: &Arc<VoiceService>,
    cache_dir: &PathBuf,
    id: u64,
    method: &str,
    params: serde_json::Value,
) {
    match method {
        "ping" => writer.respond_ok(id, serde_json::json!("pong")),

        "embed_metadata" => {
            match serde_json::from_value::<embed::EmbedRequest>(params) {
                Ok(req) => match embed::embed_metadata_sync(req, cache_dir.clone()) {
                    Ok(path) => writer.respond_ok(id, serde_json::json!(path)),
                    Err(e) => writer.respond_err(id, &e),
                },
                Err(e) => writer.respond_err(id, &format!("invalid embed request: {e}")),
            }
        }

        "voice_model_status" => {
            writer.respond_ok(id, serde_json::json!(voice_service.model_is_downloaded()))
        }

        "voice_download_model" => {
            let events = EventSink::new(writer.clone(), "voice_download", id);
            let result = runtime.block_on(voice_service.download_model(&events));
            match result {
                Ok(()) => writer.respond_ok(id, serde_json::Value::Null),
                Err(e) => writer.respond_err(id, &e),
            }
        }

        "voice_start" => {
            let events = EventSink::new(writer.clone(), "voice_transcript", id);
            match voice_service.start(events) {
                Ok(()) => writer.respond_ok(id, serde_json::Value::Null),
                Err(e) => writer.respond_err(id, &e),
            }
        }

        "voice_stop" => match runtime.block_on(voice_service.stop()) {
            Ok(text) => writer.respond_ok(id, serde_json::json!(text)),
            Err(e) => writer.respond_err(id, &e),
        },

        "voice_cancel" => {
            voice_service.cancel();
            writer.respond_ok(id, serde_json::Value::Null);
        }

        "voice_keepalive" => {
            voice_service.keepalive();
            writer.respond_ok(id, serde_json::Value::Null);
        }

        other => writer.respond_err(id, &format!("unknown method: {other}")),
    }
}
