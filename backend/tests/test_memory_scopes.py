"""Agent memory: global, project and chat files, edited like any other file."""

import pytest
from sqlalchemy import select

import memory_store
from agent.v2.prompts import get_system_prompt
from agent.v2.system_reminders import build_memory_reminder
from agent.v2.tools.edit_file import edit_file
from agent.v2.tools.read_file import read_file
from agent.v2.tools.write_file import write_file
from agent.v2.workspace import get_workspace_dir
from core.profile_context import ProfileScope
from database import Project


async def test_global_memory_round_trips_through_settings(client):
    path = memory_store.global_memory_path("default")
    path.unlink()

    response = await client.patch("/api/settings/agent", json={"memory": "- Prefers photographic styles.\n"})
    assert response.status_code == 200
    assert response.json()["memory"] == "- Prefers photographic styles.\n"
    assert path.read_text() == "- Prefers photographic styles.\n"
    assert (await client.get("/api/settings/agent")).json()["memory"] == "- Prefers photographic styles.\n"


async def test_global_memory_seeds_from_legacy_field_once(monkeypatch, tmp_path):
    import app_dirs
    from types import SimpleNamespace

    monkeypatch.setattr(app_dirs, "get_profile_dir", lambda profile_id=None: tmp_path)
    legacy = SimpleNamespace(get_agent_for_profile=lambda _: SimpleNamespace(memory="old note"))
    monkeypatch.setattr("config.get_settings", lambda: legacy)

    assert memory_store.read_global_memory("p") == "old note\n"
    memory_store.write_global_memory("", "p")
    assert memory_store.read_global_memory("p") == ""  # an emptied file stays empty


async def test_project_memory_lives_in_project_file(client, db_session):
    project = (await client.post("/api/projects", json={"name": "Campaign"})).json()
    assert project["memory"] == ""

    updated = (await client.put(f"/api/projects/{project['id']}", json={"memory": "Brand blue is #1d4ed8."})).json()
    assert updated["memory"] == "Brand blue is #1d4ed8."
    assert memory_store.project_memory_path(project["id"]).read_text() == "Brand blue is #1d4ed8."

    async with db_session() as session:
        row = (await session.execute(select(Project).where(Project.id == project["id"]))).scalar_one()
        assert row.memory is None  # the old column is no longer written


async def test_project_memory_seeds_from_legacy_column(db_session):
    async with db_session() as session:
        project = Project(name="Legacy", memory="Recurring character: Mara.")
        session.add(project)
        await session.commit()
        assert memory_store.read_project_memory(project) == "Recurring character: Mara.\n"


async def test_chat_memory_round_trips_through_agent_settings(client):
    chat = (await client.post("/api/chats", json={})).json()
    assert (await client.get(f"/api/chats/{chat['id']}/agent-settings")).json()["memory"] == ""

    response = await client.put(f"/api/chats/{chat['id']}/agent-settings", json={"memory": "Keep these 16:9."})
    assert response.status_code == 200
    assert response.json()["memory"] == "Keep these 16:9."
    assert (get_workspace_dir(chat["id"]) / "memory" / "chat.md").read_text() == "Keep these 16:9."


async def test_file_tools_edit_each_scope(client):
    project = (await client.post("/api/projects", json={"name": "Tools"})).json()
    chat = (await client.post("/api/chats", json={"project_id": project["id"]})).json()
    workspace = get_workspace_dir(chat["id"], project["id"])
    with ProfileScope("default"):
        memory_store.ensure_memory_mount(workspace, project["id"])
        memory_store.write_global_memory("- Likes muted palettes.\n")
        kw = {"workspace_dir": str(workspace), "chat_id": chat["id"]}

        result = await edit_file(
            file_path="memory/global.md",
            old_string="- Likes muted palettes.\n",
            new_string="- Likes muted palettes.\n- Writes in American English.\n",
            **kw,
        )
        assert result.startswith("Edited memory/global.md"), result
        assert memory_store.read_global_memory() == "- Likes muted palettes.\n- Writes in American English.\n"

        assert (await write_file(file_path="memory/project.md", content="Goal: spring launch.\n", **kw)).startswith("The file")
        assert memory_store.read_project_memory_file(project["id"]) == "Goal: spring launch.\n"

        await write_file(file_path="memory/chat.md", content="Hero is red-haired.\n", **kw)
        assert memory_store.read_chat_memory(chat["id"], project["id"]) == "Hero is red-haired.\n"
        assert "Goal: spring launch." in await read_file(file_path="memory/project.md", **kw)

        reminder = build_memory_reminder(chat["id"], project["id"])
        assert "### memory/global.md\n- Likes muted palettes." in reminder
        assert "### memory/project.md\nGoal: spring launch." in reminder
        assert "### memory/chat.md\nHero is red-haired." in reminder


async def test_non_project_chat_has_no_project_memory(client):
    chat = (await client.post("/api/chats", json={})).json()
    workspace = get_workspace_dir(chat["id"])
    with ProfileScope("default"):
        memory_store.ensure_memory_mount(workspace, None)
        result = await write_file(file_path="memory/project.md", content="x", workspace_dir=str(workspace))
        assert "isn't in a project" in result
        reminder = build_memory_reminder(chat["id"], None)
    assert "memory/project.md" not in reminder.split("isn't in a project")[0]
    assert "### memory/chat.md\n(empty)" in reminder


def test_system_prompt_explains_scopes_without_contents():
    prompt = get_system_prompt()
    for path in ("memory/chat.md", "memory/project.md", "memory/global.md"):
        assert path in prompt
    assert "save_memory" not in prompt
    assert "narrowest scope" in prompt


@pytest.mark.parametrize("name", ["global.md", "project.md"])
def test_mount_links_shared_files(tmp_path, monkeypatch, name):
    monkeypatch.setattr(memory_store, "global_memory_path", lambda profile_id=None: tmp_path / "g.md")
    monkeypatch.setattr(memory_store, "project_memory_path", lambda project_id, legacy=None: tmp_path / "p.md")
    (tmp_path / "g.md").write_text("g")
    (tmp_path / "p.md").write_text("p")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    memory_store.ensure_memory_mount(workspace, 7)
    link = workspace / "memory" / name
    assert link.is_symlink() and link.read_text() == name[0]
    assert (workspace / "memory" / "chat.md").read_text() == ""


async def test_flow_workspace_cannot_reach_shared_memory(tmp_path):
    with ProfileScope("default"):
        memory_store.write_global_memory("- Keep me.\n")
        flow_dir = tmp_path / "flows" / "3"
        flow_dir.mkdir(parents=True)
        await write_file(file_path="memory/global.md", content="overwritten", workspace_dir=str(flow_dir))
        assert memory_store.read_global_memory() == "- Keep me.\n"
