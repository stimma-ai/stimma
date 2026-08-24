"""
Integration tests for generation/tool invocation system.

Tests the full stack: API endpoints -> generation queue -> provider execution -> database state.
"""

import asyncio
import io
import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import UploadFile
from sqlalchemy import select

from database import Asset, AssetRevision, GenerationJob, MediaItem, MediaOwner
from providers.test_provider import TestToolConfig
from tests.helpers import (
    create_media_item,
    create_media_with_generation_metadata,
    process_job,
)
from routes import generation as generation_routes


class TestReferenceUploadDisposition:
    async def test_editor_reference_can_skip_asset_materialization(self):
        media = SimpleNamespace(
            id=17,
            file_hash="hash",
            width=320,
            height=200,
        )
        upload = AsyncMock(return_value=(media, "/managed/composite.png"))
        service = SimpleNamespace(upload_file=upload)
        file = UploadFile(filename="composite.png", file=io.BytesIO(b"png"))

        with patch("upload_service.get_upload_service", return_value=service):
            result = await generation_routes.upload_reference_image(
                file=file,
                materialize_asset=False,
            )

        upload.assert_awaited_once_with(
            b"png",
            "composite.png",
            materialize_asset=False,
        )
        assert result["media_id"] == 17


# =============================================================================
# Job Submission Tests
# =============================================================================


class TestSourceInputResolution:
    async def test_existing_media_is_returned_in_place_with_picker_metadata(
        self,
        generation_db_session,
    ):
        async with generation_db_session() as session:
            media = await create_media_item(
                session,
                file_path=Path("/managed/objects/source.png"),
                file_hash="stable-source-hash",
                width=640,
                height=480,
                materialize_asset=True,
            )
            await session.commit()

            resolved = await generation_routes._resolve_source_inputs(
                session,
                [{"media_id": media.id, "file_path": "/obsolete/reference-copy.png", "role": "input_image"}],
            )

        assert resolved == [{
            "media_id": media.id,
            "file_path": "/managed/objects/source.png",
            "file_hash": "stable-source-hash",
            "width": 640,
            "height": 480,
            "role": "input_image",
        }]


