"""User Tools Provider — hosts flows frozen into first-class tools.

Each ``UserTool`` row is a flow frozen into a tool: a self-contained
``program_text`` snapshot plus a canonical STP interface (``parameter_schema``
/ ``output_schema`` / ``task_types``). This provider loads those rows from the
current profile DB, exposes one ``ToolDescriptor`` per row, and executes them
via ``flow_runtime.oneshot.run_flow_once`` — running the flow in an ephemeral
scope so there are zero library side effects (see plans/FLOW_TO_TOOL.md §7).

The single canonical output media item is created by the normal outer
tool-invocation path; this provider returns only the declared output's bytes.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from sqlalchemy import select

from .base import (
    ExecutionProgress,
    ExecutionResult,
    ProviderStatus,
    ToolDescriptor,
    ToolProvider,
)

logger = logging.getLogger(__name__)


def _open_session():
    """Open a fresh AsyncSession bound to the current profile's DB."""
    from core.profile_context import get_current_profile
    from database_registry import get_database_registry

    profile_id = get_current_profile()
    db = get_database_registry().get_database(profile_id)
    return db.async_session_maker()


def _make_hitl_resolver(hitl_policies: Dict[str, Any]) -> Optional[Callable]:
    """Compile per-equation freeze policies into a one-shot HITL resolver.

    ``hitl_policies`` maps an equation key to a policy descriptor, e.g.
    ``{"hitl_3": {"policy": "first"}}``. Supported policies:

    - ``first`` / ``accept_first`` — select the first candidate, approve True.
    - ``random`` — select a random candidate, approve True.

    Anything unmapped falls back to the oneshot ``_default_hitl_resolver``
    behavior (first candidate / accept).
    """
    if not hitl_policies:
        return None

    import random

    from flow_runtime.oneshot import OneShotError, _default_hitl_resolver

    def _resolver(eq, resolved_inputs: Dict[str, Any]) -> Any:
        policy_entry = hitl_policies.get(eq.key) or {}
        policy = (policy_entry.get("policy") or "").strip().lower()
        hitl_type = eq.definition.get("hitl_type")

        if hitl_type == "select":
            candidates = resolved_inputs.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                raise OneShotError(f"{eq.key}: hitl.select had no candidates to resolve")
            count = int(eq.definition.get("count", 1) or 1)
            if policy == "random":
                chosen = random.sample(candidates, min(count, len(candidates)))
                return chosen[0] if count == 1 else chosen
            # "first" / "accept_first" / unmapped -> deterministic first(s)
            return candidates[0] if count == 1 else candidates[:count]

        if hitl_type == "approve":
            return True

        # Unknown hitl type with no usable policy: defer to the default.
        return _default_hitl_resolver(eq, resolved_inputs)

    return _resolver


