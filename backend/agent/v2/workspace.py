"""Session workspace directory management."""

from pathlib import Path
import shutil

from app_dirs import get_cache_dir, get_data_dir
from project_service import (
    get_project_chat_workspace_dir,
    get_project_root,
    get_project_workspace_dir,
)


def get_chat_workspace_dir(chat_id: int) -> Path:
    """Return the durable Application Support workspace path for a non-project chat."""
    return get_data_dir() / "chats" / str(chat_id) / "workspace"


def get_legacy_chat_workspace_dir(chat_id: int) -> Path:
    """Return the old cache-backed workspace path for a non-project chat."""
    return get_cache_dir() / "workspaces" / str(chat_id)


def get_workspace_dir(chat_id: int, project_id: int | None = None) -> Path:
    """Get or create the workspace directory for a chat session."""
    if project_id is not None:
        workspace = get_project_chat_workspace_dir(project_id, chat_id)
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    workspace = get_chat_workspace_dir(chat_id)
    legacy_workspace = get_legacy_chat_workspace_dir(chat_id)

    if legacy_workspace.exists() and not workspace.exists():
        workspace.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_workspace), str(workspace))

    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def get_project_workspace(project_id: int | None) -> Path | None:
    if project_id is None:
        return None
    workspace = get_project_workspace_dir(project_id)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _chat_workspace_path(chat_id: int, project_id: int | None) -> Path:
    """Where a chat's workspace lives, without creating it."""
    if project_id is not None:
        return get_project_root(project_id) / "chats" / str(chat_id) / "workspace"
    return get_chat_workspace_dir(chat_id)


def _remove_empty_dirs(path: Path, stop: Path) -> None:
    """Remove ``path`` and empty ancestors up to (not including) ``stop``."""
    try:
        path.relative_to(stop)
    except ValueError:
        return
    while path != stop and path.exists():
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


def move_chat_workspace(chat_id: int, from_project_id: int | None, to_project_id: int | None) -> Path:
    """Move a chat's workspace when the chat moves between projects.

    Returns the destination. A missing source just means there's nothing to
    move yet. Files already at the destination are kept; on a name clash the
    moving file wins only if the destination entry doesn't exist.
    """
    source = _chat_workspace_path(chat_id, from_project_id)
    if from_project_id is None and not source.exists():
        legacy = get_legacy_chat_workspace_dir(chat_id)
        if legacy.exists():
            source = legacy
    destination = _chat_workspace_path(chat_id, to_project_id)
    if source == destination or not source.exists():
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.move(str(source), str(destination))
    else:
        for entry in list(source.iterdir()):
            target = destination / entry.name
            if not target.exists():
                shutil.move(str(entry), str(target))
        if not any(source.iterdir()):
            source.rmdir()

    stop = get_project_root(from_project_id) if from_project_id is not None else get_data_dir()
    _remove_empty_dirs(source.parent, stop)
    return destination
