"""Grep workspace files — Claude Code compatible."""

import re
from pathlib import Path

from ..tools_registry import tool, ToolParameter
from ._workspace_files import resolve_workspace_path, IMAGE_EXTENSIONS

MAX_RESULTS = 250
MAX_CONTENT_LINES = 500

# Binary-ish extensions to skip
_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
    ".ico", ".pdf", ".zip", ".gz", ".tar", ".7z",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pyc", ".pyo", ".so", ".dylib", ".dll",
    ".stimmalayout",
}


@tool(
    name="grep",
    description="Search file contents in the workspace using regex. Supports content, files_with_matches, and count output modes.",
    parameters=[
        ToolParameter(
            name="pattern",
            type="string",
            description="Regular expression pattern to search for.",
        ),
        ToolParameter(
            name="path",
            type="string",
            description="File or subdirectory within workspace to search. Default: entire workspace.",
            required=False,
        ),
        ToolParameter(
            name="glob",
            type="string",
            description="Glob pattern to filter files (e.g. '*.html', '*.{css,js}').",
            required=False,
        ),
        ToolParameter(
            name="output_mode",
            type="string",
            description="Output mode: 'content' shows matching lines, 'files_with_matches' shows file paths (default), 'count' shows match counts.",
            required=False,
            enum=["content", "files_with_matches", "count"],
        ),
        ToolParameter(
            name="context",
            type="integer",
            description="Number of context lines before and after each match (content mode only).",
            required=False,
        ),
        ToolParameter(
            name="head_limit",
            type="integer",
            description="Limit output to first N entries. Default: 250.",
            required=False,
        ),
    ],
    scope="both",
)
async def grep_files(
    pattern: str | None = None,
    path: str | None = None,
    glob: str | None = None,
    output_mode: str = "files_with_matches",
    context: int = 0,
    head_limit: int = MAX_RESULTS,
    **kwargs,
) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    if not workspace_dir:
        return "Error: No workspace directory available"
    if not pattern:
        return "Error: pattern is required."

    workspace = Path(workspace_dir).resolve()

    # Determine search root
    if path:
        resolved, err = resolve_workspace_path(workspace_dir, path)
        if err:
            return err
        search_root = resolved
    else:
        search_root = workspace

    # Compile regex
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    # Collect files to search
    if search_root.is_file():
        files = [search_root]
    else:
        if glob:
            files = sorted(search_root.rglob(glob))
        else:
            files = sorted(search_root.rglob("*"))
        files = [f for f in files if f.is_file() and f.suffix.lower() not in _BINARY_EXTENSIONS]

    head_limit = min(head_limit, 1000)

    if output_mode == "files_with_matches":
        return _files_with_matches(files, regex, workspace, head_limit)
    elif output_mode == "count":
        return _count_mode(files, regex, workspace, head_limit)
    else:
        return _content_mode(files, regex, workspace, context, head_limit)


def _rel(filepath: Path, workspace: Path) -> str:
    try:
        return str(filepath.relative_to(workspace))
    except ValueError:
        return str(filepath)


def _read_text_safe(filepath: Path) -> str | None:
    try:
        return filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _files_with_matches(files: list[Path], regex, workspace: Path, limit: int) -> str:
    matches = []
    for f in files:
        if len(matches) >= limit:
            break
        content = _read_text_safe(f)
        if content and regex.search(content):
            matches.append(_rel(f, workspace))

    if not matches:
        return "No files matched."

    truncated = len(matches) >= limit
    result = f"Found {len(matches)} file{'s' if len(matches) != 1 else ''}:\n"
    result += "\n".join(matches)
    if truncated:
        result += f"\n... (truncated at {limit} results)"
    return result


def _count_mode(files: list[Path], regex, workspace: Path, limit: int) -> str:
    counts = []
    total_matches = 0
    for f in files:
        if len(counts) >= limit:
            break
        content = _read_text_safe(f)
        if not content:
            continue
        n = len(regex.findall(content))
        if n > 0:
            counts.append((_rel(f, workspace), n))
            total_matches += n

    if not counts:
        return "No matches found."

    lines = [f"{path}:{count}" for path, count in counts]
    result = "\n".join(lines)
    result += f"\n\n{total_matches} total match{'es' if total_matches != 1 else ''} across {len(counts)} file{'s' if len(counts) != 1 else ''}"
    return result


def _content_mode(files: list[Path], regex, workspace: Path, ctx: int, limit: int) -> str:
    output_lines = []
    for f in files:
        if len(output_lines) >= limit:
            break
        content = _read_text_safe(f)
        if not content:
            continue
        lines = content.split("\n")
        rel = _rel(f, workspace)
        file_matches = []

        for i, line in enumerate(lines):
            if regex.search(line):
                file_matches.append(i)

        if not file_matches:
            continue

        # Collect lines with context, deduplicating overlapping ranges
        shown = set()
        for match_idx in file_matches:
            start = max(0, match_idx - ctx)
            end = min(len(lines) - 1, match_idx + ctx)
            for j in range(start, end + 1):
                shown.add(j)

        prev_j = -2
        for j in sorted(shown):
            if len(output_lines) >= limit:
                break
            if j > prev_j + 1 and prev_j >= 0:
                output_lines.append("--")
            output_lines.append(f"{rel}:{j + 1}:{lines[j]}")
            prev_j = j

    if not output_lines:
        return "No matches found."

    truncated = len(output_lines) >= limit
    result = "\n".join(output_lines)
    if truncated:
        result += f"\n... (truncated at {limit} lines)"
    return result
