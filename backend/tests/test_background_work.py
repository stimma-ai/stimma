"""
Tests for background work enable/disable functionality.

Tests cover:
- Phase disabled at startup → no processing for that phase
- Dynamic disable via API → processing stops (via config reload signal)
- Dynamic enable via API → processing starts (via config reload signal)
"""

import pytest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from database import DeleteOperation, DeleteOperationItem, MediaItem
from tests.helpers.media import create_media_item
from asset_service import create_asset_from_media


async def test_processing_stats_preserve_backlog_and_report_live_enabled_flags(db_session):
    from routes.processing import get_processing_stats

    settings = SimpleNamespace(
        clip=SimpleNamespace(enabled=False),
        face_detection=SimpleNamespace(enabled=False),
        captioning=SimpleNamespace(enabled=False),
    )
    async with db_session() as session:
        await create_media_item(session, clip_status="pending", face_detection_status="pending")
        await session.commit()
        with patch("routes.processing.get_settings", return_value=settings), patch(
            "ingestion.get_ingestion", return_value=None
        ):
            disabled = (await get_processing_stats(session))["phase_stats"]
            assert disabled["metadata"]["enabled"] is True
            for phase in ("clip", "face_detection", "vlm_caption"):
                assert disabled[phase]["enabled"] is False
            assert disabled["clip"]["pending"] > 0
            assert disabled["face_detection"]["pending"] > 0

            settings.clip.enabled = True
            settings.captioning.enabled = True
            enabled = (await get_processing_stats(session))["phase_stats"]
            assert enabled["clip"]["enabled"] is True
            assert enabled["vlm_caption"]["enabled"] is True
            assert enabled["face_detection"]["enabled"] is False
            assert enabled["clip"]["pending"] == disabled["clip"]["pending"]


