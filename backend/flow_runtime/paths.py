"""On-disk layout for flows and the global equation store."""

from __future__ import annotations

from pathlib import Path

# Import the module, not the bound function, so test patches applied via
# patch.multiple("app_dirs", ...) take effect here too.
import app_dirs


def get_flows_root() -> Path:
    return app_dirs.get_data_dir() / "flows"


def get_flow_dir(flow_id: int) -> Path:
    return get_flows_root() / str(flow_id)


def get_flow_state_db_path(flow_id: int) -> Path:
    return get_flow_dir(flow_id) / "state.db"


def get_flow_program_path(flow_id: int) -> Path:
    return get_flow_dir(flow_id) / "program.py"


def get_flow_program_base_path(flow_id: int) -> Path:
    """program_base.py is only present on forks (snapshot of parent at fork time)."""
    return get_flow_dir(flow_id) / "program_base.py"


def get_flow_resources_dir(flow_id: int) -> Path:
    return get_flow_dir(flow_id) / "resources"


def get_flow_metadata_path(flow_id: int) -> Path:
    return get_flow_dir(flow_id) / "metadata.json"


def get_equation_store_dir() -> Path:
    return app_dirs.get_data_dir() / "equation_store"


def get_equation_store_db_path() -> Path:
    return get_equation_store_dir() / "equations.db"


def get_equation_store_blobs_dir() -> Path:
    return get_equation_store_dir() / "blobs"
