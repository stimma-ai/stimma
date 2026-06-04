"""Read a file from the agent workspace."""

import base64
import mimetypes

from ..tools_registry import tool, ToolParameter
from ._workspace_files import resolve_workspace_path, format_numbered_lines, IMAGE_EXTENSIONS


@tool(
    name="read_file",
    description="Read the contents of a workspace file. Returns text with line numbers for text files, or a description for image files.",
    parameters=[
        ToolParameter(
            name="file_path",
            type="string",
            description="Filename or relative path within the workspace.",
        ),
        ToolParameter(
            name="offset",
            type="integer",
            description="Starting line number (1-based). Default: 1.",
            required=False,
        ),
        ToolParameter(
            name="limit",
            type="integer",
            description="Maximum number of lines to return. Default: 500.",
            required=False,
        ),
    ],
    scope="both",
)
async def read_file(file_path: str | None = None, offset: int = 1, limit: int = 500, **kwargs) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    if not workspace_dir:
        return "Error: No workspace directory available"
    if not file_path:
        return "Error: file_path is required."

    resolved, err = resolve_workspace_path(workspace_dir, file_path)
    if err:
        return err

    if not resolved.exists():
        return f"Error: File not found: {file_path}"

    if not resolved.is_file():
        return f"Error: Not a file: {file_path}"

    # Image files — return description (base64 handling would need multimodal message support)
    if resolved.suffix.lower() in IMAGE_EXTENSIONS:
        size = resolved.stat().st_size
        mime = mimetypes.guess_type(str(resolved))[0] or "image/png"
        return f"[Image file: {file_path} ({size:,} bytes, {mime})]"

    # Text files
    offset = max(1, offset)
    limit = max(1, min(2000, limit))

    try:
        content = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: File appears to be binary, not a text file: {file_path}"

    formatted, num_lines, total_lines = format_numbered_lines(content, offset, limit)

    if not formatted:
        return f"{file_path} is empty (0 lines)"

    start_line = max(1, offset)
    end_line = start_line + num_lines - 1
    header = f"{file_path} ({total_lines} lines, showing {start_line}-{end_line}):"

    result = f"{header}\n{formatted}"

    if end_line < total_lines:
        result += f"\n... (showing lines {start_line}-{end_line} of {total_lines}. Use offset={end_line + 1} to continue.)"

    return result
