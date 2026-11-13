from unittest.mock import patch

from agent.v2.workspace import (
    get_chat_workspace_dir,
    get_legacy_chat_workspace_dir,
    get_workspace_dir,
)


def test_non_project_chat_workspaces_live_in_data_dir(temp_appdata_dir):
    chat_id = 123

    with patch("app_dirs.get_data_dir", return_value=temp_appdata_dir), patch(
        "app_dirs.get_cache_dir", return_value=temp_appdata_dir / "cache"
    ):
        workspace = get_workspace_dir(chat_id)

        assert workspace == temp_appdata_dir / "chats" / str(chat_id) / "workspace"
        assert workspace.exists()
        assert "cache" not in workspace.parts


def test_non_project_chat_workspaces_migrate_from_cache(temp_appdata_dir):
    chat_id = 456
    cache_dir = temp_appdata_dir / "cache"

    with patch("app_dirs.get_data_dir", return_value=temp_appdata_dir), patch(
        "app_dirs.get_cache_dir", return_value=cache_dir
    ):
        legacy_workspace = get_legacy_chat_workspace_dir(chat_id)
        legacy_workspace.mkdir(parents=True, exist_ok=True)
        legacy_file = legacy_workspace / "notes.txt"
        legacy_file.write_text("persist me")

        workspace = get_workspace_dir(chat_id)

        assert workspace == get_chat_workspace_dir(chat_id)
        assert workspace.exists()
        assert (workspace / "notes.txt").read_text() == "persist me"
        assert not legacy_workspace.exists()


def test_attachment_names_lose_unicode_whitespace():
    """A macOS screenshot carries U+202F before AM/PM. The agent is told the
    filename as text and then opens it as a path — and a model retyping that
    name emits a plain space, so the open fails on a file that plainly exists.
    Normalizing at copy time keeps the two in sync."""
    from agent.v2.service import _workspace_safe_filename

    assert (
        _workspace_safe_filename("Screenshot 2026-07-29 at 12.51.16 PM.png")
        == "Screenshot 2026-07-29 at 12.51.16 PM.png"
    )
    assert _workspace_safe_filename("a b　c.png") == "a b c.png"
    assert _workspace_safe_filename("wide​name.png") == "widename.png"
    assert _workspace_safe_filename("plain name.png") == "plain name.png"
    # A name made entirely of exotic whitespace must not collapse to nothing.
    assert _workspace_safe_filename(" ") == " "
