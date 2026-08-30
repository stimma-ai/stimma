//! stdio JSON-lines protocol.
//!
//! stdin:  one request per line: {"id": <u64>, "method": "<name>", "params": {...}}
//! stdout: frames ONLY —
//!   response: {"id": <u64>, "result": <json>} | {"id": <u64>, "error": "<msg>"}
//!   event:    {"event": "<stream>", "id": <originating request id>, "payload": {...}}
//! stderr: logs (env_logger). Never protocol frames.
//!
//! Rules:
//! - Request ids are caller-chosen and echoed verbatim; events carry the id of
//!   the request that opened the stream (voice_download_model / voice_start).
//! - One in-flight voice session; a new voice_start supersedes the previous.
//! - Requests over MAX_LINE_BYTES are rejected without being parsed.
//! - stdout writes are line-atomic behind a mutex (no interleaving).
//! - EOF on stdin = parent gone → cancel any capture and exit.

use std::io::Write;
use std::sync::{Arc, Mutex};

use serde::Serialize;

/// 10 MB: far above any legitimate request (embed payloads are metadata, not
/// pixels), low enough to stop a runaway writer.
pub const MAX_LINE_BYTES: usize = 10 * 1024 * 1024;

#[derive(Clone)]
pub struct Writer(Arc<Mutex<std::io::Stdout>>);

impl Writer {
    pub fn new() -> Self {
        Writer(Arc::new(Mutex::new(std::io::stdout())))
    }

    pub fn write_line(&self, value: &serde_json::Value) {
        let mut out = self.0.lock().unwrap();
        if let Ok(line) = serde_json::to_string(value) {
            let _ = out.write_all(line.as_bytes());
            let _ = out.write_all(b"\n");
            let _ = out.flush();
        }
    }

    pub fn respond_ok(&self, id: u64, result: serde_json::Value) {
        self.write_line(&serde_json::json!({ "id": id, "result": result }));
    }

    pub fn respond_err(&self, id: u64, message: &str) {
        self.write_line(&serde_json::json!({ "id": id, "error": message }));
    }
}

/// A handle streams named events tied to one originating request.
#[derive(Clone)]
pub struct EventSink {
    writer: Writer,
    stream: &'static str,
    request_id: u64,
}

impl EventSink {
    pub fn new(writer: Writer, stream: &'static str, request_id: u64) -> Self {
        EventSink {
            writer,
            stream,
            request_id,
        }
    }

    pub fn send<T: Serialize>(&self, payload: &T) {
        if let Ok(value) = serde_json::to_value(payload) {
            self.writer.write_line(&serde_json::json!({
                "event": self.stream,
                "id": self.request_id,
                "payload": value,
            }));
        }
    }
}
