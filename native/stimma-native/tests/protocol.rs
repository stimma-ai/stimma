//! Black-box protocol tests: spawn the built helper and speak JSON lines.

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdout, Command, Stdio};

struct Helper {
    child: Child,
    stdout: BufReader<ChildStdout>,
}

impl Helper {
    fn spawn(cache_dir: &std::path::Path) -> Helper {
        let bin = env!("CARGO_BIN_EXE_stimma-native");
        let mut child = Command::new(bin)
            .args(["--cache-dir", cache_dir.to_str().unwrap()])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn helper");
        let stdout = BufReader::new(child.stdout.take().unwrap());
        Helper { child, stdout }
    }

    fn request(&mut self, value: serde_json::Value) -> serde_json::Value {
        let line = serde_json::to_string(&value).unwrap();
        let stdin = self.child.stdin.as_mut().unwrap();
        stdin.write_all(line.as_bytes()).unwrap();
        stdin.write_all(b"\n").unwrap();
        stdin.flush().unwrap();
        self.read_frame()
    }

    fn read_frame(&mut self) -> serde_json::Value {
        let mut line = String::new();
        self.stdout.read_line(&mut line).expect("read frame");
        serde_json::from_str(&line).expect("frame is JSON")
    }
}

impl Drop for Helper {
    fn drop(&mut self) {
        drop(self.child.stdin.take()); // EOF → helper exits
        let _ = self.child.wait();
    }
}

fn temp_dir(tag: &str) -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "stimma-native-proto-{tag}-{}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// Minimal valid PNG (matches the unit-test fixture builder).
fn tiny_png() -> Vec<u8> {
    let mut out: Vec<u8> = vec![0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];
    let mut chunk = |ty: &[u8], data: &[u8]| {
        out.extend_from_slice(&(data.len() as u32).to_be_bytes());
        out.extend_from_slice(ty);
        let mut crc = crc32fast::Hasher::new();
        crc.update(ty);
        crc.update(data);
        out.extend_from_slice(data);
        out.extend_from_slice(&crc.finalize().to_be_bytes());
    };
    chunk(b"IHDR", &[0, 0, 0, 1, 0, 0, 0, 1, 8, 0, 0, 0, 0]);
    chunk(b"IDAT", &[0x78, 0x9C, 0x63, 0x00, 0x00, 0x00, 0x02, 0x00, 0x01]);
    chunk(b"IEND", &[]);
    out
}

#[test]
fn ping_round_trips() {
    let dir = temp_dir("ping");
    let mut helper = Helper::spawn(&dir);
    let resp = helper.request(serde_json::json!({"id": 7, "method": "ping"}));
    assert_eq!(resp["id"], 7);
    assert_eq!(resp["result"], "pong");
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn unknown_method_errors() {
    let dir = temp_dir("unknown");
    let mut helper = Helper::spawn(&dir);
    let resp = helper.request(serde_json::json!({"id": 1, "method": "nope"}));
    assert_eq!(resp["id"], 1);
    assert!(resp["error"].as_str().unwrap().contains("unknown method"));
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn embed_metadata_over_protocol() {
    let dir = temp_dir("embed");
    let src = dir.join("img.png");
    std::fs::write(&src, tiny_png()).unwrap();

    let mut helper = Helper::spawn(&dir);
    let resp = helper.request(serde_json::json!({
        "id": 2,
        "method": "embed_metadata",
        "params": {
            "source_path": src.to_str().unwrap(),
            "format": "png",
            "a1111": "a prompt",
            "stimma_json": "{\"v\":1}",
            "jpeg_exif_hex": null
        }
    }));
    assert_eq!(resp["id"], 2);
    let out_path = resp["result"].as_str().expect("embed returns a path");
    let bytes = std::fs::read(out_path).unwrap();
    let needle = b"parameters\0a prompt";
    assert!(bytes.windows(needle.len()).any(|w| w == needle));

    // Same request again resolves the cached snapshot (same path).
    let resp2 = helper.request(serde_json::json!({
        "id": 3,
        "method": "embed_metadata",
        "params": {
            "source_path": src.to_str().unwrap(),
            "format": "png",
            "a1111": "a prompt",
            "stimma_json": "{\"v\":1}",
            "jpeg_exif_hex": null
        }
    }));
    assert_eq!(resp2["result"].as_str().unwrap(), out_path);

    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn voice_model_status_false_on_empty_cache() {
    let dir = temp_dir("voicestatus");
    let mut helper = Helper::spawn(&dir);
    let resp = helper.request(serde_json::json!({"id": 4, "method": "voice_model_status"}));
    assert_eq!(resp["result"], false);
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn voice_session_without_model_errors_cleanly() {
    let dir = temp_dir("voicestart");
    let mut helper = Helper::spawn(&dir);
    let resp = helper.request(serde_json::json!({"id": 5, "method": "voice_start"}));
    assert!(resp["error"].as_str().unwrap().contains("not downloaded"));
    // stop with no session returns an empty transcript, not an error.
    let resp = helper.request(serde_json::json!({"id": 6, "method": "voice_stop"}));
    assert_eq!(resp["result"], "");
    // keepalive/cancel are safe no-ops without a session.
    let resp = helper.request(serde_json::json!({"id": 7, "method": "voice_keepalive"}));
    assert!(resp.get("error").is_none());
    let resp = helper.request(serde_json::json!({"id": 8, "method": "voice_cancel"}));
    assert!(resp.get("error").is_none());
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn helper_exits_on_stdin_close() {
    let dir = temp_dir("eof");
    let mut helper = Helper::spawn(&dir);
    drop(helper.child.stdin.take());
    let status = helper.child.wait().expect("helper exits after EOF");
    assert!(status.success());
    std::fs::remove_dir_all(dir).ok();
}
