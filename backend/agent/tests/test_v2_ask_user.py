import json

import pytest
from sqlalchemy import select

from agent.hitl import HumanActionRequest, parse_human_response
from agent.v2.service import _annotate_ask_sequence, interrupt_execution
from database import ChatItem


def test_human_action_request_round_trips_ask_user_progress_metadata():
    action = HumanActionRequest(
        type="ask_user",
        prompt="Which style?",
        node_id="tool_123",
        tool_call_id="tool_123",
        ask_options=[
            {"label": "Editorial", "description": "Sharper, polished look"},
            {"label": "Film", "description": "Soft grain and mood"},
        ],
        ask_question_index=1,
        ask_question_total=3,
        ask_question_plan=["Style", "Subject", "Output size"],
    )

    round_tripped = HumanActionRequest.from_dict(action.to_dict())

    assert round_tripped.ask_question_index == 1
    assert round_tripped.ask_question_total == 3
    assert round_tripped.ask_question_plan == ["Style", "Subject", "Output size"]
    assert round_tripped.ask_questions is None


def test_human_action_request_round_trips_grouped_ask_questions():
    action = HumanActionRequest(
        type="ask_user",
        prompt="Answer these before I generate",
        node_id="tool_grouped",
        tool_call_id="tool_grouped",
        ask_questions=[
            {
                "question": "What style?",
                "options": [{"label": "Photo", "description": "Photoreal"}],
            },
            {
                "question": "How many cats?",
                "options": [{"label": "One", "description": "Single cat"}],
            },
        ],
    )

    round_tripped = HumanActionRequest.from_dict(action.to_dict())

    assert len(round_tripped.ask_questions) == 2
    assert round_tripped.ask_questions[0]["question"] == "What style?"


def test_parse_human_response_preserves_interrupt_flag():
    response = parse_human_response("ask_user", {"answer": "", "interrupted": True})

    assert response.answer == ""
    assert response.interrupted is True


def test_annotate_ask_sequence_adds_progress_metadata_for_consecutive_questions():
    current_args = {
        "question": "Pick a style",
        "options": [{"label": "Clean", "description": "Minimal"}],
    }
    remaining_tool_calls = [
        {
            "fn_name": "ask_user",
            "fn_arguments": json.dumps({
                "question": "Pick an aspect ratio",
                "options": [{"label": "Square", "description": "1:1"}],
            }),
            "tool_call_id": "tool_2",
        },
        {
            "fn_name": "show",
            "fn_arguments": json.dumps({"media_ids": [1]}),
            "tool_call_id": "tool_3",
        },
    ]

    annotated_current, annotated_remaining = _annotate_ask_sequence(current_args, remaining_tool_calls)

    assert annotated_current["question_index"] == 1
    assert annotated_current["question_total"] == 2
    assert annotated_current["question_plan"] == ["Pick a style", "Pick an aspect ratio"]

    next_ask = json.loads(annotated_remaining[0]["fn_arguments"])
    assert next_ask["question_index"] == 2
    assert next_ask["question_total"] == 2
    assert next_ask["question_plan"] == ["Pick a style", "Pick an aspect ratio"]


@pytest.mark.asyncio
async def test_interrupt_execution_marks_in_progress_thinking_as_interrupted(session, test_chat, mock_ws):
    thinking_item = ChatItem(
        chat_id=test_chat.id,
        item_type="assistant_message",
        message_text="",
        item_metadata=json.dumps({"thinking_status": "in_progress"}),
    )
    session.add(thinking_item)
    await session.commit()

    was_active = await interrupt_execution(test_chat, session, mock_ws)

    assert was_active is False

    await session.refresh(thinking_item)
    metadata = json.loads(thinking_item.item_metadata)
    assert metadata == {
        "thinking_status": "failed",
        "thinking_content": "Interrupted by user.",
        "thinking_duration_seconds": 0,
    }

    updated_events = mock_ws.get_broadcasts("chat_item_updated")
    assert updated_events[-1]["chat_id"] == test_chat.id
    assert updated_events[-1]["item"]["id"] == thinking_item.id
    assert updated_events[-1]["item"]["item_metadata"]["thinking_status"] == "failed"

    stopped_events = mock_ws.get_broadcasts("agent_stopped")
    assert stopped_events[-1]["reason"] == "cancelled"


@pytest.mark.asyncio
async def test_interrupt_execution_marks_pending_ask_user_as_interrupted(session, test_chat, mock_ws):
    test_chat.generation_settings = json.dumps({
        "_v2_ask_pending": {"tool_call_id": "tool_123", "turn": 4}
    })
    session.add(ChatItem(
        chat_id=test_chat.id,
        item_type="hitl_request",
        item_metadata=json.dumps({
            "type": "ask_user",
            "prompt": "Which direction?",
            "node_id": "tool_123",
            "tool_call_id": "tool_123",
        }),
    ))
    await session.commit()

    was_active = await interrupt_execution(test_chat, session, mock_ws)

    assert was_active is False

    await session.refresh(test_chat)
    settings = json.loads(test_chat.generation_settings or "{}")
    assert "_v2_ask_pending" not in settings

    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == test_chat.id, ChatItem.item_type == "hitl_response")
        .order_by(ChatItem.created_at.desc())
        .limit(1)
    )
    response_item = result.scalar_one()
    response_data = json.loads(response_item.item_metadata)
    assert response_data == {"answer": "", "interrupted": True}

    created_events = mock_ws.get_broadcasts("chat_item_created")
    assert created_events[-1]["chat_id"] == test_chat.id
    assert created_events[-1]["item"]["item_type"] == "hitl_response"

    stopped_events = mock_ws.get_broadcasts("agent_stopped")
    assert stopped_events[-1]["reason"] == "cancelled"


@pytest.mark.asyncio
async def test_interrupt_execution_broadcasts_denial_for_pending_v2_tool_permission(session, test_chat, mock_ws):
    test_chat.generation_settings = json.dumps({
        "_v2_pending": {"tool_call_id": "tool_456", "turn": 2}
    })
    session.add(ChatItem(
        chat_id=test_chat.id,
        item_type="hitl_request",
        item_metadata=json.dumps({
            "type": "v2_tool_permission",
            "prompt": "Allow Flux Dev?",
            "node_id": "tool_456",
            "tool_call_id": "tool_456",
        }),
    ))
    await session.commit()

    was_active = await interrupt_execution(test_chat, session, mock_ws)

    assert was_active is False

    await session.refresh(test_chat)
    settings = json.loads(test_chat.generation_settings or "{}")
    assert "_v2_pending" not in settings

    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == test_chat.id, ChatItem.item_type == "hitl_response")
        .order_by(ChatItem.created_at.desc())
        .limit(1)
    )
    response_item = result.scalar_one()
    response_data = json.loads(response_item.item_metadata)
    assert response_data == {"approved": False, "scope": "once"}

    created_events = mock_ws.get_broadcasts("chat_item_created")
    assert created_events[-1]["chat_id"] == test_chat.id
    assert created_events[-1]["item"]["item_type"] == "hitl_response"
    assert created_events[-1]["item"]["item_metadata"] == {"approved": False, "scope": "once"}

    stopped_events = mock_ws.get_broadcasts("agent_stopped")
    assert stopped_events[-1]["reason"] == "cancelled"
