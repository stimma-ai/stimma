"""Edit a workspace file via exact string replacement — Claude Code compatible."""

import difflib
import json

from ..tools_registry import tool, ToolParameter
from ._workspace_files import maybe_sync_flow_program, readonly_workspace_error, resolve_workspace_path


@tool(
    name="edit_file",
    description="Edit a file by replacing an exact string match. The old_string must match precisely including whitespace and indentation. For creating new files, use write_file instead.",
    parameters=[
        ToolParameter(
            name="file_path",
            type="string",
            description="Filename or relative path within the workspace.",
        ),
        ToolParameter(
            name="old_string",
            type="string",
            description="The exact text to find and replace. Must match the file content precisely including whitespace.",
        ),
        ToolParameter(
            name="new_string",
            type="string",
            description="The replacement text.",
        ),
        ToolParameter(
            name="replace_all",
            type="boolean",
            description="If true, replace all occurrences. Default: replace only the first.",
            required=False,
        ),
    ],
    scope="both",
)
async def edit_file(
    file_path: str | None = None,
    old_string: str | None = None,
    new_string: str | None = None,
    replace_all: bool = False,
    **kwargs,
) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    if not workspace_dir:
        return "Error: No workspace directory available"
    if not file_path:
        return "Error: file_path is required."
    if old_string is None:
        return "Error: old_string is required."
    if new_string is None:
        return "Error: new_string is required."

    ro_err = readonly_workspace_error(file_path)
    if ro_err:
        return ro_err

    resolved, err = resolve_workspace_path(workspace_dir, file_path)
    if err:
        return err

    if not resolved.exists():
        return f"Error: File not found: {file_path}. Use write_file to create new files."

    try:
        original = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: File appears to be binary, not a text file: {file_path}"

    if old_string == new_string:
        return "Error: old_string and new_string are identical — nothing to change."

    # Count occurrences
    count = original.count(old_string)

    if count == 0:
        return _not_found_error(file_path, old_string, original)

    # Perform replacement
    if replace_all:
        new_content = original.replace(old_string, new_string)
        replaced_count = count
    else:
        new_content = original.replace(old_string, new_string, 1)
        replaced_count = 1

    resolved.write_text(new_content, encoding="utf-8")

    # Build structured patch for metadata
    structured_patch = _build_structured_patch(original, new_content)

    # Stash structured data via kwargs (same pattern as run_code's _llm_usage_out)
    metadata_out = kwargs.get("_metadata_out")
    if metadata_out is not None:
        metadata_out["edit_data"] = {
            "filePath": file_path,
            "oldString": old_string,
            "newString": new_string,
            "replaceAll": replace_all,
            "structuredPatch": structured_patch,
            "userModified": False,
        }

    # If this targets a flow chat's program.py, rebuild its compiled graph
    # so the frontend phase tree reflects the edit immediately AND the agent
    # sees build errors in the tool result.
    rebuild_note = await maybe_sync_flow_program(
        kwargs.get("session"), kwargs.get("chat_id"), file_path
    )

    # Model-visible result. When the flow graph build failed, lead with the
    # failure so the agent doesn't interpret the edit success as meaning the
    # program is valid.
    new_lines = new_content.count("\n") + (1 if new_content and not new_content.endswith("\n") else 0)
    if rebuild_note and "FAILED" in rebuild_note:
        cont_out = kwargs.get("_needs_continuation_out")
        if isinstance(cont_out, list):
            cont_out.append(True)
        return (
            f"{file_path} was edited on disk but the flow graph FAILED to build. "
            f"Fix the program before doing anything else.\n\n{rebuild_note}"
        )
    msg = f"Edited {file_path}: replaced {replaced_count} occurrence{'s' if replaced_count > 1 else ''}. File is now {new_lines} lines."
    if count > 1 and not replace_all:
        msg += f" (Note: {count} total occurrences found; only replaced the first. Use replace_all=true to replace all.)"
    if rebuild_note:
        msg = f"{msg}\n\n{rebuild_note}"
    return msg


def _not_found_error(file_path: str, old_string: str, content: str) -> str:
    """Build a helpful error when old_string is not found."""
    lines = content.split("\n")
    total = len(lines)
    parts = [f"Error: old_string not found in {file_path} ({total} lines)."]

    # Try fuzzy match to suggest what the agent might have meant
    old_lines = old_string.split("\n")
    if len(old_lines) == 1 and len(old_string) < 200:
        # Single-line search — find closest matching line
        matches = difflib.get_close_matches(old_string.strip(), [l.strip() for l in lines], n=3, cutoff=0.5)
        if matches:
            parts.append("Similar lines found:")
            for m in matches:
                # Find line number
                for i, l in enumerate(lines):
                    if l.strip() == m:
                        parts.append(f"  Line {i + 1}: {m}")
                        break
    else:
        # Multi-line — show first/last few lines of file for orientation
        preview_lines = min(15, total)
        parts.append(f"First {preview_lines} lines of {file_path}:")
        for i in range(preview_lines):
            parts.append(f"  {i + 1}: {lines[i]}")
        if total > preview_lines:
            parts.append(f"  ... ({total - preview_lines} more lines)")

    return "\n".join(parts)


def _build_structured_patch(original: str, modified: str) -> list[dict]:
    """Build unified-diff structured patch hunks."""
    old_lines = original.splitlines(keepends=True)
    new_lines = modified.splitlines(keepends=True)

    hunks = []
    for group in difflib.SequenceMatcher(None, old_lines, new_lines).get_grouped_opcodes(3):
        hunk_lines = []
        old_start = group[0][1] + 1  # 1-based
        old_count = 0
        new_start = group[0][3] + 1
        new_count = 0

        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for line in old_lines[i1:i2]:
                    # Convert tabs for display
                    hunk_lines.append(" " + line.rstrip("\n\r").expandtabs(4))
                old_count += i2 - i1
                new_count += j2 - j1
            elif tag == "replace":
                for line in old_lines[i1:i2]:
                    hunk_lines.append("-" + line.rstrip("\n\r").expandtabs(4))
                for line in new_lines[j1:j2]:
                    hunk_lines.append("+" + line.rstrip("\n\r").expandtabs(4))
                old_count += i2 - i1
                new_count += j2 - j1
            elif tag == "delete":
                for line in old_lines[i1:i2]:
                    hunk_lines.append("-" + line.rstrip("\n\r").expandtabs(4))
                old_count += i2 - i1
            elif tag == "insert":
                for line in new_lines[j1:j2]:
                    hunk_lines.append("+" + line.rstrip("\n\r").expandtabs(4))
                new_count += j2 - j1

        hunks.append({
            "oldStart": old_start,
            "oldLines": old_count,
            "newStart": new_start,
            "newLines": new_count,
            "lines": hunk_lines,
        })

    return hunks