async def test_processing_monitor_broadcasts_enabled_changes_without_counter_changes():
    import asyncio
    from utils.background_tasks import monitor_processing_stats

    settings = SimpleNamespace(
        profiles=[],
        clip=SimpleNamespace(enabled=False),
        face_detection=SimpleNamespace(enabled=False),
        captioning=SimpleNamespace(enabled=False),
    )
    ticks = 0

    async def tick(_seconds):
        nonlocal ticks
        ticks += 1
        if ticks == 3:
            settings.clip.enabled = True
        if ticks == 4:
            raise asyncio.CancelledError

    ws = SimpleNamespace(broadcast=AsyncMock())
    with patch("utils.background_tasks.get_settings", return_value=settings), patch(
        "utils.background_tasks.get_database_registry"
    ), patch("utils.background_tasks.asyncio.sleep", side_effect=tick):
        await monitor_processing_stats(ws)

    snapshots = [call.args[1]["phase_stats"] for call in ws.broadcast.call_args_list]
    assert len(snapshots) == 2  # The unchanged second poll stays quiet.
    assert snapshots[0]["clip"]["enabled"] is False
    assert snapshots[1]["clip"]["enabled"] is True


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

    async def test_processing_prioritizes_metadata_backlog(self):
        """Visual inference must not starve first-run Asset materialization."""
        import ingestion

        worker = MagicMock(spec=ingestion.MediaIngestion)
        worker._process_metadata = AsyncMock(return_value=16)
        worker._has_pending_metadata = AsyncMock(return_value=True)
        worker._process_clip = AsyncMock(return_value=4)
        worker._process_face_detection = AsyncMock(return_value=2)
        worker._process_vlm_captions = AsyncMock(return_value=3)

        worked = await ingestion.MediaIngestion._process_pending_items(worker)

        assert worked is True
        worker._process_clip.assert_not_awaited()
        worker._process_face_detection.assert_not_awaited()
        worker._process_vlm_captions.assert_not_awaited()

    async def test_processing_starts_analysis_after_metadata_is_materialized(self):
        import ingestion

        worker = MagicMock(spec=ingestion.MediaIngestion)
        worker._process_metadata = AsyncMock(return_value=0)
        worker._has_pending_metadata = AsyncMock(return_value=False)
        worker._process_clip = AsyncMock(return_value=4)
        worker._process_face_detection = AsyncMock(return_value=2)
        worker._process_vlm_captions = AsyncMock(return_value=3)

        worked = await ingestion.MediaIngestion._process_pending_items(worker)

        assert worked is True
        worker._process_clip.assert_awaited_once()
        worker._process_face_detection.assert_awaited_once()
        worker._process_vlm_captions.assert_awaited_once()

    async def test_init_caption_service_skips_llm_resolution_when_disabled(self):
        """Caption service init should not resolve LLM config when captioning is disabled."""
        import ingestion

        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = MagicMock()
        mock_ingestion.settings.captioning.enabled = False
        mock_ingestion.caption_service = None

        with patch('llm_resolver.get_effective_llm_config', new_callable=AsyncMock) as mock_resolver:
            await ingestion.MediaIngestion._init_caption_service(mock_ingestion)

        mock_resolver.assert_not_called()
        assert mock_ingestion.caption_service is None

    async def test_init_caption_service_tolerates_unavailable_llm(self):
        """Caption service init should not fail ingestion when no LLM is configured."""
        import ingestion
        from llm_resolver import LLMNotConfiguredError

        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = MagicMock()
        mock_ingestion.settings.captioning.enabled = True
        mock_ingestion.caption_service = None

        with patch(
            'llm_resolver.get_effective_llm_config',
            new=AsyncMock(side_effect=LLMNotConfiguredError("Sign in to Stimma Cloud or choose a local endpoint."))
        ):
            await ingestion.MediaIngestion._init_caption_service(mock_ingestion)

        assert mock_ingestion.caption_service is None


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

    async def test_reload_config_triggers_scan_when_source_folders_change(self):
        """Adding a Source wakes discovery instead of waiting for the periodic scan."""
        import ingestion

        initial_profile = MagicMock()
        initial_profile.id = "profile-1"
        initial_profile.folders = []
        new_profile = MagicMock()
        new_profile.id = "profile-1"
        new_profile.folders = [SimpleNamespace(path="/external/media")]

        initial_settings = MagicMock()
        initial_settings.profiles = [initial_profile]
        new_settings = MagicMock()
        new_settings.profiles = [new_profile]

        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = initial_settings
        mock_ingestion.registry = MagicMock()
        mock_ingestion.folder_to_profile = {}
        mock_ingestion.last_scan_time = datetime.now()
        mock_ingestion._work_available = MagicMock()

        with patch('config.reload_settings', return_value=new_settings):
            await ingestion.MediaIngestion._reload_config(mock_ingestion)

        assert mock_ingestion.last_scan_time is None
        mock_ingestion._work_available.set.assert_called_once()

    async def test_reload_config_does_not_scan_for_unrelated_setting_change(self):
        """Background-work changes reload settings without forcing filesystem I/O."""
        import ingestion

        folder = SimpleNamespace(path="/external/media")
        initial_profile = MagicMock(id="profile-1", folders=[folder])
        initial_profile.id = "profile-1"
        initial_profile.folders = [folder]
        new_profile = MagicMock(id="profile-1", folders=[folder])
        new_profile.id = "profile-1"
        new_profile.folders = [folder]

        initial_settings = MagicMock()
        initial_settings.profiles = [initial_profile]
        new_settings = MagicMock()
        new_settings.profiles = [new_profile]

        mock_ingestion = MagicMock(spec=ingestion.MediaIngestion)
        mock_ingestion.settings = initial_settings
        mock_ingestion.registry = MagicMock()
        mock_ingestion.folder_to_profile = {}
        previous_scan_time = datetime.now()
        mock_ingestion.last_scan_time = previous_scan_time
        mock_ingestion._work_available = MagicMock()

        with patch('config.reload_settings', return_value=new_settings):
            await ingestion.MediaIngestion._reload_config(mock_ingestion)

        assert mock_ingestion.last_scan_time == previous_scan_time
        mock_ingestion._work_available.set.assert_not_called()


@pytest.mark.asyncio
async def test_background_work_excludes_trashed_and_deleting_asset_media(
    db_session,
):
    from background_work_filters import media_eligible_for_background_work

    async with db_session() as session:
        active_media = await create_media_item(session)
        trashed_media = await create_media_item(session)
        deleting_media = await create_media_item(session)
        queued_media = await create_media_item(session)
        active_asset = await create_asset_from_media(
            session,
            media_id=active_media.id,
        )
        trashed_asset = await create_asset_from_media(
            session,
            media_id=trashed_media.id,
        )
        deleting_asset = await create_asset_from_media(
            session,
            media_id=deleting_media.id,
        )
        trashed_asset.state = "trashed"
        trashed_asset.deleted_at = datetime.utcnow()
        deleting_asset.state = "deleting"
        deleting_asset.deleted_at = datetime.utcnow()
        operation = DeleteOperation(
            kind="asset",
            profile_id="default",
            status="running",
            current_phase="unlinking_artifacts",
            total_items=1,
        )
        session.add(operation)
        await session.flush()
        session.add(
            DeleteOperationItem(
                operation_id=operation.id,
                media_id=queued_media.id,
                state="media_deleted",
            )
        )
        await session.commit()
        candidate_ids = [
            active_media.id,
            trashed_media.id,
            deleting_media.id,
            queued_media.id,
        ]

        eligible_ids = set(
            await session.scalars(
                select(MediaItem.id).where(
                    MediaItem.id.in_(candidate_ids),
                    media_eligible_for_background_work(),
                )
            )
        )

    assert active_asset.state == "active"
    assert eligible_ids == {active_media.id}
