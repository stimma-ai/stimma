#![cfg(target_os = "linux")]

use std::{
    io::{BufRead, BufReader},
    process::{Child, Command, Stdio},
    time::{Duration, Instant},
};

const WATCHDOG: &str = env!("CARGO_BIN_EXE_stimma-watchdog");

struct Supervisor(Child);

impl Drop for Supervisor {
    fn drop(&mut self) {
        let _ = Command::new(WATCHDOG)
            .args(["--shutdown-watchdog", &self.0.id().to_string()])
            .status();
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn synchronous_shutdown_reaps_backend_and_workers_before_returning() {
    // The worker ignores TERM, just like an unresponsive native Python task.
    let mut supervisor = Supervisor(
        Command::new(WATCHDOG)
            .args([
                "--parent-pid",
                &std::process::id().to_string(),
                "/bin/sh",
                "-c",
                "trap '' TERM; sleep 60 & echo \"$$ $!\"; wait",
            ])
            .stdout(Stdio::piped())
            .spawn()
            .unwrap(),
    );
    let mut line = String::new();
    BufReader::new(supervisor.0.stdout.take().unwrap())
        .read_line(&mut line)
        .unwrap();
    let pids: Vec<u32> = line
        .split_whitespace()
        .map(|pid| pid.parse().unwrap())
        .collect();
    assert_eq!(pids.len(), 2);
    let mut neighbor = Command::new("sleep").arg("60").spawn().unwrap();

    let started = Instant::now();
    let stopped = Command::new(WATCHDOG)
        .args(["--shutdown-watchdog", &supervisor.0.id().to_string()])
        .status()
        .unwrap();
    let neighbor_alive = neighbor.try_wait().unwrap().is_none();
    let _ = neighbor.kill();
    let _ = neighbor.wait();

    assert!(stopped.success());
    assert!(started.elapsed() < Duration::from_secs(5));
    for pid in pids {
        assert!(
            !std::path::Path::new(&format!("/proc/{pid}")).exists(),
            "Process {pid} survived shutdown"
        );
    }
    assert!(
        neighbor_alive,
        "Shutdown must stay inside the backend process group"
    );
    assert!(supervisor.0.wait().unwrap().success());
    // Repeating the quit hook after the supervisor is reaped is harmless.
    assert!(Command::new(WATCHDOG)
        .args(["--shutdown-watchdog", &supervisor.0.id().to_string()])
        .status()
        .unwrap()
        .success());
}

#[test]
fn parent_death_still_kills_backend_group() {
    let mut parent = Command::new("/bin/sh")
        .args([
            "-c",
            "\"$1\" --parent-pid $$ /bin/sh -c 'sleep 60 & echo \"$$ $!\"; wait' & wait",
            "parent",
            WATCHDOG,
        ])
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut line = String::new();
    BufReader::new(parent.stdout.take().unwrap())
        .read_line(&mut line)
        .unwrap();
    let pids: Vec<u32> = line
        .split_whitespace()
        .map(|pid| pid.parse().unwrap())
        .collect();
    let _ = parent.kill();
    let _ = parent.wait();
    assert_eq!(pids.len(), 2);
    let deadline = Instant::now() + Duration::from_secs(3);
    while pids
        .iter()
        .any(|pid| std::path::Path::new(&format!("/proc/{pid}")).exists())
    {
        assert!(
            Instant::now() < deadline,
            "Parent-death cleanup left workers alive"
        );
        std::thread::sleep(Duration::from_millis(25));
    }
}
