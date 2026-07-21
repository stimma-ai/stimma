"""
Provider Registry - manages registered providers and their lifecycle.

The registry is the central point for:
- Registering/unregistering providers
- Looking up tools by full_tool_id (provider_id:tool_id)
- Listing all available tools across all providers
- Subscribing to provider status changes
- Caching tool metadata to database for offline display
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set, Tuple

from .base import ProviderStatus, ToolDescriptor, ToolProvider

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Singleton registry for tool providers.

    Manages provider lifecycle and provides unified tool lookup.
    """

    _instance: Optional["ProviderRegistry"] = None
    _lock: asyncio.Lock

    def __new__(cls) -> "ProviderRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._providers: Dict[str, ToolProvider] = {}
        self._tools_cache: Dict[str, Tuple[ToolProvider, ToolDescriptor]] = {}
        self._status_subscribers: List[Callable[[str, ProviderStatus], None]] = []
        # Subscribers fired whenever the set of available tools changes —
        # provider registered/unregistered, refresh_tools updated a provider's
        # tool list, etc. Used by the flow engine to self-heal equations
        # that were parked in WAITING_FOR_TOOL once their tool reappears.
        self._tools_changed_subscribers: List[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._initialized = True

    # --- Database Caching ---

    async def _get_db_session_makers(self):
        """Return every profile database that carries the global tool cache."""
        from database_registry import get_database_registry

        registry = get_database_registry()
        return [
            registry.get_database(profile["id"]).async_session_maker
            for profile in registry.list_profiles()
        ]

    async def _cache_tools_to_db(self, provider: ToolProvider, tools: List[ToolDescriptor]) -> None:
        """Cache tools from provider to database for offline display.

        This upserts all tools from the provider and retires cached tools that
        were not in this registration.  Retired descriptors remain available
        for historical Media-lineage display.
        """
        from database import CachedProviderTool
        from sqlalchemy import select

        session_makers = await self._get_db_session_makers()
        if not session_makers:
            return

        for session_maker in session_makers:
            async with session_maker() as session:
                try:
                    provider_id = provider.provider_id
                    provider_name = provider.provider_name
                    now = datetime.utcnow()

                    registered_ids = set()

                    for tool in tools:
                        full_tool_id = f"{provider_id}:{tool.id}"
                        registered_ids.add(full_tool_id)

                        result = await session.execute(
                            select(CachedProviderTool).where(
                                CachedProviderTool.full_tool_id == full_tool_id
                            )
                        )
                        cached = result.scalar_one_or_none()

                        task_types_json = (
                            json.dumps(tool.task_types) if tool.task_types else None
                        )

                        if cached:
                            cached.provider_name = provider_name
                            cached.name = tool.name
                            cached.task_type = tool.task_type
                            cached.task_types = task_types_json
                            cached.model_vendor = tool.model_vendor
                            cached.model = tool.model
                            cached.parameter_schema = (
                                json.dumps(tool.parameter_schema)
                                if tool.parameter_schema
                                else None
                            )
                            cached.output_schema = (
                                json.dumps(tool.output_schema)
                                if tool.output_schema
                                else None
                            )
                            cached.tool_metadata = (
                                json.dumps(tool.metadata) if tool.metadata else None
                            )
                            cached.last_registered_at = now
                            cached.deleted_at = None
                        else:
                            session.add(CachedProviderTool(
                                full_tool_id=full_tool_id,
                                provider_id=provider_id,
                                provider_name=provider_name,
                                tool_id=tool.id,
                                name=tool.name,
                                task_type=tool.task_type,
                                task_types=task_types_json,
                                model_vendor=tool.model_vendor,
                                model=tool.model,
                                parameter_schema=(
                                    json.dumps(tool.parameter_schema)
                                    if tool.parameter_schema
                                    else None
                                ),
                                output_schema=(
                                    json.dumps(tool.output_schema)
                                    if tool.output_schema
                                    else None
                                ),
                                tool_metadata=(
                                    json.dumps(tool.metadata)
                                    if tool.metadata
                                    else None
                                ),
                                last_registered_at=now,
                            ))

                    result = await session.execute(
                        select(CachedProviderTool).where(
                            CachedProviderTool.provider_id == provider_id,
                            CachedProviderTool.deleted_at.is_(None),
                        )
                    )
                    all_cached = result.scalars().all()

                    for cached in all_cached:
                        if cached.full_tool_id not in registered_ids:
                            cached.deleted_at = now

                    await session.commit()

                except Exception as e:
                    logger.error(
                        f"Error caching tools for provider {provider.provider_id}: {e}"
                    )
                    await session.rollback()
        logger.info(
            f"Cached {len(tools)} tools from provider {provider.provider_id} "
            f"across {len(session_makers)} profiles"
        )

    async def _broadcast_provider_status(self, provider_id: str, status: str, tool_count: int = 0) -> None:
        """Broadcast provider status change via WebSocket."""
        try:
            from utils.websocket import ws_manager
            await ws_manager.broadcast("provider_status_changed", {
                "provider_id": provider_id,
                "status": status,
                "tool_count": tool_count,
            })
        except Exception as e:
            logger.error(f"Error broadcasting provider status: {e}")

    # --- Provider Management ---

    async def register(self, provider: ToolProvider) -> None:
        """
        Register and connect a provider.

        Args:
            provider: The provider to register

        Raises:
            ValueError: If provider_id is already registered
            ConnectionError: If provider fails to connect
        """
        async with self._lock:
            if provider.provider_id in self._providers:
                raise ValueError(f"Provider already registered: {provider.provider_id}")

            logger.info(f"Registering provider: {provider.provider_id}")

            # Connect the provider
            await provider.connect()

            # Add to registry
            self._providers[provider.provider_id] = provider

            # Cache tools in memory
            await self._refresh_tools_for_provider(provider)

            tool_count = len([t for t in self._tools_cache.values() if t[0] == provider])
            logger.info(
                f"Provider registered: {provider.provider_id} "
                f"with {tool_count} tools"
            )

            # Copy tools list while holding lock to avoid "dict changed size during iteration"
            tools = [tool for p, tool in self._tools_cache.values() if p == provider]

        # Cache tools to database (outside lock to avoid blocking)
        try:
            await self._cache_tools_to_db(provider, tools)
        except Exception as e:
            logger.error(f"Failed to cache tools to database: {e}")

        # Broadcast status change
        await self._broadcast_provider_status(
            provider.provider_id, "connected", tool_count
        )
        # Wake up any consumers that are parked on a missing tool (flow
        # engine most notably). Fire after the DB cache + WS broadcast so
        # subscribers see a fully consistent registry.
        self._notify_tools_changed()

    async def unregister(self, provider_id: str) -> None:
        """
        Disconnect and unregister a provider.

        Args:
            provider_id: The provider ID to unregister
        """
        async with self._lock:
            provider = self._providers.pop(provider_id, None)
            if provider:
                logger.info(f"Unregistering provider: {provider_id}")

                # Disconnect
                try:
                    await provider.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting provider {provider_id}: {e}")

                # Clear tool cache for this provider
                self._tools_cache = {
                    full_id: entry
                    for full_id, entry in self._tools_cache.items()
                    if entry[0] != provider
                }

                # Notify subscribers
                self._notify_status_change(provider_id, ProviderStatus.DISCONNECTED)

        # Broadcast disconnect (outside lock)
        if provider:
            await self._broadcast_provider_status(provider_id, "disconnected", 0)
            self._notify_tools_changed()

    async def _refresh_tools_for_provider(
        self,
        provider: ToolProvider,
        force_refresh: bool = False
    ) -> None:
        """
        Refresh the tool cache for a specific provider.

        Args:
            provider: The provider to refresh
            force_refresh: If True, call provider.refresh_tools() to trigger
                          re-discovery (e.g., LoRAs). If False, just re-list.
        """
        # Clear existing tools for this provider
        self._tools_cache = {
            full_id: entry
            for full_id, entry in self._tools_cache.items()
            if entry[0] != provider
        }

        # Cache new tools
        try:
            if force_refresh:
                # Trigger provider's refresh logic (e.g., re-discover LoRAs)
                tools = await provider.refresh_tools()
            else:
                tools = await provider.list_tools()
            for tool in tools:
                full_id = f"{provider.provider_id}:{tool.id}"
                self._tools_cache[full_id] = (provider, tool)

            # Update DB cache to match (removes tools no longer provided)
            try:
                await self._cache_tools_to_db(provider, tools)
            except Exception as e:
                logger.error(f"Failed to update DB cache for {provider.provider_id}: {e}")
        except Exception as e:
            logger.error(f"Error listing tools from {provider.provider_id}: {e}")

    async def refresh_tools(
        self,
        provider_id: Optional[str] = None,
        force_refresh: bool = True
    ) -> None:
        """
        Refresh the tool cache.

        Args:
            provider_id: Optional - refresh only this provider, or all if None
            force_refresh: If True, triggers provider.refresh_tools() which may
                          re-discover LoRAs or other dynamic data. Default True.
        """
        async with self._lock:
            if provider_id:
                provider = self._providers.get(provider_id)
                if provider:
                    await self._refresh_tools_for_provider(provider, force_refresh)
            else:
                for provider in self._providers.values():
                    await self._refresh_tools_for_provider(provider, force_refresh)
        self._notify_tools_changed()

    # --- Provider Lookup ---

    def get_provider(self, provider_id: str) -> Optional[ToolProvider]:
        """Get a provider by ID."""
        return self._providers.get(provider_id)

    def list_providers(self) -> List[ToolProvider]:
        """List all registered providers."""
        return list(self._providers.values())

    def get_provider_ids(self) -> Set[str]:
        """Get set of all registered provider IDs."""
        return set(self._providers.keys())

    def get_configured_provider_ids(self) -> Set[str]:
        """Get set of provider IDs from current config."""
        from config import get_settings
        settings = get_settings()
        return {p.id for p in settings.tool_providers}

    def get_enabled_provider_ids(self) -> Set[str]:
        """Get set of provider IDs that are enabled.

        Includes:
        - Config-based providers with enabled=true
        - Stimma Cloud when it has no explicit disabled config entry
        - Programmatically registered providers (builtin) that aren't in config
        """
        from config import get_settings
        from tool_provider_identity import STIMMA_TOOL_PROVIDER_ID
        settings = get_settings()

        # Start with config-based enabled providers
        enabled = {p.id for p in settings.tool_providers if p.enabled}

        # Stimma Cloud is account-managed and normally has no config row. It
        # remains a known, enabled provider while signed out so its cached tools
        # can render as disconnected; an explicit disabled row still hides it.
        cloud_config = next(
            (p for p in settings.tool_providers if p.id == STIMMA_TOOL_PROVIDER_ID),
            None,
        )
        if cloud_config is None:
            enabled.add(STIMMA_TOOL_PROVIDER_ID)

        # Also include connected providers that aren't in config (programmatic providers)
        # Copy keys to avoid "dict changed size during iteration"
        config_ids = {p.id for p in settings.tool_providers}
        provider_ids = list(self._providers.keys())
        for pid in provider_ids:
            if pid not in config_ids:
                enabled.add(pid)

        return enabled

    async def soft_delete_provider_tools(self, provider_id: str) -> None:
        """Soft-delete cached tools when a provider is removed from config.

        This marks tools as deleted_at so they won't be shown in the UI,
        but preserves the data in case the provider is re-added.
        """
        from database import CachedProviderTool
        from sqlalchemy import select

        session_makers = await self._get_db_session_makers()
        if not session_makers:
            return

        deleted_count = 0
        for session_maker in session_makers:
            async with session_maker() as session:
                try:
                    now = datetime.utcnow()
                    result = await session.execute(
                        select(CachedProviderTool).where(
                            CachedProviderTool.provider_id == provider_id,
                            CachedProviderTool.deleted_at.is_(None),
                        )
                    )
                    cached_tools = result.scalars().all()

                    for tool in cached_tools:
                        tool.deleted_at = now

                    await session.commit()
                    deleted_count += len(cached_tools)

                except Exception as e:
                    logger.error(
                        f"Error soft-deleting tools for provider {provider_id}: {e}"
                    )
                    await session.rollback()

        logger.info(
            f"Soft-deleted {deleted_count} cached tools for unconfigured provider "
            f"{provider_id} across {len(session_makers)} profiles"
        )
        await self._broadcast_provider_status(provider_id, "unconfigured", 0)

    # --- Tool Lookup ---

    def get_tool(self, full_tool_id: str) -> Optional[Tuple[ToolProvider, ToolDescriptor]]:
        """
        Get tool by full ID (provider_id:tool_id).

        Lookup is case-insensitive to handle agent variations.

        Returns:
            Tuple of (provider, tool_descriptor) or None if not found
        """
        # Try exact match first
        result = self._tools_cache.get(full_tool_id)
        if result:
            return result

        # Try case-insensitive match
        full_tool_id_lower = full_tool_id.lower()
        for cached_id, cached_tool in self._tools_cache.items():
            if cached_id.lower() == full_tool_id_lower:
                return cached_tool

        return None

    def list_all_tools(self) -> List[Tuple[str, ToolProvider, ToolDescriptor]]:
        """
        List all tools across all providers.

        Returns:
            List of (full_tool_id, provider, tool_descriptor) tuples
        """
        # Copy items to avoid "dict changed size during iteration"
        cache_snapshot = list(self._tools_cache.items())
        return [
            (full_id, provider, tool)
            for full_id, (provider, tool) in cache_snapshot
        ]

    def list_tools_by_task_type(self, task_type: str) -> List[Tuple[str, ToolProvider, ToolDescriptor]]:
        """
        List all tools that handle a specific task type.

        Args:
            task_type: e.g., "text-to-image", "image-to-image"

        Returns:
            List of (full_tool_id, provider, tool_descriptor) tuples
        """
        # Copy items to avoid "dict changed size during iteration"
        cache_snapshot = list(self._tools_cache.items())
        return [
            (full_id, provider, tool)
            for full_id, (provider, tool) in cache_snapshot
            if task_type in tool.task_types or tool.task_type == task_type
        ]

    def list_tools_by_provider(self, provider_id: str) -> List[Tuple[str, ToolDescriptor]]:
        """
        List all tools from a specific provider.

        Returns:
            List of (full_tool_id, tool_descriptor) tuples
        """
        # Copy items to avoid "dict changed size during iteration"
        cache_snapshot = list(self._tools_cache.items())
        return [
            (full_id, tool)
            for full_id, (provider, tool) in cache_snapshot
            if provider.provider_id == provider_id
        ]

    # --- Status Subscriptions ---

    def subscribe_status(self, callback: Callable[[str, ProviderStatus], None]) -> None:
        """
        Subscribe to provider status changes.

        Args:
            callback: Function called with (provider_id, new_status)
        """
        self._status_subscribers.append(callback)

    def unsubscribe_status(self, callback: Callable[[str, ProviderStatus], None]) -> None:
        """Unsubscribe from provider status changes."""
        if callback in self._status_subscribers:
            self._status_subscribers.remove(callback)

    def _notify_status_change(self, provider_id: str, status: ProviderStatus) -> None:
        """Notify all subscribers of a status change."""
        for callback in self._status_subscribers:
            try:
                callback(provider_id, status)
            except Exception as e:
                logger.error(f"Error in status subscriber: {e}")

    def subscribe_tools_changed(self, callback: Callable[[], None]) -> None:
        """Subscribe to tool-availability changes.

        Fired after any mutation to the tool cache: provider registered or
        unregistered, refresh_tools updated a provider's list, etc. The
        callback receives no arguments — subscribers re-query the registry
        for the tools they care about.
        """
        self._tools_changed_subscribers.append(callback)

    def unsubscribe_tools_changed(self, callback: Callable[[], None]) -> None:
        if callback in self._tools_changed_subscribers:
            self._tools_changed_subscribers.remove(callback)

    def _notify_tools_changed(self) -> None:
        for callback in list(self._tools_changed_subscribers):
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in tools-changed subscriber: {e}")

    # --- Execution Helper ---

    async def execute_tool(
        self,
        full_tool_id: str,
        parameters: Dict,
        progress_callback: Optional[Callable] = None,
    ):
        """
        Execute a tool by full ID.

        This is a convenience method that looks up the provider and delegates.

        Args:
            full_tool_id: Full tool ID (provider_id:tool_id)
            parameters: All parameters (prompt, images, cfg, steps, etc.)
            progress_callback: Optional progress callback

        Yields:
            ExecutionProgress and ExecutionResult from the provider

        Raises:
            ValueError: If tool not found
            RuntimeError: If provider is disconnected
        """
        result = self.get_tool(full_tool_id)
        if not result:
            raise ValueError(f"Tool not found: {full_tool_id}")

        provider, tool = result

        if provider.status != ProviderStatus.CONNECTED:
            raise RuntimeError(f"Provider disconnected: {provider.provider_id}")

        async for item in provider.execute(
            tool.id, parameters, progress_callback=progress_callback
        ):
            yield item

    # --- Tool File Upload ---

    async def upload_to_tool(
        self,
        full_tool_id: str,
        parameter: str,
        filename: str,
        file_data: bytes,
    ) -> dict:
        """
        Upload a file to a tool's parameter.

        Args:
            full_tool_id: Full tool ID (provider_id:tool_id)
            parameter: Parameter name (e.g., "loras")
            filename: Original filename
            file_data: Raw file bytes

        Returns:
            Upload result dict

        Raises:
            ValueError: If tool not found
            RuntimeError: If provider doesn't support uploads
        """
        result = self.get_tool(full_tool_id)
        if not result:
            raise ValueError(f"Tool not found: {full_tool_id}")

        provider, tool = result

        if provider.status != ProviderStatus.CONNECTED:
            raise RuntimeError(f"Provider disconnected: {provider.provider_id}")

        upload_result = await provider.upload_to_tool(
            tool.id, parameter, filename, file_data
        )

        await self._post_upload_refresh(provider)
        return upload_result

    async def upload_prepare(
        self,
        full_tool_id: str,
        parameter: str,
        filename: str,
        file_size: int,
    ) -> dict:
        """
        First half of a split upload — get the URL the frontend should PUT to.
        See JsonRpcProvider.upload_prepare for details.
        """
        result = self.get_tool(full_tool_id)
        if not result:
            raise ValueError(f"Tool not found: {full_tool_id}")
        provider, tool = result
        if provider.status != ProviderStatus.CONNECTED:
            raise RuntimeError(f"Provider disconnected: {provider.provider_id}")

        return await provider.upload_prepare(tool.id, parameter, filename, file_size)

    async def upload_finalize(
        self,
        full_tool_id: str,
        upload_id: str,
    ) -> dict:
        """
        Second half of a split upload — tell the provider the bytes are in
        place. After success, refresh the tool cache + broadcast.
        """
        result = self.get_tool(full_tool_id)
        if not result:
            raise ValueError(f"Tool not found: {full_tool_id}")
        provider, _ = result
        if provider.status != ProviderStatus.CONNECTED:
            raise RuntimeError(f"Provider disconnected: {provider.provider_id}")

        finalize_result = await provider.upload_finalize(upload_id)
        await self._post_upload_refresh(provider)
        return finalize_result

    async def _post_upload_refresh(self, provider) -> None:
        """Refresh tool cache + cache to DB + broadcast — shared by both
        upload_to_tool and upload_finalize paths."""
        # Refresh the registry's tool cache after successful upload
        async with self._lock:
            await self._refresh_tools_for_provider(provider)

        # Cache updated tools to database
        tools = [t for p, t in self._tools_cache.values() if p == provider]
        try:
            await self._cache_tools_to_db(provider, tools)
        except Exception as e:
            logger.error(f"Failed to cache tools after upload: {e}")

        # Broadcast tools changed
        try:
            from utils.websocket import ws_manager
            await ws_manager.broadcast("tools_updated", {
                "provider_id": provider.provider_id,
            })
        except Exception as e:
            logger.error(f"Failed to broadcast tools update: {e}")

    # --- Interrupt Control ---

    async def interrupt_all(self, provider_id: Optional[str] = None) -> int:
        """
        Interrupt running generations on all or a specific provider.

        Args:
            provider_id: Optional provider to interrupt. If None, interrupts all.

        Returns:
            Total number of interrupted operations
        """
        total = 0

        if provider_id:
            provider = self._providers.get(provider_id)
            if provider:
                total = await provider.interrupt()
        else:
            for provider in self._providers.values():
                total += await provider.interrupt()

        logger.info(f"Interrupted {total} operations")
        return total

    async def interrupt_and_clear_all(self, provider_id: Optional[str] = None) -> int:
        """
        Interrupt running generations AND clear pending queues.

        Args:
            provider_id: Optional provider to interrupt. If None, interrupts all.

        Returns:
            Total number of affected operations
        """
        total = 0

        if provider_id:
            provider = self._providers.get(provider_id)
            if provider:
                total = await provider.interrupt_and_clear()
        else:
            for provider in self._providers.values():
                total += await provider.interrupt_and_clear()

        logger.info(f"Interrupted and cleared {total} operations")
        return total

    # --- Cleanup ---

    async def shutdown(self) -> None:
        """Disconnect all providers and clear the registry."""
        logger.info("Shutting down provider registry")

        # Get list of provider IDs to avoid modification during iteration
        provider_ids = list(self._providers.keys())

        for provider_id in provider_ids:
            await self.unregister(provider_id)

        self._tools_cache.clear()
        self._status_subscribers.clear()

    # --- Singleton Access ---

    @classmethod
    def get_instance(cls) -> "ProviderRegistry":
        """Get the singleton instance."""
        return cls()

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        if cls._instance:
            cls._instance._providers.clear()
            cls._instance._tools_cache.clear()
            cls._instance._status_subscribers.clear()
