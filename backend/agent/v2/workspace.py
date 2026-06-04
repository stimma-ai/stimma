"""Session workspace directory management."""

from pathlib import Path
import shutil

from app_dirs import get_cache_dir, get_data_dir
from project_service import get_project_chat_workspace_dir, get_project_workspace_dir


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
