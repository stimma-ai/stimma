"""Tests for the summary view of GET /api/tools/providers/tools.

Launcher, picker and search surfaces render only names, task types,
availability and a few display keys, so the catalog can be read without every
tool's input/output schemas (``view=summary``). The full tool, schemas
included, still comes from /provider-tool/{full_tool_id} when a tool is
opened, and the default view stays the full catalog for older clients.
"""

import json
import re
from pathlib import Path

import httpx

from routes.tools import OUTLINE_PARAMETER_NAMES, PARAMETER_OUTLINE_KEYS, SUMMARY_METADATA_KEYS

SCHEMA_FIELDS = {"parameter_schema", "output_schema", "layout"}


async def _catalog(client: httpx.AsyncClient, **params):
    response = await client.get("/api/tools/providers/tools", params=params)
    assert response.status_code == 200, response.text
    return response


class TestCatalogSummaryView:
    async def test_default_view_is_the_full_catalog(self, generation_client: httpx.AsyncClient):
        tools = (await _catalog(generation_client)).json()
        assert tools, "the test app registers tools"
        for tool in tools:
            assert SCHEMA_FIELDS <= tool.keys()
        assert any(tool["parameter_schema"].get("properties") for tool in tools)

    async def test_summary_lists_the_same_tools_without_schemas(self, generation_client: httpx.AsyncClient):
        full = (await _catalog(generation_client)).json()
        summary = (await _catalog(generation_client, view="summary")).json()

        assert [t["full_tool_id"] for t in summary] == [t["full_tool_id"] for t in full]
        by_id = {t["full_tool_id"]: t for t in full}
        for entry in summary:
            assert not (SCHEMA_FIELDS & entry.keys()), entry["full_tool_id"]
            tool = by_id[entry["full_tool_id"]]
            for field in ("tool_id", "name", "subtitle", "task_type", "task_types", "provider_id",
                          "provider_name", "model_vendor", "model", "availability", "preview_frames"):
                assert entry[field] == tool[field], field
            assert entry["metadata"] == {
                key: tool["metadata"][key] for key in SUMMARY_METADATA_KEYS if key in tool["metadata"]
            }
            properties = tool["parameter_schema"].get("properties")
            if not isinstance(properties, dict):
                assert entry["parameter_outline"] == {}
                continue
            assert entry["parameter_outline"] == {"properties": {
                name: {key: schema[key] for key in PARAMETER_OUTLINE_KEYS if key in schema}
                for name, schema in properties.items()
                if name in OUTLINE_PARAMETER_NAMES or "x-accept-media" in schema
            }}

    def test_outline_covers_the_frontend_media_slots(self):
        # The frontend's send-to checks read these slots from the outline, so
        # every slot it knows must be kept.
        source = (Path(__file__).parents[2] / "frontend/src/utils/taskTypeIcons.ts").read_text()
        table = re.search(r"MEDIA_INPUT_SLOT_DEFAULTS[^{]*\{([^}]*)\}", source)
        assert table, "MEDIA_INPUT_SLOT_DEFAULTS not found"
        slots = set(re.findall(r"^\s*(\w+)\s*:", table.group(1), re.MULTILINE))
        assert "input_images" in slots
        assert slots <= OUTLINE_PARAMETER_NAMES

    async def test_summary_keeps_what_send_to_menus_check(self, generation_client: httpx.AsyncClient):
        # Built-in filters declare per-slot x-accept-media and image tools take
        # array slots with item limits; menus route media by exactly these.
        summary = (await _catalog(generation_client, view="summary")).json()
        slots = [
            schema
            for entry in summary
            for schema in entry["parameter_outline"].get("properties", {}).values()
        ]
        assert any("x-accept-media" in slot for slot in slots), "some test tool declares x-accept-media"
        assert any(slot.get("type") == "array" for slot in slots)
        for slot in slots:
            assert set(slot) <= set(PARAMETER_OUTLINE_KEYS)

    async def test_summary_is_much_smaller(self, generation_client: httpx.AsyncClient):
        full = await _catalog(generation_client)
        summary = await _catalog(generation_client, view="summary")
        full_bytes, summary_bytes = len(full.content), len(summary.content)
        print(f"catalog bytes: full={full_bytes} summary={summary_bytes} tools={len(full.json())}")
        assert summary_bytes * 5 < full_bytes

    async def test_summary_honours_filters(self, generation_client: httpx.AsyncClient):
        full = (await _catalog(generation_client, task_type="text-to-image", include_unavailable="false")).json()
        summary = (await _catalog(generation_client, task_type="text-to-image", include_unavailable="false", view="summary")).json()
        assert full
        assert [t["full_tool_id"] for t in summary] == [t["full_tool_id"] for t in full]

    async def test_full_tool_still_carries_its_schema(self, generation_client: httpx.AsyncClient):
        summary = (await _catalog(generation_client, view="summary")).json()
        entry = next(t for t in summary if t["parameter_outline"].get("properties"))
        response = await generation_client.get(f"/api/tools/provider-tool/{entry['full_tool_id']}")
        assert response.status_code == 200, response.text
        tool = response.json()
        properties = tool["parameter_schema"]["properties"]
        assert set(entry["parameter_outline"]["properties"]) < set(properties)
        assert "prompt" in properties
        assert "output_schema" in tool

    async def test_unknown_view_is_rejected(self, generation_client: httpx.AsyncClient):
        response = await generation_client.get("/api/tools/providers/tools", params={"view": "tiny"})
        assert response.status_code == 422

    async def test_summary_metadata_drops_large_keys(self, generation_client: httpx.AsyncClient):
        summary = (await _catalog(generation_client, view="summary")).json()
        for entry in summary:
            assert set(entry["metadata"]) <= set(SUMMARY_METADATA_KEYS)
            assert "layout" not in json.dumps(entry["metadata"])
