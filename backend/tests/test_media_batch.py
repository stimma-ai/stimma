"""
Tests for media-batch processing (run a tool once per item in one media slot).

Covers POST /api/generate/submit-media-batch:
- One job per media id under a shared batch_id
- batch_total stored on the first job only
- batched field + media-id companion injected per item
- _batch_presentation_only marker (outputs stay individual, no output set)
- uniform batch-safe prep applied per item via the preprocess pipeline
- validation (empty / nonexistent / over-limit)
"""

import json
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock

import prompt_pipeline as pp
from database import CachedProviderTool
from tests.helpers.media import create_media_item


def _capture_queue():
    """Return (mock_queue, calls) where calls collects submit_batch_job kwargs."""
    mock_queue = AsyncMock()
    calls = []

    def _submit(*args, **kwargs):
        calls.append(kwargs)
        return len(calls)

    mock_queue.submit_batch_job = AsyncMock(side_effect=_submit)
    return mock_queue, calls


UPSCALE_TOOL_ID = "test:upscale-image:test-upscale"
EDIT_TOOL_ID = "test:image-to-image:test-edit"


async def _seed_pose_tool(session):
    schema = {
        "type": "object",
        "required": ["input_images", "pose_image"],
        "properties": {
            "input_images": {
                "type": "array",
                "items": {"type": "string", "format": "file-path"},
                "minItems": 1,
                "maxItems": 1,
                "x-control": "image_picker",
            },
            "pose_image": {"type": "string", "format": "image-file"},
            "steps": {"type": "integer"},
        },
    }
    session.add(CachedProviderTool(
        full_tool_id="test:pose",
        provider_id="test",
        provider_name="Test",
        tool_id="pose",
        name="Pose Test",
        task_type="image-to-image",
        task_types=json.dumps(["image-to-image"]),
        parameter_schema=json.dumps(schema),
        output_schema=json.dumps({}),
    ))
    await session.commit()


