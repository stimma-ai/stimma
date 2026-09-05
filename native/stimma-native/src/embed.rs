//! Drag-out metadata embedding.
//!
//! The backend prepares format-specific payload (A1111 string, Stimma JSON,
//! and for JPEG a pre-built EXIF block). This module copies the source file
//! to a backend-reserved, deletion-indexed cache path and splices in the
//! metadata at byte level — no pixel decode, no re-encode.
//!
//! - PNG: insert two `tEXt` chunks (`parameters`, `stimma`) before the first
//!   IDAT, stripping any pre-existing entries with the same keys.
//! - JPEG: replace the EXIF APP1 segment with the bytes Python prepared via
//!   `piexif.dump`.
//!
//! Moved verbatim from src-tauri/src/embed.rs (minus the Tauri command
//! wrapper); the byte-splicing functions are unchanged.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::Deserialize;

const PNG_SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];

#[derive(Debug, Deserialize)]
pub struct EmbedRequest {
    pub source_path: String,
    pub destination_path: Option<String>,
    pub format: String,
    pub a1111: Option<String>,
    pub stimma_json: Option<String>,
    pub jpeg_exif_hex: Option<String>,
}

pub fn embed_metadata_sync(req: EmbedRequest, cache_root: PathBuf) -> Result<String, String> {
    let source_path = PathBuf::from(&req.source_path);

    if req.format == "passthrough" {
        return Ok(req.source_path);
    }

    let source_bytes = fs::read(&source_path).map_err(|e| format!("read source: {e}"))?;

    // Only the backend can reserve a snapshot directory, after indexing it
    // under the Media deletion barrier. Never recreate a revoked reservation.
    let dst_path = PathBuf::from(req.destination_path.as_deref()
        .ok_or("missing backend snapshot reservation")?);
    let parent = dst_path.parent().ok_or("invalid snapshot destination")?;
    let cache_root = cache_root.canonicalize().map_err(|e| format!("cache root: {e}"))?;
    let resolved_parent = parent.canonicalize().map_err(|e| format!("snapshot reservation: {e}"))?;
    if !dst_path.is_absolute()
        || !resolved_parent.starts_with(&cache_root)
        || resolved_parent.parent().and_then(Path::file_name).and_then(|s| s.to_str()) != Some("drag_snapshots")
        || !matches!(dst_path.file_name().and_then(|s| s.to_str()), Some("snapshot.png" | "snapshot.jpeg"))
    {
        return Err("invalid snapshot reservation".into());
    }
    let ext = dst_path.extension().and_then(|s| s.to_str()).unwrap_or("bin");

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

pub fn embed_png(
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

pub fn embed_jpeg(src: &[u8], exif_hex: Option<&str>) -> Result<Vec<u8>, String> {
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

    /// Build a minimal-but-valid PNG: signature + IHDR + optional extra
    /// chunks + IDAT + IEND.
    fn tiny_png(extra_text: &[(&[u8], &[u8])]) -> Vec<u8> {
        let mut out = Vec::new();
        out.extend_from_slice(&PNG_SIGNATURE);
        let chunk = |out: &mut Vec<u8>, ty: &[u8], data: &[u8]| {
            out.extend_from_slice(&(data.len() as u32).to_be_bytes());
            out.extend_from_slice(ty);
            let mut crc = crc32fast::Hasher::new();
            crc.update(ty);
            crc.update(data);
            out.extend_from_slice(data);
            out.extend_from_slice(&crc.finalize().to_be_bytes());
        };
        chunk(&mut out, b"IHDR", &[0, 0, 0, 1, 0, 0, 0, 1, 8, 0, 0, 0, 0]);
        for (keyword, text) in extra_text {
            let mut data = Vec::new();
            data.extend_from_slice(keyword);
            data.push(0);
            data.extend_from_slice(text);
            chunk(&mut out, b"tEXt", &data);
        }
        chunk(&mut out, b"IDAT", &[0x78, 0x9C, 0x63, 0x00, 0x00, 0x00, 0x02, 0x00, 0x01]);
        chunk(&mut out, b"IEND", &[]);
        out
    }

    fn text_chunks(png: &[u8]) -> Vec<(Vec<u8>, Vec<u8>)> {
        let mut found = Vec::new();
        let mut pos = 8usize;
        while pos + 8 <= png.len() {
            let len = u32::from_be_bytes([png[pos], png[pos + 1], png[pos + 2], png[pos + 3]]) as usize;
            let ty = &png[pos + 4..pos + 8];
            let data = &png[pos + 8..pos + 8 + len];
            if ty == b"tEXt" {
                if let Some(null) = data.iter().position(|&b| b == 0) {
                    found.push((data[..null].to_vec(), data[null + 1..].to_vec()));
                }
            }
            if ty == b"IEND" {
                break;
            }
            pos += 12 + len;
        }
        found
    }

    #[test]
    fn png_inserts_parameters_and_stimma_before_idat() {
        let src = tiny_png(&[]);
        let out = embed_png(&src, Some("params here"), Some("{\"a\":1}")).unwrap();
        let texts = text_chunks(&out);
        assert_eq!(
            texts,
            vec![
                (b"parameters".to_vec(), b"params here".to_vec()),
                (b"stimma".to_vec(), b"{\"a\":1}".to_vec()),
            ]
        );
        // Deterministic: same input → identical bytes.
        assert_eq!(out, embed_png(&src, Some("params here"), Some("{\"a\":1}")).unwrap());
    }

    #[test]
    fn png_strips_preexisting_stimma_chunks() {
        let src = tiny_png(&[
            (b"parameters", b"old"),
            (b"stimmer", b"legacy"),
            (b"comment", b"keep me"),
        ]);
        let out = embed_png(&src, Some("new"), None).unwrap();
        let texts = text_chunks(&out);
        assert_eq!(
            texts,
            vec![
                (b"comment".to_vec(), b"keep me".to_vec()),
                (b"parameters".to_vec(), b"new".to_vec()),
            ]
        );
    }

    #[test]
    fn png_rejects_bad_signature() {
        assert!(embed_png(b"not a png", Some("x"), None).is_err());
    }

    /// Minimal JPEG: SOI + APP0 + (optional old EXIF APP1) + SOS + data + EOI.
    fn tiny_jpeg(with_old_exif: bool) -> Vec<u8> {
        let mut out = vec![0xFF, 0xD8];
        // APP0 JFIF
        let app0: &[u8] = b"JFIF\0\x01\x01\x00\x00\x01\x00\x01\x00\x00";
        out.extend_from_slice(&[0xFF, 0xE0]);
        out.extend_from_slice(&((app0.len() + 2) as u16).to_be_bytes());
        out.extend_from_slice(app0);
        if with_old_exif {
            let old: &[u8] = b"Exif\0\0OLDEXIFDATA";
            out.extend_from_slice(&[0xFF, 0xE1]);
            out.extend_from_slice(&((old.len() + 2) as u16).to_be_bytes());
            out.extend_from_slice(old);
        }
        // SOS with a fake 2-byte body, then entropy data + EOI.
        out.extend_from_slice(&[0xFF, 0xDA, 0x00, 0x04, 0x01, 0x02]);
        out.extend_from_slice(&[0x12, 0x34, 0x56]);
        out.extend_from_slice(&[0xFF, 0xD9]);
        out
    }

    #[test]
    fn jpeg_inserts_fresh_exif_after_soi() {
        let src = tiny_jpeg(false);
        let out = embed_jpeg(&src, Some("aabbcc")).unwrap();
        assert_eq!(&out[..2], &[0xFF, 0xD8]);
        assert_eq!(&out[2..4], &[0xFF, 0xE1]);
        assert_eq!(&out[6..12], b"Exif\0\0");
        assert_eq!(&out[12..15], &[0xAA, 0xBB, 0xCC]);
        // Entropy data + EOI preserved verbatim at the tail.
        assert_eq!(&out[out.len() - 5..], &[0x12, 0x34, 0x56, 0xFF, 0xD9]);
    }

    #[test]
    fn jpeg_replaces_existing_exif() {
        let src = tiny_jpeg(true);
        let out = embed_jpeg(&src, Some("dd")).unwrap();
        let old_needle = b"OLDEXIFDATA";
        assert!(!out.windows(old_needle.len()).any(|w| w == old_needle));
        assert_eq!(&out[12..13], &[0xDD]);
    }

    #[test]
    fn jpeg_requires_exif_payload() {
        assert!(embed_jpeg(&tiny_jpeg(false), None).is_err());
        assert!(embed_jpeg(b"nope", Some("aa")).is_err());
    }

    #[test]
    fn embed_metadata_sync_passthrough_and_cache() {
        let dir = std::env::temp_dir().join(format!("stimma-embed-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let src = dir.join("img.png");
        std::fs::write(&src, tiny_png(&[])).unwrap();

        let pass = embed_metadata_sync(
            EmbedRequest {
                source_path: src.to_string_lossy().into_owned(),
                destination_path: None,
                format: "passthrough".into(),
                a1111: None,
                stimma_json: None,
                jpeg_exif_hex: None,
            },
            dir.clone(),
        )
        .unwrap();
        assert_eq!(pass, src.to_string_lossy());

        let reservation = dir.join("drag_snapshots").join("reservation");
        std::fs::create_dir_all(&reservation).unwrap();
        let destination = reservation.join("snapshot.png");
        let req = || EmbedRequest {
            source_path: src.to_string_lossy().into_owned(),
            destination_path: Some(destination.to_string_lossy().into_owned()),
            format: "png".into(),
            a1111: Some("p".into()),
            stimma_json: None,
            jpeg_exif_hex: None,
        };
        let first = embed_metadata_sync(req(), dir.clone()).unwrap();
        let second = embed_metadata_sync(req(), dir.clone()).unwrap();
        assert_eq!(first, second, "cache key must be stable");
        assert!(std::path::Path::new(&first).exists());

        // Permanent deletion revokes both cached and in-flight work. A stale
        // request cannot recreate the directory or publish another copy.
        std::fs::remove_dir_all(&reservation).unwrap();
        assert!(embed_metadata_sync(req(), dir.clone()).is_err());
        assert!(!reservation.exists());
        let mut unreserved = req();
        unreserved.destination_path = None;
        assert!(embed_metadata_sync(unreserved, dir.clone()).is_err());

        std::fs::remove_dir_all(dir).unwrap();
    }
}
