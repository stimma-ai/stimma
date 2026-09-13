"""Shared helpers for workspace file tools — sandbox validation and formatting."""

from pathlib import Path

from core.logging import get_logger

MAX_FILE_SIZE = 1_048_576  # 1 MB

_log = get_logger(__name__)

# Extensions recognised as images (for read_file image handling)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

# The .stimma/ tree is an auto-generated, read-only projection of the tool
# catalog. It is browsable (read/glob/grep) but must not be edited — the runtime
# owns it and overwrites it.
READONLY_PREFIX = ".stimma/"
SKILLS_MOUNT = "skills"


def readonly_workspace_error(file_path: str, workspace_dir: str | None = None) -> str | None:
    """Return an error if file_path targets a read-only tree, else None.

    Read-only trees: the generated ``.stimma/`` tool catalog, and any
    marketplace-installed stimpack under ``skills/`` (a marketplace update
    would overwrite edits; the agent forks instead).
    """
    normalized = (file_path or "").replace("\\", "/")
    normalized = "/".join(part for part in normalized.split("/") if part not in ("", "."))
    if workspace_dir is not None:
        resolved, err = resolve_workspace_path(workspace_dir, file_path)
        if err:
            return err
        normalized = workspace_relative(Path(workspace_dir).resolve(), resolved) or normalized
    if normalized == ".stimma" or normalized.startswith(READONLY_PREFIX):
        return (
            "Error: .stimma/ is a generated, read-only view of available tools — "
            "it cannot be edited. Browse it with read_file/glob/grep; it refreshes "
            "automatically when the tool catalog changes."
        )
    parts = normalized.split("/")
    if len(parts) >= 2 and parts[0] == SKILLS_MOUNT and parts[1]:
        try:
            from ..stimpacks import marketplace_pack_dir_names
            marketplace_dirs = marketplace_pack_dir_names()
        except Exception as e:  # pragma: no cover - defensive
            _log.debug(f"marketplace pack lookup failed: {e}")
            marketplace_dirs = set()
        if parts[1] in marketplace_dirs:
            return (
                f"Error: {SKILLS_MOUNT}/{parts[1]}/ is a marketplace-installed stimpack and is read-only — "
                "a marketplace update would overwrite edits. Fork the skill instead: copy its folder to "
                f"{SKILLS_MOUNT}/<slug>/ (keep the same `name:` so your copy takes precedence over the original) "
                "and edit the copy."
            )
    return None


# The profile's stimpacks directory is mounted into every workspace as
# ``skills/`` so the agent develops skills with its ordinary file tools
# (read/write/edit/glob/grep/bash) instead of a bespoke editing API. The mount
# is a symlink where the platform allows it; the path resolver also maps the
# ``skills/`` prefix directly so the file tools work even without the link.


def skills_mount_target() -> Path | None:
    """The real directory ``skills/`` maps to (the current profile's stimpacks dir)."""
    try:
        from ..stimpacks import get_user_stimpacks_dir
        return get_user_stimpacks_dir().resolve()
    except Exception as e:  # pragma: no cover - defensive (no profile in some tests)
        _log.debug(f"skills mount target unavailable: {e}")
        return None


def ensure_skills_mount(workspace_dir: str | Path) -> None:
    """Create or refresh the ``skills/`` symlink in a workspace. Best-effort."""
    target = skills_mount_target()
    if target is None:
        return
    link = Path(workspace_dir) / SKILLS_MOUNT
    try:
        if link.is_symlink():
            if link.resolve() == target:
                return
            link.unlink()
        elif link.exists():
            # A real file/dir the agent or user created with that name; leave it.
            _log.warning(f"workspace has a non-symlink '{SKILLS_MOUNT}' entry; skills mount skipped")
            return
        link.symlink_to(target, target_is_directory=True)
    except OSError as e:
        # Windows without symlink privilege, read-only workspace, etc. The
        # resolver still maps the prefix, so file tools keep working.
        _log.info(f"could not create skills mount in workspace: {e}")


def _is_within(path: Path, root: Path) -> bool:
    return path.is_relative_to(root)


