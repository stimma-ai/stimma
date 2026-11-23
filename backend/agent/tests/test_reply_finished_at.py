import json
from datetime import datetime, timedelta

from agent.v2.service import _finalize_thinking_item
from database import ChatItem


class _Session:
    async def commit(self):
        pass


class _Ws:
    async def broadcast(self, *_args, **_kwargs):
        pass


async def test_finalized_reply_records_when_it_landed():
    # The row is created when the model call starts; a long call must not show its start time.
    started = datetime.utcnow() - timedelta(minutes=20)
    item = ChatItem(chat_id=1, item_type="assistant_message", created_at=started)

    await _finalize_thinking_item(item, "Done.", None, 1.0, _Session(), _Ws())

    finished = datetime.fromisoformat(json.loads(item.item_metadata)["finished_at"])
    assert finished - started > timedelta(minutes=19)
    assert item.created_at == started
