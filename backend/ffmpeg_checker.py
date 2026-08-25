"""
FFmpeg detection and installation guidance service.

Provides FFmpeg availability checking with singleton caching,
platform-specific installation instructions, and one-time warning flags.
"""
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple
from core.logging import get_logger

from app_dirs import get_cache_dir
from config import get_settings

log = get_logger(__name__)


class ExecutableStatus(str, Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    BROKEN = "broken"


@dataclass(frozen=True)
class FFmpegHealth:
    ffmpeg: ExecutableStatus
    ffprobe: ExecutableStatus

    @property
    def available(self) -> bool:
        return self.ffmpeg == ExecutableStatus.AVAILABLE and self.ffprobe == ExecutableStatus.AVAILABLE

    @property
    def warning_type(self) -> Optional[str]:
        if ExecutableStatus.BROKEN in (self.ffmpeg, self.ffprobe):
            return "ffmpeg_broken"
        if ExecutableStatus.MISSING in (self.ffmpeg, self.ffprobe):
            return "ffmpeg_missing"
        return None


class FFmpegChecker:
    """Singleton service for detecting FFmpeg availability and providing installation instructions."""

    _instance: Optional['FFmpegChecker'] = None
    _cache_ttl = 300  # 5 minutes in seconds

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._last_check_time: float = 0
        self._cached_health = FFmpegHealth(ExecutableStatus.MISSING, ExecutableStatus.MISSING)

        log.debug("FFmpegChecker initialized")

    def check_availability(self, use_cache: bool = True) -> Tuple[bool, bool]:
        """
        Check if ffmpeg and ffprobe are available on the system.

        Args:
            use_cache: If True, use cached result if within TTL. Default True.

        Returns:
            Tuple of (ffmpeg_available, ffprobe_available)
        """
        health = self.check_health(use_cache=use_cache)
        return (
            health.ffmpeg == ExecutableStatus.AVAILABLE,
            health.ffprobe == ExecutableStatus.AVAILABLE,
        )

    def check_health(self, use_cache: bool = True) -> FFmpegHealth:
        """Return whether each executable is available, missing, or broken."""
        current_time = time.time()

        # Dev-only override to simulate a missing FFmpeg install (e.g. for screenshots)
        if get_settings().debug_force_ffmpeg_missing:
            self._last_check_time = current_time
            self._cached_health = FFmpegHealth(ExecutableStatus.MISSING, ExecutableStatus.MISSING)
            log.debug("FFmpeg availability forced to missing via debug_force_ffmpeg_missing")
            return self._cached_health

        # Return cached result if within TTL
        if use_cache and (current_time - self._last_check_time) < self._cache_ttl:
            log.debug("FFmpeg health from cache", health=self._cached_health)
            return self._cached_health

        health = FFmpegHealth(self._check_executable("ffmpeg"), self._check_executable("ffprobe"))

        # Update cache
        self._last_check_time = current_time
        self._cached_health = health

        log.info("FFmpeg health checked", ffmpeg=health.ffmpeg.value, ffprobe=health.ffprobe.value)
        return health

    @staticmethod
    def _check_executable(name: str) -> ExecutableStatus:
        """Find an executable and prove its loader/runtime can start it."""
        executable = shutil.which(name)
        if executable is None:
            return ExecutableStatus.MISSING

        try:
            result = subprocess.run(
                [executable, "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("Video tool failed its health check", executable=name, error=str(exc))
            return ExecutableStatus.BROKEN

        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace")[:500] if result.stderr else ""
            log.warning(
                "Video tool failed its health check",
                executable=name,
                returncode=result.returncode,
                detail=detail,
            )
            return ExecutableStatus.BROKEN
        return ExecutableStatus.AVAILABLE

    @staticmethod
    def warning_for_health(health: FFmpegHealth) -> Optional[dict]:
        """Build the user-facing warning for a non-healthy installation."""
        if health.warning_type == "ffmpeg_broken":
            return {
                "type": "ffmpeg_broken",
                "title": "Video tools are broken",
                "message": "FFmpeg is installed but can't run, so video import and export won't work.",
                "action_url": "https://stimma.ai/link/ffmpeg",
                "action_label": "Fix FFmpeg",
            }
        if health.warning_type == "ffmpeg_missing":
            return {
                "type": "ffmpeg_missing",
                "title": "Video tools unavailable",
                "message": "A required video component isn't installed, so video import and export won't work.",
                "action_url": "https://stimma.ai/link/ffmpeg",
                "action_label": "Install",
            }
        return None

    def get_install_instructions(self, platform_name: Optional[str] = None) -> str:
        """
        Get platform-specific installation instructions for FFmpeg.

        Args:
            platform_name: Platform name override (Darwin, Linux, Windows).
                          If None, auto-detect using platform.system().

        Returns:
            String with installation instructions including command and help link
        """
        if platform_name is None:
            platform_name = platform.system()

        base_url = "https://stimma.ai/link/ffmpeg"

        if platform_name == "Darwin":
            cmd = "brew install ffmpeg"
            return f"Install FFmpeg using Homebrew:\n{cmd}\n\nFor more help: {base_url}"

        elif platform_name == "Windows":
            cmd = "winget install ffmpeg"
            return f"Install FFmpeg using winget:\n{cmd}\n\nFor more help: {base_url}"

        elif platform_name == "Linux":
            # Detect distro for better instructions
            distro_cmd = self._get_linux_package_manager()
            return f"Install FFmpeg using your package manager:\n{distro_cmd}\n\nFor more help: {base_url}"

        else:
            return f"Install FFmpeg for your platform.\n\nFor installation instructions: {base_url}"

    def _get_linux_package_manager(self) -> str:
        """
        Detect Linux package manager and return appropriate install command.

        Returns:
            Package manager install command for FFmpeg
        """
        # Check for common package managers
        if shutil.which("apt"):
            return "sudo apt install ffmpeg"
        elif shutil.which("dnf"):
            return "sudo dnf install ffmpeg"
        elif shutil.which("zypper"):
            return "sudo zypper install ffmpeg"
        elif shutil.which("pacman"):
            return "sudo pacman -S ffmpeg"
        else:
            # Generic fallback
            return "sudo apt install ffmpeg  # or use your package manager"

    def is_warning_shown(self) -> bool:
        """
        Check if the FFmpeg warning has already been shown to the user.

        Returns:
            True if warning was previously shown, False otherwise
        """
        warning_file = self._get_warning_flag_path()
        exists = warning_file.exists()
        log.debug(f"FFmpeg warning flag check: {exists} (path: {warning_file})")
        return exists

    def mark_warning_shown(self) -> None:
        """
        Mark the FFmpeg warning as shown by creating a flag file.
        Creates parent directories if needed.
        """
        warning_file = self._get_warning_flag_path()

        try:
            # Ensure parent directory exists
            warning_file.parent.mkdir(parents=True, exist_ok=True)

            # Create the flag file
            warning_file.touch()
            log.info(f"FFmpeg warning flag created at: {warning_file}")

        except Exception as e:
            log.error(f"Failed to create FFmpeg warning flag: {e}", exc_info=True)

    def _get_warning_flag_path(self) -> Path:
        """
        Get the path to the warning flag file.

        Returns:
            Path to ~/.cache/Stimma/ffmpeg_warning_shown (or platform equivalent)
        """
        cache_dir = get_cache_dir()
        return cache_dir / "ffmpeg_warning_shown"

    def clear_cache(self) -> None:
        """Force cache invalidation for next availability check."""
        self._last_check_time = 0
        log.debug("FFmpeg availability cache cleared")


# Convenience function for quick access
def get_ffmpeg_checker() -> FFmpegChecker:
    """Get the singleton FFmpegChecker instance."""
    return FFmpegChecker()
