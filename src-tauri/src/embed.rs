//! Drag-out metadata embedding.
//!
//! The backend prepares format-specific payload (A1111 string, Stimma JSON,
//! and for JPEG a pre-built EXIF block). This module copies the source file
//! to a per-(file_hash, metadata_hash) temp path and splices in the
//! metadata at byte level — no pixel decode, no re-encode.
//!
//! - PNG: insert two `tEXt` chunks (`parameters`, `stimma`) before the first
//!   IDAT, stripping any pre-existing entries with the same keys.
//! - JPEG: replace the EXIF APP1 segment with the bytes Python prepared via
//!   `piexif.dump`.

use std::collections::hash_map::DefaultHasher;
use std::fs;
use std::hash::{Hash, Hasher};
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::Deserialize;

const PNG_SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];

#[derive(Debug, Deserialize)]
pub struct EmbedRequest {
    pub source_path: String,
    pub format: String,
    pub a1111: Option<String>,
    pub stimma_json: Option<String>,
    pub jpeg_exif_hex: Option<String>,
}

#[tauri::command]
pub async fn embed_metadata(
    app: tauri::AppHandle,
    req: EmbedRequest,
) -> Result<String, String> {
    use tauri::Manager;
    let cache_dir = app
        .path()
        .app_cache_dir()
        .map_err(|e| format!("resolve cache dir: {e}"))?;
    tauri::async_runtime::spawn_blocking(move || embed_metadata_sync(req, cache_dir))
        .await
        .map_err(|e| format!("join error: {e}"))?
}

fn embed_metadata_sync(req: EmbedRequest, cache_root: PathBuf) -> Result<String, String> {
    let source_path = PathBuf::from(&req.source_path);

    if req.format == "passthrough" {
        return Ok(req.source_path);
    }

    let source_bytes = fs::read(&source_path).map_err(|e| format!("read source: {e}"))?;

    // Cache key: source path + mtime/size + payload fingerprint. Not cryptographic
    // — just enough to dedupe drag-out snapshots for the same media+metadata.
    let meta = fs::metadata(&source_path).map_err(|e| format!("stat source: {e}"))?;
    let cache_key = {
        let mut h = DefaultHasher::new();
        req.source_path.hash(&mut h);
        meta.len().hash(&mut h);
        if let Ok(modified) = meta.modified() {
            if let Ok(dur) = modified.duration_since(std::time::UNIX_EPOCH) {
                dur.as_nanos().hash(&mut h);
            }
        }
        req.a1111.as_deref().unwrap_or("").hash(&mut h);
        req.stimma_json.as_deref().unwrap_or("").hash(&mut h);
        req.jpeg_exif_hex.as_deref().unwrap_or("").hash(&mut h);
        format!("{:016x}", h.finish())
    };

    let cache_dir = cache_root.join("drag_snapshots");
    fs::create_dir_all(&cache_dir).map_err(|e| format!("create cache dir: {e}"))?;
    let ext = source_path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("bin");
    let dst_path = cache_dir.join(format!("{cache_key}.{ext}"));

    if dst_path.exists() {
        return Ok(path_to_string(&dst_path));
    }

    let output = match req.format.as_str() {
        "png" => embed_png(
            &source_bytes,
            req.a1111.as_deref(),
            req.stimma_json.as_deref(),
        )?,
        "jpeg" => embed_jpeg(&source_bytes, req.jpeg_exif_hex.as_deref())?,
        other => return Err(format!("unsupported format: {other}")),
    };

    // Atomic write via tmp + rename so concurrent drags don't see a partial file.
    let tmp_path = dst_path.with_extension(format!("{ext}.tmp"));
    {
        let mut f = fs::File::create(&tmp_path).map_err(|e| format!("create tmp: {e}"))?;
        f.write_all(&output).map_err(|e| format!("write tmp: {e}"))?;
    }
    fs::rename(&tmp_path, &dst_path).map_err(|e| format!("rename tmp: {e}"))?;

    Ok(path_to_string(&dst_path))
}

// ----- PNG -----------------------------------------------------------------