def resolve_workspace_path(workspace_dir: str, file_path: str) -> tuple[Path, str | None]:
    """Resolve a relative file_path within workspace_dir.

    ``skills/...`` resolves into the profile's stimpacks directory (see
    ``SKILLS_MOUNT``), whether or not the workspace symlink exists.

    Returns (resolved_path, error_string_or_None).
    """
    if not file_path:
        return Path(), "Error: file_path is required"
    if file_path.startswith("/"):
        return Path(), "Error: file_path must be relative to workspace, not absolute"
    # Reject obvious traversal before resolution
    normalized = file_path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if ".." in parts:
        return Path(), "Error: file_path must not contain '..'"

    workspace = Path(workspace_dir).resolve()
    skills_root = skills_mount_target()
    if parts and parts[0] == SKILLS_MOUNT and skills_root is not None and not (workspace / SKILLS_MOUNT).is_dir():
        resolved = skills_root.joinpath(*parts[1:]).resolve()
    else:
        resolved = (workspace / normalized).resolve()
    if _is_within(resolved, workspace):
        return resolved, None
    if skills_root is not None and _is_within(resolved, skills_root):
        return resolved, None
    return Path(), "Error: file_path escapes workspace directory"


def workspace_relative(workspace: Path, path: Path) -> str | None:
    """Display form of a resolved path: workspace-relative, with the skills
    mount shown as ``skills/...``. None if the path is outside both."""
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        pass
    skills_root = skills_mount_target()
    if skills_root is not None:
        try:
            return f"{SKILLS_MOUNT}/{path.relative_to(skills_root).as_posix()}".rstrip("/")
        except ValueError:
            pass
    return None


async def maybe_sync_flow_program(session, chat_id: int | None, file_path: str) -> str | None:
    """Trigger a compiled-graph rebuild if this write targeted a flow's program.py.

    Flow chats use the flow's on-disk directory as their workspace, so
    write_file/edit_file can update program.py directly. But the frontend's
    phase tree reads from the compiled state.db, which is only populated at
    graph-build time (Start / resume). Without this hook, the agent writes
    the program and the tree stays empty until the user hits Start, which
    produced the "I created a flow — but the page is blank" UX bug.

    Returns a short agent-visible message describing the rebuild outcome
    ("graph built: N equations" or "graph build FAILED: ...") so the agent
    can loop on real DSL errors instead of assuming the write succeeded just
    because the file was saved. Returns None when the hook didn't apply
    (non-flow chat or non-program.py path).

    Infrastructure errors (DB down, import failures) are logged and swallowed
    — the file already landed on disk, and a broken rebuild shouldn't be
    reported to the model as a write failure.
    """
    if chat_id is None:
        return None

    path = Path(file_path)
    if path.name != "program.py" or str(path.parent) not in (".", ""):
        return None

    try:
        from sqlalchemy import select

        from database import Chat

        result = await session.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()
        if chat is None or chat.flow_id is None:
            return None

        import flow_lifecycle

        load_error = await flow_lifecycle.apply_program_edit(
            session, chat.flow_id, auto_start=True,
        )
        if load_error is None:
            return "Graph built successfully — phase tree refreshed."
        # Compact, agent-friendly formatting.
        lines = [f"Graph build FAILED ({load_error.get('category', 'error')}):"]
        lines.append(load_error.get("message", "unknown error"))
        suggestion = load_error.get("suggestion")
        if suggestion:
            lines.append(f"Hint: {suggestion}")
        return "\n".join(lines)
    except Exception:
        _log.exception("failed to sync flow program after workspace edit")
        return None


def format_numbered_lines(content: str, offset: int = 1, limit: int | None = None) -> tuple[str, int, int]:
    """Format content with line numbers like cat -n.

    Returns (formatted_string, num_lines_returned, total_lines).
    """
    lines = content.split("\n")
    # Remove trailing empty line from final newline
    if lines and lines[-1] == "":
        lines = lines[:-1]
    total_lines = len(lines)

    start_idx = max(0, offset - 1)  # offset is 1-based
    if limit is not None:
        end_idx = min(start_idx + limit, total_lines)
    else:
        end_idx = total_lines

    selected = lines[start_idx:end_idx]
    if not selected:
        return "", 0, total_lines

    # Dynamic width for line numbers
    max_num = start_idx + len(selected)
    width = len(str(max_num))

    numbered = []
    for i, line in enumerate(selected):
        line_num = start_idx + i + 1
        numbered.append(f"{line_num:>{width}}\t{line}")

    return "\n".join(numbered), len(selected), total_lines
