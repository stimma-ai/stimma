from datetime import datetime

from routes.chats import ChatItemResponse
from database import ChatItem


def test_chat_item_response_accepts_list_tool_result():
    item = ChatItemResponse(
        id=1,
        chat_id=1,
        created_at="2026-03-10T21:52:00.064984",
        item_type="tool_result",
        message_text=None,
        tool_name=None,
        tool_call_id="call-1",
        tool_args=None,
        tool_result=[{"media_id": 1, "filename": "a.png"}],
        tool_error=None,
        media_id=None,
        media_ids=None,
        grid_layout=None,
        parent_item_id=None,
        item_metadata=None,
    )

    assert isinstance(item.tool_result, list)
    assert item.tool_result[0]["media_id"] == 1


def test_chat_item_to_dict_tolerates_concatenated_tool_args():
    item = ChatItem(
        id=1,
        chat_id=1,
        created_at=datetime(2026, 3, 10, 21, 52, 0),
        item_type="tool_call",
        tool_call_id="call-1",
        tool_args='{"tool_id": "comfyui:z-image-turbo"}{"extra": true}',
    )

    data = item.to_dict()

    assert data["tool_args"] == {"tool_id": "comfyui:z-image-turbo"}