fn embed_png(
    src: &[u8],
    a1111: Option<&str>,
    stimma_json: Option<&str>,
) -> Result<Vec<u8>, String> {
    if src.len() < 8 || src[..8] != PNG_SIGNATURE {
        return Err("not a PNG (bad signature)".into());
    }

    let mut out: Vec<u8> = Vec::with_capacity(src.len() + 1024);
    out.extend_from_slice(&PNG_SIGNATURE);

    let mut pos = 8usize;
    let mut new_chunks_emitted = false;

    while pos + 8 <= src.len() {
        let len = u32::from_be_bytes([src[pos], src[pos + 1], src[pos + 2], src[pos + 3]]) as usize;
        let type_start = pos + 4;
        let data_start = pos + 8;
        let data_end = data_start
            .checked_add(len)
            .ok_or_else(|| "chunk length overflow".to_string())?;
        let crc_end = data_end + 4;
        if crc_end > src.len() {
            return Err("truncated chunk".into());
        }
        let chunk_type = &src[type_start..data_start];

        // Strip any pre-existing parameters/stimma/stimmer tEXt chunks so we
        // don't end up with duplicates after re-embedding.
        let is_replaceable_text = chunk_type == b"tEXt"
            && {
                let data = &src[data_start..data_end];
                data.iter()
                    .position(|&b| b == 0)
                    .map(|null| {
                        let keyword = &data[..null];
                        keyword == b"parameters" || keyword == b"stimma" || keyword == b"stimmer"
                    })
                    .unwrap_or(false)
            };

        if !new_chunks_emitted && (chunk_type == b"IDAT" || chunk_type == b"IEND") {
            // Insert our new tEXt chunks right before the first pixel data
            // (or IEND, for the degenerate case of a chunk-less PNG).
            if let Some(a) = a1111 {
                append_text_chunk(&mut out, b"parameters", a.as_bytes());
            }
            if let Some(s) = stimma_json {
                append_text_chunk(&mut out, b"stimma", s.as_bytes());
            }
            new_chunks_emitted = true;
        }

        if !is_replaceable_text {
            out.extend_from_slice(&src[pos..crc_end]);
        }

        if chunk_type == b"IEND" {
            // Trailing bytes after IEND are non-standard; preserve them anyway.
            if crc_end < src.len() {
                out.extend_from_slice(&src[crc_end..]);
            }
            return Ok(out);
        }
        pos = crc_end;
    }

    Err("PNG missing IEND chunk".into())
}

fn append_text_chunk(out: &mut Vec<u8>, keyword: &[u8], text: &[u8]) {
    let mut data: Vec<u8> = Vec::with_capacity(keyword.len() + 1 + text.len());
    data.extend_from_slice(keyword);
    data.push(0);
    data.extend_from_slice(text);

    let len = data.len() as u32;
    out.extend_from_slice(&len.to_be_bytes());
    out.extend_from_slice(b"tEXt");
    let mut crc = crc32fast::Hasher::new();
    crc.update(b"tEXt");
    crc.update(&data);
    out.extend_from_slice(&data);
    out.extend_from_slice(&crc.finalize().to_be_bytes());
}

// ----- JPEG ----------------------------------------------------------------
//
// JPEG is a series of marker segments. We strip any existing APP1 EXIF
// segment (FFE1 starting with "Exif\0\0") and insert a fresh one right after
// the SOI marker (FFD8). The EXIF bytes come prepared by piexif.dump on the
// Python side — we just wrap them in the APP1 header.

