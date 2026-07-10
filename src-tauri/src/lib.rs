use std::io::{BufRead, BufReader};
#[cfg(target_os = "macos")]
use std::path::Path;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Arc;
use tauri::Manager;
use tokio::sync::RwLock;

mod embed;
mod voice;

/// Set to true only when the app is genuinely quitting (Cmd-Q on macOS, the
/// tray "Quit" item on Windows/Linux). Closing the main window leaves this
/// false so the close is intercepted and the window is hidden instead — the
/// Tauri process stays alive, which keeps the watchdog and backend warm.
static QUITTING: AtomicBool = AtomicBool::new(false);

/// Build distribution, baked in at compile time: "dev" (default) or
/// "official" (set only by release CI via the STIMMA_DISTRIBUTION env var).
/// Passed to the backend sidecar so all three layers agree.
const STIMMA_DISTRIBUTION: &str = match option_env!("STIMMA_DISTRIBUTION") {
    Some(v) => v,
    None => "dev",
};

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

// Shared state for the backend port
struct BackendState {
    port: RwLock<Option<u16>>,
    watchdog_pid: AtomicU32,
}

// Tauri command to trigger the native print dialog on the webview
#[tauri::command]
async fn print_webview(webview: tauri::Webview) -> Result<(), String> {
    webview.print().map_err(|e| e.to_string())
}

// Tauri command to receive console logs from the webview.
#[tauri::command]
fn log_from_webview(level: String, message: String) {
    match level.as_str() {
        "error" => log::error!(target: "web", "{}", message),
        "warn" => log::warn!(target: "web", "{}", message),
        "debug" => log::debug!(target: "web", "{}", message),
        _ => log::info!(target: "web", "{}", message),
    }
}

