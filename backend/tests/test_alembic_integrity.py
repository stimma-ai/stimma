from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_single_head_and_unique_revision_ids() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    revisions = list(script.walk_revisions(base="base", head="heads"))
    revision_ids = [revision.revision for revision in revisions]

    assert len(revision_ids) == len(set(revision_ids)), "Alembic revision IDs must be unique"

    heads = script.get_heads()
    assert len(heads) == 1, f"Alembic must have exactly one head, found: {heads}"
