//! Chromium/WebView2 localStorage reader for the Tauri→Electron migration.
//!
//! Tauri's Windows shell points WebView2 at the sandbox browser directory.
//! WebView2 stores DOM localStorage in a Chromium LevelDB below
//! `EBWebView/Default/Local Storage/leveldb`.  Chromium's schema is:
//!
//!   _<serialized storage key>\0<encoded script key> -> <encoded value>
//!
//! Script strings carry a one-byte format tag (0 = UTF-16LE, 1 = Latin-1).
//! We copy the complete database before opening it: LevelDB recovery may
//! rewrite manifests/logs, and the migration must never mutate the Tauri
//! source so rollback remains safe.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use rusty_leveldb::{LdbIterator, Options, DB};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct ReadRequest {
    pub db_path: String,
}

pub fn read_local_storage(req: ReadRequest) -> Result<BTreeMap<String, String>, String> {
    let source = PathBuf::from(&req.db_path);
    if !source.is_dir() {
        return Err(format!("no such directory: {}", req.db_path));
    }

    let staged = stage_database(&source).map_err(|e| format!("stage database: {e}"))?;
    let result = read_leveldb(&staged.dir);
    staged.cleanup();
    result
}

struct StagedDb {
    dir: PathBuf,
}

impl StagedDb {
    fn cleanup(&self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

fn stage_database(source: &Path) -> std::io::Result<StagedDb> {
    let dir = std::env::temp_dir().join(format!(
        "stimma-chromium-storage-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ));
    std::fs::create_dir_all(&dir)?;
    for entry in std::fs::read_dir(source)? {
        let entry = entry?;
        if entry.file_type()?.is_file() {
            std::fs::copy(entry.path(), dir.join(entry.file_name()))?;
        }
    }
    Ok(StagedDb { dir })
}

fn read_leveldb(db_path: &Path) -> Result<BTreeMap<String, String>, String> {
    let options = Options {
        create_if_missing: false,
        ..Options::default()
    };
    let mut db = DB::open(db_path, options).map_err(|e| format!("open: {e}"))?;
    let mut iter = db.new_iter().map_err(|e| format!("iterate: {e}"))?;
    let mut items = BTreeMap::new();

    while iter.advance() {
        let Some((raw_key, raw_value)) = iter.current() else {
            continue;
        };
        let Some(separator) = raw_key.iter().position(|&byte| byte == 0) else {
            continue;
        };
        // Data rows begin with `_<storage key>\0`; VERSION/META rows do not.
        if raw_key.first() != Some(&b'_') || separator + 1 >= raw_key.len() {
            continue;
        }
        let Some(key) = decode_script_string(&raw_key[separator + 1..]) else {
            continue;
        };
        let Some(value) = decode_script_string(&raw_value) else {
            continue;
        };
        items.insert(key, value);
    }

    Ok(items)
}

fn decode_script_string(bytes: &[u8]) -> Option<String> {
    let (&format, payload) = bytes.split_first()?;
    match format {
        0 if payload.len() % 2 == 0 => {
            let units: Vec<u16> = payload
                .chunks_exact(2)
                .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
                .collect();
            String::from_utf16(&units).ok()
        }
        1 => Some(payload.iter().map(|&byte| char::from(byte)).collect()),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn encoded(text: &str) -> Vec<u8> {
        if text.chars().all(|c| (c as u32) <= 0xff) {
            let mut out = vec![1];
            out.extend(text.chars().map(|c| c as u8));
            out
        } else {
            let mut out = vec![0];
            out.extend(text.encode_utf16().flat_map(u16::to_le_bytes));
            out
        }
    }

    fn fixture_dir() -> PathBuf {
        std::env::temp_dir().join(format!(
            "stimma-chromium-storage-fixture-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ))
    }

    #[test]
    fn reads_latin1_and_utf16_values_without_touching_source() {
        let dir = fixture_dir();
        let _ = std::fs::remove_dir_all(&dir);
        let mut options = Options::default();
        options.create_if_missing = true;
        {
            let mut db = DB::open(&dir, options).unwrap();
            let prefix = b"_http://tauri.localhost\0";
            for (key, value) in [
                ("profileId", "profile-abc123"),
                ("stimma_global_theme", "dark"),
                ("stimma_unicode", "héllo 🎨 世界"),
            ] {
                let mut db_key = prefix.to_vec();
                db_key.extend(encoded(key));
                db.put(&db_key, &encoded(value)).unwrap();
            }
            db.flush().unwrap();
        }

        let before: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        let items = read_local_storage(ReadRequest {
            db_path: dir.to_string_lossy().into_owned(),
        })
        .unwrap();
        let after: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();

        assert_eq!(items["profileId"], "profile-abc123");
        assert_eq!(items["stimma_global_theme"], "dark");
        assert_eq!(items["stimma_unicode"], "héllo 🎨 世界");
        assert_eq!(
            before, after,
            "reader must not recover/mutate source LevelDB"
        );
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn rejects_missing_directory() {
        let err = read_local_storage(ReadRequest {
            db_path: "Z:/nonexistent/stimma-leveldb".into(),
        })
        .unwrap_err();
        assert!(err.contains("no such directory"));
    }
}
