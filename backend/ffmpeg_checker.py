"""
FFmpeg detection and installation guidance service.

Provides FFmpeg availability checking with singleton caching,
platform-specific installation instructions, and one-time warning flags.
"""
import platform
import shutil
import time
from pathlib import Path
from typing import Optional, Tuple
from core.logging import get_logger

from app_dirs import get_cache_dir
from config import get_settings

log = get_logger(__name__)


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
        self._cached_ffmpeg_available: bool = False
        self._cached_ffprobe_available: bool = False

        log.debug("FFmpegChecker initialized")

    def check_availability(self, use_cache: bool = True) -> Tuple[bool, bool]:
        """
        Check if ffmpeg and ffprobe are available on the system.

        Args:
            use_cache: If True, use cached result if within TTL. Default True.

        Returns:
            Tuple of (ffmpeg_available, ffprobe_available)
        """
        current_time = time.time()

        # Dev-only override to simulate a missing FFmpeg install (e.g. for screenshots)
        if get_settings().debug_force_ffmpeg_missing:
            self._last_check_time = current_time
            self._cached_ffmpeg_available = False
            self._cached_ffprobe_available = False
            log.debug("FFmpeg availability forced to missing via debug_force_ffmpeg_missing")
            return False, False

        # Return cached result if within TTL
        if use_cache and (current_time - self._last_check_time) < self._cache_ttl:
            log.debug(f"FFmpeg availability from cache: ffmpeg={self._cached_ffmpeg_available}, ffprobe={self._cached_ffprobe_available}")
            return self._cached_ffmpeg_available, self._cached_ffprobe_available

        # Perform actual check
        ffmpeg_available = shutil.which("ffmpeg") is not None
        ffprobe_available = shutil.which("ffprobe") is not None

        # Update cache
        self._last_check_time = current_time
        self._cached_ffmpeg_available = ffmpeg_available
        self._cached_ffprobe_available = ffprobe_available

        log.info(f"FFmpeg availability checked: ffmpeg={ffmpeg_available}, ffprobe={ffprobe_available}")
        return ffmpeg_available, ffprobe_available

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
