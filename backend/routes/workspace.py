"""The shared workspace: what every client of a profile sees as one."""
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import workspace_service as service
from core.dependencies import get_db_session
from utils.websocket import ws_manager

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class WorkspaceOp(BaseModel):
    namespace: str
    key: str
    # Absent means "not replacing". Pydantic can't tell absent from null on its
    # own, so model_fields_set decides.
    value: Any = None
    set: Optional[dict] = None
    unset: Optional[List[str]] = None
    deleted: bool = False

    def as_op(self) -> dict:
        op: dict = {"namespace": self.namespace, "key": self.key}
        if self.deleted:
            op["deleted"] = True
        elif "value" in self.model_fields_set:
            op["value"] = self.value
        else:
            op["set"] = self.set or {}
            op["unset"] = self.unset or []
        return op


class WorkspaceOpsRequest(BaseModel):
    origin: Optional[str] = None  # The writing client; it ignores its own event.
    ops: List[WorkspaceOp]


class MigratedDoc(BaseModel):
    namespace: str
    key: str
    value: Any = None


class WorkspaceMigrateRequest(BaseModel):
    client_id: str = Field(min_length=8, max_length=128)
    docs: List[MigratedDoc]
    meta: Optional[dict] = None


def _http_error(error: service.WorkspaceError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=str(error))


async def _announce(changes: list, origin: Optional[str]) -> None:
    if changes:
        await ws_manager.broadcast("workspace_docs_changed", service.event_payload(changes, origin))


@router.get("")
async def read_workspace(session: AsyncSession = Depends(get_db_session)):
    async with service.write_lock():
        return await service.snapshot(session)


@router.post("/docs")
async def write_docs(request: WorkspaceOpsRequest, session: AsyncSession = Depends(get_db_session)):
    async with service.write_lock():
        try:
            changes = await service.apply_ops(session, [op.as_op() for op in request.ops])
        except service.WorkspaceError as error:
            await session.rollback()
            raise _http_error(error)
        await session.commit()
        await _announce(changes, request.origin)
    return {"changes": [{"namespace": c["namespace"], "key": c["key"], "rev": c["rev"]} for c in changes]}


@router.get("/docs/{namespace}/{key:path}")
async def read_doc(namespace: str, key: str, session: AsyncSession = Depends(get_db_session)):
    doc = await service.get_doc(session, namespace, key)
    if doc is None:
        raise HTTPException(status_code=404, detail="Not found")
    return doc


@router.post("/migrate")
async def migrate_workspace(request: WorkspaceMigrateRequest, session: AsyncSession = Depends(get_db_session)):
    async with service.write_lock():
        try:
            result = await service.migrate(
                session,
                request.client_id,
                [doc.model_dump() for doc in request.docs],
                request.meta,
            )
        except service.WorkspaceError as error:
            await session.rollback()
            raise _http_error(error)
    changes = result.pop("changes")
    if changes:
        # Clients already open re-read rather than apply a whole import inline.
        await ws_manager.broadcast("workspace_reset", {"origin": request.client_id})
    return result


@router.get("/blobs/{key:path}")
async def read_blob(key: str, session: AsyncSession = Depends(get_db_session)):
    data = await service.get_blob(session, key)
    if data is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(content=data, media_type="application/octet-stream")


@router.put("/blobs/{key:path}")
async def write_blob(
    key: str,
    request: Request,
    origin: Optional[str] = Query(default=None),
    if_absent: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
):
    data = await request.body()
    async with service.write_lock():
        try:
            changes = await service.put_blob(session, key, data, if_absent)
        except service.WorkspaceError as error:
            await session.rollback()
            raise _http_error(error)
        await session.commit()
        await _announce(changes, origin)
    return {"changes": [{"namespace": c["namespace"], "key": c["key"], "rev": c["rev"]} for c in changes]}
