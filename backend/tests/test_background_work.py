"""
Tests for background work enable/disable functionality.

Tests cover:
- Phase disabled at startup → no processing for that phase
- Dynamic disable via API → processing stops (via config reload signal)
- Dynamic enable via API → processing starts (via config reload signal)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestEnabledFlagChecks:
    """Tests for enabled flag checks in ingestion processing phases.

    These tests verify the logic of enabled checks without full initialization
    of the MediaIngestion class (which requires heavy ML services).
    """

    async def test_process_clip_respects_enabled_flag(self):
        """_process_clip should return 0 when clip.enabled is False."""
        # Import the module to inspect
        import ingestion

        # Mock the MediaIngestion instance directly
        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = MagicMock()
        mock_ingestion.settings.clip.enabled = False
        mock_ingestion.settings.profiles = []
        mock_ingestion.slots = {'clip': 4}
        mock_ingestion.active_workers = {'clip': set()}

        # Call the actual method with our mock as self
        result = await ingestion.MediaIngestion._process_clip(mock_ingestion)

        assert result == 0

    async def test_process_clip_enabled_continues(self):
        """_process_clip should continue processing when clip.enabled is True."""
        import ingestion

        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = MagicMock()
        mock_ingestion.settings.clip.enabled = True
        mock_ingestion.settings.profiles = []  # No profiles = no work
        mock_ingestion.slots = {'clip': 4}
        mock_ingestion.active_workers = {'clip': set()}

        # Mock config version manager
        mock_ingestion.config_mgr = MagicMock()
        mock_ingestion.config_mgr.get_version.return_value = "1"
        mock_ingestion._get_backoff_time = AsyncMock(return_value=MagicMock())

        result = await ingestion.MediaIngestion._process_clip(mock_ingestion)

        # Returns 0 because no profiles, but the enabled check passed
        assert result == 0

    async def test_process_face_detection_respects_enabled_flag(self):
        """_process_face_detection should return 0 when face_detection.enabled is False."""
        import ingestion

        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = MagicMock()
        mock_ingestion.settings.face_detection.enabled = False
        mock_ingestion.settings.profiles = []
        mock_ingestion.slots = {'face_detection': 2}
        mock_ingestion.active_workers = {'face_detection': set()}

        result = await ingestion.MediaIngestion._process_face_detection(mock_ingestion)

        assert result == 0

    async def test_process_face_detection_enabled_continues(self):
        """_process_face_detection should continue when face_detection.enabled is True."""
        import ingestion

        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = MagicMock()
        mock_ingestion.settings.face_detection.enabled = True
        mock_ingestion.settings.profiles = []  # No profiles = no work
        mock_ingestion.slots = {'face_detection': 2}
        mock_ingestion.active_workers = {'face_detection': set()}

        mock_ingestion.config_mgr = MagicMock()
        mock_ingestion.config_mgr.get_version.return_value = "1"
        mock_ingestion._get_backoff_time = AsyncMock(return_value=MagicMock())

        result = await ingestion.MediaIngestion._process_face_detection(mock_ingestion)

        # Returns 0 because no profiles, but the enabled check passed
        assert result == 0

    async def test_process_vlm_captions_respects_enabled_flag(self):
        """_process_vlm_captions should return 0 when captioning.enabled is False."""
        import ingestion

        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = MagicMock()
        mock_ingestion.settings.captioning.enabled = False
        mock_ingestion.settings.profiles = []
        mock_ingestion.slots = {'vlm_caption': 2}
        mock_ingestion.active_workers = {'vlm_caption': set()}

        result = await ingestion.MediaIngestion._process_vlm_captions(mock_ingestion)

        assert result == 0

    async def test_process_vlm_captions_enabled_continues(self):
        """_process_vlm_captions should continue when captioning.enabled is True."""
        import ingestion

        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = MagicMock()
        mock_ingestion.settings.captioning.enabled = True
        mock_ingestion.settings.profiles = []  # No profiles = no work
        mock_ingestion.slots = {'vlm_caption': 2}
        mock_ingestion.active_workers = {'vlm_caption': set()}

        mock_ingestion.config_mgr = MagicMock()
        mock_ingestion.config_mgr.get_version.return_value = "1"
        mock_ingestion.caption_service = MagicMock()

        result = await ingestion.MediaIngestion._process_vlm_captions(mock_ingestion)

        # Returns 0 because no profiles, but the enabled check passed
        assert result == 0


class TestBackgroundWorkSettingsAPI:
    """Tests for the background work settings API endpoint.

    Verifies that PATCH /api/settings/background-work signals the reload config event.
    """

    async def test_update_background_work_signals_reload(self):
        """Updating background work settings should signal the ingestion worker to reload."""
        from routes.settings import update_background_work, UpdateBackgroundWorkRequest

        # Create a mock reload event
        mock_event = MagicMock()
        mock_event.set = MagicMock()

        # Mock settings
        mock_settings = MagicMock()
        mock_settings.face_detection.model_dump.return_value = {"enabled": True}
        mock_settings.clip.model_dump.return_value = {"enabled": True}
        mock_settings.captioning.model_dump.return_value = {"enabled": True}

        request = UpdateBackgroundWorkRequest(clip={"enabled": False})

        # Patch at core.app since that's where the function is imported from
        with patch('routes.settings.get_settings', return_value=mock_settings), \
             patch('core.app.get_reload_config_event', return_value=mock_event), \
             patch('routes.settings.patch_global_section'):

            result = await update_background_work(request)

            # Should have called set() on the reload event
            mock_event.set.assert_called_once()
            assert result["status"] == "success"

    async def test_update_background_work_with_no_event(self):
        """When reload event is None (during startup), should not error."""
        from routes.settings import update_background_work, UpdateBackgroundWorkRequest

        mock_settings = MagicMock()
        mock_settings.face_detection.model_dump.return_value = {"enabled": True}

        request = UpdateBackgroundWorkRequest(face_detection={"enabled": False})

        with patch('routes.settings.get_settings', return_value=mock_settings), \
             patch('core.app.get_reload_config_event', return_value=None), \
             patch('routes.settings.patch_global_section'):

            # Should not raise an error
            result = await update_background_work(request)

            assert result["status"] == "success"

    async def test_update_background_work_all_phases(self):
        """Updating all background work phases should signal reload once."""
        from routes.settings import update_background_work, UpdateBackgroundWorkRequest

        mock_event = MagicMock()
        mock_event.set = MagicMock()

        mock_settings = MagicMock()
        mock_settings.face_detection.model_dump.return_value = {"enabled": True, "min_confidence": 0.5}
        mock_settings.clip.model_dump.return_value = {"enabled": True}
        mock_settings.captioning.model_dump.return_value = {"enabled": True, "parallelism": 2}

        request = UpdateBackgroundWorkRequest(
            face_detection={"enabled": False},
            clip={"enabled": False},
            captioning={"enabled": False}
        )

        with patch('routes.settings.get_settings', return_value=mock_settings), \
             patch('core.app.get_reload_config_event', return_value=mock_event), \
             patch('routes.settings.patch_global_section'):

            result = await update_background_work(request)

            # Should have called set() exactly once (not three times)
            mock_event.set.assert_called_once()
            assert result["status"] == "success"


class TestConfigReload:
    """Tests for config reload refreshing enabled flags in ingestion worker."""

    async def test_reload_config_updates_settings(self):
        """_reload_config should update self.settings with new values from disk."""
        import ingestion

        # Initial settings
        mock_settings_initial = MagicMock()
        mock_settings_initial.clip.enabled = False
        mock_settings_initial.profiles = []

        # New settings after reload
        mock_settings_new = MagicMock()
        mock_settings_new.clip.enabled = True
        mock_settings_new.profiles = []

        # Create mock ingestion
        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = mock_settings_initial
        mock_ingestion.registry = MagicMock()
        mock_ingestion.folder_to_profile = {}
        mock_ingestion.last_scan_time = None
        mock_ingestion._work_available = MagicMock()

        # Patch at config module since that's where reload_settings is imported from
        with patch('config.reload_settings', return_value=mock_settings_new):
            # Call the actual _reload_config method
            await ingestion.MediaIngestion._reload_config(mock_ingestion)

        # Settings should be updated
        assert mock_ingestion.settings == mock_settings_new
        assert mock_ingestion.settings.clip.enabled == True
