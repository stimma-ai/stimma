"""Share live workspace references without creating library assets."""

import asyncio
import json
from fastapi import HTTPException
from ..tools_registry import tool, ToolParameter


@tool(
    name="share_files",
    description="Share files with the user as clickable live workspace references. Paths are relative to the chat or project workspace. Files are not saved to the library.",
    parameters=[
        ToolParameter(
            name="files",
            type="array",
            description="Files to share, with optional captions and workspace root.",
            required=True,
            items={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "root": {"type": "string", "enum": ["chat", "project"]},
                    "caption": {"type": "string"},
                },
                "required": ["path"],
            },
        ),
    ],
    scope="agent",
)
async def share_files(files: list[dict], **kwargs) -> str:
    from database import ChatItem
    from routes.workspace_files import file_context
    from workspace_files import describe_file
    from utils.websocket import ws_manager

    session, chat_id = kwargs.get("session"), kwargs.get("chat_id")
    if not session or not chat_id:
        return "Error: No chat session available"
    if not files or len(files) > 100:
        return "Error: Share between 1 and 100 files"
    rows = []
    for item in files:
        root, path = item.get("root", "chat"), item.get("path", "")
        if root not in {"chat", "project"}:
            return "Error: root must be chat or project"
        try:
            _, _, file = await file_context(session, chat_id, root, path)
            row = await asyncio.to_thread(describe_file, chat_id, root, path, file)
            rows.append({**row, "caption": item.get("caption")})
        except HTTPException as exc:
            return f"Error: {exc.detail}"
    item = ChatItem(
        chat_id=chat_id,
        item_type="file_display",
        item_metadata=json.dumps({"files": rows}),
    )
    session.add(item)
    await session.commit()
    await ws_manager.broadcast(
        "chat_item_created", {"chat_id": chat_id, "item": item.to_dict()}
    )
    return json.dumps({"files": rows})
