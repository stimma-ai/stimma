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

#[cfg(target_os = "linux")]
extern "C" fn request_shutdown(_: libc::c_int) {
    SHUTDOWN.store(true, Ordering::SeqCst);
}

/// Called synchronously by Electron before it releases the AppImage mount.
/// A pidfd also becomes readable for a zombie, unlike kill(pid, 0): Electron
/// cannot reap its watchdog while blocked waiting for this command to return.
#[cfg(target_os = "linux")]
fn shutdown_watchdog(pid: u32) -> io::Result<()> {
    if pid <= 1 || pid > i32::MAX as u32 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "Invalid watchdog PID",
        ));
    }
    unsafe {
        let fd = libc::syscall(libc::SYS_pidfd_open, pid, 0) as i32;
        if fd < 0 {
            let error = io::Error::last_os_error();
            return if error.raw_os_error() == Some(libc::ESRCH) {
                Ok(())
            } else {
                Err(error)
            };
        }
        // Signal through the same handle so PID reuse cannot target another app.
        let result = libc::syscall(libc::SYS_pidfd_send_signal, fd, libc::SIGTERM, 0usize, 0);
        let outcome = if result < 0 {
            Err(io::Error::last_os_error())
        } else {
            let mut pollfd = libc::pollfd {
                fd,
                events: libc::POLLIN,
                revents: 0,
            };
            match libc::poll(&mut pollfd, 1, 5000) {
                0 => Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "Watchdog shutdown timed out",
                )),
                -1 => Err(io::Error::last_os_error()),
                _ => Ok(()),
            }
        };
        libc::close(fd);
        outcome
    }
}

/// The backend process PID (so parent monitor thread can kill it).
static BACKEND_PID: AtomicU32 = AtomicU32::new(0);

/// Max consecutive restart attempts before giving up.
const MAX_RESTARTS: u32 = 5;

/// Delay between restart attempts.
const RESTART_DELAY: Duration = Duration::from_secs(2);

/// If backend runs longer than this, reset the restart counter.
const STABILITY_THRESHOLD: Duration = Duration::from_secs(30);

