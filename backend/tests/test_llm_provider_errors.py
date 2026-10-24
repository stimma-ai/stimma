"""Provider rejections retain actionable diagnostics without exposing requests."""

import json

import httpx
import pytest
from fastapi import HTTPException

from llm_http import LLMProviderHTTPError, _provider_http_error


IMAGE_LIMIT = "At most 2 image(s) may be provided in one prompt. (parameter=image)"


@pytest.mark.parametrize(("body", "message", "metadata"), [
    ({"error": {"message": IMAGE_LIMIT, "type": "BadRequestError", "param": "image", "code": 400}},
     IMAGE_LIMIT, {"type": "BadRequestError", "param": "image", "code": 400}),
    ({"error": "Unsupported parameter: temperature"}, "Unsupported parameter: temperature", {}),
    ({"detail": "Context length exceeded"}, "Context length exceeded", {}),
    ({"message": "Too many images", "code": "invalid_value"},
     "Too many images", {"code": "invalid_value"}),
    ({"error": {"message": ["invalid"], "code": {"unexpected": "shape"}}}, None, {}),
    (["unexpected", "response"], None, {}),
])
def test_provider_error_envelopes(body, message, metadata):
    request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
    response = httpx.Response(400, request=request, json=body)
    error = _provider_http_error(response, provider="test")

    assert isinstance(error, httpx.HTTPStatusError)
    assert error.response is response
    assert error.upstream_status == 400
    assert error.upstream_message == message
    assert error.upstream_metadata == metadata
    assert str(error) == "The AI provider rejected the request (HTTP 400)."


@pytest.mark.parametrize(("body", "expected"), [
    ("Unsupported image format", "Unsupported image format"),
    ("<!DOCTYPE html><html>proxy failure</html>", None),
    ("", None),
])
def test_plain_provider_error_fallback(body, expected):
    response = httpx.Response(502, text=body, request=httpx.Request("POST", "https://provider.example/v1"))
    assert _provider_http_error(response, provider="test").upstream_message == expected


def test_provider_details_are_bounded_and_redact_credentials():
    request = httpx.Request("POST", "https://provider.example/v1", headers={
        "Authorization": "Bearer private-auth-value",
        "x-api-key": "private-api-value",
    })
    message = (
        "At most 2 images. private-auth-value private-api-value "
        "Bearer unrelated-token sk-another-secret-value api_key=another-key "
        "https://internal.example/v1?token=private data:image/png;base64,private "
        "\x1b[31mERROR\x1b[0m\x00\n" + "x" * 2000
    )
    response = httpx.Response(400, request=request, json={"error": {
        "message": message, "type": "t" * 300, "code": "private-api-value",
        "param": "https://internal.example/secret",
        "request": {"prompt": "must not be copied"},
    }})
    error = _provider_http_error(response, provider="test")
    detail = json.dumps({"message": error.upstream_message, "fields": error.upstream_metadata})
    for secret in ("private-auth-value", "private-api-value", "unrelated-token",
                   "sk-another-secret-value", "another-key", "internal.example",
                   "base64,private", "must not be copied"):
        assert secret not in detail
    assert error.upstream_message.startswith("At most 2 images.")
    assert len(error.upstream_message) <= 1000
    assert len(error.upstream_metadata["type"]) <= 160
    assert "\x1b" not in error.upstream_message and "\x00" not in error.upstream_message


async def test_http_rejection_survives_prompt_enhancement_and_agent_tool(monkeypatch):
    """Exercise transport -> improve route -> agent-visible exception text."""
    import llm_http
    import routes.prompt_enhancement as pe
    from agent.v2.tools.call_tool import _enhance_prompt_for_tool
    from agent.v2.service import _format_raw_error

    responses = []

    async def assistant_config(*args, **kwargs):
        return object()

    monkeypatch.setattr("llm_resolver.get_effective_llm_config", assistant_config)
    monkeypatch.setattr(pe, "get_prompt", lambda *args: "Rewrite the supplied prompt.")

    def reject(request):
        responses.append(request)
        return httpx.Response(400, json={"error": {
            "message": IMAGE_LIMIT, "type": "BadRequestError", "param": "image", "code": 400,
        }})

    client = httpx.AsyncClient
    monkeypatch.setattr(llm_http.httpx, "AsyncClient", lambda **kw: client(
        **kw, transport=httpx.MockTransport(reject),
    ))

    async def complete(**kwargs):
        return await llm_http.acompletion(
            model="test-model", api_base="https://provider.example/v1", api_key="test-key",
            messages=kwargs["messages"],
        )

    monkeypatch.setattr(pe, "llm_complete_text", complete)
    with pytest.raises(HTTPException) as failure:
        await pe.improve_prompt(pe.ImprovePromptRequest(prompt="a landscape"), session=None)
    error = failure.value
    assert error.status_code == 502
    assert error.detail["code"] == "llm_provider_error"
    assert error.detail["upstream_status"] == 400
    assert error.detail["upstream_metadata"]["param"] == "image"
    assert IMAGE_LIMIT in error.detail["message"]
    # The same transport exception also supplies chat's Details disclosure.
    assert isinstance(error.__cause__, LLMProviderHTTPError)
    assert IMAGE_LIMIT in _format_raw_error(error.__cause__)

    async def enhance(params, **kwargs):
        return await pe.improve_prompt(pe.ImprovePromptRequest(prompt=params["prompt"]), session=None)

    monkeypatch.setattr("routes.generation.enhance_tool_prompt", enhance)
    with pytest.raises(ValueError) as agent_failure:
        await _enhance_prompt_for_tool(
            {"prompt": "a landscape"}, tool_id="test:image", task_type="text-to-image",
            enhance_prompt=True, project_id=None,
        )
    message = str(agent_failure.value)
    assert "Prompt enhancement failed" in message
    assert "HTTP 400" in message and IMAGE_LIMIT in message
    assert '"param": "image"' in message and '"type": "BadRequestError"' in message
    assert "No generation was started" in message
    assert len(responses) == 2  # One attempt per call; no retry of this 400.