class TestPromptPipelineRouting:
    """Tests for backend prompt-enhancement context inferred at submit time."""

    def test_image_size_parameter_does_not_count_as_input_image(self):
        parameters = {
            "prompt": "a beautiful modern handbag on display on a table",
            "aspect_ratio": "1:1",
            "image_size": "1K",
        }
        schema_props = {
            "prompt": {"type": "string"},
            "aspect_ratio": {"type": "string", "description": "Output image aspect ratio"},
            "image_size": {"type": "string", "description": "Output image size"},
        }

        assert generation_routes._prompt_input_image_count(parameters, schema_props, "text-to-image") == 0

    def test_real_image_picker_counts_as_input_image(self):
        parameters = {
            "prompt": "make it luxe",
            "input_images": ["/tmp/source.png"],
            "image_size": "1K",
        }
        schema_props = {
            "prompt": {"type": "string"},
            "input_images": {
                "type": "array",
                "items": {"type": "string", "format": "file-path"},
                "x-control": "image_picker",
            },
            "image_size": {"type": "string", "description": "Output image size"},
        }

        assert generation_routes._prompt_input_image_count(parameters, schema_props, "image-to-image") == 1

    def test_optional_image_picker_without_actual_image_does_not_count(self):
        parameters = {
            "prompt": "a beautiful modern handbag on display on a table",
            "input_images": [],
            "input_media_ids": [],
        }
        schema_props = {
            "prompt": {"type": "string"},
            "input_images": {
                "type": "array",
                "items": {"type": "string", "format": "file-path"},
                "x-control": "image_picker",
            },
        }

        assert generation_routes._prompt_input_image_count(parameters, schema_props, "text-to-image") == 0

    def test_media_id_companion_without_path_does_not_count_as_input_image(self):
        parameters = {
            "prompt": "a beautiful modern handbag on display on a table",
            "input_media_ids": [123],
        }
        schema_props = {
            "prompt": {"type": "string"},
            "input_images": {
                "type": "array",
                "items": {"type": "string", "format": "file-path"},
                "x-control": "image_picker",
            },
        }

        assert generation_routes._prompt_input_image_count(parameters, schema_props, "text-to-image") == 0

    def test_audio_picker_with_a_track_marks_the_job_audio_conditioned(self):
        parameters = {
            "prompt": "she speaks to the camera",
            "input_images": ["/tmp/portrait.png"],
            "input_audios": ["/tmp/vo.wav"],
        }
        schema_props = {
            "prompt": {"type": "string"},
            "input_images": {"type": "array", "x-control": "video_frame_picker"},
            "input_audios": {"type": "array", "x-control": "audio_picker"},
        }

        assert generation_routes._prompt_audio_conditioned(parameters, schema_props) is True

    def test_audio_picker_without_a_track_is_not_audio_conditioned(self):
        parameters = {"prompt": "she speaks", "input_audios": []}
        schema_props = {
            "prompt": {"type": "string"},
            "input_audios": {"type": "array", "x-control": "audio_picker"},
        }

        assert generation_routes._prompt_audio_conditioned(parameters, schema_props) is False

    def test_reference_role_audio_is_not_audio_conditioned(self):
        # A voice sample steers audio the tool still generates (STP x-audio-role),
        # so the prompt should keep describing sound.
        parameters = {
            "prompt": "she speaks to the camera",
            "input_audios": ["/tmp/voice-sample.wav"],
        }
        schema_props = {
            "prompt": {"type": "string"},
            "input_audios": {
                "type": "array", "x-control": "audio_picker", "x-audio-role": "reference",
            },
        }

        assert generation_routes._prompt_audio_conditioned(parameters, schema_props) is False

    def test_missing_audio_role_defaults_to_driving(self):
        parameters = {"prompt": "x", "input_audios": ["/tmp/vo.wav"]}
        schema_props = {"input_audios": {"type": "array", "x-control": "audio_picker"}}

        assert generation_routes._prompt_audio_conditioned(parameters, schema_props) is True

    def test_audio_output_tool_is_not_audio_conditioned(self):
        # A text-to-audio tool generates sound; it doesn't condition on a track.
        # That's the is_audio axis, and it must not trip this one.
        parameters = {"prompt": "rain on a tin roof", "duration": 8}
        schema_props = {"prompt": {"type": "string"}, "duration": {"type": "integer"}}

        assert generation_routes._prompt_audio_conditioned(parameters, schema_props) is False

    def test_i2v_source_media_id_uses_only_start_frame_slot(self):
        assert generation_routes._prompt_media_id(
            {"input_media_ids": [None, 456]},
            "image-to-video",
        ) is None
        assert generation_routes._prompt_media_id(
            {"input_media_ids": [123, 456]},
            "image-to-video",
        ) == 123

    def test_h3_context_derives_task_duration_frames_and_audio(self):
        assert generation_routes._prompt_h3_context({"duration": 5}) == (
            "t2va", 5.0, [], True, [],
        )
        assert generation_routes._prompt_h3_context({
            "input_images": ["first.png"],
            "input_media_ids": [123],
            "duration": 6.5,
        }) == ("i2va", 6.5, [123], True, [])
        assert generation_routes._prompt_h3_context({
            "input_images": ["first.png", "last.png"],
            "input_media_ids": [123, 456],
            "duration": 8,
            "generate_audio": False,
        }) == ("fl2va", 8.0, [123, 456], False, [])

    def test_h3_reference_context_matches_model_presentation_order(self):
        task, duration, media_ids, generate_audio, manifest = (
            generation_routes._prompt_h3_context(
                {
                    "input_images": ["one.png", "two.png"],
                    "input_media_ids": [101, 102],
                    "input_videos": ["one.mp4", "two.mp4"],
                    "input_audios": ["voice.wav", "music.wav"],
                    "duration": 9,
                },
                "reference-to-video",
            )
        )

        assert (task, duration, media_ids, generate_audio) == (
            "ref2va", 9.0, [101, 102], True,
        )
        assert [(item["label"], item["kind"]) for item in manifest] == [
            ("Picture 1", "image"),
            ("Picture 2", "image"),
            ("Audio 1", "video_audio"),
            ("Video 1", "video"),
            ("Audio 2", "video_audio"),
            ("Video 2", "video"),
            ("Audio 3", "audio"),
            ("Audio 4", "audio"),
        ]

    def test_h3_context_supports_named_last_frame_only(self):
        assert generation_routes._prompt_h3_context({
            "last_frame": "last.png",
            "duration": "7.5",
        })[:2] == ("l2va", 7.5)

    def test_prompt_context_uses_descriptor_metadata_and_name_fallbacks(self, monkeypatch):
        descriptor = SimpleNamespace(
            model=None,
            model_vendor=None,
            metadata={"model_name": "sdxl_base_1.0.safetensors", "model_vendor": "stability"},
            name="Friendly Tool Name",
            task_type="text-to-image",
            parameter_schema={"properties": {"prompt": {"type": "string"}}},
        )
        registry = SimpleNamespace(get_tool=lambda tool_id: (SimpleNamespace(provider_id="test"), descriptor))

        import providers.registry as provider_registry

        monkeypatch.setattr(provider_registry.ProviderRegistry, "get_instance", lambda: registry)

        model, vendor, task, props = generation_routes._prompt_pipeline_context("test:tool", None, None)

        assert model == "sdxl_base_1.0.safetensors"
        assert vendor == "stability"
        assert task == "text-to-image"
        assert "prompt" in props

    def test_prompt_context_uses_tool_name_when_model_metadata_is_absent(self, monkeypatch):
        descriptor = SimpleNamespace(
            model=None,
            model_vendor="ideogram",
            metadata={},
            name="Ideogram 4.0",
            task_type="text-to-image",
            parameter_schema={"properties": {"prompt": {"type": "string"}}},
        )
        registry = SimpleNamespace(get_tool=lambda tool_id: (SimpleNamespace(provider_id="test"), descriptor))

        import providers.registry as provider_registry

        monkeypatch.setattr(provider_registry.ProviderRegistry, "get_instance", lambda: registry)

        model, vendor, _, _ = generation_routes._prompt_pipeline_context("test:ideogram", None, None)

        assert model == "Ideogram 4.0"
        assert vendor == "ideogram"

    def test_prompt_context_prefers_client_model_hint_before_name_fallback(self, monkeypatch):
        descriptor = SimpleNamespace(
            model=None,
            model_vendor=None,
            metadata={},
            name="Friendly Display Name",
            task_type="text-to-image",
            parameter_schema={"properties": {"prompt": {"type": "string"}}},
        )
        registry = SimpleNamespace(get_tool=lambda tool_id: (SimpleNamespace(provider_id="test"), descriptor))

        import providers.registry as provider_registry

        monkeypatch.setattr(provider_registry.ProviderRegistry, "get_instance", lambda: registry)

        model, _, _, _ = generation_routes._prompt_pipeline_context(
            "test:tool",
            None,
            {"autoImprove": {"model": "sdxl_base_1.0.safetensors"}},
        )

        assert model == "sdxl_base_1.0.safetensors"


