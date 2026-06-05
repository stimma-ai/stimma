"""
Provider health monitoring system.

Tracks provider availability and notifies subscribers of status changes.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from core.logging import get_logger
from .base import ProviderStatus, ToolProvider
from .registry import ProviderRegistry

log = get_logger(__name__)


@dataclass
class ProviderHealth:
    """Health status for a single provider."""

    provider_id: str
    status: ProviderStatus
    last_check: datetime
    last_healthy: Optional[datetime] = None
    consecutive_failures: int = 0
    error_message: Optional[str] = None


# Type alias for status change callbacks
StatusChangeCallback = Callable[[str, ProviderStatus, Optional[str]], None]


class ProviderHealthMonitor:
    """
    Monitors provider health and notifies subscribers of status changes.

    Features:
    - Periodic health checks via ping()
    - Status change notifications
    - Tracks consecutive failures
    - Thread-safe subscriber management
    """

    _instance: Optional["ProviderHealthMonitor"] = None

    def __init__(
        self,
        check_interval: float = 30.0,  # seconds between checks
        failure_threshold: int = 3,  # failures before marking unhealthy
    ):
        self._check_interval = check_interval
        self._failure_threshold = failure_threshold
        self._health: Dict[str, ProviderHealth] = {}
        self._subscribers: List[StatusChangeCallback] = []
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

    @classmethod
    def get_instance(cls) -> "ProviderHealthMonitor":
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def subscribe(self, callback: StatusChangeCallback) -> None:
        """Subscribe to status change notifications."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: StatusChangeCallback) -> None:
        """Unsubscribe from status change notifications."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify_subscribers(
        self, provider_id: str, status: ProviderStatus, error: Optional[str] = None
    ) -> None:
        """Notify all subscribers of a status change."""
        for callback in self._subscribers:
            try:
                callback(provider_id, status, error)
            except Exception as e:
                log.warning(
                    "subscriber callback failed",
                    provider_id=provider_id,
                    error=str(e),
                )

    async def start(self) -> None:
        """Start the health monitoring loop."""
        if self._running:
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        log.info("health monitor started", interval=self._check_interval)

    async def stop(self) -> None:
        """Stop the health monitoring loop."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        log.info("health monitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_all_providers()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception("health check error", error=str(e))
                await asyncio.sleep(self._check_interval)

    async def _check_all_providers(self) -> None:
        """Check health of all registered providers."""
        registry = ProviderRegistry.get_instance()

        # Copy items to avoid "dict changed size during iteration"
        providers_snapshot = list(registry._providers.items())
        for provider_id, provider in providers_snapshot:
            await self._check_provider(provider_id, provider)

    async def _check_provider(self, provider_id: str, provider: ToolProvider) -> None:
        """Check health of a single provider."""
        now = datetime.utcnow()
        previous_health = self._health.get(provider_id)
        previous_status = previous_health.status if previous_health else None

        try:
            # Quick status check first
            current_status = provider.status

            if current_status != ProviderStatus.CONNECTED:
                # Provider reports not connected
                self._update_health(
                    provider_id,
                    current_status,
                    now,
                    error="Provider not connected",
                )
            else:
                # Provider reports connected, verify with ping
                is_healthy = await asyncio.wait_for(provider.ping(), timeout=10.0)

                if is_healthy:
                    self._update_health(
                        provider_id,
                        ProviderStatus.CONNECTED,
                        now,
                        healthy=True,
                    )
                else:
                    self._handle_failure(provider_id, now, "Ping returned false")

        except asyncio.TimeoutError:
            self._handle_failure(provider_id, now, "Health check timed out")
        except Exception as e:
            self._handle_failure(provider_id, now, str(e))

        # Notify if status changed
        current_health = self._health.get(provider_id)
        if current_health and current_health.status != previous_status:
            self._notify_subscribers(
                provider_id,
                current_health.status,
                current_health.error_message,
            )

    def _update_health(
        self,
        provider_id: str,
        status: ProviderStatus,
        check_time: datetime,
        healthy: bool = False,
        error: Optional[str] = None,
    ) -> None:
        """Update health record for a provider."""
        health = self._health.get(provider_id)

        if health is None:
            health = ProviderHealth(
                provider_id=provider_id,
                status=status,
                last_check=check_time,
            )
            self._health[provider_id] = health
        else:
            health.status = status
            health.last_check = check_time

        if healthy:
            health.last_healthy = check_time
            health.consecutive_failures = 0
            health.error_message = None
        else:
            health.error_message = error

    def _handle_failure(
        self, provider_id: str, check_time: datetime, error: str
    ) -> None:
        """Handle a health check failure."""
        health = self._health.get(provider_id)

        if health is None:
            health = ProviderHealth(
                provider_id=provider_id,
                status=ProviderStatus.ERROR,
                last_check=check_time,
                consecutive_failures=1,
                error_message=error,
            )
            self._health[provider_id] = health
        else:
            health.consecutive_failures += 1
            health.last_check = check_time
            health.error_message = error

            if health.consecutive_failures >= self._failure_threshold:
                health.status = ProviderStatus.ERROR

        log.warning(
            "provider health check failed",
            provider_id=provider_id,
            failures=health.consecutive_failures,
            error=error,
        )

    def get_health(self, provider_id: str) -> Optional[ProviderHealth]:
        """Get health status for a provider."""
        return self._health.get(provider_id)

    def get_all_health(self) -> Dict[str, ProviderHealth]:
        """Get health status for all providers."""
        return self._health.copy()

    def get_available_providers(self) -> List[str]:
        """Get list of healthy provider IDs."""
        # Copy items to avoid "dict changed size during iteration"
        health_snapshot = list(self._health.items())
        return [
            provider_id
            for provider_id, health in health_snapshot
            if health.status == ProviderStatus.CONNECTED
        ]

    def is_provider_available(self, provider_id: str) -> bool:
        """Check if a provider is available."""
        health = self._health.get(provider_id)
        return health is not None and health.status == ProviderStatus.CONNECTED


# Convenience function
def get_health_monitor() -> ProviderHealthMonitor:
    """Get the singleton health monitor instance."""
    return ProviderHealthMonitor.get_instance()
