"""Glob workspace files — Claude Code compatible."""

import time
from pathlib import Path

from ..tools_registry import tool, ToolParameter
from ._workspace_files import SKILLS_MOUNT, resolve_workspace_path, workspace_relative

MAX_RESULTS = 1000


@tool(
    name="glob",
    description="Find files in the workspace matching a glob pattern. Returns matching filenames; directories are listed with a trailing '/'.",
    parameters=[
        ToolParameter(
            name="pattern",
            type="string",
            description="Glob pattern to match files (e.g. '*.html', '**/*.css', 'images/*.png').",
        ),
        ToolParameter(
            name="path",
            type="string",
            description="Subdirectory within workspace to search. Default: workspace root.",
            required=False,
        ),
    ],
    scope="both",
)
async def glob_files(pattern: str | None = None, path: str | None = None, **kwargs) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    if not workspace_dir:
        return "Error: No workspace directory available"
    if not pattern:
        return "Error: pattern is required."

    workspace = Path(workspace_dir).resolve()

    if path:
        resolved, err = resolve_workspace_path(workspace_dir, path)
        if err:
            return err
        if not resolved.is_dir():
            return f"Error: Not a directory: {path}"
        search_root = resolved
    else:
        search_root = workspace

    # Resolve a literal mount prefix before searching, including on platforms
    # where the workspace symlink could not be created.
    search_pattern = pattern.replace("\\", "/")
    parts = [part for part in search_pattern.split("/") if part not in ("", ".")]
    if ".." in parts or search_pattern.startswith("/"):
        return "Error: pattern must be relative and must not contain '..'"
    if search_root == workspace and parts and parts[0] == SKILLS_MOUNT:
        search_root, err = resolve_workspace_path(workspace_dir, SKILLS_MOUNT)
        if err:
            return err
        search_pattern = "/".join(parts[1:])

    start = time.monotonic()
    matches = sorted(search_root.glob(search_pattern)) if search_pattern else [search_root]
    duration_ms = round((time.monotonic() - start) * 1000, 1)

    # Directories are included (with a trailing '/') so discovery patterns like
    # '.stimma' or '.stimma/tools/*' — whose matches are all directories — don't
    # come back as "no matches" and send the model hunting outside the workspace.
    filenames = []
    for m in matches:
        rel = workspace_relative(workspace, m)
        if rel is None:
            continue
        if m.is_dir():
            filenames.append(f"{rel}/")
        elif m.is_file():
            filenames.append(str(rel))

    truncated = len(filenames) > MAX_RESULTS
    if truncated:
        filenames = filenames[:MAX_RESULTS]

    # Stash structured data
    metadata_out = kwargs.get("_metadata_out")
    if metadata_out is not None:
        metadata_out["glob_data"] = {
            "durationMs": duration_ms,
            "numFiles": len(filenames),
            "filenames": filenames,
            "truncated": truncated,
        }

    # Model-visible result
    if not filenames:
        return f"No files or directories matching '{pattern}'"

    result = "\n".join(filenames)
    if truncated:
        result += f"\n... (truncated at {MAX_RESULTS} results)"
    return result
