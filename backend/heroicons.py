"""
Heroicons service for loading icons from the heroicons GitHub repository.

Supports syntax 'heroicons:icon-name' which resolves to optimized/24/solid/{icon-name}.svg
from https://github.com/tailwindlabs/heroicons

Icons are downloaded once and cached to disk, then held in RAM for fast access.
"""
import httpx
from pathlib import Path
from typing import Optional
import threading

import app_dirs
from core.logging import get_logger

log = get_logger(__name__)

HEROICONS_BASE_URL = "https://raw.githubusercontent.com/tailwindlabs/heroicons/master/optimized/24/solid"


class HeroiconsService:
    """Singleton service for loading and caching heroicons."""

    def __init__(self):
        self._cache: dict[str, str] = {}  # icon_name -> svg_content
        self._lock = threading.Lock()
        self._cache_dir: Optional[Path] = None

    def _get_cache_dir(self) -> Path:
        """Get the heroicons cache directory, creating if needed."""
        if self._cache_dir is None:
            self._cache_dir = app_dirs.get_cache_dir() / "heroicons"
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        return self._cache_dir

    def _get_cached_path(self, icon_name: str) -> Path:
        """Get the path where an icon would be cached."""
        return self._get_cache_dir() / f"{icon_name}.svg"

    def get_icon(self, icon_name: str) -> Optional[str]:
        """
        Get an icon's SVG content by name.

        Args:
            icon_name: The icon name (e.g., 'bookmark', 'heart', 'star')

        Returns:
            The SVG content as a string, or None if not found
        """
        # Check RAM cache first
        if icon_name in self._cache:
            return self._cache[icon_name]

        with self._lock:
            # Double-check after acquiring lock
            if icon_name in self._cache:
                return self._cache[icon_name]

            # Check disk cache
            cached_path = self._get_cached_path(icon_name)
            if cached_path.exists():
                svg_content = cached_path.read_text()
                self._cache[icon_name] = svg_content
                log.debug("heroicon loaded from disk cache", icon=icon_name)
                return svg_content

            # Download from GitHub
            svg_content = self._download_icon(icon_name)
            if svg_content:
                # Save to disk cache
                cached_path.write_text(svg_content)
                # Save to RAM cache
                self._cache[icon_name] = svg_content
                log.info("heroicon downloaded and cached", icon=icon_name)
                return svg_content

            return None

    def _download_icon(self, icon_name: str) -> Optional[str]:
        """Download an icon from the heroicons GitHub repository."""
        url = f"{HEROICONS_BASE_URL}/{icon_name}.svg"
        try:
            response = httpx.get(url, timeout=10.0, follow_redirects=True)
            if response.status_code == 200:
                return response.text
            else:
                log.warning("heroicon not found", icon=icon_name, status=response.status_code)
                return None
        except Exception as e:
            log.error("heroicon download failed", icon=icon_name, error=str(e))
            return None

    def resolve_icon_svg(self, icon_svg: str) -> str:
        """
        Resolve an icon_svg value, fetching from heroicons if needed.

        Args:
            icon_svg: Either raw SVG content or 'heroicons:icon-name' syntax

        Returns:
            The resolved SVG content
        """
        if icon_svg.startswith("heroicons:"):
            icon_name = icon_svg[len("heroicons:"):]
            resolved = self.get_icon(icon_name)
            if resolved:
                return resolved
            else:
                log.warning("heroicon not found, using fallback", icon=icon_name)
                # Return a simple fallback icon (question mark circle)
                return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M2.25 12c0-5.385 4.365-9.75 9.75-9.75s9.75 4.365 9.75 9.75-4.365 9.75-9.75 9.75S2.25 17.385 2.25 12Zm11.378-3.917c-.89-.777-2.366-.777-3.255 0a.75.75 0 0 1-.988-1.129c1.454-1.272 3.776-1.272 5.23 0 1.513 1.324 1.513 3.518 0 4.842a3.75 3.75 0 0 1-.837.552c-.676.328-1.028.774-1.028 1.152v.75a.75.75 0 0 1-1.5 0v-.75c0-1.279 1.06-2.107 1.875-2.502.182-.088.351-.199.503-.331.83-.727.83-1.857 0-2.584ZM12 18a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z" clip-rule="evenodd"/></svg>'
        # Already raw SVG content
        return icon_svg


# Singleton instance
_heroicons_service: Optional[HeroiconsService] = None


def get_heroicons_service() -> HeroiconsService:
    """Get or create the global heroicons service singleton."""
    global _heroicons_service
    if _heroicons_service is None:
        _heroicons_service = HeroiconsService()
    return _heroicons_service


def resolve_icon_svg(icon_svg: str) -> str:
    """
    Convenience function to resolve an icon_svg value.

    Args:
        icon_svg: Either raw SVG content or 'heroicons:icon-name' syntax

    Returns:
        The resolved SVG content
    """
    return get_heroicons_service().resolve_icon_svg(icon_svg)
