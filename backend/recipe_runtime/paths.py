"""On-disk layout for recipes and the global equation store."""

from __future__ import annotations

from pathlib import Path

# Import the module, not the bound function, so test patches applied via
# patch.multiple("app_dirs", ...) take effect here too.
import app_dirs


def get_recipes_root() -> Path:
    return app_dirs.get_data_dir() / "recipes"


def get_recipe_dir(recipe_id: int) -> Path:
    return get_recipes_root() / str(recipe_id)


def get_recipe_state_db_path(recipe_id: int) -> Path:
    return get_recipe_dir(recipe_id) / "state.db"


def get_recipe_program_path(recipe_id: int) -> Path:
    return get_recipe_dir(recipe_id) / "program.py"


def get_recipe_program_base_path(recipe_id: int) -> Path:
    """program_base.py is only present on forks (snapshot of parent at fork time)."""
    return get_recipe_dir(recipe_id) / "program_base.py"


def get_recipe_resources_dir(recipe_id: int) -> Path:
    return get_recipe_dir(recipe_id) / "resources"


def get_recipe_metadata_path(recipe_id: int) -> Path:
    return get_recipe_dir(recipe_id) / "metadata.json"


def get_equation_store_dir() -> Path:
    return app_dirs.get_data_dir() / "equation_store"


def get_equation_store_db_path() -> Path:
    return get_equation_store_dir() / "equations.db"


def get_equation_store_blobs_dir() -> Path:
    return get_equation_store_dir() / "blobs"
