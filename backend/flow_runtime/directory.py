"""Flow on-disk directory lifecycle (create, delete, fork).

Layout per FLOWS_TECH.md §"On-Disk Storage":

    <data_dir>/flows/<flow_id>/
    ├── program.py
    ├── program_base.py        # only on forks
    ├── state.db
    ├── resources/
    └── metadata.json
"""

from __future__ import annotations

import ctypes
import json
import platform
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.logging import get_logger

from .paths import (
    get_flow_dir,
    get_flow_metadata_path,
    get_flow_program_base_path,
    get_flow_program_path,
    get_flow_resources_dir,
    get_flow_state_db_path,
)
from .state_db import (
    create_flow_state_db,
    delete_pending_tasks,
    reset_transient_equation_states,
)

log = get_logger(__name__)


_EMPTY_PROGRAM = '''"""Flow program — edited by the flow agent.

This file defines the flow's equation graph using the flow DSL.
It is empty until the agent (or you) adds steps.
"""
'''

# Older placeholders that should still register as "empty" for legacy flows.
_LEGACY_EMPTY_PROGRAMS = (
    '''"""Flow program — edited by the flow agent.

Phase 1 placeholder. In Phase 2 this file defines the equation graph using
the flow DSL.
"""
''',
)


def is_empty_flow_program(program_text: str) -> bool:
    """Return True when program.py is still the new-flow placeholder."""
    return program_text == _EMPTY_PROGRAM or program_text in _LEGACY_EMPTY_PROGRAMS


def get_empty_flow_program() -> str:
    """Return the canonical placeholder source for an empty flow program."""
    return _EMPTY_PROGRAM


# Marker file used to signal that the user (not the agent) just edited
# program.py. The agent's next turn picks this up via a system reminder so it
# knows to re-read the file before making further edits, then clears it.
_USER_EDIT_MARKER = ".user_program_edit_pending"


def get_user_program_edit_marker_path(flow_id: int) -> Path:
    return get_flow_dir(flow_id) / _USER_EDIT_MARKER


def mark_user_program_edit(flow_id: int) -> None:
    """Drop a sentinel file noting the user has just saved a program.py edit."""
    path = get_user_program_edit_marker_path(flow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.utcnow().isoformat() + "Z")


def consume_user_program_edit_marker(flow_id: int) -> bool:
    """Return True (and delete the marker) if a user edit is pending."""
    path = get_user_program_edit_marker_path(flow_id)
    if not path.exists():
        return False
    try:
        path.unlink()
    except OSError:
        log.warning("could not remove user-edit marker", extra={"flow_id": flow_id})
    return True


def has_user_program_edit_marker(flow_id: int) -> bool:
    return get_user_program_edit_marker_path(flow_id).exists()


def _write_metadata(flow_id: int, metadata: dict[str, Any]) -> None:
    get_flow_metadata_path(flow_id).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    )


def create_flow_directory(flow_id: int, metadata: Optional[dict[str, Any]] = None) -> Path:
    """Create the on-disk layout for a brand-new (non-fork) flow.

    Creates program.py (empty placeholder), state.db (with schema), resources/,
    metadata.json. Does NOT create program_base.py — that file exists only on
    forks as a snapshot of the parent's program at fork time.
    """
    flow_dir = get_flow_dir(flow_id)
    flow_dir.mkdir(parents=True, exist_ok=True)

    program = get_flow_program_path(flow_id)
    if not program.exists():
        program.write_text(_EMPTY_PROGRAM)

    resources = get_flow_resources_dir(flow_id)
    resources.mkdir(parents=True, exist_ok=True)

    create_flow_state_db(get_flow_state_db_path(flow_id))

    _write_metadata(flow_id, metadata or {"flow_id": flow_id})

    return flow_dir


def write_empty_flow_program(flow_id: int) -> Path:
    """Overwrite program.py with the canonical empty placeholder."""
    program_path = get_flow_program_path(flow_id)
    program_path.parent.mkdir(parents=True, exist_ok=True)
    program_path.write_text(_EMPTY_PROGRAM)
    return program_path


def delete_flow_directory(flow_id: int) -> bool:
    """Remove the on-disk directory for a flow. Returns True if it existed.

    Only used for hard-deletes — soft delete (setting deleted_at on the DB row)
    preserves the directory so state can be restored.
    """
    flow_dir = get_flow_dir(flow_id)
    if not flow_dir.exists():
        return False
    shutil.rmtree(flow_dir)
    return True


