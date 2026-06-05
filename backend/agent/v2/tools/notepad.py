"""Agent notepad — persistent task list and scratchpad, injected into system prompt."""

import json
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter

from core.logging import get_logger

log = get_logger(__name__)

TASKS_FILE = "_tasks.json"
SCRATCHPAD_FILE = "_scratchpad.md"
NOTEPAD_ITEM_FILE = "_notepad_item_id.txt"


def _tasks_path(workspace_dir: str) -> Path:
    return Path(workspace_dir) / TASKS_FILE


def _scratchpad_path(workspace_dir: str) -> Path:
    return Path(workspace_dir) / SCRATCHPAD_FILE


def _notepad_item_path(workspace_dir: str) -> Path:
    return Path(workspace_dir) / NOTEPAD_ITEM_FILE


def _read_tasks(workspace_dir: str) -> dict:
    p = _tasks_path(workspace_dir)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"tasks": [], "next_id": 1}


def _write_tasks(workspace_dir: str, data: dict) -> None:
    _tasks_path(workspace_dir).write_text(json.dumps(data))


def _read_scratchpad(workspace_dir: str) -> str:
    p = _scratchpad_path(workspace_dir)
    if p.exists():
        try:
            return p.read_text()
        except OSError:
            pass
    return ""


def _write_scratchpad(workspace_dir: str, content: str) -> None:
    _scratchpad_path(workspace_dir).write_text(content)


def _summary(tasks_data: dict, scratchpad: str) -> str:
    tasks = tasks_data.get("tasks", [])
    if not tasks and not scratchpad:
        return "Notepad is empty."
    parts = []
    if tasks:
        done = sum(1 for t in tasks if t["status"] == "done")
        in_progress = sum(1 for t in tasks if t["status"] == "in_progress")
        total = len(tasks)
        parts.append(f"Tasks: {done}/{total} done" + (f", {in_progress} in progress" if in_progress else ""))
    if scratchpad:
        lines = scratchpad.strip().splitlines()
        parts.append(f"Scratchpad: {len(lines)} line{'s' if len(lines) != 1 else ''}")
    return " | ".join(parts)


def format_notepad_for_prompt(workspace_dir: str) -> str:
    """Format notepad state for system prompt injection. Returns empty string if notepad is unused."""
    tasks_data = _read_tasks(workspace_dir)
    scratchpad = _read_scratchpad(workspace_dir)
    tasks = tasks_data.get("tasks", [])

    if not tasks and not scratchpad:
        return "\n## Your Notepad\n(empty)"

    lines = ["\n## Your Notepad\n"]

    if tasks:
        lines.append("### Tasks")
        status_markers = {"done": "[x]", "in_progress": "[>]", "pending": "[ ]", "failed": "[!]"}
        for t in tasks:
            marker = status_markers.get(t["status"], "[ ]")
            lines.append(f"{t['id']}. {marker} {t['text']}")
        lines.append("")

    if scratchpad:
        # Cap at ~2000 chars
        text = scratchpad
        if len(text) > 2000:
            text = text[:2000] + "\n... (truncated)"
        lines.append("### Scratchpad")
        lines.append(text)

    return "\n".join(lines)


async def _sync_chat_item(
    workspace_dir: str,
    chat_id: int,
    session: AsyncSession,
    tasks_data: dict,
    scratchpad: str,
) -> None:
    """Create or update the persistent notepad ChatItem."""
    from utils.websocket import ws_manager
    from database import ChatItem

    item_path = _notepad_item_path(workspace_dir)
    existing_id = None
    if item_path.exists():
        try:
            existing_id = int(item_path.read_text().strip())
        except (ValueError, OSError):
            pass

    metadata = {
        "kind": "v2_notepad",
        "tasks": tasks_data.get("tasks", []),
        "scratchpad": scratchpad,
    }

    if existing_id:
        # Try to update existing item
        from sqlalchemy import select
        result = await session.execute(
            select(ChatItem).where(ChatItem.id == existing_id, ChatItem.chat_id == chat_id)
        )
        item = result.scalar_one_or_none()
        if item:
            item.item_metadata = json.dumps(metadata)
            await session.commit()
            await ws_manager.broadcast("chat_item_updated", {
                "chat_id": chat_id,
                "item": item.to_dict(),
            })
            return

    # Create new item
    item = ChatItem(
        chat_id=chat_id,
        item_type="system",
        item_metadata=json.dumps(metadata),
    )
    session.add(item)
    await session.commit()
    item_path.write_text(str(item.id))
    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": item.to_dict(),
    })


