"""
Tests for the global search endpoint (/api/search).
"""

import pytest
from httpx import AsyncClient


async def _create_chat(client: AsyncClient, name: str) -> int:
    response = await client.post("/api/chats", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _create_board(client: AsyncClient, name: str) -> int:
    response = await client.post("/api/boards", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _create_project(client: AsyncClient, name: str) -> int:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _create_flow(client: AsyncClient, name: str) -> int:
    response = await client.post("/api/flows", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _create_preset(client: AsyncClient, name: str) -> int:
    response = await client.post(
        "/api/presets",
        json={"name": name, "tool_id": "builtin:test:tool:text-to-image", "state": {}},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


class TestGlobalSearch:
    @pytest.mark.asyncio
    async def test_empty_query_rejected(self, client: AsyncClient):
        response = await client.get("/api/search", params={"q": ""})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_matches_across_entity_types(self, client: AsyncClient):
        await _create_chat(client, "Portrait explorations")
        await _create_board(client, "Portrait reference wall")
        await _create_project(client, "Portrait project")
        await _create_flow(client, "Portrait batch cleanup")
        await _create_preset(client, "Portrait studio light")
        await _create_chat(client, "Unrelated chat")

        response = await client.get("/api/search", params={"q": "portrait"})
        assert response.status_code == 200
        data = response.json()

        assert [c["name"] for c in data["chats"]] == ["Portrait explorations"]
        assert [b["name"] for b in data["boards"]] == ["Portrait reference wall"]
        assert [p["name"] for p in data["projects"]] == ["Portrait project"]
        assert [f["name"] for f in data["flows"]] == ["Portrait batch cleanup"]
        assert [p["name"] for p in data["presets"]] == ["Portrait studio light"]
        assert data["presets"][0]["tool_id"] == "builtin:test:tool:text-to-image"

    @pytest.mark.asyncio
    async def test_match_is_case_insensitive_substring(self, client: AsyncClient):
        await _create_chat(client, "My VINTAGE grading session")

        response = await client.get("/api/search", params={"q": "vintage"})
        assert response.status_code == 200
        assert [c["name"] for c in response.json()["chats"]] == [
            "My VINTAGE grading session"
        ]

    @pytest.mark.asyncio
    async def test_prefix_matches_rank_before_substring(self, client: AsyncClient):
        # Substring match created last (newest updated_at) — prefix still wins.
        await _create_board(client, "Polar expedition")
        await _create_board(client, "North pole moodboard")

        response = await client.get("/api/search", params={"q": "pol"})
        assert response.status_code == 200
        names = [b["name"] for b in response.json()["boards"]]
        assert names.index("Polar expedition") < names.index("North pole moodboard")

    @pytest.mark.asyncio
    async def test_soft_deleted_excluded(self, client: AsyncClient):
        board_id = await _create_board(client, "Doomed board xq")
        delete = await client.delete(f"/api/boards/{board_id}")
        assert delete.status_code == 200

        response = await client.get("/api/search", params={"q": "doomed board xq"})
        assert response.status_code == 200
        assert response.json()["boards"] == []

    @pytest.mark.asyncio
    async def test_flow_backed_chats_excluded(self, client: AsyncClient):
        flow_id = await _create_flow(client, "Zebra flow host")
        response = await client.post(
            "/api/chats", json={"name": "Zebra flow chat", "flow_id": flow_id}
        )
        assert response.status_code == 200

        response = await client.get("/api/search", params={"q": "zebra"})
        assert response.status_code == 200
        data = response.json()
        assert [c["name"] for c in data["chats"]] == []
        assert [f["name"] for f in data["flows"]] == ["Zebra flow host"]

    @pytest.mark.asyncio
    async def test_token_match_ignores_punctuation_and_order(self, client: AsyncClient):
        await _create_chat(client, "Flux.2 Space Pro session")

        # "flux2" must match "Flux.2" and tokens may be scattered/out of order.
        for query in ("flux2 pro", "pro flux2", "FLUX2 space"):
            response = await client.get("/api/search", params={"q": query})
            assert response.status_code == 200
            names = [c["name"] for c in response.json()["chats"]]
            assert "Flux.2 Space Pro session" in names, query

    @pytest.mark.asyncio
    async def test_contiguous_match_ranks_above_scattered(self, client: AsyncClient):
        # Contiguous match created FIRST (older) so recency alone can't win.
        await _create_board(client, "Old Klein2 Pro board")  # contiguous, older
        await _create_board(client, "Klein.2 Space Pro")  # scattered, newer

        response = await client.get("/api/search", params={"q": "klein2 pro"})
        assert response.status_code == 200
        names = [b["name"] for b in response.json()["boards"]]
        assert names.index("Old Klein2 Pro board") < names.index("Klein.2 Space Pro")

    @pytest.mark.asyncio
    async def test_project_scope_filters_entities(self, client: AsyncClient):
        project_id = await _create_project(client, "Scopetest project")
        response = await client.post(
            "/api/chats", json={"name": "Scopetest chat inside", "project_id": project_id}
        )
        assert response.status_code == 200
        await _create_chat(client, "Scopetest chat outside")

        scoped = await client.get(
            "/api/search", params={"q": "scopetest", "project_id": project_id}
        )
        assert scoped.status_code == 200
        data = scoped.json()
        assert [c["name"] for c in data["chats"]] == ["Scopetest chat inside"]
        assert data["projects"] == []  # project list suppressed under scope

        unscoped = await client.get("/api/search", params={"q": "scopetest"})
        names = [c["name"] for c in unscoped.json()["chats"]]
        assert "Scopetest chat inside" in names and "Scopetest chat outside" in names

    @pytest.mark.asyncio
    async def test_all_tokens_must_match(self, client: AsyncClient):
        await _create_chat(client, "Zanzibar sunset")

        response = await client.get("/api/search", params={"q": "zanzibar mountains"})
        assert response.status_code == 200
        assert response.json()["chats"] == []

    @pytest.mark.asyncio
    async def test_limit_caps_each_type(self, client: AsyncClient):
        for i in range(5):
            await _create_chat(client, f"Limitcase chat {i}")

        response = await client.get("/api/search", params={"q": "limitcase", "limit": 3})
        assert response.status_code == 200
        assert len(response.json()["chats"]) == 3
