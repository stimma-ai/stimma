# Agent system - visual media copilot
from .context import WorkingContext, MediaRef, ToolOutput
from .hitl import HumanActionRequest, HumanActionRequired


async def run_agent(chat, user_message, session, ws_manager, selected_media_ids=None, max_turns=None, force_plan=False):
    """Run the agent (v2 agentic loop).

    ``max_turns=None`` lets the v2 loop derive the cap from the chat
    (``_max_turns_for_chat``: 50 for normal chats, 100 for flow chats).
    A hardcoded default here shadows that intent — passing any value makes
    the v2 ``if max_turns is None`` fall-through dead — so leave it None.
    """
    from .v2 import run_agent as _v2_run_agent
    await _v2_run_agent(chat, user_message, session, ws_manager, selected_media_ids, max_turns, force_plan)


async def abort_plan(chat, session, ws_manager):
    """Interrupt agent execution."""
    from .v2 import interrupt_execution as _v2_interrupt_execution
    await _v2_interrupt_execution(chat, session, ws_manager)


async def resume_agent_after_hitl(chat, response_data, session, ws_manager):
    """Resume the agent after a human-in-the-loop action."""
    import json
    from sqlalchemy import select
    from database import ChatItem

    # Peek at the pending HITL action type to decide which handler to use
    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat.id)
        .where(ChatItem.item_type == "hitl_request")
        .order_by(ChatItem.created_at.desc())
        .limit(1)
    )
    hitl_item = result.scalar_one_or_none()

    if hitl_item and hitl_item.item_metadata:
        try:
            action_data = json.loads(hitl_item.item_metadata) if isinstance(hitl_item.item_metadata, str) else hitl_item.item_metadata
            action_type = action_data.get("type")
            if action_type == "v2_tool_permission":
                from .v2.service import resume_after_hitl
                await resume_after_hitl(chat, response_data, session, ws_manager)
                return
            elif action_type == "ask_user":
                from .v2.service import resume_after_ask_user
                await resume_after_ask_user(chat, response_data, session, ws_manager)
                return
        except (json.JSONDecodeError, KeyError):
            pass