class TestJobSubmission:
    """Tests for POST /api/generate/submit"""

    async def test_submit_text_to_image_job(
        self, generation_client: httpx.AsyncClient, output_folder: str
    ):
        """Submit a valid text-to-image job and verify it gets queued."""
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {
                    "prompt": "test prompt",
                    "width": 64,
                    "height": 64,
"steps": 10,
                    "seed": 42
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"

    async def test_submit_with_invalid_tool_returns_400(
        self, generation_client: httpx.AsyncClient, output_folder: str
    ):
        """Submitting with an unknown tool ID returns 400."""
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "nonexistent:tool:id",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "test"},
            },
        )

        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()

    async def test_submit_ignores_client_selected_output_folder(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
    ):
        """Output placement is private and cannot be redirected by a client."""
        requested_folder = "/nonexistent/user-selected-folder"
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": requested_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "test"},
            },
        )

        assert response.status_code == 200
        job_id = response.json()["job_id"]
        async with generation_db_session() as session:
            job = await session.get(GenerationJob, job_id)
            assert job is not None
            assert job.folder_path != requested_folder
            assert Path(job.folder_path).parts[-2:] == ("staging", "generated")

        await generation_queue.cancel_job(job_id)

    async def test_submit_runs_prompt_pipeline_server_side(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        output_folder: str,
    ):
        """The submit route stores the backend-processed prompt, not raw editor text."""
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {
                    "prompt": "visible\n# enhancer-only note\n[fixed words]",
                    "width": 64,
                    "height": 64,
                    "steps": 10,
                    "seed": 42,
                },
            },
        )

        assert response.status_code == 200
        async with generation_db_session() as session:
            job = await session.get(GenerationJob, response.json()["job_id"])
            params = json.loads(job.parameters)

        assert params["prompt"] == "visible\nfixed words"

    async def test_submit_declines_reserved_work_when_prompt_pipeline_fails_before_queue(
        self,
        generation_client: httpx.AsyncClient,
        output_folder: str,
    ):
        """Server-side enhancement failures must not strand forever-mode slots."""
        mock_queue = AsyncMock()
        mock_queue.submit_job = AsyncMock()
        mock_queue.decline_work_request = AsyncMock()

        with (
            patch("generation_queue.get_generation_queue", return_value=mock_queue),
            patch(
                "routes.generation._apply_generation_prompt_pipeline",
                AsyncMock(side_effect=RuntimeError("enhancement failed")),
            ),
        ):
            response = await generation_client.post(
                "/api/generate/submit",
                json={
                    "tool_id": "test:text-to-image:test-model",
                    "folder_path": output_folder,
                    "task_type": "text-to-image",
                    "parameters": {"prompt": "test"},
                    "generator_instance_id": "forever-client",
                    "forever_work_reserved": True,
                    "prompt_options": {"autoImprove": {"enabled": True}},
                },
            )

        assert response.status_code == 500
        mock_queue.submit_job.assert_not_called()
        mock_queue.decline_work_request.assert_awaited_once_with("forever-client", "test")


class TestSubmitOutputDisposition:
    """The submit route lets a client place output outside the library.

    The editor needs this so candidate generations are durable and reachable
    without ever becoming library Assets. The route is deliberately narrower
    than the queue: only 'context' rooted at an existing working document.
    """

    async def _working_document(self, generation_db_session) -> int:
        from asset_service import create_asset_from_media, create_working_document

        async with generation_db_session() as session:
            media = await create_media_item(
                session,
                file_path=Path("/managed/objects/editor-base.png"),
                file_hash="editor-base-hash",
                width=64,
                height=64,
            )
            asset = await create_asset_from_media(session, media_id=media.id)
            document = await create_working_document(
                session, asset_id=asset.id, editor_type="image-stack"
            )
            await session.commit()
            return document.id

    async def test_context_output_is_owned_by_the_working_document(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        document_id = await self._working_document(generation_db_session)

        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "candidate", "width": 64, "height": 64, "seed": 1},
                "output_disposition": "context",
                "output_context_kind": "working_document",
                "output_context_id": str(document_id),
            },
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        await process_job(generation_queue, job_id)

        async with generation_db_session() as session:
            job = await session.get(GenerationJob, job_id)
            assert job.status == "completed"
            assert job.output_disposition == "context"
            assert job.output_context_kind == "working_document"
            assert job.output_context_id == str(document_id)
            # The whole point: durable Media, no library Asset.
            assert job.result_asset_id is None

            owner = (
                await session.execute(
                    select(MediaOwner).where(
                        MediaOwner.media_id == job.result_media_id,
                        MediaOwner.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            assert [(o.root_kind, o.root_id, o.role) for o in owner] == [
                ("working_document", str(document_id), "result")
            ]

    async def test_default_submission_still_creates_an_asset(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        """Omitting the field must not change existing behaviour."""
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "library item", "width": 64, "height": 64, "seed": 2},
            },
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        await process_job(generation_queue, job_id)

        async with generation_db_session() as session:
            job = await session.get(GenerationJob, job_id)
            assert job.output_disposition == "asset"
            assert job.result_asset_id is not None

    async def test_unknown_working_document_is_rejected(
        self, generation_client: httpx.AsyncClient, output_folder: str
    ):
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "x"},
                "output_disposition": "context",
                "output_context_kind": "working_document",
                "output_context_id": "999999",
            },
        )
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "disposition,kind,context_id",
        [
            # Server-owned dispositions a client must not be able to mint.
            ("ephemeral", None, None),
            ("container_member", "batch", "batch-1"),
            # A context root outside the allowlist.
            ("context", "chat", "1"),
            # Context without a root, and a root without context.
            ("context", "working_document", None),
            ("asset", "working_document", "1"),
        ],
    )
    async def test_disallowed_dispositions_are_rejected(
        self,
        generation_client: httpx.AsyncClient,
        output_folder: str,
        disposition,
        kind,
        context_id,
    ):
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "x"},
                "output_disposition": disposition,
                "output_context_kind": kind,
                "output_context_id": context_id,
            },
        )
        assert response.status_code == 400


