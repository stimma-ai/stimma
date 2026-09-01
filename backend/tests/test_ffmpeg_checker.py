import subprocess

import ffmpeg_checker
import pytest
from ffmpeg_checker import ExecutableStatus, FFmpegChecker


@pytest.fixture(autouse=True)
def _isolate_checker_cache():
    """Synthetic health results must not leak into later media tests."""
    FFmpegChecker().clear_cache()
    yield
    FFmpegChecker().clear_cache()


def _checker(monkeypatch):
    checker = FFmpegChecker()
    checker.clear_cache()
    monkeypatch.setattr(ffmpeg_checker.get_settings(), "debug_force_ffmpeg_missing", False)
    return checker


def test_health_runs_both_binaries(monkeypatch):
    checker = _checker(monkeypatch)
    monkeypatch.setattr(ffmpeg_checker.shutil, "which", lambda name: f"/tools/{name}")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(ffmpeg_checker.subprocess, "run", run)

    health = checker.check_health(use_cache=False)

    assert health.ffmpeg == ExecutableStatus.AVAILABLE
    assert health.ffprobe == ExecutableStatus.AVAILABLE
    assert [call[0] for call in calls] == [["/tools/ffmpeg", "-version"], ["/tools/ffprobe", "-version"]]
    assert all(call[1]["timeout"] == 5 for call in calls)


def test_health_distinguishes_missing_from_broken(monkeypatch):
    checker = _checker(monkeypatch)
    monkeypatch.setattr(
        ffmpeg_checker.shutil,
        "which",
        lambda name: None if name == "ffprobe" else "/tools/ffmpeg",
    )
    monkeypatch.setattr(
        ffmpeg_checker.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, b"", b"dyld failed"),
    )

    health = checker.check_health(use_cache=False)
    warning = checker.warning_for_health(health)

    assert health.ffmpeg == ExecutableStatus.BROKEN
    assert health.ffprobe == ExecutableStatus.MISSING
    assert checker.check_availability() == (False, False)
    assert warning["type"] == "ffmpeg_broken"
    assert warning["action_url"] == "https://stimma.ai/link/ffmpeg"


def test_health_treats_loader_error_as_broken(monkeypatch):
    checker = _checker(monkeypatch)
    monkeypatch.setattr(ffmpeg_checker.shutil, "which", lambda name: f"/tools/{name}")
    monkeypatch.setattr(
        ffmpeg_checker.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("Library not loaded")),
    )

    health = checker.check_health(use_cache=False)

    assert health.ffmpeg == ExecutableStatus.BROKEN
    assert health.ffprobe == ExecutableStatus.BROKEN


def test_health_treats_hung_binary_as_broken(monkeypatch):
    checker = _checker(monkeypatch)
    monkeypatch.setattr(ffmpeg_checker.shutil, "which", lambda name: f"/tools/{name}")
    monkeypatch.setattr(
        ffmpeg_checker.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        ),
    )

    health = checker.check_health(use_cache=False)

    assert health.ffmpeg == ExecutableStatus.BROKEN
    assert health.ffprobe == ExecutableStatus.BROKEN