// Tauri command to get the backend port
#[tauri::command]
async fn get_backend_port(state: tauri::State<'_, Arc<BackendState>>) -> Result<u16, String> {
    log::info!("[get_backend_port] Command invoked, waiting for port...");
    for i in 0..300 {
        if let Some(port) = *state.port.read().await {
            log::info!("[get_backend_port] Returning port: {}", port);
            return Ok(port);
        }
        if i % 20 == 0 {
            log::info!("[get_backend_port] Still waiting... attempt {}/300", i);
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
    log::error!("[get_backend_port] Timeout waiting for port!");
    Err("Backend port not available after timeout".to_string())
}

fn parse_backend_port(line: &str) -> Option<u16> {
    let idx = line.find("STIMMA_BACKEND_PORT=")?;
    let after_prefix = &line[idx + "STIMMA_BACKEND_PORT=".len()..];
    let port_str: String = after_prefix
        .chars()
        .take_while(|c| c.is_ascii_digit())
        .collect();
    port_str.parse::<u16>().ok()
}

/// Derive the data and cache directories from the bundle identifier.
///
/// Explicit directory environment variables take precedence. Otherwise, the
/// bundle ID (e.g., "ai.stimma.stimma.debug") is used directly as the folder
/// name. Packaged apps default to the "default" sandbox; dev launches can
/// override it with STIMMA_SANDBOX.
pub(crate) fn get_app_dirs(bundle_id: &str) -> (PathBuf, PathBuf) {
    let explicit_data_dir = std::env::var_os("STIMMA_DATA_DIR").map(PathBuf::from);
    let explicit_cache_dir = std::env::var_os("STIMMA_CACHE_DIR").map(PathBuf::from);
    let sandbox = std::env::var("STIMMA_SANDBOX")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "default".to_string());

    #[cfg(target_os = "macos")]
    {
        let home = std::env::var("HOME").unwrap_or_default();
        let data_dir = PathBuf::from(&home)
            .join("Library")
            .join("Application Support")
            .join(bundle_id)
            .join(&sandbox);
        let cache_dir = PathBuf::from(&home)
            .join("Library")
            .join("Caches")
            .join(bundle_id)
            .join(&sandbox);
        (
            explicit_data_dir.unwrap_or(data_dir),
            explicit_cache_dir.unwrap_or(cache_dir),
        )
    }

    #[cfg(target_os = "windows")]
    {
        let local_app_data = std::env::var("LOCALAPPDATA")
            .unwrap_or_else(|_| {
                let home = std::env::var("USERPROFILE").unwrap_or_default();
                format!("{}\\AppData\\Local", home)
            });
        let data_dir = PathBuf::from(&local_app_data).join(bundle_id).join(&sandbox);
        let cache_dir = data_dir.clone();
        (
            explicit_data_dir.unwrap_or(data_dir),
            explicit_cache_dir.unwrap_or(cache_dir),
        )
    }

    #[cfg(target_os = "linux")]
    {
        let home = std::env::var("HOME").unwrap_or_default();
        let xdg_data = std::env::var("XDG_DATA_HOME")
            .unwrap_or_else(|_| format!("{}/.local/share", home));
        let xdg_cache = std::env::var("XDG_CACHE_HOME")
            .unwrap_or_else(|_| format!("{}/.cache", home));
        let data_dir = PathBuf::from(&xdg_data).join(bundle_id).join(&sandbox);
        let cache_dir = PathBuf::from(&xdg_cache).join(bundle_id).join(&sandbox);
        (
            explicit_data_dir.unwrap_or(data_dir),
            explicit_cache_dir.unwrap_or(cache_dir),
        )
    }
}

/// Load the WKWebView profile identifier owned by this Stimma sandbox.
///
/// WKWebView does not support a caller-selected data directory on macOS. On
/// macOS 14+ it does support named persistent data stores, so keeping a random
/// identifier inside the sandbox gives the browser profile the same lifecycle
/// as the rest of the sandbox: remove the sandbox and the next launch gets an
/// empty profile instead of reconnecting to stale data in ~/Library/WebKit.
#[cfg(target_os = "macos")]
fn get_or_create_webview_data_store_id(browser_dir: &Path) -> std::io::Result<[u8; 16]> {
    use std::io::Write;

    std::fs::create_dir_all(browser_dir)?;
    let id_path = browser_dir.join("data-store-id");

    let existing_bytes = std::fs::read(&id_path);
    if let Ok(bytes) = &existing_bytes {
        if let Ok(identifier) = <[u8; 16]>::try_from(bytes.as_slice()) {
            return Ok(identifier);
        }
    }

    let identifier = *uuid::Uuid::new_v4().as_bytes();
    let temporary_path = browser_dir.join(format!(".data-store-id.{}", std::process::id()));
    let mut temporary = std::fs::File::create(&temporary_path)?;
    temporary.write_all(&identifier)?;
    temporary.sync_all()?;
    drop(temporary);

    let selected_identifier = if existing_bytes.is_ok() {
        // Repair a corrupt/partial marker left by an interrupted old launch.
        std::fs::rename(&temporary_path, &id_path)?;
        identifier
    } else {
        // `hard_link` is an atomic create-if-absent. If two app processes race
        // before the single-instance plugin selects the winner, both use the
        // identifier that actually won on disk.
        match std::fs::hard_link(&temporary_path, &id_path) {
            Ok(()) => identifier,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                let bytes = std::fs::read(&id_path)?;
                <[u8; 16]>::try_from(bytes.as_slice()).map_err(|_| {
                    std::io::Error::new(
                        std::io::ErrorKind::InvalidData,
                        "browser data-store identifier is corrupt",
                    )
                })?
            }
            Err(error) => return Err(error),
        }
    };

    let _ = std::fs::remove_file(temporary_path);
    Ok(selected_identifier)
}

#[cfg(all(test, target_os = "macos"))]
mod webview_data_store_tests {
    use super::get_or_create_webview_data_store_id;

