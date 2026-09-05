"""Explicit, temporary desktop selection snapshots; no ambient window reads."""

import time
from database import Asset, AssetRevision
from .access import access, Caller, McpError

_snapshots = {}


async def share(profile_id, asset_ids, session):
    _, db, stamp = access.stamp(profile_id)
    caller = Caller(profile_id, "desktop", db.db_guid, stamp)
    targets = []
    for identifier in dict.fromkeys(asset_ids):
        asset = await session.get(Asset, identifier)
        if not asset or asset.deleted_at:
            raise McpError("not_found", "A selected Asset is unavailable.")
        revision = await session.get(AssetRevision, asset.current_revision_id)
        targets.append(
            {
                "asset_ref": access.ref(caller, "asset", asset.id),
                "revision_ref": access.ref(caller, "revision", revision.id),
                "media_ref": access.ref(caller, "media", revision.primary_media_id),
            }
        )
    result = {"shared": True, "targets": targets, "expires_at": time.time() + 600}
    _snapshots[profile_id] = stamp, result
    return result


def read(caller):
    snapshot = _snapshots.get(caller.profile_id)
    if (
        not snapshot
        or snapshot[0] != caller.stamp
        or snapshot[1]["expires_at"] < time.time()
    ):
        return {"shared": False, "targets": []}
    return snapshot[1]


def clear(profile_id):
    _snapshots.pop(profile_id, None)
