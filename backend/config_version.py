"""
Config version manager - tracks configuration changes and invalidates processing when needed.
"""
import hashlib
from core.logging import get_logger
from typing import Dict, Optional
from config import get_settings
from prompts import get_prompt

log = get_logger(__name__)


class ConfigVersionManager:
    """Manages config versions for each processing phase."""

    def __init__(self):
        self.settings = get_settings()
        self._version_cache: Dict[str, str] = {}
        self._compute_versions()

    def _compute_hash(self, *values: str) -> str:
        """Compute SHA256 hash of concatenated values."""
        combined = "|".join(str(v) for v in values)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _compute_versions(self):
        """Compute current config version for each phase."""
        # Metadata version: static version since it doesn't depend on config
        # Only increment this if the metadata extraction logic changes
        # v2: Improved prompt parsing for ComfyUI, A1111, Fooocus formats
        # v3: EXIF-orientation-corrected dimensions (upload path stored raw w/h)
        # v4: has_alpha (header-only alpha-channel detection, no pixel decode)
        self._version_cache['metadata'] = 'v4'

        # CLIP version: model + pretrained dataset
        self._version_cache['clip'] = self._compute_hash(
            self.settings.clip.model,
            self.settings.clip.pretrained
        )

        # Visual analysis version: model + prompt (both affect output)
        # Generates both caption and keywords in one call
        if "agent-fast" in self.settings.llms:
            caption_model = self.settings.get_llm("agent-fast").get_model() or "stimma_cloud"
        else:
            caption_model = "disabled"
        self._version_cache['vlm_caption'] = self._compute_hash(
            caption_model,
            get_prompt("visual_analysis")
        )

        # Face detection version: model + min_confidence + max_faces (all affect output)
        # Model name is hardcoded in face_detection_service.py - update here if changed
        self._version_cache['face_detection'] = self._compute_hash(
            'auraface',  # Model name - changing this triggers re-processing
            str(self.settings.face_detection.min_confidence),
            str(self.settings.face_detection.max_faces)
        )

        log.info(f"Config versions computed:")
        for phase, version in self._version_cache.items():
            log.info(f"  {phase}: {version}")

    def get_version(self, phase: str) -> str:
        """Get current config version for a phase."""
        return self._version_cache.get(phase, "unknown")

    def needs_reprocessing(self, phase: str, item_version: Optional[str]) -> bool:
        """Check if an item needs reprocessing based on config version."""
        if item_version is None:
            return True  # Never processed with any version

        current_version = self.get_version(phase)
        if current_version != item_version:
            log.debug(f"Item needs reprocessing - {phase} version mismatch: {item_version} != {current_version}")
            return True

        return False

    def get_all_versions(self) -> Dict[str, str]:
        """Get all current config versions."""
        return self._version_cache.copy()


# Global singleton
_config_version_manager: Optional[ConfigVersionManager] = None


def get_config_version_manager() -> ConfigVersionManager:
    """Get or create config version manager singleton."""
    global _config_version_manager
    if _config_version_manager is None:
        _config_version_manager = ConfigVersionManager()
    return _config_version_manager