    #[test]
    fn browser_profile_follows_the_sandbox_lifecycle() {
        let sandbox = std::env::temp_dir().join(format!(
            "stimma-webview-profile-test-{}",
            uuid::Uuid::new_v4()
        ));
        let browser_dir = sandbox.join("browser");

        let first = get_or_create_webview_data_store_id(&browser_dir).unwrap();
        let reopened = get_or_create_webview_data_store_id(&browser_dir).unwrap();
        assert_eq!(
            first, reopened,
            "an existing sandbox must retain its profile"
        );

        std::fs::remove_dir_all(&sandbox).unwrap();
        let recreated = get_or_create_webview_data_store_id(&browser_dir).unwrap();
        assert_ne!(
            first, recreated,
            "a recreated sandbox must not reconnect to stale browser state"
        );

        std::fs::remove_dir_all(sandbox).unwrap();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let dev_mode = std::env::var("STIMMA_DEV").is_ok();

    // Route whisper.cpp / ggml's internal logging through the `log` crate so it
    // obeys our level filters instead of spewing per-token decoder dumps raw to
    // stderr. Paired with a `Warn` filter on its target below.
    whisper_rs::install_whisper_log_trampoline();

    let dev_backend_port = std::env::var("STIMMA_BACKEND_PORT")
        .ok()
        .and_then(|p| p.parse::<u16>().ok())
        .unwrap_or(9191);

    let backend_state = Arc::new(BackendState {
        port: RwLock::new(if dev_mode {
            Some(dev_backend_port)
        } else {
            None
        }),
        watchdog_pid: AtomicU32::new(0),
    });

    // Tauri normally creates configured windows before `setup`, which leaves
    // their WebView storage at the OS default. Take ownership of the main
    // window config so we can attach a sandbox-specific browser profile before
    // the WebView is constructed.
    let mut context = tauri::generate_context!();
    let main_window_index = context
        .config()
        .app
        .windows
        .iter()
        .position(|window| window.label == "main")
        .expect("main window missing from Tauri config");
    let main_window_config = context.config_mut().app.windows.remove(main_window_index);
    let bundle_id = context.config().identifier.clone();
    let (app_data_dir, app_cache_dir) = get_app_dirs(&bundle_id);
    let browser_data_dir = app_data_dir.join("browser");

    std::fs::create_dir_all(&app_data_dir).expect("failed to create Stimma data directory");
    std::fs::create_dir_all(&app_cache_dir).expect("failed to create Stimma cache directory");
    std::fs::create_dir_all(&browser_data_dir).expect("failed to create browser data directory");

    #[cfg(target_os = "macos")]
    let browser_data_store_id = get_or_create_webview_data_store_id(&browser_data_dir)
        .expect("failed to initialize sandbox browser profile");

    tauri::Builder::default()
        // Must be the first plugin registered. If the user relaunches Stimma
        // while the window is hidden (taskbar/launcher click, or when a Linux
        // tray icon failed to render), focus the existing instance instead of
        // spawning a second Tauri process — which would start a second watchdog
        // and backend, colliding on ports and paying the startup cost twice.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main_window(app);
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_log::Builder::default()
                // whisper.cpp's info/debug logging is an extreme firehose (every
                // decoder token, every seek). Keep warnings/errors, drop the rest.
                .level_for("whisper_rs::whisper_sys_log", log::LevelFilter::Warn)
                .build(),
        )
        .plugin(tauri_plugin_drag::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(backend_state.clone())
        .manage(Arc::new(voice::VoiceState::new()))
        .invoke_handler(tauri::generate_handler![
            get_backend_port,
            print_webview,
            log_from_webview,
            embed::embed_metadata,
            voice::voice_model_status,
            voice::voice_download_model,
            voice::voice_start,
            voice::voice_stop,
            voice::voice_cancel,
            voice::voice_keepalive
        ])
        .on_window_event(|window, event| {
            // Closing the main window hides it rather than quitting, so the
            // backend stays warm. A genuine quit sets QUITTING first.
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" && !QUITTING.load(Ordering::SeqCst) {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .setup(move |app| {
            let main_window_builder =
                tauri::WebviewWindowBuilder::from_config(app.handle(), &main_window_config)?
                    .data_directory(browser_data_dir.clone());

            #[cfg(target_os = "macos")]
            let main_window_builder =
                main_window_builder.data_store_identifier(browser_data_store_id);

            main_window_builder.build()?;

            log::info!("[stimma] Browser data dir: {:?}", browser_data_dir);

            // macOS keeps the app in the Dock with no windows (like Music.app);
            // the default app menu already binds Quit to Cmd-Q. Windows/Linux
            // have no Dock equivalent, so a hidden window needs a tray icon to
            // get back to it and to quit.
            #[cfg(not(target_os = "macos"))]
            {
                use tauri::menu::{Menu, MenuItem};
                use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};

                let show_item = MenuItem::with_id(app, "show", "Show Stimma", true, None::<&str>)?;
                let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
                let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

                TrayIconBuilder::with_id("main")
                    .tooltip("Stimma")
                    .icon(app.default_window_icon().unwrap().clone())
                    .menu(&menu)
                    .show_menu_on_left_click(false)
                    .on_menu_event(|app, event| match event.id.as_ref() {
                        "show" => show_main_window(app),
                        "quit" => {
                            QUITTING.store(true, Ordering::SeqCst);
                            app.exit(0);
                        }
                        _ => {}
                    })
                    .on_tray_icon_event(|tray, event| {
                        if let TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        } = event
                        {
                            show_main_window(tray.app_handle());
                        }
                    })
                    .build(app)?;
            }

            if dev_mode {
                log::info!(
                    "[stimma] Dev mode: using external backend on port {}",
                    dev_backend_port
                );
            } else {
                // Production: spawn the watchdog which supervises the backend
                // Watchdog uses getppid() polling to detect when we die
                let exe_path = std::env::current_exe().expect("Failed to get current exe path");
                let exe_dir = exe_path.parent().expect("Failed to get exe directory");
                let watchdog_path = {
                    let base = exe_dir.join("stimma-watchdog");
                    if base.exists() {
                        base
                    } else {
                        exe_dir.join("stimma-watchdog.exe")
                    }
                };
                let parent_pid = std::process::id().to_string();

                // Read the bundle identifier from Tauri config (baked in at build time,
                // patched by CI per channel). This determines the data directory.
                let bundle_id = app.config().identifier.clone();

                let (data_dir, cache_dir) = get_app_dirs(&bundle_id);

                // Ensure directories exist
                std::fs::create_dir_all(&data_dir).ok();
                std::fs::create_dir_all(&cache_dir).ok();

                log::info!("[stimma] Bundle ID: {}", bundle_id);
                log::info!("[stimma] Data dir: {:?}", data_dir);
                log::info!("[stimma] Cache dir: {:?}", cache_dir);
                log::info!("[stimma] Spawning watchdog from: {:?}", watchdog_path);

                let app_version = app.package_info().version.to_string();

                let mut cmd = std::process::Command::new(&watchdog_path);
                cmd.args(["--parent-pid", &parent_pid, "stimma-backend", "--port", "0"])
                    .env("STIMMA_DATA_DIR", &data_dir)
                    .env("STIMMA_CACHE_DIR", &cache_dir)
                    // Build distribution (compile-time constant) and app
                    // version, threaded through to the backend sidecar.
                    .env("STIMMA_DISTRIBUTION", STIMMA_DISTRIBUTION)
                    .env("STIMMA_APP_VERSION", &app_version)
                    // Prevent the bundled Python from writing .pyc files into the
                    // (code-signed) app bundle at runtime, which invalidates the
                    // macOS signature seal and triggers "app is damaged".
                    .env("PYTHONDONTWRITEBYTECODE", "1")
                    .stdin(Stdio::null())
                    .stdout(Stdio::piped())
                    .stderr(Stdio::piped());

                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    const CREATE_NO_WINDOW: u32 = 0x08000000;
                    cmd.creation_flags(CREATE_NO_WINDOW);
                }

                let mut child = cmd.spawn().expect("Failed to spawn watchdog");

                let pid = child.id();
                backend_state.watchdog_pid.store(pid, Ordering::SeqCst);
                log::info!("[stimma] Watchdog spawned with pid: {}", pid);

                let stdout = child.stdout.take().expect("Failed to get stdout");
                let stderr = child.stderr.take().expect("Failed to get stderr");

                // Don't need the child handle anymore
                drop(child);

                let state_clone = backend_state.clone();

                // Thread to read stdout and parse port
                std::thread::spawn(move || {
                    let reader = BufReader::new(stdout);
                    for line in reader.lines() {
                        match line {
                            Ok(line_str) => {
                                if let Some(port) = parse_backend_port(&line_str) {
                                    log::info!("[backend] Detected port: {}", port);
                                    let state = state_clone.clone();
                                    tauri::async_runtime::spawn(async move {
                                        *state.port.write().await = Some(port);
                                    });
                                }
                                log::info!("[backend] {}", line_str);
                            }
                            Err(e) => {
                                log::error!("[backend] stdout read error: {}", e);
                                break;
                            }
                        }
                    }
                    log::info!("[backend] stdout reader finished");
                });

                // Thread to read stderr
                std::thread::spawn(move || {
                    let reader = BufReader::new(stderr);
                    for line in reader.lines() {
                        match line {
                            Ok(line_str) => {
                                if let Some(port) = parse_backend_port(&line_str) {
                                    log::info!("[backend] Detected port from stderr: {}", port);
                                    let state = backend_state.clone();
                                    tauri::async_runtime::spawn(async move {
                                        *state.port.write().await = Some(port);
                                    });
                                }
                                log::warn!("[backend] {}", line_str);
                            }
                            Err(e) => {
                                log::error!("[backend] stderr read error: {}", e);
                                break;
                            }
                        }
                    }
                    log::info!("[backend] stderr reader finished");
                });
            }

            Ok(())
        })
        .build(context)
        .expect("error while building tauri application")
        .run(|_app, _event| {
            // Clicking the Dock icon with no visible windows re-shows the
            // hidden main window (macOS only). The watchdog still detects our
            // death via getppid() when the process actually exits.
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = _event {
                show_main_window(_app);
            }
        });
}