# =============================================================================
# Job Processing Tests
# =============================================================================


class TestJobProcessing:
    """Tests for job execution through the queue."""

    async def test_job_state_transitions(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        """Verify job transitions from queued -> processing -> completed."""
        # Submit job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "auto_delete_duration": "1h",
                "parameters": {"prompt": "state transition test", "width": 64, "height": 64, "steps": 5, "seed": 123},
            },
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        # Verify initial state is queued
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        assert job_response.json()["status"] == "queued"

        # Process the job
        await process_job(generation_queue, job_id)

        # Verify completed
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        job = job_response.json()
        assert job["status"] == "completed"
        assert job["result_media_id"] is not None
        assert job["result_asset_id"] is not None
        assert job["expires_at"] is not None

        async with generation_db_session() as session:
            asset = await session.get(Asset, job["result_asset_id"])
            assert asset.expires_at.isoformat() == job["expires_at"]

    async def test_completed_job_creates_media_item(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        """Verify completed job creates a MediaItem with correct metadata."""
        # Submit job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "media creation test", "width": 64, "height": 64, "steps": 5, "seed": 456},
            },
        )
        job_id = response.json()["job_id"]

        # Process the job
        await process_job(generation_queue, job_id)

        # Get job details
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        job = job_response.json()
        assert job["status"] == "completed"

        # Verify MediaItem in database
        async with generation_db_session() as session:
            media = await session.get(MediaItem, job["result_media_id"])
            assert media is not None
            assert media.generation_metadata is not None

            # Verify metadata structure
            meta = json.loads(media.generation_metadata)
            assert meta["prompt"] == "media creation test"
            assert meta["tool_id"] == "test:text-to-image:test-model"
            assert meta["task_type"] == "text-to-image"

            # Verify file was created
            assert Path(media.file_path).exists()
            asset = await session.get(Asset, job["result_asset_id"])
            assert asset is not None
            revision = await session.get(AssetRevision, asset.current_revision_id)
            assert revision.primary_media_id == media.id

    async def test_failed_job_records_error(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        test_provider,
        output_folder: str,
    ):
        """Configure provider to fail and verify error is recorded."""
        # Configure provider to fail
        test_provider.configure_tool(
            "text-to-image:test-model",
            TestToolConfig(
                should_fail=True,
                fail_at_progress=0.5,
                fail_message="GPU out of memory",
            ),
        )

        try:
            # Submit job
            response = await generation_client.post(
                "/api/generate/submit",
                json={
                    "tool_id": "test:text-to-image:test-model",
                    "folder_path": output_folder,
                    "task_type": "text-to-image",
                    "parameters": {"prompt": "failure test", "steps": 5, "seed": 789},
                },
            )
            job_id = response.json()["job_id"]

            # Process the job (will fail)
            await process_job(generation_queue, job_id)

            # Verify failed state
            job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
            job = job_response.json()
            assert job["status"] == "failed"
            assert "GPU out of memory" in job["error"]
        finally:
            # Reset provider config
            test_provider.reset_configs()

    async def test_websocket_events_broadcast(
        self,
        generation_client: httpx.AsyncClient,
        generation_queue,
        mock_ws,
        output_folder: str,
    ):
        """Verify WebSocket events are broadcast during job lifecycle."""
        mock_ws.clear()

        # Submit job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "websocket test", "steps": 5, "seed": 111},
            },
        )
        job_id = response.json()["job_id"]

        # Process the job
        await process_job(generation_queue, job_id)

        # Verify broadcast events
        mock_ws.assert_broadcast("generation_job_queued")


# =============================================================================
# Job Cancellation Tests
# =============================================================================


class TestJobCancellation:
    """Tests for DELETE /api/generate/jobs/{job_id}"""

    async def test_cancel_queued_job(
        self,
        generation_client: httpx.AsyncClient,
        output_folder: str,
    ):
        """Cancelling a queued job should succeed."""
        # Submit job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "cancel queued test", "steps": 5, "seed": 888},
            },
        )
        job_id = response.json()["job_id"]

        # Cancel the queued job
        cancel_response = await generation_client.delete(
            f"/api/generate/jobs/{job_id}"
        )
        assert cancel_response.status_code == 200
        assert cancel_response.json()["success"] is True

        # Verify job is cancelled
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        assert job_response.json()["status"] == "cancelled"

    async def test_cancel_completed_job_returns_400(
        self,
        generation_client: httpx.AsyncClient,
        generation_queue,
        output_folder: str,
    ):
        """Cancelling a completed job returns 400."""
        # Submit job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "cancel test", "steps": 5, "seed": 222},
            },
        )
        job_id = response.json()["job_id"]

        # Process to completion
        await process_job(generation_queue, job_id)

        # Try to cancel completed job
        cancel_response = await generation_client.delete(
            f"/api/generate/jobs/{job_id}"
        )
        assert cancel_response.status_code == 400


