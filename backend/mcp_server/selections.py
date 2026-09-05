"""Stable all-match selections. Membership uses Assets; payloads pin revisions."""

import json
import time
import uuid
from database import Asset, AssetRevision
from .models import McpOperation
from .access import access, McpError
from .workspace import query_binding
from .jobs import fingerprint


async def create(caller, query, session):
    targets = []
    page = 1
    while True:
        result = await query_binding.run(
            caller, {**query, "page": page, "page_size": 200}, session
        )
        for item in result["items"]:
            asset_ref = item.get("asset_id") or item["id"]
            asset = await session.get(
                Asset, int(access.resolve(caller, asset_ref, "asset"))
            )
            revision = await session.get(AssetRevision, asset.current_revision_id)
            targets.append(
                {
                    "asset_ref": asset_ref,
                    "revision_ref": access.ref(caller, "revision", revision.id),
                    "media_ref": access.ref(caller, "media", revision.primary_media_id),
                }
            )
        if len(targets) > 10000:
            raise McpError(
                "selection_too_large", "Narrow this query to at most 10,000 Assets."
            )
        if len(targets) >= result["total"]:
            break
        if not result["items"]:
            raise McpError(
                "selection_changed", "The query changed during selection. Try again."
            )
        page += 1
    identifier = uuid.uuid4().hex
    data = {"targets": targets, "expires_at": time.time() + 86400}
    session.add(
        McpOperation(
            id=identifier,
            client_id=caller.client_id,
            operation="selection",
            request_key=identifier,
            input_hash=fingerprint(query),
            input_json=json.dumps(query),
            state="succeeded",
            result_json=json.dumps(data),
        )
    )
    await session.commit()
    return {
        "selection_ref": access.ref(caller, "selection", identifier),
        "count": len(targets),
        "expires_at": data["expires_at"],
    }


async def read(caller, reference, offset, session):
    identifier = access.resolve(caller, reference, "selection")
    row = await session.get(McpOperation, identifier)
    if not row or row.operation != "selection" or row.deleted_at:
        raise McpError("not_found", "Selection is unavailable.")
    data = json.loads(row.result_json)
    if data["expires_at"] < time.time():
        raise McpError(
            "selection_expired", "Create a fresh selection before starting new work."
        )
    targets = data["targets"]
    return {
        "items": targets[offset : offset + 200],
        "count": len(targets),
        "next_offset": offset + 200 if offset + 200 < len(targets) else None,
    }
