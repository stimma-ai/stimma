"""Write a file to the agent workspace."""

from pathlib import Path

from ..tools_registry import tool, ToolParameter
from ._workspace_files import (
    readonly_workspace_error,
    MAX_FILE_SIZE,
    maybe_sync_flow_program,
    resolve_workspace_path,
)
from .edit_file import _build_structured_patch


@tool(
    name="write_file",
    description="Write content to a file in the workspace. Creates the file if it doesn't exist, overwrites if it does.",
    parameters=[
        ToolParameter(
            name="file_path",
            type="string",
            description="Filename or relative path within the workspace (e.g. 'layout.html', 'styles/main.css').",
        ),
        ToolParameter(
            name="content",
            type="string",
            description="The full file content to write.",
        ),
    ],
    scope="both",
)
async def write_file(file_path: str | None = None, content: str | None = None, **kwargs) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    if not workspace_dir:
        return "Error: No workspace directory available"
    if not file_path:
        return "Error: file_path is required."
    if content is None:
        return "Error: content is required. Pass the full file content as a string."

    ro_err = readonly_workspace_error(file_path)
    if ro_err:
        return ro_err

    resolved, err = resolve_workspace_path(workspace_dir, file_path)
    if err:
        return err

    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        return f"Error: Content exceeds maximum file size ({MAX_FILE_SIZE // 1024}KB)"

    # Determine create vs update
    is_update = resolved.exists()
    original_file = None
    if is_update:
        try:
            original_file = resolved.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            original_file = None

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")

    # Build structured patch
    if is_update and original_file is not None:
        structured_patch = _build_structured_patch(original_file, content)
    else:
        structured_patch = []  # create => empty patch per spec

    # Stash structured data (WriteOutput)
    metadata_out = kwargs.get("_metadata_out")
    if metadata_out is not None:
        metadata_out["write_data"] = {
            "type": "update" if is_update else "create",
            "filePath": file_path,
            "content": content,
            "structuredPatch": structured_patch,
            "originalFile": original_file,
        }

    # If this targets a flow chat's program.py, rebuild its compiled graph
    # so the frontend phase tree reflects the edit immediately AND the agent
    # sees build errors in the tool result (otherwise the agent assumes a
    # successful file write means the program is valid).
    rebuild_note = await maybe_sync_flow_program(
        kwargs.get("session"), kwargs.get("chat_id"), file_path
    )

    # Model-visible result. When the flow graph build failed, lead with the
    # failure so the agent doesn't interpret "updated successfully" as meaning
    # the program is valid.
    if rebuild_note and "FAILED" in rebuild_note:
        # Flag this for the loop — if the LLM narrates "let me fix it" and
        # ends its turn without calling a tool, the loop nudges it once.
        cont_out = kwargs.get("_needs_continuation_out")
        if isinstance(cont_out, list):
            cont_out.append(True)
        return (
            f"{file_path} was written to disk but the flow graph FAILED to build. "
            f"Fix the program before doing anything else.\n\n{rebuild_note}"
        )
    if is_update:
        msg = f"The file {file_path} has been updated successfully."
    else:
        msg = f"File created successfully at: {file_path}"
    if rebuild_note:
        msg = f"{msg}\n\n{rebuild_note}"
    return msg
