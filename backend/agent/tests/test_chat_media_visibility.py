"""The agent can find media from its own chat after the turn that made it.

The transcript never replays display rows, and stale tool results are
compressed, so media handles must survive in tool results and a chat-scoped
library query must be able to list everything the user has seen here.
"""

import json
from pathlib import Path

import pytest

from agent.v2.code_runtime import ToolResult, _format_run_code_receipt
from agent.v2.conversation import STALE_TURN_THRESHOLD, TRUNCATION_MIN_CHARS, _compress_stale_items
from agent.v2.tools.library import library
from agent.v2.tools.show import show
from database import Chat, ChatItem, GenerationJob
from tests.helpers.media import create_media_item


def _chat_job(media_id: int, chat_id: int) -> GenerationJob:
    return GenerationJob(
        status="completed",
        task_type="text-to-image",
        generator_type="test",
        generator_name="test",
        model_name="test",
        parameters="{}",
        folder_path="/tmp",
        result_media_id=media_id,
        output_disposition="context",
        output_context_kind="chat",
        output_context_id=str(chat_id),
    )


@pytest.mark.asyncio
async def test_intermediate_show_reports_the_media_ids_it_displayed(session, test_chat):
    first = await create_media_item(session, file_hash="shown-a")
    second = await create_media_item(session, file_hash="shown-b")
    await session.commit()

    result = await show(
        role="intermediate", media_ids=[first.id, second.id],
        session=session, chat_id=test_chat.id,
    )

    assert f"media_id={first.id}" in result
    assert f"media_id={second.id}" in result


@pytest.mark.asyncio
async def test_chat_scope_lists_this_chats_generations_and_displays_only(session, test_chat):
    other_chat = Chat(name="Other")
    session.add(other_chat)
    generated = await create_media_item(session, file_hash="generated-here")
    shown = await create_media_item(session, file_hash="shown-here")
    elsewhere = await create_media_item(session, file_hash="generated-elsewhere")
    await session.commit()
    session.add_all([_chat_job(generated.id, test_chat.id), _chat_job(elsewhere.id, other_chat.id)])
    session.add(ChatItem(chat_id=test_chat.id, item_type="media_display", media_ids=json.dumps([shown.id])))
    await session.commit()

    raw = await library(action="browse", scope="chat", session=session, workspace_dir=None, chat_id=test_chat.id)
    ids = {item["media_id"] for item in json.loads(raw)["items"]}

    # Neither is an Asset, so the default library scope cannot see them.
    assert ids == {generated.id, shown.id}


@pytest.mark.asyncio
async def test_chat_scope_requires_a_chat(session):
    with pytest.raises(ValueError, match="scope='chat'"):
        await library(action="browse", scope="chat", session=session, workspace_dir=None)


@pytest.mark.asyncio
async def test_compressed_tool_result_keeps_its_media_ids():
    class _NoopSession:
        async def commit(self):
            pass

    content = "This run produced 3 generations:\n" + "\n".join(
        f"  - media_id={mid} — turbo, prompt=\"{'x' * 200}\"" for mid in (41, 42, 43)
    )
    assert len(content) > TRUNCATION_MIN_CHARS
    call = ChatItem(item_type="tool_call", tool_call_id="c1", tool_name="run_code")
    result = ChatItem(item_type="tool_result", tool_call_id="c1", tool_result=content)
    items = [ChatItem(item_type="user_message"), call, result]
    items += [ChatItem(item_type="user_message") for _ in range(STALE_TURN_THRESHOLD + 1)]

    await _compress_stale_items(items, _NoopSession())

    assert result.tool_result.startswith("[run_code result:")
    assert "media_id 41, 42, 43" in result.tool_result


def test_large_batch_receipt_lists_every_media_id(tmp_path):
    results = [ToolResult(path=Path(tmp_path / f"{i}.png"), media_id=100 + i, tool_name="turbo") for i in range(30)]

    receipt = _format_run_code_receipt(results, [], workspace_dir=tmp_path)

    assert "24 more: media_id 103, 104" in receipt
    for i in range(30):
        assert str(100 + i) in receipt