fn embed_jpeg(src: &[u8], exif_hex: Option<&str>) -> Result<Vec<u8>, String> {
    if src.len() < 4 || src[0] != 0xFF || src[1] != 0xD8 {
        return Err("not a JPEG (bad SOI)".into());
    }
    let exif_hex = exif_hex.ok_or_else(|| "missing jpeg_exif_hex".to_string())?;
    let exif_bytes = hex_decode(exif_hex)?;

    let mut out: Vec<u8> = Vec::with_capacity(src.len() + exif_bytes.len() + 16);
    out.extend_from_slice(&src[..2]); // SOI

    // Insert APP1 EXIF segment.
    out.push(0xFF);
    out.push(0xE1);
    // APP1 length includes the length field itself but not the marker, max 65533.
    let inner_len = 2 + 6 + exif_bytes.len();
    if inner_len > 0xFFFF {
        return Err("EXIF too large for a single APP1 segment".into());
    }
    out.extend_from_slice(&(inner_len as u16).to_be_bytes());
    out.extend_from_slice(b"Exif\0\0");
    out.extend_from_slice(&exif_bytes);

    // Walk the rest, skipping any existing APP1 EXIF segment.
    let mut pos = 2usize;
    while pos + 2 <= src.len() {
        if src[pos] != 0xFF {
            // We've fallen out of marker-land into entropy-coded data; copy the
            // remainder as-is.
            out.extend_from_slice(&src[pos..]);
            return Ok(out);
        }
        let marker = src[pos + 1];
        // Standalone markers with no length: SOI (D8) — already handled above,
        // RST0-7 (D0-D7), EOI (D9), TEM (01).
        if marker == 0xD9 {
            // EOI: copy SOI marker and finish.
            out.extend_from_slice(&src[pos..pos + 2]);
            if pos + 2 < src.len() {
                out.extend_from_slice(&src[pos + 2..]);
            }
            return Ok(out);
        }
        if matches!(marker, 0x01 | 0xD0..=0xD7) {
            out.extend_from_slice(&src[pos..pos + 2]);
            pos += 2;
            continue;
        }
        // SOS (DA) starts entropy-coded scan; we still emit the SOS segment
        // by length, then copy everything until EOI as a single block (it
        // contains 0xFF escapes; we don't reinterpret it).
        if pos + 4 > src.len() {
            return Err("truncated JPEG segment header".into());
        }
        let seg_len =
            u16::from_be_bytes([src[pos + 2], src[pos + 3]]) as usize;
        let seg_end = pos + 2 + seg_len;
        if seg_end > src.len() {
            return Err("truncated JPEG segment body".into());
        }

        let is_exif_app1 = marker == 0xE1
            && seg_len >= 8
            && &src[pos + 4..pos + 10] == b"Exif\0\0";

        if !is_exif_app1 {
            out.extend_from_slice(&src[pos..seg_end]);
        }
        pos = seg_end;

        if marker == 0xDA {
            // After SOS: copy entropy-coded data through EOI verbatim.
            out.extend_from_slice(&src[pos..]);
            return Ok(out);
        }
    }

    Ok(out)
}

// ----- helpers -------------------------------------------------------------

fn hex_decode(s: &str) -> Result<Vec<u8>, String> {
    if s.len() % 2 != 0 {
        return Err("odd hex length".into());
    }
    let mut out = Vec::with_capacity(s.len() / 2);
    let b = s.as_bytes();
    for i in (0..b.len()).step_by(2) {
        let hi = hex_nibble(b[i])?;
        let lo = hex_nibble(b[i + 1])?;
        out.push((hi << 4) | lo);
    }
    Ok(out)
}

fn hex_nibble(c: u8) -> Result<u8, String> {
    match c {
        b'0'..=b'9' => Ok(c - b'0'),
        b'a'..=b'f' => Ok(c - b'a' + 10),
        b'A'..=b'F' => Ok(c - b'A' + 10),
        _ => Err(format!("invalid hex char: {c}")),
    }
}

fn path_to_string(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Instant;

    #[test]
    #[ignore] // fixture not committed
    fn png_round_trip() {
        let src = std::fs::read(
            "tests/fixtures/png_round_trip.png",
        )
        .expect("test image present");

        let t0 = Instant::now();
        let out = embed_png(&src, Some("hello\nNegative prompt: world\nSteps: 20"), Some("{\"source\":\"stimma\"}"))
            .expect("embed ok");
        let elapsed = t0.elapsed();
        eprintln!("embed_png elapsed: {:?}, size {} -> {}", elapsed, src.len(), out.len());

        // First chunk after signature should still be IHDR (we don't move it).
        assert_eq!(&out[..8], &PNG_SIGNATURE);
        assert_eq!(&out[12..16], b"IHDR");

        // Walk chunks looking for our tEXts.
        let mut pos = 8usize;
        let mut found_params = false;
        let mut found_stimma = false;
        while pos + 8 <= out.len() {
            let len = u32::from_be_bytes([out[pos], out[pos+1], out[pos+2], out[pos+3]]) as usize;
            let ct = &out[pos+4..pos+8];
            let data = &out[pos+8..pos+8+len];
            if ct == b"tEXt" {
                if let Some(null) = data.iter().position(|&b| b==0) {
                    if &data[..null] == b"parameters" { found_params = true; }
                    if &data[..null] == b"stimma" { found_stimma = true; }
                }
            }
            if ct == b"IEND" { break; }
            pos += 12 + len;
        }
        assert!(found_params, "parameters chunk missing");
        assert!(found_stimma, "stimma chunk missing");
    }
}
