//! stimma-watchdog: Process supervisor with parent death detection.

use std::{
    env,
    fs::OpenOptions,
    io::{self, Write},
    path::{Path, PathBuf},
    process::{self, Command, Stdio},
    sync::atomic::{AtomicBool, AtomicU32, Ordering},
    thread,
    time::{Duration, Instant},
};

/// Set to true when parent dies or we need to shut down.
static SHUTDOWN: AtomicBool = AtomicBool::new(false);

/// The backend process PID (so parent monitor thread can kill it).
static BACKEND_PID: AtomicU32 = AtomicU32::new(0);

/// Max consecutive restart attempts before giving up.
const MAX_RESTARTS: u32 = 5;

/// Delay between restart attempts.
const RESTART_DELAY: Duration = Duration::from_secs(2);

/// If backend runs longer than this, reset the restart counter.
const STABILITY_THRESHOLD: Duration = Duration::from_secs(30);

/// How often to check if parent is still alive.
const PARENT_CHECK_INTERVAL: Duration = Duration::from_millis(500);

fn log_path() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(tmp) = env::var("TEMP") {
            return PathBuf::from(tmp).join("watchdog.log");
        }
        return PathBuf::from("watchdog.log");
    }

    #[cfg(not(windows))]
    {
        PathBuf::from("/tmp/watchdog.log")
    }
}

fn log(msg: &str) {
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(log_path()) {
        let _ = writeln!(f, "[{}] {}", process::id(), msg);
    }
}

#[derive(Debug)]
struct Args {
    parent_pid: Option<u32>,
    backend_binary: String,
    backend_args: Vec<String>,
}

fn parse_args(raw: &[String]) -> Result<Args, String> {
    if raw.is_empty() {
        return Err("Usage: stimma-watchdog [--parent-pid PID] <backend-binary> [args...]".to_string());
    }

    let mut idx = 0;
    let mut parent_pid: Option<u32> = None;

    if raw.get(idx).map(|s| s.as_str()) == Some("--parent-pid") {
        let pid = raw
            .get(idx + 1)
            .ok_or_else(|| "Missing value for --parent-pid".to_string())?
            .parse::<u32>()
            .map_err(|_| "Invalid parent PID".to_string())?;
        parent_pid = Some(pid);
        idx += 2;
    }

    let backend_binary = raw
        .get(idx)
        .ok_or_else(|| "Missing backend-binary argument".to_string())?
        .to_string();
    let backend_args = raw[idx + 1..].to_vec();

    Ok(Args {
        parent_pid,
        backend_binary,
        backend_args,
    })
}