class TestMediaBatchSubmission:
    async def test_submit_media_batch_basic(self, generation_client: AsyncClient, generation_db_session):
        """N media ids -> N jobs, shared batch_id, batch_total on first job only."""
        async with generation_db_session() as session:
            m1 = await create_media_item(session, file_format='png')
            m2 = await create_media_item(session, file_format='png')
            m3 = await create_media_item(session, file_format='png')

        mock_queue, calls = _capture_queue()
        with patch('generation_queue.get_generation_queue', return_value=mock_queue):
            response = await generation_client.post("/api/generate/submit-media-batch", json={
                "tool_id": UPSCALE_TOOL_ID,
                "folder_path": "/tmp/test",
                "task_type": "upscale-image",
                "batch_input": {"field": "input_images", "media_ids": [m1.id, m2.id, m3.id]},
                "parameters": {
                    "prompt": "clean up\n# enhancer note\n[leave this alone]",
                    "steps": 20,
                    "resolution": 2048,
                },
            })

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total_jobs"] == 3
        assert len(data["job_ids"]) == 3
        assert mock_queue.submit_batch_job.call_count == 3
        assert [c["consume_pending_request"] for c in calls] == [True, False, False]

        # All jobs share one batch_id
        batch_ids = {c["batch_id"] for c in calls}
        assert len(batch_ids) == 1

        # batch_total only on the first job
        totals = [c["batch_total"] for c in calls]
        assert totals[0] == 3
        assert all(t is None for t in totals[1:])

        # Each job carries one item in the batched field + media-id companion,
        # plus the presentation-only marker and a batch index.
        expected = [(m1.id, m1.file_path), (m2.id, m2.file_path), (m3.id, m3.file_path)]
        for idx, (call, (mid, path)) in enumerate(zip(calls, expected)):
            params = call["parameters"]
            assert params["input_images"] == [path]
            assert params["input_media_ids"] == [mid]
            assert params["_batch_presentation_only"] is True
            assert params["_batch_index"] == idx
            assert params["prompt"] == "clean up\nleave this alone"
            assert params["steps"] == 20
            # No output set for presentation-only batches
            assert call["batch_output_title"] is None

    async def test_submit_media_batch_uses_one_prompt_preload_per_child(
        self, generation_client: AsyncClient, generation_db_session, monkeypatch
    ):
        """Prompt preloads are one-use child hints, not one shared batch hint."""
        async with generation_db_session() as session:
            m1 = await create_media_item(session, file_format='png')
            m2 = await create_media_item(session, file_format='png')

        import routes.prompt_enhancement as pe

        async def fail_improve(request, session):
            raise AssertionError("matching child prompt preloads should skip live improve")

        monkeypatch.setattr(pe, "improve_prompt", fail_improve)

        signature = pp.prompt_sources_signature([], [])
        prompt_preloads = [
            {
                "originalPrompt": "clean up",
                "processedPrompt": "clean up",
                "improvedPrompt": "cached prompt one",
                "instructions": None,
                "model": "Test Upscale",
                "isVideo": False,
                "isAudio": False,
                "inputImageCount": 1,
                "promptSourcesSignature": signature,
            },
            {
                "originalPrompt": "clean up",
                "processedPrompt": "clean up",
                "improvedPrompt": "cached prompt two",
                "instructions": None,
                "model": "Test Upscale",
                "isVideo": False,
                "isAudio": False,
                "inputImageCount": 1,
                "promptSourcesSignature": signature,
            },
        ]

        mock_queue, calls = _capture_queue()
        with patch('generation_queue.get_generation_queue', return_value=mock_queue):
            response = await generation_client.post("/api/generate/submit-media-batch", json={
                "tool_id": UPSCALE_TOOL_ID,
                "folder_path": "/tmp/test",
                "task_type": "upscale-image",
                "batch_input": {"field": "input_images", "media_ids": [m1.id, m2.id]},
                "parameters": {"prompt": "clean up"},
                "prompt_options": {"autoImprove": {"enabled": True, "model": "Test Upscale"}},
                "prompt_preloads": prompt_preloads,
            })

        assert response.status_code == 200, response.text
        assert [c["parameters"]["prompt"] for c in calls] == ["cached prompt one", "cached prompt two"]

    async def test_submit_media_batch_prompt_pipeline_failure_queues_no_partial_jobs(
        self, generation_client: AsyncClient, generation_db_session
    ):
        async with generation_db_session() as session:
            m1 = await create_media_item(session, file_format='png')
            m2 = await create_media_item(session, file_format='png')

        mock_queue, _ = _capture_queue()

        async def fail_second(parameters, **kwargs):
            if parameters.get("_batch_index") == 1:
                raise RuntimeError("enhancement failed")
            return parameters

        with (
            patch('generation_queue.get_generation_queue', return_value=mock_queue),
            patch('routes.generation._apply_generation_prompt_pipeline', side_effect=fail_second),
        ):
            response = await generation_client.post("/api/generate/submit-media-batch", json={
                "tool_id": UPSCALE_TOOL_ID,
                "folder_path": "/tmp/test",
                "task_type": "upscale-image",
                "batch_input": {"field": "input_images", "media_ids": [m1.id, m2.id]},
                "parameters": {"prompt": "clean up"},
            })

        assert response.status_code == 500
        mock_queue.submit_batch_job.assert_not_called()

    async def test_submit_media_batch_applies_prep(self, generation_client: AsyncClient, generation_db_session):
        """Uniform prep is applied per item via the preprocess pipeline."""
        async with generation_db_session() as session:
            m1 = await create_media_item(session, file_format='png')
            m2 = await create_media_item(session, file_format='png')

        mock_queue, calls = _capture_queue()
        prep = {
            "scale": {"mode": "factor", "factor": 0.5},
            "flip": {"horizontal": True},
            "preprocessor": "canny",
            "preprocessor_params": {"low": 100, "high": 200},
        }

        async def fake_pipeline(req):
            return {"path": req.source_path + ".prepped.png", "width": 64, "height": 64}

        with patch('generation_queue.get_generation_queue', return_value=mock_queue), \
             patch('routes.generation.preprocess_reference_pipeline', side_effect=fake_pipeline) as mock_prep:
            response = await generation_client.post("/api/generate/submit-media-batch", json={
                "tool_id": EDIT_TOOL_ID,
                "folder_path": "/tmp/test",
                "task_type": "image-to-image",
                "batch_input": {"field": "input_images", "media_ids": [m1.id, m2.id]},
                "parameters": {"prompt": "hello", "steps": 20},
                "prep": prep,
            })

        assert response.status_code == 200, response.text
        assert mock_prep.call_count == 2  # once per item

        first = calls[0]["parameters"]
        assert first["input_images"] == [m1.file_path + ".prepped.png"]
        assert first["input_media_ids"] == [m1.id]
        # Lineage metadata recorded as one-element arrays
        assert first["_original_input_paths"] == [m1.file_path]
        assert first["_input_preprocessors"] == ["canny"]
        assert first["_input_preprocessor_params"] == [{"low": 100, "high": 200}]
        assert first["_input_scales"] == [{"mode": "factor", "factor": 0.5}]
        assert first["_input_flips"] == [{"horizontal": True}]

    async def test_submit_media_batch_constant_inputs(self, generation_client: AsyncClient, generation_db_session):
        """Constant media slots are resolved and applied to every run."""
        async with generation_db_session() as session:
            await _seed_pose_tool(session)
            m1 = await create_media_item(session, file_format='png')
            m2 = await create_media_item(session, file_format='png')
            pose = await create_media_item(session, file_format='png')

        mock_queue, calls = _capture_queue()
        with patch('generation_queue.get_generation_queue', return_value=mock_queue):
            response = await generation_client.post("/api/generate/submit-media-batch", json={
                "tool_id": "test:pose",
                "folder_path": "/tmp/test",
                "task_type": "image-to-image",
                "batch_input": {"field": "input_images", "media_ids": [m1.id, m2.id]},
                "constant_inputs": {"pose_image": pose.id},
                "parameters": {"steps": 20},
            })

        assert response.status_code == 200, response.text
        for call in calls:
            params = call["parameters"]
            assert params["pose_image"] == pose.file_path
            assert params["pose_image_media_id"] == pose.id

    async def test_submit_media_batch_empty(self, generation_client: AsyncClient):
        response = await generation_client.post("/api/generate/submit-media-batch", json={
            "tool_id": UPSCALE_TOOL_ID,
            "folder_path": "/tmp/test",
            "task_type": "upscale-image",
            "batch_input": {"field": "input_images", "media_ids": []},
        })
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    async def test_submit_media_batch_nonexistent(self, generation_client: AsyncClient):
        response = await generation_client.post("/api/generate/submit-media-batch", json={
            "tool_id": UPSCALE_TOOL_ID,
            "folder_path": "/tmp/test",
            "task_type": "upscale-image",
            "batch_input": {"field": "input_images", "media_ids": [999999]},
        })
        assert response.status_code == 404

    async def test_submit_media_batch_over_limit(self, generation_client: AsyncClient):
        response = await generation_client.post("/api/generate/submit-media-batch", json={
            "tool_id": UPSCALE_TOOL_ID,
            "folder_path": "/tmp/test",
            "task_type": "upscale-image",
            "batch_input": {"field": "input_images", "media_ids": list(range(1, 102))},
        })
        assert response.status_code == 400
        assert "too large" in response.json()["detail"].lower()
