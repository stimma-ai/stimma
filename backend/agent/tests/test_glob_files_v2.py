import pytest

from agent.v2.tools.glob_files import glob_files


@pytest.fixture
def workspace(tmp_path):
    stimma = tmp_path / ".stimma"
    (stimma / "tools" / "text-to-image").mkdir(parents=True)
    (stimma / "tools" / "text-to-image" / "flux_klein_9b.py").write_text("# stub")
    (stimma / "README.md").write_text("# catalog")
    (tmp_path / "result.png").write_bytes(b"png")
    return tmp_path


@pytest.mark.asyncio
async def test_glob_lists_directories_with_trailing_slash(workspace):
    """Discovery patterns whose matches are all directories must not read as
    'nothing here' — that's what sent the agent hunting outside the workspace."""
    result = await glob_files(pattern=".stimma", workspace_dir=str(workspace))
    assert result == ".stimma/"

    result = await glob_files(pattern=".stimma/tools/*", workspace_dir=str(workspace))
    assert result == ".stimma/tools/text-to-image/"


@pytest.mark.asyncio
async def test_glob_lists_files_and_directories_together(workspace):
    result = await glob_files(pattern=".stimma/*", workspace_dir=str(workspace))
    lines = result.splitlines()
    assert ".stimma/README.md" in lines
    assert ".stimma/tools/" in lines


@pytest.mark.asyncio
async def test_glob_files_still_plain(workspace):
    result = await glob_files(pattern="*.png", workspace_dir=str(workspace))
    assert result == "result.png"


@pytest.mark.asyncio
async def test_glob_no_matches_message(workspace):
    result = await glob_files(pattern="nope*", workspace_dir=str(workspace))
    assert result == "No files or directories matching 'nope*'"