@tool(
    name="notepad",
    description="Persistent task list and scratchpad. Use to track multi-step work and jot down notes. State is always visible in your system prompt.",
    parameters=[
        ToolParameter(
            name="action",
            type="string",
            description="Action to perform",
            required=True,
            enum=["set_tasks", "update_task", "add_tasks", "write_scratchpad", "append_scratchpad", "read"],
        ),
        ToolParameter(
            name="tasks",
            type="array",
            description="Task descriptions (for set_tasks/add_tasks)",
            required=False,
            items={"type": "string"},
        ),
        ToolParameter(
            name="task_id",
            type="integer",
            description="Task ID to update (for update_task)",
            required=False,
        ),
        ToolParameter(
            name="status",
            type="string",
            description="New status (for update_task)",
            required=False,
            enum=["pending", "in_progress", "done", "failed"],
        ),
        ToolParameter(
            name="content",
            type="string",
            description="Scratchpad content (for write_scratchpad/append_scratchpad)",
            required=False,
        ),
    ],
)
async def notepad(
    action: str,
    tasks: list[str] | None = None,
    task_id: int | None = None,
    status: str | None = None,
    content: str | None = None,
    **kwargs,
) -> str:
    session: AsyncSession = kwargs.get("session")
    chat_id: int = kwargs.get("chat_id")
    workspace_dir: str = kwargs.get("workspace_dir")

    if not workspace_dir:
        return "Error: No workspace directory"

    tasks_data = _read_tasks(workspace_dir)
    scratchpad = _read_scratchpad(workspace_dir)

    if action == "set_tasks":
        if not tasks:
            return "Error: tasks parameter required for set_tasks"
        new_tasks = []
        next_id = 1
        for text in tasks:
            new_tasks.append({"id": next_id, "text": text, "status": "pending"})
            next_id += 1
        tasks_data = {"tasks": new_tasks, "next_id": next_id}
        _write_tasks(workspace_dir, tasks_data)

    elif action == "add_tasks":
        if not tasks:
            return "Error: tasks parameter required for add_tasks"
        next_id = tasks_data.get("next_id", 1)
        for text in tasks:
            tasks_data["tasks"].append({"id": next_id, "text": text, "status": "pending"})
            next_id += 1
        tasks_data["next_id"] = next_id
        _write_tasks(workspace_dir, tasks_data)

    elif action == "update_task":
        if task_id is None or not status:
            return "Error: task_id and status required for update_task"
        found = False
        for t in tasks_data.get("tasks", []):
            if t["id"] == task_id:
                t["status"] = status
                found = True
                break
        if not found:
            return f"Error: Task {task_id} not found"
        _write_tasks(workspace_dir, tasks_data)

    elif action == "write_scratchpad":
        if content is None:
            return "Error: content parameter required for write_scratchpad"
        scratchpad = content
        _write_scratchpad(workspace_dir, scratchpad)

    elif action == "append_scratchpad":
        if content is None:
            return "Error: content parameter required for append_scratchpad"
        if scratchpad:
            scratchpad += "\n" + content
        else:
            scratchpad = content
        _write_scratchpad(workspace_dir, scratchpad)

    elif action == "read":
        pass  # Just return current state

    else:
        return f"Error: Unknown action '{action}'"

    # Sync the ChatItem for frontend display
    if session and chat_id:
        await _sync_chat_item(workspace_dir, chat_id, session, tasks_data, scratchpad)

    return _summary(tasks_data, scratchpad)
