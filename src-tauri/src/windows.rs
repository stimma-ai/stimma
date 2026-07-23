//! Multi-window profile management.
//!
//! Browser-style semantics: each open window is pinned to one profile,
//! switching profiles opens (or focuses) that profile's window, and the set
//! of open windows is persisted so a relaunch restores them. The frontend
//! asks `get_window_profile` at boot to learn which profile its window is
//! pinned to; the legacy single-window path (label "main", no pinned
//! profile) resolves the profile itself and reports it back.

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::Manager;

#[derive(Clone, Serialize, Deserialize)]
pub struct WindowEntry {
    pub label: String,
    pub profile_id: Option<String>,
}

#[derive(Serialize, Deserialize, Default)]
struct RegistryFile {
    windows: Vec<WindowEntry>,
}

/// The persisted window ↔ profile mapping. The file always reflects the
/// currently open windows: entries are added when a window is created,
/// updated when the frontend reports its resolved profile, and removed when
/// the user closes a window while others remain. Quitting leaves the file
/// as-is, which is exactly the set to restore on the next launch.
pub struct WindowRegistry {
    path: PathBuf,
    entries: Mutex<Vec<WindowEntry>>,
}

impl WindowRegistry {
    pub fn load(data_dir: &Path) -> Self {
        let path = data_dir.join("windows.json");
        let mut entries = std::fs::read(&path)
            .ok()
            .and_then(|bytes| serde_json::from_slice::<RegistryFile>(&bytes).ok())
            .map(|file| file.windows)
            .unwrap_or_default();
        let mut seen = std::collections::HashSet::new();
        entries.retain(|entry| !entry.label.is_empty() && seen.insert(entry.label.clone()));
        WindowRegistry {
            path,
            entries: Mutex::new(entries),
        }
    }

    fn persist_locked(&self, entries: &[WindowEntry]) {
        let file = RegistryFile {
            windows: entries.to_vec(),
        };
        let Ok(json) = serde_json::to_vec_pretty(&file) else {
            return;
        };
        let tmp = self.path.with_extension("json.tmp");
        if std::fs::write(&tmp, &json).is_ok() {
            let _ = std::fs::rename(&tmp, &self.path);
        }
    }

    pub fn snapshot(&self) -> Vec<WindowEntry> {
        self.entries.lock().unwrap().clone()
    }

    pub fn replace(&self, new_entries: Vec<WindowEntry>) {
        let mut entries = self.entries.lock().unwrap();
        *entries = new_entries;
        self.persist_locked(&entries);
    }

    pub fn profile_for(&self, label: &str) -> Option<String> {
        self.entries
            .lock()
            .unwrap()
            .iter()
            .find(|entry| entry.label == label)
            .and_then(|entry| entry.profile_id.clone())
    }

    pub fn label_for_profile(&self, profile_id: &str) -> Option<String> {
        self.entries
            .lock()
            .unwrap()
            .iter()
            .find(|entry| entry.profile_id.as_deref() == Some(profile_id))
            .map(|entry| entry.label.clone())
    }

    pub fn set_profile(&self, label: &str, profile_id: &str) {
        let mut entries = self.entries.lock().unwrap();
        if let Some(entry) = entries.iter_mut().find(|entry| entry.label == label) {
            entry.profile_id = Some(profile_id.to_string());
        } else {
            entries.push(WindowEntry {
                label: label.to_string(),
                profile_id: Some(profile_id.to_string()),
            });
        }
        self.persist_locked(&entries);
    }

    pub fn remove(&self, label: &str) {
        let mut entries = self.entries.lock().unwrap();
        entries.retain(|entry| entry.label != label);
        self.persist_locked(&entries);
    }
}

/// Everything needed to build another app window identical to the main one:
/// the window config template from tauri.conf.json plus the shared browser
/// profile, so all windows live in one WebView storage origin (localStorage
/// keys are already profile-namespaced on the frontend).
pub struct WindowFactory {
    pub config: tauri::utils::config::WindowConfig,
    pub browser_data_dir: PathBuf,
    #[cfg(target_os = "macos")]
    pub data_store_id: [u8; 16],
}

