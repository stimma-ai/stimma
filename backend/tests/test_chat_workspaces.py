from unittest.mock import patch

from agent.v2.workspace import (
    get_chat_workspace_dir,
    get_legacy_chat_workspace_dir,
    get_workspace_dir,
)


def test_non_project_chat_workspaces_live_in_data_dir(temp_appdata_dir):
    chat_id = 123

    with patch("agent.v2.workspace.get_data_dir", return_value=temp_appdata_dir), patch(
        "agent.v2.workspace.get_cache_dir", return_value=temp_appdata_dir / "cache"
    ):
        workspace = get_workspace_dir(chat_id)

        assert workspace == temp_appdata_dir / "chats" / str(chat_id) / "workspace"
        assert workspace.exists()
        assert "cache" not in workspace.parts


def test_non_project_chat_workspaces_migrate_from_cache(temp_appdata_dir):
    chat_id = 456
    cache_dir = temp_appdata_dir / "cache"

    with patch("agent.v2.workspace.get_data_dir", return_value=temp_appdata_dir), patch(
        "agent.v2.workspace.get_cache_dir", return_value=cache_dir
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
