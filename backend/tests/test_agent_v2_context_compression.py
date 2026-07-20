import json

import pytest

from agent.v2.conversation import (
    MAX_ACTIVE_VIEW_IMAGES,
    STALE_TURN_THRESHOLD,
    TRUNCATION_MIN_CHARS,
    _compress_stale_items,
)
from database import ChatItem


class _NoopSession:
    """Stand-in for AsyncSession — _compress_stale_items only awaits commit()."""

    async def commit(self):
        pass


def _user_turn():
    return ChatItem(item_type="user_message", message_text="go")


def _view_image_result(tool_call_id: str):
    marker = {"__view_image__": True, "path": "/tmp/whatever.png", "detail": "low"}
    return ChatItem(
        item_type="tool_result",
        tool_call_id=tool_call_id,
        tool_result=json.dumps(marker),
    )


def _big_text_result(tool_call_id: str, tool_name: str = "some_tool"):
    return ChatItem(
        item_type="tool_call",
        tool_call_id=tool_call_id,
        tool_name=tool_name,
    ), ChatItem(
        item_type="tool_result",
        tool_call_id=tool_call_id,
        tool_result="x" * (TRUNCATION_MIN_CHARS + 1),
    )


@pytest.mark.asyncio
async def test_stale_view_image_result_gets_placeholdered():
    tool_call, tool_result = _big_text_result("t1")
    view_image_result = _view_image_result("t2")

    items = [tool_call, tool_result, view_image_result]
    # Push both results older than STALE_TURN_THRESHOLD user turns.
    items += [_user_turn() for _ in range(STALE_TURN_THRESHOLD + 1)]

    await _compress_stale_items(items, _NoopSession())

    assert tool_result.tool_result.startswith("[some_tool result:")
    assert view_image_result.tool_result == (
        "[Image shown earlier in this conversation — call view_image again if you need to see it]"
    )


@pytest.mark.asyncio
async def test_only_view_image_results_older_than_the_threshold_are_compressed():
    old_view_image = _view_image_result("old")
    recent_view_image = _view_image_result("recent")

    # STALE_TURN_THRESHOLD + 2 user turns: old_view_image sits before the
    # cutoff (compressed), recent_view_image sits after it (left alone).
    items = (
        [_user_turn(), old_view_image]
        + [_user_turn() for _ in range(STALE_TURN_THRESHOLD)]
        + [recent_view_image]
    )

    await _compress_stale_items(items, _NoopSession())

    assert old_view_image.tool_result == (
        "[Image shown earlier in this conversation — call view_image again if you need to see it]"
    )
    parsed = json.loads(recent_view_image.tool_result)
    assert parsed["__view_image__"] is True


@pytest.mark.asyncio
async def test_view_image_budget_applies_within_one_user_turn():
    images = [_view_image_result(f"image-{i}") for i in range(MAX_ACTIVE_VIEW_IMAGES + 2)]
    items = [_user_turn(), *images]

    await _compress_stale_items(items, _NoopSession())

    for image in images[:-MAX_ACTIVE_VIEW_IMAGES]:
        assert image.tool_result == (
            "[Image shown earlier in this conversation — call view_image again if you need to see it]"
        )
    for image in images[-MAX_ACTIVE_VIEW_IMAGES:]:
        assert json.loads(image.tool_result)["__view_image__"] is True


class TestToolCallArgsSanitized:
    def test_malformed_tool_args_replaced_with_valid_json(self):
        import json
        from types import SimpleNamespace
        from agent.v2.conversation import _item_to_message

        item = SimpleNamespace(
            item_type="tool_call", tool_call_id="abc", tool_name="write_file",
            tool_args='{"file_path": "x.html", "content": "<div>',  # truncated
            message_text=None, item_metadata=None,
        )
        msg = _item_to_message(item)
        args = msg["tool_calls"][0]["function"]["arguments"]
        parsed = json.loads(args)  # must not raise
        assert "_malformed_arguments" in parsed

    def test_valid_tool_args_pass_through(self):
        import json
        from types import SimpleNamespace
        from agent.v2.conversation import _item_to_message

        item = SimpleNamespace(
            item_type="tool_call", tool_call_id="abc", tool_name="write_file",
            tool_args='{"file_path": "x.html"}',
            message_text=None, item_metadata=None,
        )
        msg = _item_to_message(item)
        assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"file_path": "x.html"}