/// How long the backend leader gets to run its shutdown hooks after SIGTERM
/// before the group is killed. Electron waits five seconds for the whole stop
/// on Linux, so this leaves room to kill and reap the survivors.
#[cfg(unix)]
const GRACEFUL_STOP: Duration = Duration::from_secs(3);

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
    if let Ok(mut f) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path())
    {
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
        return Err(
            "Usage: stimma-watchdog [--parent-pid PID] <backend-binary> [args...]".to_string(),
        );
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

    let raw_args: Vec<String> = env::args().skip(1).collect();
    #[cfg(target_os = "linux")]
    {
        if raw_args.first().map(String::as_str) == Some("--shutdown-watchdog") {
            let result = raw_args
                .get(1)
                .and_then(|pid| pid.parse().ok())
                .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "Missing watchdog PID"))
                .and_then(shutdown_watchdog);
            if let Err(error) = result {
                eprintln!("Unable to stop watchdog: {error}");
                process::exit(1);
            }
            return;
        }
        unsafe {
            libc::signal(
                libc::SIGTERM,
                request_shutdown as *const () as libc::sighandler_t,
            );
            // Adopt Python grandchildren so cleanup can wait for all of them,
            // not just the backend leader, before acknowledging shutdown.
            if libc::prctl(libc::PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0 {
                eprintln!(
                    "Unable to supervise backend descendants: {}",
                    io::Error::last_os_error()
                );
                process::exit(1);
            }
        }
    }
    let _ = std::fs::remove_file(log_path());
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
    log(&format!(
        "My PID: {}, Parent PID: {}",
        process::id(),
        parent_pid
    ));

    // The installer can terminate us before parent_monitor runs. A Windows
    // job owns the entire descendant tree, including cmd.exe, Python, and
    // multiprocessing workers, even if an intermediate process has exited.
    // Enrol ourselves BEFORE spawning anything so children inherit the job
    // without a spawn/assignment race. Only this process owns the job handle.
    #[cfg(windows)]
    if let Err(error) = own_process_tree() {
        eprintln!("Unable to supervise backend process tree: {error}");
        process::exit(1);
    }

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
                        log("Shutdown during wait, stopping backend tree");
                        request_backend_stop(&mut child);
                        kill_process_tree(pid);
                        let _ = child.wait();
                        reap_backend_descendants(pid);
                        process::exit(0);
                    }

                    match child.try_wait() {
                        Ok(Some(status)) => {
                            let runtime = start_time.elapsed();
                            log(&format!(
                                "Backend exited with status: {:?} (ran for {:?})",
                                status, runtime
                            ));
                            kill_process_tree(pid);
                            reap_backend_descendants(pid);
                            BACKEND_PID.store(0, Ordering::SeqCst);

                            if runtime >= STABILITY_THRESHOLD {
                                restart_count = 0;
                            }

                            if status.success() {
                                log("Backend exited cleanly, shutting down");
                                process::exit(0);
                            }

                            // Tell the shell to preserve its bounded console tail before
                            // a restart replaces early failures with ordinary output.
                            eprintln!("[watchdog] Backend crashed: {:?}", status);
                            restart_count += 1;
                            if restart_count >= MAX_RESTARTS {
                                log(&format!(
                                    "Max restarts ({}) exceeded, giving up",
                                    MAX_RESTARTS
                                ));
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

#[cfg(windows)]
fn own_process_tree() -> io::Result<()> {
    use windows_sys::Win32::{
        Foundation::CloseHandle,
        System::{
            JobObjects::{
                AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
                SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
            },
            Threading::GetCurrentProcess,
        },
    };
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return Err(io::Error::last_os_error());
        }
        let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &limits as *const _ as *const _,
            std::mem::size_of_val(&limits) as u32,
        ) == 0
            || AssignProcessToJobObject(job, GetCurrentProcess()) == 0
        {
            let error = io::Error::last_os_error();
            CloseHandle(job);
            return Err(error);
        }
        // Intentionally retain the non-inheritable handle until process exit.
        // Windows closes it even on TerminateProcess, killing all descendants.
        Ok(())
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

    log(&format!(
        "Parent monitor started, watching PID {}",
        original_parent_pid
    ));

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
            log(&format!(
                "PARENT DIED! parent={} no longer alive",
                original_parent_pid
            ));
            SHUTDOWN.store(true, Ordering::SeqCst);

            // Let the supervisor thread kill and reap the whole tree. Exiting
            // here would race it and abandon descendants before cleanup.
            return;
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

/// The backend command line. A Windows `run.cmd` launcher is spawned directly:
/// Rust's standard library runs batch files through cmd.exe with its path and
/// arguments escaped for it, while a hand-built `cmd /C` line loses the quotes
/// around install paths containing spaces or `&`.
fn backend_command(binary: &Path, args: &[String]) -> Command {
    let mut cmd = Command::new(binary);
    cmd.args(args);
    cmd
}

fn spawn_backend(binary: &PathBuf, args: &[String]) -> io::Result<process::Child> {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;

        let mut cmd = backend_command(binary, args);
        cmd.env("PYTHONUTF8", "1")
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

        log(&format!(
            "spawn_backend command: {:?} args: {:?}",
            binary, args
        ));
        return cmd.spawn();
    }

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;

        let mut cmd = backend_command(binary, args);
        cmd.stdin(Stdio::null())
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

/// Ask the backend leader to shut down so its shutdown hooks run and it stops
/// its own workers, then give it a bounded wait. The caller kills the group.
fn request_backend_stop(child: &mut process::Child) {
    #[cfg(unix)]
    {
        unsafe {
            libc::kill(child.id() as i32, libc::SIGTERM);
        }
        let deadline = Instant::now() + GRACEFUL_STOP;
        while Instant::now() < deadline {
            match child.try_wait() {
                Ok(None) => thread::sleep(Duration::from_millis(50)),
                _ => return,
            }
        }
        log("Backend did not stop in time, killing it");
    }
    #[cfg(not(unix))]
    let _ = child;
}

fn kill_process_tree(pid: u32) {
    log(&format!("Killing backend process tree for pid {}", pid));

    #[cfg(unix)]
    unsafe {
        // spawn_backend creates this group before exec. Killing just the
        // leader strands multiprocessing workers and the resource tracker.
        libc::kill(-(pid as i32), libc::SIGKILL);
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

fn reap_backend_descendants(pid: u32) {
    #[cfg(target_os = "linux")]
    unsafe {
        // The group has received SIGKILL. Wait for adopted workers to release
        // their mappings too; returning after only the leader exits is a race.
        loop {
            if libc::waitpid(-(pid as i32), std::ptr::null_mut(), 0) >= 0 {
                continue;
            }
            if io::Error::last_os_error().raw_os_error() != Some(libc::EINTR) {
                break;
            }
        }
    }
    #[cfg(not(target_os = "linux"))]
    let _ = pid;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn batch_launcher_is_spawned_directly_with_its_arguments() {
        let launcher = Path::new(r"C:\Program Files\R&D Tools\Stimma\resources\backend\run.cmd");
        let args = vec!["--port".to_string(), "9191".to_string()];
        let cmd = backend_command(launcher, &args);
        assert_eq!(cmd.get_program(), launcher.as_os_str());
        let built: Vec<_> = cmd.get_args().collect();
        assert_eq!(built, ["--port", "9191"]);
    }
}