# =============================================================================
# Generate More Tests
# =============================================================================


class TestGenerateMore:
    """Tests for GET /api/tools/generate-more-tools/{media_id}"""

    async def test_get_tools_for_generated_media(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        """Get compatible tools for media with generation metadata."""
        # Create a completed job to generate media with proper metadata
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "generator_instance_id": "tool-test_text-to-image_test-model__i_17@@browser-guid",
                "parameters": {"prompt": "generate more test", "width": 64, "height": 64, "steps": 5, "seed": 9999},
            },
        )
        job_id = response.json()["job_id"]
        await process_job(generation_queue, job_id)

        # Get the media ID from the completed job
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        media_id = job_response.json()["result_media_id"]

        # Get generate-more tools
        response = await generation_client.get(f"/api/tools/generate-more-tools/{media_id}")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

        # Find the test tool in the response
        test_tools = [t for t in data if "test" in t["full_tool_id"]]
        assert len(test_tools) > 0
        original = next(t for t in test_tools if t["is_original"])
        assert original["original_generator_instance_id"] == (
            "tool-test_text-to-image_test-model__i_17@@browser-guid"
        )

    async def test_original_tool_has_no_instance_when_generation_job_is_gone(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
    ):
        """Old media keeps the base-tool fallback when instance provenance is unavailable."""
        async with generation_db_session() as session:
            media = await create_media_with_generation_metadata(session)
            await session.commit()
            media_id = media.id

        response = await generation_client.get(f"/api/tools/remix-tools/{media_id}")
        assert response.status_code == 200

        original = next(tool for tool in response.json() if tool["is_original"])
        assert original["full_tool_id"] == "test:text-to-image:test-model"
        assert original["original_generator_instance_id"] is None

    async def test_remix_tools_exclude_disconnected_providers(
        self,
        generation_app,
        generation_client: httpx.AsyncClient,
        generation_db_session,
    ):
        """Remix is an action menu, so cached tools must not be offered."""
        from providers.base import ProviderStatus

        async with generation_db_session() as session:
            media = await create_media_with_generation_metadata(session)
            await session.commit()
            media_id = media.id

        provider = generation_app.state.test_provider
        provider._status = ProviderStatus.DISCONNECTED
        try:
            response = await generation_client.get(f"/api/tools/remix-tools/{media_id}")
        finally:
            provider._status = ProviderStatus.CONNECTED

        assert response.status_code == 200
        assert all(tool["provider_id"] != provider.provider_id for tool in response.json())


# =============================================================================
# Config From Media Tests
# =============================================================================


class TestConfigFromMedia:
    """Tests for POST /api/generate/config-from-media/{media_id}"""

    async def test_extract_config_without_target_tool(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        """Extract generation config from media without specifying target tool."""
        # Create a completed job to generate media with proper metadata
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "config extraction test", "width": 64, "height": 64, "steps": 30, "seed": 98765, "cfg": 8.5},
            },
        )
        job_id = response.json()["job_id"]
        await process_job(generation_queue, job_id)

        # Get the media ID from the completed job
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        media_id = job_response.json()["result_media_id"]

        # Extract config without target_tool_id (avoids the list_tools bug)
        response = await generation_client.post(
            f"/api/generate/config-from-media/{media_id}",
        )
        assert response.status_code == 200

        data = response.json()
        assert data["prompt"] == "config extraction test"
        assert data["input_media_id"] == media_id

    async def test_caption_only_media_sets_disable_all_loras(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
    ):
        """Caption-only media should return disable_all_loras=True."""
        from tests.helpers import create_media_item

        # Create a media item with only vlm_caption (no generation_metadata)
        async with generation_db_session() as session:
            media = await create_media_item(
                session,
                vlm_caption="A beautiful sunset over mountains",
                vlm_caption_status="complete",
                # No generation_metadata - simulates imported image with caption
            )

        # Extract config
        response = await generation_client.post(
            f"/api/generate/config-from-media/{media.id}",
        )
        assert response.status_code == 200

        data = response.json()
        assert data["prompt"] == "A beautiful sunset over mountains"
        assert data.get("loras") == []
        assert data.get("disable_all_loras") is True

    async def test_video_config_preserves_duration(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
    ):
        """Modern duration-based video tools retain duration when remixed."""
        from tests.helpers import create_media_item

        async with generation_db_session() as session:
            media = await create_media_item(
                session,
                file_format="mp4",
                generation_metadata=json.dumps({
                    "tool_id": "test:text-to-video:duration-model",
                    "prompt": "A slow camera move",
                    "parameters": {"duration": 8, "seed": 123},
                }),
            )

        response = await generation_client.post(
            f"/api/generate/config-from-media/{media.id}",
        )

        assert response.status_code == 200
        assert response.json()["duration"] == 8


# =============================================================================
# Job Listing Tests
# =============================================================================