def _apfs_clonefile(src: Path, dst: Path) -> bool:
    """Attempt a macOS APFS clonefile copy of `src` to `dst`. Returns True on success.

    This is purely an optimization — falls back to normal recursive copy on any
    failure (unsupported OS, cross-volume copy, missing libc symbol, etc.).
    The dst path must not exist yet.
    """
    if platform.system() != "Darwin":
        return False
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        clonefile = libc.clonefile
        clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        clonefile.restype = ctypes.c_int
    except (OSError, AttributeError) as exc:
        log.debug(f"APFS clonefile unavailable: {exc}")
        return False

    rc = clonefile(str(src).encode(), str(dst).encode(), 0)
    if rc != 0:
        err = ctypes.get_errno()
        log.debug(f"APFS clonefile {src} -> {dst} failed errno={err}")
        return False
    return True


def _copy_directory(src: Path, dst: Path) -> None:
    """Copy `src` directory tree to `dst`, preferring APFS clonefile on macOS."""
    if dst.exists():
        raise FileExistsError(f"fork destination already exists: {dst}")

    # Try clonefile first — it's an atomic copy-on-write snapshot of the whole
    # tree. If it fails (different volume, unsupported FS, macOS < 10.12), fall
    # back to shutil.copytree.
    if _apfs_clonefile(src, dst):
        return
    shutil.copytree(src, dst, symlinks=False)


def fork_flow_directory(
    parent_flow_id: int,
    new_flow_id: int,
    *,
    metadata: Optional[dict[str, Any]] = None,
) -> Path:
    """Fork the on-disk directory of `parent_flow_id` into `new_flow_id`.

    Steps (per FLOWS_TECH.md §Forking, steps 2–5):
      2. Copy parent's flow directory to the new location (APFS clonefile
         when available, otherwise recursive copy).
      3. Snapshot the parent's current program.py as program_base.py in the
         fork. This is the common ancestor for a future 3-way merge. For a
         grandchild fork, this overwrites the inherited program_base.py —
         that's correct: the fork's base is its direct parent at fork time,
         not the root ancestor.
      5. Reset any equations in transient states (computing, awaiting_input)
         to pending; the fork starts clean.

    Returns the path to the new flow directory.
    """
    parent_dir = get_flow_dir(parent_flow_id)
    if not parent_dir.exists():
        raise FileNotFoundError(f"parent flow directory missing: {parent_dir}")

    new_dir = get_flow_dir(new_flow_id)
    new_dir.parent.mkdir(parents=True, exist_ok=True)
    _copy_directory(parent_dir, new_dir)

    # Snapshot parent's current program.py as the fork's program_base.py.
    # Use the parent's program (not the fork's inherited one) so grandchild
    # forks get THEIR parent's current state as base, not the grandparent's.
    parent_program = get_flow_program_path(parent_flow_id)
    fork_program_base = get_flow_program_base_path(new_flow_id)
    if parent_program.exists():
        shutil.copyfile(parent_program, fork_program_base)
    else:
        # Parent had no program.py (shouldn't happen after create_flow_directory
        # but be defensive). Leave program_base.py absent.
        log.warning(
            f"fork: parent {parent_flow_id} has no program.py; "
            f"fork {new_flow_id} program_base.py not created"
        )

    # Reset transient equation states in the fork's copied state.db and drop
    # parent-only actionable tasks so the fork starts without stale cards.
    fork_state_db = get_flow_state_db_path(new_flow_id)
    reset_transient_equation_states(fork_state_db)
    delete_pending_tasks(fork_state_db)

    if metadata is not None:
        _write_metadata(new_flow_id, metadata)
    else:
        # Keep metadata.json in sync with the fork's id at minimum.
        existing_meta = {}
        meta_path = get_flow_metadata_path(new_flow_id)
        if meta_path.exists():
            try:
                existing_meta = json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                existing_meta = {}
        existing_meta["flow_id"] = new_flow_id
        existing_meta["forked_from"] = parent_flow_id
        existing_meta["forked_at"] = datetime.utcnow().isoformat()
        _write_metadata(new_flow_id, existing_meta)

    return new_dir