fn main() {
    #[cfg(unix)]
    unsafe {
        libc::signal(libc::SIGPIPE, libc::SIG_IGN);
    }

    let _ = std::fs::remove_file(log_path());

    let raw_args: Vec<String> = env::args().skip(1).collect();
    let args = match parse_args(&raw_args) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("{}", e);
            process::exit(1);
        }
    };

    let backend_binary = resolve_backend_path(&args.backend_binary);
    let parent_pid = args.parent_pid.unwrap_or_else(default_parent_pid);

    log(&format!("Starting supervisor for: {:?}", backend_binary));
    log(&format!("Args: {:?}", args.backend_args));
    log(&format!("My PID: {}, Parent PID: {}", process::id(), parent_pid));

    thread::spawn(move || {
        parent_monitor(parent_pid);
    });

    let mut restart_count: u32 = 0;

    loop {
        if SHUTDOWN.load(Ordering::SeqCst) {
            log("Shutdown requested, exiting");
            let pid = BACKEND_PID.load(Ordering::SeqCst);
            if pid != 0 {
                kill_process_tree(pid);
            }
            process::exit(0);
        }

        log(&format!("Spawning backend (attempt {})", restart_count + 1));
        let start_time = Instant::now();

        match spawn_backend(&backend_binary, &args.backend_args) {
            Ok(mut child) => {
                let pid = child.id();
                BACKEND_PID.store(pid, Ordering::SeqCst);
                log(&format!("Backend started with pid: {}", pid));

                loop {
                    if SHUTDOWN.load(Ordering::SeqCst) {
                        log("Shutdown during wait, killing backend tree");
                        kill_process_tree(pid);
                        process::exit(0);
                    }

                    match child.try_wait() {
                        Ok(Some(status)) => {
                            let runtime = start_time.elapsed();
                            log(&format!(
                                "Backend exited with status: {:?} (ran for {:?})",
                                status, runtime
                            ));

                            if runtime >= STABILITY_THRESHOLD {
                                restart_count = 0;
                            }

                            if status.success() {
                                log("Backend exited cleanly, shutting down");
                                process::exit(0);
                            }

                            restart_count += 1;
                            if restart_count >= MAX_RESTARTS {
                                log(&format!("Max restarts ({}) exceeded, giving up", MAX_RESTARTS));
                                process::exit(2);
                            }

                            log(&format!("Will restart in {:?}...", RESTART_DELAY));
                            thread::sleep(RESTART_DELAY);
                            break;
                        }
                        Ok(None) => {
                            thread::sleep(Duration::from_millis(100));
                        }
                        Err(e) => {
                            log(&format!("Error waiting for backend: {}", e));
                            break;
                        }
                    }
                }
            }
            Err(e) => {
                let msg = format!("Failed to spawn backend {:?}: {}", backend_binary, e);
                log(&msg);
                eprintln!("{}", msg);
                restart_count += 1;

                if restart_count >= MAX_RESTARTS {
                    let msg = format!("Max restarts ({}) exceeded, giving up", MAX_RESTARTS);
                    log(&msg);
                    eprintln!("{}", msg);
                    process::exit(2);
                }

                thread::sleep(RESTART_DELAY);
            }
        }
    }
}

#[cfg(unix)]
fn default_parent_pid() -> u32 {
    unsafe { libc::getppid() as u32 }
}

#[cfg(windows)]
fn default_parent_pid() -> u32 {
    // Prefer explicit --parent-pid on Windows; fallback disables parent monitoring.
    0
}

fn parent_monitor(original_parent_pid: u32) {
    if original_parent_pid == 0 {
        log("Parent monitor disabled (parent pid = 0)");
        return;
    }

    log(&format!("Parent monitor started, watching PID {}", original_parent_pid));

    let mut check_count = 0u64;
    loop {
        check_count += 1;

        #[cfg(unix)]
        let parent_dead = {
            let current_ppid = unsafe { libc::getppid() as u32 };
            if check_count % 10 == 0 {
                log(&format!(
                    "Still watching parent {}, current ppid={}, checks={}",
                    original_parent_pid, current_ppid, check_count
                ));
            }
            current_ppid != original_parent_pid
        };

        #[cfg(windows)]
        let parent_dead = {
            if check_count % 10 == 0 {
                log(&format!(
                    "Still watching parent {}, checks={}",
                    original_parent_pid, check_count
                ));
            }
            is_process_dead_windows(original_parent_pid)
        };

        if parent_dead {
            log(&format!("PARENT DIED! parent={} no longer alive", original_parent_pid));
            SHUTDOWN.store(true, Ordering::SeqCst);

            let pid = BACKEND_PID.load(Ordering::SeqCst);
            log(&format!("Backend PID to kill: {}", pid));
            if pid != 0 {
                kill_process_tree(pid);
            }

            log("Cleanup complete, exiting");
            process::exit(0);
        }

        thread::sleep(PARENT_CHECK_INTERVAL);
    }
}

fn resolve_launcher(dir: &Path) -> Option<PathBuf> {
    #[cfg(windows)]
    {
        let exe = dir.join("main.dist").join("stimma-backend.exe");
        if exe.exists() {
            return Some(exe);
        }
        let run_cmd = dir.join("run.cmd");
        if run_cmd.exists() {
            return Some(run_cmd);
        }
        None
    }

    #[cfg(not(windows))]
    {
        let run_sh = dir.join("run.sh");
        if run_sh.exists() {
            return Some(run_sh);
        }
        let bin = dir.join("main.dist").join("stimma-backend");
        if bin.exists() {
            return Some(bin);
        }
        None
    }
}