class UserToolsProvider(ToolProvider):
    """Provider for flows frozen into first-class tools."""

    def __init__(self):
        self._status = ProviderStatus.DISCONNECTED
        self._descriptors: Dict[str, ToolDescriptor] = {}
        self._rows: Dict[str, Any] = {}  # tool_id -> UserTool.to_dict()
        self._assets: Dict[str, bytes] = {}

    @property
    def provider_id(self) -> str:
        return "user-tools"

    @property
    def provider_name(self) -> str:
        return "Custom Tools"

    @property
    def provider_type(self) -> str:
        return "user-tools"

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def max_concurrent(self) -> int:
        return 2

    async def connect(self) -> None:
        """Load all live UserTool rows and build descriptors."""
        self._status = ProviderStatus.CONNECTING
        try:
            await self._load_tools()
            self._status = ProviderStatus.CONNECTED
            logger.info(
                f"UserToolsProvider connected with {len(self._descriptors)} tools"
            )
        except Exception as e:
            self._status = ProviderStatus.ERROR
            logger.error(f"Failed to connect UserToolsProvider: {e}", exc_info=True)
            raise

    async def disconnect(self) -> None:
        self._status = ProviderStatus.DISCONNECTED
        self._descriptors.clear()
        self._rows.clear()
        self._assets.clear()
        logger.info("UserToolsProvider disconnected")

    async def _load_tools(self) -> None:
        """Load UserTool rows (deleted_at IS NULL) and build descriptors."""
        from database import UserTool

        descriptors: Dict[str, ToolDescriptor] = {}
        rows: Dict[str, Any] = {}

        async with _open_session() as session:
            result = await session.execute(
                select(UserTool).where(UserTool.deleted_at.is_(None))
            )
            from user_tools_service import slugify_tool_name

            for row in result.scalars().all():
                # Stable id: a slug frozen at creation (survives renames) + row id
                # (keeps it unique). Fall back to a name-derived slug for any
                # legacy row created before the slug column existed.
                slug = row.slug or slugify_tool_name(row.name)
                tool_id = f"{slug}-{row.id}"
                task_types = json.loads(row.task_types) if row.task_types else []
                parameter_schema = (
                    json.loads(row.parameter_schema) if row.parameter_schema else {}
                )
                output_schema = json.loads(row.output_schema) if row.output_schema else {}

                descriptors[tool_id] = ToolDescriptor(
                    id=tool_id,
                    name=row.name,
                    description=row.description,
                    task_type=task_types[0] if task_types else None,
                    task_types=task_types,
                    parameter_schema=parameter_schema,
                    output_schema=output_schema,
                    metadata={
                        "flow_id": row.flow_id,
                        "user_tool_id": row.id,
                        "provenance": "user-flow",
                    },
                )
                # to_dict() omits program_text (kept out of API responses); the
                # provider needs the runnable body to execute, so include it here.
                rows[tool_id] = {**row.to_dict(), "program_text": row.program_text}

        self._descriptors = descriptors
        self._rows = rows

    async def list_tools(self) -> List[ToolDescriptor]:
        return list(self._descriptors.values())

    async def get_tool(self, tool_id: str) -> Optional[ToolDescriptor]:
        return self._descriptors.get(tool_id)

    async def refresh_tools(self) -> List[ToolDescriptor]:
        await self._load_tools()
        return list(self._descriptors.values())

    async def upload_asset(self, data: bytes, mime_type: str) -> str:
        asset_id = f"user_tools_{uuid.uuid4().hex}"
        self._assets[asset_id] = data
        return asset_id

    async def download_asset(self, asset_id: str) -> bytes:
        if asset_id not in self._assets:
            raise ValueError(f"Asset not found: {asset_id}")
        return self._assets[asset_id]

    async def execute(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        output_path: Optional[str] = None,
        progress_callback: Optional[Callable[[ExecutionProgress], None]] = None,
        request_id: Optional[str] = None,
    ) -> AsyncIterator[ExecutionProgress | ExecutionResult]:
        """Run the frozen flow once and yield its declared output bytes."""
        from flow_runtime.oneshot import run_flow_once

        row = self._rows.get(tool_id)
        if not row:
            yield ExecutionResult(success=False, error=f"Unknown tool: {tool_id}")
            return

        yield ExecutionProgress(
            progress=0.0,
            stage="starting",
            message=f"Running {row.get('name') or tool_id}...",
        )

        try:
            hitl_policies = row.get("hitl_policies") or {}
            output_map = row.get("output_map") or {}
            output_schema = row.get("output_schema") or {}
            parameter_schema = row.get("parameter_schema") or {}
            flow_id = row.get("flow_id") or 0

            resolver = _make_hitl_resolver(hitl_policies)

            # Pass ONLY the flow's declared inputs. The generation/tool-call path
            # injects extras (prompt_metadata, seed, ...) the flow function does not
            # accept — passing them through raises "unexpected keyword argument".
            declared = set((parameter_schema.get("properties") or {}).keys())
            flow_inputs = {k: v for k, v in (parameters or {}).items() if k in declared}

            result = await run_flow_once(
                flow_id=flow_id,
                inputs=flow_inputs,
                program_text=row["program_text"],
                hitl_resolver=resolver,
                model_slug=row.get("model_slug"),
            )

            # Resolve the task's required output (e.g. "assets" / "detections")
            # to the flow output name via output_map, then to a OneShotValue.
            required_outputs = list((output_schema.get("properties") or {}).keys())
            target_key = required_outputs[0] if required_outputs else None

            flow_output_name = None
            if target_key and target_key in output_map:
                flow_output_name = output_map[target_key]
            elif output_map:
                # No matching task key — take the single mapping we have.
                flow_output_name = next(iter(output_map.values()))

            one_shot_value = None
            if flow_output_name and flow_output_name in result.outputs:
                one_shot_value = result.outputs[flow_output_name]
            elif result.outputs:
                # Fall back to the flow's first declared output.
                one_shot_value = next(iter(result.outputs.values()))

            if one_shot_value is None or not one_shot_value.media:
                yield ExecutionResult(
                    success=False,
                    error="Frozen flow produced no output media",
                )
                return

            output_media = one_shot_value.media[0]

            if output_path:
                with open(output_path, "wb") as f:
                    f.write(output_media.data)

            yield ExecutionProgress(progress=1.0, stage="complete", message="Complete")

            yield ExecutionResult(
                success=True,
                output_data=output_media.data,
                metadata={
                    "output_path": output_path,
                    "file_format": output_media.file_format,
                    "user_tool_id": row.get("id"),
                    "flow_id": flow_id,
                },
            )

        except Exception as e:
            logger.error(
                f"User tool {tool_id} failed: {e}", exc_info=True
            )
            yield ExecutionResult(success=False, error=str(e))


# Singleton instance
_user_tools_provider: Optional[UserToolsProvider] = None


def get_user_tools_provider() -> UserToolsProvider:
    """Get the singleton UserToolsProvider instance."""
    global _user_tools_provider
    if _user_tools_provider is None:
        _user_tools_provider = UserToolsProvider()
    return _user_tools_provider


async def refresh() -> None:
    """Re-load tools and refresh the registry so a freshly frozen tool
    registers immediately (and a deleted one disappears).

    Also broadcasts ``tools_updated`` over the WebSocket so open views (ToolView,
    AllToolsView, the sidebar) re-fetch live — the registry's own refresh only
    fires in-process subscribers, not a client broadcast, so without this an
    edited/resynced tool would look stale until a manual reload.
    """
    provider = get_user_tools_provider()
    await provider._load_tools()
    try:
        from .registry import ProviderRegistry

        registry = ProviderRegistry.get_instance()
        if registry.get_provider(provider.provider_id) is not None:
            await registry.refresh_tools(provider.provider_id, force_refresh=True)
    except Exception as e:  # noqa: BLE001 — refresh is best-effort
        logger.warning(f"UserToolsProvider registry refresh skipped: {e}")

    try:
        from utils.websocket import ws_manager

        await ws_manager.broadcast(
            "tools_updated", {"provider_id": provider.provider_id}
        )
    except Exception as e:  # noqa: BLE001 — broadcast is best-effort
        logger.warning(f"UserToolsProvider tools_updated broadcast skipped: {e}")
