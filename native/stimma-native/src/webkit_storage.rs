//! WKWebView localStorage reader for the Tauri→Electron migration.
//!
//! WKWebView persists DOM localStorage as a SQLite file:
//!   ItemTable(key TEXT UNIQUE, value BLOB NOT NULL)
//! Keys are UTF-8 text; values are the raw bytes of the stored JS string —
//! UTF-16LE for 16-bit strings, Latin-1/UTF-8 for 8-bit strings. Decode
//! defensively and never fail the whole dump for one undecodable row.
//!
//! The file may sit next to live -wal/-shm companions from the (now gone)
//! Tauri process; copy the trio to a temp dir and open the copy read-write
//! so SQLite can recover the WAL without touching the original.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct ReadRequest {
    pub db_path: String,
}

pub fn read_local_storage(req: ReadRequest) -> Result<BTreeMap<String, String>, String> {
    let source = PathBuf::from(&req.db_path);
    if !source.is_file() {
        return Err(format!("no such file: {}", req.db_path));
    }

    let staged = stage_database(&source).map_err(|e| format!("stage database: {e}"))?;
    let result = read_item_table(&staged.db_path);
    staged.cleanup();
    result
}

struct StagedDb {
    dir: PathBuf,
    db_path: PathBuf,
}

impl StagedDb {
    fn cleanup(&self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

/// Copy the database (and any -wal/-shm companions) into a temp dir so we can
/// let SQLite replay the WAL on a private copy.
fn stage_database(source: &Path) -> std::io::Result<StagedDb> {
    let dir = std::env::temp_dir().join(format!(
        "stimma-webkit-storage-{}-{}",
        std::process::id(),
        source
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("db")
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir)?;

    let db_path = dir.join("localstorage.sqlite3");
    std::fs::copy(source, &db_path)?;
    for suffix in ["-wal", "-shm"] {
        let companion = PathBuf::from(format!("{}{suffix}", source.display()));
        if companion.is_file() {
            std::fs::copy(&companion, dir.join(format!("localstorage.sqlite3{suffix}")))?;
        }
    }
    Ok(StagedDb { dir, db_path })
}

fn read_item_table(db_path: &Path) -> Result<BTreeMap<String, String>, String> {
    let connection = rusqlite::Connection::open(db_path).map_err(|e| format!("open: {e}"))?;
    let mut statement = connection
        .prepare("SELECT key, value FROM ItemTable")
        .map_err(|e| format!("prepare: {e}"))?;

    let mut items = BTreeMap::new();
    let mut rows = statement.query([]).map_err(|e| format!("query: {e}"))?;
    while let Some(row) = rows.next().map_err(|e| format!("row: {e}"))? {
        let key: String = match row.get(0) {
            Ok(k) => k,
            Err(_) => continue,
        };
        let value: Vec<u8> = match row.get(1) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if let Some(decoded) = decode_value(&value) {
            items.insert(key, decoded);
        }
    }
    Ok(items)
}

/// WebKit stores the JS string's raw bytes: UTF-16LE for 16-bit strings,
/// Latin-1 for 8-bit strings. Prefer UTF-16LE when the shape fits (even
/// length; for ASCII-ish payloads the odd bytes are zero), else fall back.
fn decode_value(bytes: &[u8]) -> Option<String> {
    if bytes.is_empty() {
        return Some(String::new());
    }
    if bytes.len() % 2 == 0 && looks_utf16le(bytes) {
        let units: Vec<u16> = bytes
            .chunks_exact(2)
            .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
            .collect();
        if let Ok(text) = String::from_utf16(&units) {
            return Some(text);
        }
    }
    if let Ok(text) = std::str::from_utf8(bytes) {
        return Some(text.to_string());
    }
    // Latin-1: every byte maps to the same code point.
    Some(bytes.iter().map(|&b| b as char).collect())
}

/// Heuristic: in UTF-16LE text that is mostly BMP/ASCII, a large share of the
/// odd-index bytes are zero. Latin-1/UTF-8 text essentially never has NULs.
fn looks_utf16le(bytes: &[u8]) -> bool {
    let odd_zeroes = bytes.iter().skip(1).step_by(2).filter(|&&b| b == 0).count();
    let pairs = bytes.len() / 2;
    if pairs == 0 {
        return false;
    }
    odd_zeroes * 2 >= pairs
}

#[cfg(test)]
mod tests {
    use super::*;

    fn utf16le(text: &str) -> Vec<u8> {
        text.encode_utf16().flat_map(|u| u.to_le_bytes()).collect()
    }

    fn build_fixture(dir: &Path, rows: &[(&str, Vec<u8>)]) -> PathBuf {
        std::fs::create_dir_all(dir).unwrap();
        let db_path = dir.join("localstorage.sqlite3");
        let conn = rusqlite::Connection::open(&db_path).unwrap();
        conn.execute(
            "CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB NOT NULL ON CONFLICT FAIL)",
            [],
        )
        .unwrap();
        for (key, value) in rows {
            conn.execute(
                "INSERT INTO ItemTable (key, value) VALUES (?1, ?2)",
                rusqlite::params![key, value],
            )
            .unwrap();
        }
        db_path
    }

    #[test]
    fn reads_utf16le_values() {
        let dir = std::env::temp_dir().join(format!("webkit-storage-test-{}", std::process::id()));
        let db = build_fixture(
            &dir,
            &[
                ("profileId", utf16le("profile-abc123")),
                ("stimma_global_theme", utf16le("dark")),
                (
                    "stimma_ai.stimma.stimma.canary_default_p1_workspace_tabs",
                    utf16le("{\"tabs\":[{\"id\":\"t1\"}]}"),
                ),
                ("utf8_value", "plain utf8".as_bytes().to_vec()),
                ("empty", Vec::new()),
            ],
        );

        let items = read_local_storage(ReadRequest {
            db_path: db.to_string_lossy().into_owned(),
        })
        .unwrap();

        assert_eq!(items["profileId"], "profile-abc123");
        assert_eq!(items["stimma_global_theme"], "dark");
        assert_eq!(
            items["stimma_ai.stimma.stimma.canary_default_p1_workspace_tabs"],
            "{\"tabs\":[{\"id\":\"t1\"}]}"
        );
        assert_eq!(items["utf8_value"], "plain utf8");
        assert_eq!(items["empty"], "");

        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn missing_file_is_an_error() {
        let err = read_local_storage(ReadRequest {
            db_path: "/nonexistent/localstorage.sqlite3".into(),
        })
        .unwrap_err();
        assert!(err.contains("no such file"));
    }

    #[test]
    fn unicode_survives_round_trip() {
        let dir = std::env::temp_dir().join(format!("webkit-storage-uni-{}", std::process::id()));
        let db = build_fixture(&dir, &[("emoji", utf16le("héllo 🎨 世界"))]);
        let items = read_local_storage(ReadRequest {
            db_path: db.to_string_lossy().into_owned(),
        })
        .unwrap();
        assert_eq!(items["emoji"], "héllo 🎨 世界");
        std::fs::remove_dir_all(dir).unwrap();
    }
}