fn resolve_backend_path(name: &str) -> PathBuf {
    let path = PathBuf::from(name);

    if path.is_absolute() || name.contains('/') || name.contains('\\') {
        if path.is_dir() {
            return resolve_launcher(&path).unwrap_or(path);
        }
        return path;
    }

    let self_path = match env::current_exe() {
        Ok(p) => p,
        Err(_) => return path,
    };

    let self_dir = match self_path.parent() {
        Some(d) => d,
        None => return path,
    };

    // macOS bundle: Contents/MacOS -> Contents/Resources
    let mac_resources = self_dir.parent().map(|p| p.join("Resources"));
    if let Some(res_dir) = mac_resources {
        let backend_dir = res_dir.join(name);
        if let Some(p) = resolve_launcher(&backend_dir) {
            return p;
        }
    }

    // Linux AppImage convention: <AppDir>/usr/bin -> <AppDir>/usr/lib/<ProductName>
    #[cfg(target_os = "linux")]
    if let Some(usr_dir) = self_dir.parent() {
        let lib_dir = usr_dir.join("lib");
        for product_dir in ["Stimma", "stimma"] {
            let backend_dir = lib_dir.join(product_dir).join(name);
            if let Some(p) = resolve_launcher(&backend_dir) {
                return p;
            }
        }
        if let Ok(entries) = std::fs::read_dir(&lib_dir) {
            for entry in entries.flatten() {
                let backend_dir = entry.path().join(name);
                if let Some(p) = resolve_launcher(&backend_dir) {
                    return p;
                }
            }
        }
    }

    // Windows/Linux bundle convention: <exe_dir>/resources
    let resources_dir = self_dir.join("resources").join(name);
    if let Some(p) = resolve_launcher(&resources_dir) {
        return p;
    }

    // Fallback: sibling directory near executable
    let sibling_dir = self_dir.join(name);
    if let Some(p) = resolve_launcher(&sibling_dir) {
        return p;
    }

    path
}

fn spawn_backend(binary: &PathBuf, args: &[String]) -> io::Result<process::Child> {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;

        let mut cmd = if binary
            .extension()
            .and_then(|ext| ext.to_str())
            .map(|ext| ext.eq_ignore_ascii_case("cmd") || ext.eq_ignore_ascii_case("bat"))
            .unwrap_or(false)
        {
            let mut c = Command::new("cmd");
            c.arg("/C").arg(binary);
            c
        } else {
            Command::new(binary)
        };

        cmd.args(args)
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .creation_flags(CREATE_NO_WINDOW);

        if let Some(parent_dir) = binary.parent() {
            let cwd = if parent_dir
                .file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.eq_ignore_ascii_case("main.dist"))
                .unwrap_or(false)
            {
                parent_dir.parent().unwrap_or(parent_dir)
            } else {
                parent_dir
            };
            cmd.current_dir(cwd);
        }

        log(&format!("spawn_backend command: {:?} args: {:?}", binary, args));
        return cmd.spawn();
    }

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;

        let mut cmd = Command::new(binary);
        cmd.args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit());

        unsafe {
            cmd.pre_exec(|| {
                if libc::setpgid(0, 0) != 0 {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }

        cmd.spawn()
    }
}

fn kill_process_tree(pid: u32) {
    log(&format!("Killing backend process tree for pid {}", pid));

    #[cfg(unix)]
    unsafe {
        libc::kill(pid as i32, libc::SIGKILL);
    }

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .status();
    }
}

#[cfg(windows)]
fn is_process_dead_windows(pid: u32) -> bool {
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::Threading::{OpenProcess, WaitForSingleObject};

    const WAIT_OBJECT_0: u32 = 0x0000_0000;
    const WAIT_TIMEOUT: u32 = 0x0000_0102;
    const PROCESS_SYNCHRONIZE: u32 = 0x0010_0000;

    unsafe {
        let handle = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
        if handle.is_null() {
            return true;
        }

        let result = WaitForSingleObject(handle, 0);
        CloseHandle(handle);

        result == WAIT_OBJECT_0 || result != WAIT_TIMEOUT
    }
}
