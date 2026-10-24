import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.v2.tools.call_tool import _resolve_effective_task_type, call_tool


class _FakeToolDescriptor:
    def __init__(self):
        self.id = "image:model-a"
        self.name = "Model A"
        self.task_type = "text-to-image"
        self.task_types = ["text-to-image", "image-to-image"]
        self.parameter_schema = {
            "properties": {
                "prompt": {"type": "string"},
                "input_images": {"type": "array"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
            "required": ["prompt"],
        }
        self.default_width = 1024
        self.default_height = 1024


@pytest.fixture
def fake_provider():
    provider = MagicMock()
    provider.provider_id = "test-provider"
    return provider


@pytest.fixture
def fake_descriptor():
    return _FakeToolDescriptor()


@pytest.fixture
def fake_queue():
    queue = MagicMock()
    queue.submit_job = AsyncMock(return_value=42)
    queue._resolve_backend_info = MagicMock(return_value=("test-backend", None))
    return queue


@pytest.fixture
def mock_generation(monkeypatch, fake_queue, fake_provider, fake_descriptor):
    """Mock the generation pipeline: registry, queue, and wait_for_jobs."""
    registry = MagicMock()
    registry.get_tool.return_value = (fake_provider, fake_descriptor)

    monkeypatch.setattr(
        "agent.v2.tools.call_tool.ProviderRegistry.get_instance",
        lambda: registry,
    )
    monkeypatch.setattr(
        "agent.v2.tools.call_tool.get_generation_queue",
        lambda: fake_queue,
    )

    async def fake_wait(job_ids, session, **kwargs):
        return [555], [], 0, {42: 555}

    monkeypatch.setattr(
        "agent.v2.tools.call_tool.wait_for_jobs",
        fake_wait,
    )

    # Mock the database lookup for media file path (imported inside function body)
    monkeypatch.setattr(
        "database_registry.get_database_registry",
        lambda: MagicMock(
            get_database=lambda pid: MagicMock(
                async_session_maker=MagicMock(
                    return_value=_FakeSessionContext("/tmp/test_output.png")
                )
            )
        ),
    )
    monkeypatch.setattr(
        "agent.v2.tools.call_tool.get_current_profile",
        lambda: "test-profile",
    )
    monkeypatch.setattr(
        "agent.v2.tools.call_tool._get_default_folder",
        lambda _=None: "/tmp/output",
    )

    return registry


class _FakeSessionContext:
    """Async context manager that returns a fake session for media lookup."""

    def __init__(self, file_path):
        self._file_path = file_path

    async def __aenter__(self):
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        result = MagicMock()
        result.one_or_none.return_value = (self._file_path, 1024, 1024)
        session.execute = AsyncMock(return_value=result)
        return session

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("images", [[101], 101])
async def test_call_tool_routes_input_images(session, test_chat, fake_queue, mock_generation, tmp_path, images):
    result = await call_tool(
        tool_id="image:model-a",
        parameters={"prompt": "a cat", "input_images": images},
        session=session,
        chat_id=test_chat.id,
        workspace_dir=str(tmp_path),
        interrupt_checker=lambda: False,
    )

    assert "media_id=555" in result
    assert "Not yet shown to the user" in result
    assert fake_queue.submit_job.called
    submit_kwargs = fake_queue.submit_job.call_args
    assert submit_kwargs.kwargs["task_type"] == "image-to-image"
    assert submit_kwargs.kwargs["parameters"]["input_images"] == [101]
    assert submit_kwargs.kwargs["parameters"]["input_media_ids"] == [101]


def test_resolve_effective_task_type_routes_input_videos():
    descriptor = _FakeToolDescriptor()
    descriptor.task_type = "text-to-video"
    descriptor.task_types = ["text-to-video", "video-to-video"]

    assert _resolve_effective_task_type(descriptor, {"input_videos": [202]}) == "video-to-video"


@pytest.mark.asyncio
async def test_enhancement_rejection_reaches_agent_without_submitting_generation(
    session, test_chat, fake_queue, mock_generation, tmp_path, monkeypatch,
):
    import httpx
    from llm_http import _provider_http_error
    from routes.prompt_enhancement import _provider_http_exception

    provider_message = "At most 2 image(s) may be provided in one prompt."
    response = httpx.Response(400, request=httpx.Request("POST", "https://provider.example/v1"), json={
        "error": {"message": provider_message, "type": "BadRequestError", "param": "image", "code": 400},
    })

    async def reject(*args, **kwargs):
        raise _provider_http_exception(_provider_http_error(response, provider="test"))

    monkeypatch.setattr("routes.generation.enhance_tool_prompt", reject)
    result = await call_tool(
        tool_id="image:model-a", parameters={"prompt": "a cat"}, enhance_prompt=True,
        session=session, chat_id=test_chat.id, workspace_dir=str(tmp_path),
    )

    assert result.startswith("Error: Prompt enhancement failed:")
    assert "HTTP 400" in result and provider_message in result
    assert '"param": "image"' in result
    assert "No generation was started" in result
    fake_queue.submit_job.assert_not_called()
