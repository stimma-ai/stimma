"""Agent memory: one markdown file per scope.

    global   <profile dir>/memory.md               every chat in the profile
    project  <project root>/memory.md               every chat in the project
    chat     <chat workspace>/memory/chat.md        this chat only

The agent reads and edits these with its ordinary file tools through the
workspace's ``memory/`` folder (``global.md``, ``project.md``, ``chat.md``),
the way coding agents keep memory in markdown files. Settings, project
settings and chat settings edit the same files.

Global and project memory used to be single text fields (the profile's
``agent.memory`` and ``Project.memory``). The first read of a missing file
seeds it from that field once; after that the file is the only source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import app_dirs
from project_service import get_project_root

MEMORY_DIR = "memory"
GLOBAL_FILE = "global.md"
PROJECT_FILE = "project.md"
CHAT_FILE = "chat.md"
MEMORY_FILES = (GLOBAL_FILE, PROJECT_FILE, CHAT_FILE)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return ""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed(path: Path, legacy: Optional[str]) -> Path:
    """Create ``path`` once, from the legacy text field when there is one."""
    if not path.exists():
        _write(path, (legacy or "").strip() + ("\n" if (legacy or "").strip() else ""))
    return path


# -- global -----------------------------------------------------------------

def global_memory_path(profile_id: Optional[str] = None) -> Path:
    """The profile's global memory file, created (and seeded) if missing."""
    from core.profile_context import get_current_profile

    profile_id = profile_id or get_current_profile()
    path = app_dirs.get_profile_dir(profile_id=profile_id) / "memory.md"
    if path.exists():
        return path
    legacy = ""
    try:
        from config import get_settings
        legacy = get_settings().get_agent_for_profile(profile_id).memory
    except Exception:
        pass
    return _seed(path, legacy)


def read_global_memory(profile_id: Optional[str] = None) -> str:
    return _read(global_memory_path(profile_id))


def write_global_memory(content: str, profile_id: Optional[str] = None) -> None:
    _write(global_memory_path(profile_id), content)


# -- project ----------------------------------------------------------------

def project_memory_path(project_id: int, legacy: Optional[str] = None) -> Path:
    """The project's memory file, created (and seeded from ``legacy``) if missing."""
    return _seed(get_project_root(project_id) / "memory.md", legacy)


def read_project_memory(project) -> str:
    """Memory for a ``Project`` row (seeds from its old ``memory`` column)."""
    return _read(project_memory_path(project.id, project.memory))


def read_project_memory_file(project_id: int) -> str:
    """Project memory by id, once the file exists (``read_project_memory`` seeds it)."""
    return _read(project_memory_path(project_id))


def write_project_memory(project, content: str) -> None:
    _write(project_memory_path(project.id, project.memory), content)


# -- chat -------------------------------------------------------------------

def chat_memory_path(chat_id: int, project_id: Optional[int] = None) -> Path:
    from agent.v2.workspace import get_workspace_dir

    return get_workspace_dir(chat_id, project_id) / MEMORY_DIR / CHAT_FILE


def read_chat_memory(chat_id: int, project_id: Optional[int] = None) -> str:
    return _read(chat_memory_path(chat_id, project_id))


def write_chat_memory(chat_id: int, content: str, project_id: Optional[int] = None) -> None:
    _write(chat_memory_path(chat_id, project_id), content)


# -- workspace mount --------------------------------------------------------

def resolve_memory_file(workspace_dir: Path, name: str) -> tuple[Optional[Path], Optional[str]]:
    """Where ``memory/<name>`` in a workspace really lives.

    ``chat.md`` is a plain file in the workspace. ``global.md`` and
    ``project.md`` map to the profile and project files whether or not the
    workspace has links to them (Windows may not allow links).
    """
    if name == GLOBAL_FILE:
        return global_memory_path(), None
    if name == PROJECT_FILE:
        from project_service import infer_project_id_from_workspace_path

        project_id = infer_project_id_from_workspace_path(workspace_dir)
        if project_id is None:
            return None, (
                "Error: this chat isn't in a project, so there is no project memory. "
                "Use memory/chat.md for this chat or memory/global.md for every chat."
            )
        return project_memory_path(project_id), None
    return None, None


def ensure_memory_mount(workspace_dir: Path | str, project_id: Optional[int]) -> None:
    """Make ``memory/`` in a workspace: chat.md, plus links to global.md and
    project.md so the shell sees them too. Best-effort; the file tools map
    the paths without the links."""
    memory_dir = Path(workspace_dir) / MEMORY_DIR
    if memory_dir.is_symlink() or (memory_dir.exists() and not memory_dir.is_dir()):
        return
    memory_dir.mkdir(parents=True, exist_ok=True)
    _seed(memory_dir / CHAT_FILE, None)
    targets = {GLOBAL_FILE: global_memory_path()}
    if project_id is not None:
        targets[PROJECT_FILE] = project_memory_path(project_id)
    for name, target in targets.items():
        link = memory_dir / name
        try:
            if link.is_symlink():
                if link.resolve() == target.resolve():
                    continue
                link.unlink()
            elif link.exists():
                continue
            link.symlink_to(target)
        except OSError:
            pass
    stale = memory_dir / PROJECT_FILE
    if project_id is None and stale.is_symlink():
        try:
            stale.unlink()
        except OSError:
            pass