class TestJobListing:
    """Tests for GET /api/generate/jobs"""

    async def test_list_jobs(
        self,
        generation_client: httpx.AsyncClient,
        output_folder: str,
    ):
        """List all jobs for current profile."""
        # Submit a job first
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "list test", "steps": 5, "seed": 333},
            },
        )
        job_id = response.json()["job_id"]

        # List jobs
        list_response = await generation_client.get("/api/generate/jobs")
        assert list_response.status_code == 200

        data = list_response.json()
        assert "jobs" in data
        assert "count" in data

        # Our job should be in the list
        job_ids = [j["id"] for j in data["jobs"]]
        assert job_id in job_ids

    async def test_get_job_details(
        self,
        generation_client: httpx.AsyncClient,
        output_folder: str,
    ):
        """Get details of a specific job."""
        # Submit a job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "details test", "steps": 5, "seed": 444},
            },
        )
        job_id = response.json()["job_id"]

        # Get job details
        details_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        assert details_response.status_code == 200

        job = details_response.json()
        assert job["id"] == job_id
        assert job["task_type"] == "text-to-image"
        assert job["tool_id"] == "test:text-to-image:test-model"

    async def test_trashed_result_asset_disappears_from_tool_history(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "temporary result", "steps": 2},
            },
        )
        job_id = response.json()["job_id"]
        await process_job(generation_queue, job_id)
        job = (await generation_client.get(f"/api/generate/jobs/{job_id}")).json()

        from asset_service import trash_asset

        async with generation_db_session() as session:
            await trash_asset(session, asset_id=job["result_asset_id"])
            await session.commit()

        listed = (await generation_client.get("/api/generate/jobs")).json()["jobs"]
        assert job_id not in {item["id"] for item in listed}


# =============================================================================
# Video frame grab (POST /api/generate/extract-frame)
# =============================================================================


def _ffmpeg_available() -> bool:
    try:
        from ffmpeg_checker import FFmpegChecker

        ok, _ = FFmpegChecker().check_availability()
        return ok
    except Exception:
        return False