impl WindowFactory {
    pub fn create_window(
        &self,
        app: &tauri::AppHandle,
        label: &str,
    ) -> tauri::Result<tauri::WebviewWindow> {
        let mut config = self.config.clone();
        config.label = label.to_string();
        let builder = tauri::WebviewWindowBuilder::from_config(app, &config)?
            .data_directory(self.browser_data_dir.clone());
        #[cfg(target_os = "macos")]
        let builder = builder.data_store_identifier(self.data_store_id);
        builder.build()
    }
}

/// Window labels must stay within Tauri's allowed charset; profile ids are
/// UUID-like but sanitize defensively.
fn profile_window_label(profile_id: &str) -> String {
    let safe: String = profile_id
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '-'
            }
        })
        .collect();
    format!("profile-{safe}")
}

pub fn show_all_windows(app: &tauri::AppHandle) {
    let windows = app.webview_windows();
    for window in windows.values() {
        let _ = window.show();
        let _ = window.unminimize();
    }
    if let Some(window) = windows.values().next() {
        let _ = window.set_focus();
    }
}

fn focus_window(window: &tauri::WebviewWindow) {
    let _ = window.show();
    let _ = window.unminimize();
    let _ = window.set_focus();
}

/// The profile this window is pinned to, if the registry knows one. Returns
/// None for the bootstrap "main" window on first launch; the frontend then
/// resolves the profile itself and calls `report_window_profile`.
#[tauri::command]
pub fn get_window_profile(
    window: tauri::WebviewWindow,
    registry: tauri::State<'_, std::sync::Arc<WindowRegistry>>,
) -> Option<String> {
    registry.profile_for(window.label())
}

/// Record which profile this window resolved to, so the mapping is restored
/// on the next launch and `open_profile_window` can focus instead of
/// duplicating.
#[tauri::command]
pub fn report_window_profile(
    window: tauri::WebviewWindow,
    registry: tauri::State<'_, std::sync::Arc<WindowRegistry>>,
    profile_id: String,
) {
    registry.set_profile(window.label(), &profile_id);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_round_trips_through_disk() {
        let dir = std::env::temp_dir().join(format!("stimma-windows-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();

        let registry = WindowRegistry::load(&dir);
        assert!(registry.snapshot().is_empty());

        registry.set_profile("main", "profile-a");
        registry.set_profile("profile-b", "b");

        let reloaded = WindowRegistry::load(&dir);
        assert_eq!(reloaded.profile_for("main").as_deref(), Some("profile-a"));
        assert_eq!(reloaded.label_for_profile("b").as_deref(), Some("profile-b"));

        reloaded.remove("main");
        let reloaded = WindowRegistry::load(&dir);
        assert_eq!(reloaded.snapshot().len(), 1);
        assert!(reloaded.profile_for("main").is_none());

        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn labels_stay_in_tauri_charset() {
        assert_eq!(profile_window_label("abc-123"), "profile-abc-123");
        assert_eq!(profile_window_label("we ird/id"), "profile-we-ird-id");
    }
}

/// Close this window because its profile no longer exists. Returns false
/// when it is the last window — the caller then falls back to another
/// profile in place instead of leaving the app windowless.
#[tauri::command]
pub fn close_deleted_profile_window(
    window: tauri::WebviewWindow,
    registry: tauri::State<'_, std::sync::Arc<WindowRegistry>>,
) -> bool {
    let app = window.app_handle();
    if app.webview_windows().len() <= 1 {
        return false;
    }
    registry.remove(window.label());
    let _ = window.destroy();
    true
}

/// Browser-style profile switch: focus the profile's window if one is open,
/// otherwise open a new window pinned to it.
#[tauri::command]
pub fn open_profile_window(
    app: tauri::AppHandle,
    registry: tauri::State<'_, std::sync::Arc<WindowRegistry>>,
    factory: tauri::State<'_, std::sync::Arc<WindowFactory>>,
    profile_id: String,
) -> Result<(), String> {
    if let Some(label) = registry.label_for_profile(&profile_id) {
        if let Some(window) = app.get_webview_window(&label) {
            focus_window(&window);
            return Ok(());
        }
        registry.remove(&label);
    }

    let label = profile_window_label(&profile_id);
    if let Some(window) = app.get_webview_window(&label) {
        registry.set_profile(&label, &profile_id);
        focus_window(&window);
        return Ok(());
    }

    registry.set_profile(&label, &profile_id);
    match factory.create_window(&app, &label) {
        Ok(_) => Ok(()),
        Err(error) => {
            registry.remove(&label);
            Err(error.to_string())
        }
    }
}
