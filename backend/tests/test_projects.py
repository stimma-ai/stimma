"""Tests for project APIs and project-scoped entities."""

import json

import pytest
from sqlalchemy import select

from agent.v2.agent_config import resolve_agent_config
from agent.v2.permissions import check_permission, check_stp_permission
from agent.v2.workspace import get_project_workspace, get_workspace_dir
from database import BoardSection, Chat, Project
from project_service import initialize_project_root
from tests.helpers.media import create_test_media


@pytest.fixture
async def seeded_media(db_session):
    async with db_session() as session:
        return await create_test_media(session, count=2)


class TestProjectsApi:
    async def test_create_and_list_projects(self, client):
        create_response = await client.post("/api/projects", json={"name": "Brand Refresh", "description": "Client rebrand"})
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "Brand Refresh"
        assert created["asset_count"] == 0

        list_response = await client.get("/api/projects")
        assert list_response.status_code == 200
        items = list_response.json()
        assert any(project["id"] == created["id"] for project in items)

    async def test_blank_project_names_stay_blank(self, client):
        create_response = await client.post("/api/projects", json={"name": ""})
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == ""

        update_response = await client.put(f"/api/projects/{created['id']}", json={"name": "   "})
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["name"] == ""

    async def test_project_scoped_chat_and_board(self, client):
        project = (await client.post("/api/projects", json={"name": "Campaign"})).json()

        chat = (await client.post("/api/chats", json={"project_id": project["id"]})).json()
        assert chat["project_id"] == project["id"]

        board = (await client.post("/api/boards", json={"name": "Mood", "project_id": project["id"]})).json()
        assert board["project_id"] == project["id"]

        chats = (await client.get(f"/api/chats/previews?page=1&page_size=20&project_id={project['id']}")).json()
        assert any(item["id"] == chat["id"] for item in chats["items"])

        boards = (await client.get(f"/api/boards?project_id={project['id']}")).json()
        assert any(item["id"] == board["id"] for item in boards)

        global_boards = (await client.get("/api/boards")).json()
        assert all(item["id"] != board["id"] for item in global_boards)

    async def test_rejects_invalid_project_ids(self, client):
        chat_response = await client.post("/api/chats", json={"project_id": 999999})
        assert chat_response.status_code == 404

        board_response = await client.post("/api/boards", json={"project_id": 999999})
        assert board_response.status_code == 404

    async def test_add_and_filter_project_assets(self, client, seeded_media):
        project = (await client.post("/api/projects", json={"name": "Asset Project"})).json()
        response = await client.post(
            f"/api/projects/{project['id']}/assets",
            json={"media_ids": [seeded_media[0].id]},
        )
        assert response.status_code == 200
        assert response.json()["added"] == 1

        media = (await client.get(f"/api/media?project_id={project['id']}&page=1&page_size=20")).json()
        ids = [item["id"] for item in media["items"]]
        assert seeded_media[0].id in ids
        assert seeded_media[1].id not in ids

        delete_response = await client.delete(f"/api/projects/{project['id']}/assets/{seeded_media[0].id}")
        assert delete_response.status_code == 200

        media_after = (await client.get(f"/api/media?project_id={project['id']}&page=1&page_size=20")).json()
        assert all(item["id"] != seeded_media[0].id for item in media_after["items"])

    async def test_adding_asset_to_project_board_also_adds_it_to_project(self, client, seeded_media):
        project = (await client.post("/api/projects", json={"name": "Board Asset Project"})).json()
        board = (await client.post(
            "/api/boards",
            json={"name": "Mood", "project_id": project["id"]},
        )).json()

        add_response = await client.post(
            f"/api/boards/{board['id']}/items",
            json={"media_ids": [seeded_media[0].id]},
        )
        assert add_response.status_code == 200
        assert add_response.json()["added"] == 1

        media = (await client.get(f"/api/media?project_id={project['id']}&page=1&page_size=20")).json()
        ids = [item["id"] for item in media["items"]]
        assert seeded_media[0].id in ids
        assert seeded_media[1].id not in ids

        project_detail = (await client.get(f"/api/projects/{project['id']}")).json()
        assert project_detail["asset_count"] == 1

    async def test_delete_project_cascades_to_chats_and_boards_but_not_assets(self, client, seeded_media, db_session):
        project = (await client.post("/api/projects", json={"name": "Cascade Project"})).json()

        chat = (await client.post("/api/chats", json={"project_id": project["id"]})).json()
        board = (await client.post("/api/boards", json={"name": "Mood", "project_id": project["id"]})).json()
        attach_response = await client.post(
            f"/api/projects/{project['id']}/assets",
            json={"media_ids": [seeded_media[0].id]},
        )
        assert attach_response.status_code == 200

        delete_response = await client.delete(f"/api/projects/{project['id']}")
        assert delete_response.status_code == 200

        project_response = await client.get(f"/api/projects/{project['id']}")
        assert project_response.status_code == 404

        projects = (await client.get("/api/projects")).json()
        assert all(item["id"] != project["id"] for item in projects)

        chats = (await client.get("/api/chats/previews?page=1&page_size=20")).json()
        assert all(item["id"] != chat["id"] for item in chats["items"])

        boards = (await client.get("/api/boards")).json()
        assert all(item["id"] != board["id"] for item in boards)

        async with db_session() as session:
            sections = (
                await session.execute(
                    select(BoardSection).where(BoardSection.board_id == board["id"])
                )
            ).scalars().all()
            assert sections
            assert all(section.deleted_at is not None for section in sections)

        # Assets should remain in the library — projects don't own assets
        media = (await client.get("/api/media?page=1&page_size=20")).json()
        assert seeded_media[0].id in [item["id"] for item in media["items"]]

        # Asset should NOT be in trash
        trash = (await client.get("/api/trash")).json()
        assert seeded_media[0].id not in [item["id"] for item in trash["items"]]

    async def test_project_agent_resolution_and_workspace(self, db_session):
        async with db_session() as session:
            project = Project(
                name="Scoped Project",
                additional_instructions="Use the shared project workspace.",
                agent_tool_config=json.dumps({
                    "allowed_tools": ["provider:project-tool"],
                    "v2_permissions": {"bash": "allow"},
                }),
            )
            session.add(project)
            await session.flush()
            await initialize_project_root(session, project)

            chat = Chat(
                name="",
                project_id=project.id,
                agent_tool_config=json.dumps({
                    "v2_permissions": {"run_code": "deny"},
                }),
                generation_settings="{}",
            )
            session.add(chat)
            await session.commit()
            await session.refresh(chat)

            resolved = await resolve_agent_config(chat, session)
            assert "Use the shared project workspace." in resolved.additional_instructions

            assert await check_permission("bash", chat, session) is True
            # run_code is workspace-sandboxed and no longer uses persisted HITL gates.
            assert await check_permission("run_code", chat, session) is True
            assert await check_stp_permission("provider:project-tool", chat, session) is True

            chat_workspace = get_workspace_dir(chat.id, chat.project_id)
            project_workspace = get_project_workspace(chat.project_id)
            assert f"/projects/{project.id}/chats/{chat.id}/workspace" in str(chat_workspace)
            assert project_workspace is not None
            assert str(project_workspace).endswith(f"/projects/{project.id}/workspace")