def _make_test_video(path: Path, width: int = 320, height: int = 240, seconds: int = 1) -> None:
    """Generate a tiny test video with ffmpeg's lavfi testsrc."""
    import ffmpeg

    (
        ffmpeg.input(f"testsrc=duration={seconds}:size={width}x{height}:rate=10", f="lavfi")
        .output(str(path), pix_fmt="yuv420p")
        .overwrite_output()
        .run(capture_stdout=True, capture_stderr=True)
    )


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not available")
class TestExtractFrame:
    """Tests for POST /api/generate/extract-frame (server-side ffmpeg grab)."""

    async def test_extract_first_frame_from_uploaded_video(
        self, generation_client: httpx.AsyncClient, tmp_path: Path
    ):
        """Uploading a video returns a full-res still in the prep cache."""
        import app_dirs

        vid = tmp_path / "clip.mp4"
        _make_test_video(vid, 320, 240)

        with open(vid, "rb") as f:
            response = await generation_client.post(
                "/api/generate/extract-frame",
                files={"file": ("clip.mp4", f.read(), "video/mp4")},
                data={"position": "first"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["width"] == 320
        assert data["height"] == 240
        assert data["filename"].startswith("video_frame_")
        assert data["time_seconds"] == 0.0
        assert data["fps"] > 0  # testsrc rate=10

        stored = Path(data["path"])
        assert stored.exists()
        prep_cache = app_dirs.get_cache_dir() / "reference-prep-cache"
        assert stored.parent == prep_cache

    async def test_extract_last_frame_reports_duration(
        self, generation_client: httpx.AsyncClient, tmp_path: Path
    ):
        """Last-frame grab seeks near the end and reports the source duration."""
        vid = tmp_path / "clip2.mp4"
        _make_test_video(vid, 160, 120, seconds=2)

        with open(vid, "rb") as f:
            response = await generation_client.post(
                "/api/generate/extract-frame",
                files={"file": ("clip2.mp4", f.read(), "video/mp4")},
                data={"position": "last"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["width"] == 160 and data["height"] == 120
        assert data["duration"] > 1.0  # ~2s clip
        assert data["time_seconds"] > 0.0

    async def test_frame_preview_returns_jpeg(
        self, generation_client: httpx.AsyncClient, tmp_path: Path, output_folder: str
    ):
        """The scrub preview returns a downscaled JPEG for an allowed source path."""
        # Place the video inside the (allowed) generation/output folder so the
        # source_path passes the media-dir allow-list.
        vid = Path(output_folder) / "preview_clip.mp4"
        _make_test_video(vid, 640, 480)

        response = await generation_client.get(
            "/api/generate/frame-preview",
            params={"source_path": str(vid), "t": 0.0, "w": 320},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert len(response.content) > 0

    async def test_frame_strip_returns_montage(
        self, generation_client: httpx.AsyncClient, output_folder: str
    ):
        """The filmstrip endpoint returns a cached wide JPEG montage."""
        from io import BytesIO
        from PIL import Image

        vid = Path(output_folder) / "strip_clip.mp4"
        _make_test_video(vid, 160, 120, seconds=2)

        response = await generation_client.get(
            "/api/generate/frame-strip",
            params={"source_path": str(vid), "count": 8, "w": 64},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        img = Image.open(BytesIO(response.content))
        # 8 cells * 64px wide montage
        assert img.width == 8 * 64
        assert img.height > 0

    async def test_video_info_returns_duration_and_fps(
        self, generation_client: httpx.AsyncClient, output_folder: str
    ):
        """The video-info endpoint probes duration + fps for an allowed source path."""
        vid = Path(output_folder) / "info_clip.mp4"
        _make_test_video(vid, 160, 120, seconds=2)

        response = await generation_client.get(
            "/api/generate/video-info",
            params={"source_path": str(vid)},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["duration"] > 1.0  # ~2s clip
        assert data["fps"] > 0.0

    async def test_video_info_rejects_disallowed_source_path(
        self, generation_client: httpx.AsyncClient
    ):
        response = await generation_client.get(
            "/api/generate/video-info",
            params={"source_path": "/etc/hosts"},
        )
        assert response.status_code == 403

    async def test_extract_requires_a_source(
        self, generation_client: httpx.AsyncClient
    ):
        """No file and no source_path is a 400."""
        response = await generation_client.post(
            "/api/generate/extract-frame",
            data={"position": "first"},
        )
        assert response.status_code == 400

    async def test_extract_rejects_disallowed_source_path(
        self, generation_client: httpx.AsyncClient
    ):
        """An arbitrary filesystem path outside allowed media dirs is denied."""
        response = await generation_client.post(
            "/api/generate/extract-frame",
            data={"source_path": "/etc/hosts", "position": "first"},
        )
        assert response.status_code == 403


class TestReferencePrepCrop:
    """Crop step in the reference prep pipeline (flip → crop → scale → ...)."""

    @pytest.fixture
    def quadrant_image(self, output_folder):
        """1000x500 image with distinct quadrant colors."""
        from PIL import Image

        path = Path(output_folder) / "prep_crop_src.png"
        img = Image.new("RGB", (1000, 500))
        img.paste(Image.new("RGB", (500, 250), (255, 0, 0)), (0, 0))        # top-left red
        img.paste(Image.new("RGB", (500, 250), (0, 255, 0)), (500, 0))      # top-right green
        img.paste(Image.new("RGB", (500, 250), (0, 0, 255)), (0, 250))      # bottom-left blue
        img.paste(Image.new("RGB", (500, 250), (255, 255, 0)), (500, 250))  # bottom-right yellow
        img.save(path)
        return path

    async def test_crop_extracts_normalized_region(self, quadrant_image):
        from PIL import Image
        from routes.generation import ReferencePreprocessRequest, preprocess_reference_pipeline

        result = await preprocess_reference_pipeline(ReferencePreprocessRequest(
            source_path=str(quadrant_image),
            crop={"x": 0.5, "y": 0.0, "width": 0.5, "height": 1.0},
        ))
        assert (result["width"], result["height"]) == (500, 500)
        out = Image.open(result["path"]).convert("RGB")
        assert out.getpixel((250, 100)) == (0, 255, 0)   # green (top-right)
        assert out.getpixel((250, 400)) == (255, 255, 0) # yellow (bottom-right)

    async def test_crop_applies_after_rotation(self, quadrant_image):
        """Crop rect is relative to the post-flip image: after 90° CW rotation,
        the rotated top-left region is the original bottom-left quadrant."""
        from PIL import Image
        from routes.generation import ReferencePreprocessRequest, preprocess_reference_pipeline

        result = await preprocess_reference_pipeline(ReferencePreprocessRequest(
            source_path=str(quadrant_image),
            flip={"rotation": 90},
            crop={"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.25},
        ))
        assert (result["width"], result["height"]) == (250, 250)
        out = Image.open(result["path"]).convert("RGB")
        assert out.getpixel((125, 125)) == (0, 0, 255)  # blue (original bottom-left)

    async def test_crop_rotation_straightens_about_rect_center(self, quadrant_image):
        """crop.rotation rotates the rect clockwise on the image; the pipeline
        rotates the image the opposite way about the rect center before the
        axis-aligned cut. With 90° the quadrants pinwheel around the center."""
        from PIL import Image
        from routes.generation import ReferencePreprocessRequest, preprocess_reference_pipeline

        # Center 250x250 rect (image center = quadrant intersection at 500,250),
        # rotated 90°: content rotates 90° CCW, so the top-right (green) quadrant
        # moves into the top-left of the output.
        result = await preprocess_reference_pipeline(ReferencePreprocessRequest(
            source_path=str(quadrant_image),
            crop={"x": 0.375, "y": 0.25, "width": 0.25, "height": 0.5, "rotation": 90.0},
        ))
        assert (result["width"], result["height"]) == (250, 250)
        out = Image.open(result["path"]).convert("RGB")
        assert out.getpixel((60, 60)) == (0, 255, 0)      # green (was top-right)
        assert out.getpixel((190, 60)) == (255, 255, 0)   # yellow (was bottom-right)
        assert out.getpixel((60, 190)) == (255, 0, 0)     # red (was top-left)
        assert out.getpixel((190, 190)) == (0, 0, 255)    # blue (was bottom-left)

    async def test_scale_factor_applies_to_cropped_dims(self, quadrant_image):
        from routes.generation import ReferencePreprocessRequest, preprocess_reference_pipeline

        result = await preprocess_reference_pipeline(ReferencePreprocessRequest(
            source_path=str(quadrant_image),
            crop={"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5},
            scale={"mode": "factor", "factor": 2.0},
        ))
        assert (result["width"], result["height"]) == (1000, 500)


class TestCompletedHistoryPaging:
    """Tests for order=completed_at keyset paging on GET /api/generate/jobs and
    the /api/generate/jobs/completed-count endpoint (slideshow history)."""

    async def _seed_completed_jobs(self, generation_db_session, instance_id, count=5):
        """Create `count` completed jobs with strictly increasing completed_at.

        Returns jobs in creation order (oldest first)."""
        from datetime import datetime, timedelta
        from tests.helpers import create_generation_job

        base = datetime.utcnow() - timedelta(days=1)
        jobs = []
        async with generation_db_session() as session:
            for i in range(count):
                media = await create_media_item(session)
                job = await create_generation_job(
                    session,
                    status="completed",
                    generator_instance_id=instance_id,
                    result_media_id=media.id,
                    completed_at=base + timedelta(seconds=i),
                    output_disposition="context",
                )
                jobs.append(job)
        return jobs

    async def test_completed_order_is_completed_at_desc(
        self, generation_client, generation_db_session
    ):
        instance = "history-order-instance"
        jobs = await self._seed_completed_jobs(generation_db_session, instance, count=4)

        response = await generation_client.get(
            "/api/generate/jobs",
            params={
                "status": "completed",
                "order": "completed_at",
                "generator_instance_id": instance,
            },
        )
        assert response.status_code == 200
        listed_ids = [j["id"] for j in response.json()["jobs"]]
        assert listed_ids == [j.id for j in reversed(jobs)]

    async def test_keyset_cursor_pages_strictly_older_jobs(
        self, generation_client, generation_db_session
    ):
        instance = "history-cursor-instance"
        jobs = await self._seed_completed_jobs(generation_db_session, instance, count=5)
        anchor = jobs[2]  # jobs[0], jobs[1] are strictly older

        response = await generation_client.get(
            "/api/generate/jobs",
            params={
                "status": "completed",
                "order": "completed_at",
                "generator_instance_id": instance,
                "completed_before": anchor.completed_at.isoformat(),
                "completed_before_id": anchor.id,
            },
        )
        assert response.status_code == 200
        listed_ids = [j["id"] for j in response.json()["jobs"]]
        assert listed_ids == [jobs[1].id, jobs[0].id]

        # Offset pages within the cursor window
        response = await generation_client.get(
            "/api/generate/jobs",
            params={
                "status": "completed",
                "order": "completed_at",
                "generator_instance_id": instance,
                "completed_before": anchor.completed_at.isoformat(),
                "completed_before_id": anchor.id,
                "offset": 1,
                "limit": 10,
            },
        )
        assert response.status_code == 200
        assert [j["id"] for j in response.json()["jobs"]] == [jobs[0].id]

    async def test_cursor_breaks_completed_at_ties_by_id(
        self, generation_client, generation_db_session
    ):
        from datetime import datetime, timedelta
        from tests.helpers import create_generation_job

        instance = "history-tie-instance"
        tie_at = datetime.utcnow() - timedelta(days=2)
        jobs = []
        async with generation_db_session() as session:
            for _ in range(3):
                media = await create_media_item(session)
                jobs.append(await create_generation_job(
                    session,
                    status="completed",
                    generator_instance_id=instance,
                    result_media_id=media.id,
                    completed_at=tie_at,
                    output_disposition="context",
                ))

        # Same completed_at throughout: order and cursor fall back to id DESC.
        response = await generation_client.get(
            "/api/generate/jobs",
            params={
                "status": "completed",
                "order": "completed_at",
                "generator_instance_id": instance,
                "completed_before": jobs[2].completed_at.isoformat(),
                "completed_before_id": jobs[2].id,
            },
        )
        assert response.status_code == 200
        assert [j["id"] for j in response.json()["jobs"]] == [jobs[1].id, jobs[0].id]

    async def test_completed_count_matches_visibility_and_cursor(
        self, generation_client, generation_db_session
    ):
        from datetime import datetime
        from tests.helpers import create_generation_job

        instance = "history-count-instance"
        jobs = await self._seed_completed_jobs(generation_db_session, instance, count=5)

        async with generation_db_session() as session:
            # Deleted media: invisible to both listing and count
            deleted_media = await create_media_item(session)
            deleted_media.deleted_at = datetime.utcnow()
            await create_generation_job(
                session,
                status="completed",
                generator_instance_id=instance,
                result_media_id=deleted_media.id,
                completed_at=jobs[0].completed_at,
                output_disposition="context",
            )
            # Non-completed job: never counted
            await create_generation_job(
                session,
                status="queued",
                generator_instance_id=instance,
            )
            await session.commit()

        response = await generation_client.get(
            "/api/generate/jobs/completed-count",
            params={"generator_instance_id": instance},
        )
        assert response.status_code == 200
        assert response.json()["count"] == 5

        anchor = jobs[2]
        response = await generation_client.get(
            "/api/generate/jobs/completed-count",
            params={
                "generator_instance_id": instance,
                "completed_before": anchor.completed_at.isoformat(),
                "completed_before_id": anchor.id,
            },
        )
        assert response.status_code == 200
        assert response.json()["count"] == 2

    async def test_invalid_completed_before_returns_400(self, generation_client):
        response = await generation_client.get(
            "/api/generate/jobs",
            params={"completed_before": "not-a-timestamp"},
        )
        assert response.status_code == 400

        response = await generation_client.get(
            "/api/generate/jobs/completed-count",
            params={"completed_before": "not-a-timestamp"},
        )
        assert response.status_code == 400


# =============================================================================
# Fixtures for this test file
# =============================================================================


@pytest.fixture(autouse=True)
def reset_test_provider(test_provider):
    """Reset test provider config between tests."""
    yield
    test_provider.reset_configs()
