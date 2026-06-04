"""
Anonymous usage telemetry client.

Sends events directly to PostHog. Fire-and-forget: telemetry failures
never affect app functionality.

Sessions are owned by the frontend (posthog-js). The frontend's
``$session_id`` arrives via the ``X-Stimma-Session-Id`` header on every
sidecar API call (see ``core.session_middleware``); we stamp it onto
every event we emit. Events fired before the first request from the
frontend (e.g. very early startup) go out without a session_id — that
is fine; PostHog still records them under the install's distinct_id.
"""
import asyncio
import json
import os
import platform
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from config import get_settings
from core.logging import get_logger
from core.session_context import get_session_id, on_session_change

log = get_logger(__name__)

# PostHog project (public key — safe to ship in the binary).
POSTHOG_PROJECT_KEY = "phc_qyrQKHfPzCsSvBuY5tywS2TXZyvF8Q6cZU8tmGSNpxbp"
POSTHOG_HOST = "https://us.i.posthog.com"


def _get_os() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    elif system == "Windows":
        return "windows"
    return "linux"


def _read_tauri_conf() -> dict:
    """Read tauri.conf.json."""
    try:
        conf_path = Path(__file__).parent.parent / "src-tauri" / "tauri.conf.json"
        if conf_path.exists():
            return json.loads(conf_path.read_text())
    except Exception:
        pass
    return {}


def _get_app_version() -> str:
    from app_context import get_bundle_id, BUNDLE_ID_STABLE
    if get_bundle_id() != BUNDLE_ID_STABLE:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=Path(__file__).parent.parent,
            )
            if result.returncode == 0:
                return f"0.0.0-{result.stdout.strip()}"
        except Exception:
            pass
        return "0.0.0"
    return _read_tauri_conf().get("version", "0.0.0")


def _get_app_branch() -> str:
    """Derive app branch from bundle ID or Tauri updater endpoint.

    Non-stable bundle IDs map to 'dev'.
    Packaged installs parse the branch from the updater endpoint URL
    (e.g. .../stimma/production/... -> 'production').
    """
    from app_context import get_bundle_id, BUNDLE_ID_STABLE
    if get_bundle_id() != BUNDLE_ID_STABLE:
        return "dev"

    # Parse branch from updater endpoint: .../stimma/{branch}/...
    conf = _read_tauri_conf()
    endpoints = conf.get("plugins", {}).get("updater", {}).get("endpoints", [])
    if endpoints:
        # URL like https://updates.stimma.ai/stimma/production/darwin-aarch64/latest.json
        parts = endpoints[0].split("/")
        try:
            idx = parts.index("stimma")
            if idx + 1 < len(parts):
                branch = parts[idx + 1]
                if branch in ("alpha", "beta", "production"):
                    return branch
        except ValueError:
            pass

    return "alpha"


class TelemetryClient:
    def __init__(self):
        self._install_id: Optional[str] = None
        self._app_version: str = _get_app_version()
        self._app_branch: str = _get_app_branch()
        self._os: str = _get_os()
        self._first_session_handled: bool = False
        self._started: bool = False

    def _is_enabled(self) -> bool:
        try:
            if os.environ.get("DO_NOT_TRACK", "0") == "1":
                return False
            settings = get_settings()
            return settings.telemetry.enabled
        except Exception:
            return False

    def _ensure_install_id(self) -> str:
        if self._install_id:
            return self._install_id

        try:
            settings = get_settings()
            if settings.telemetry.install_id:
                self._install_id = settings.telemetry.install_id
                return self._install_id
        except Exception:
            pass

        # Generate and persist new install ID
        new_id = str(uuid.uuid4())
        self._install_id = new_id

        try:
            import config_writer
            config_writer.patch_global_section("telemetry", {
                "enabled": get_settings().telemetry.enabled,
                "install_id": new_id,
            })
            log.info("telemetry install_id generated")
        except Exception as e:
            log.info(f"failed to persist telemetry install_id: {e}")

        return new_id

    def _get_user_id(self) -> Optional[str]:
        try:
            from auth_storage import load_auth_state
            auth = load_auth_state()
            if auth and auth.get("user"):
                return auth["user"].get("uid")
        except Exception:
            pass
        return None

    def _distinct_id(self) -> Optional[str]:
        """Match the frontend's identification rule: Firebase UID if signed in,
        else install_id. Returns None if install_id isn't ready yet."""
        return self._get_user_id() or self._install_id

    def _build_props(self, properties: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        props = dict(properties) if properties else {}
        session_id = get_session_id()
        if session_id:
            props.setdefault("$session_id", session_id)
        # Stable per-event environment metadata. PostHog also has these as
        # person properties (set in _init_posthog), but stamping them per-event
        # makes branch/version filtering reliable across person merges.
        props.setdefault("appVersion", self._app_version)
        props.setdefault("appBranch", self._app_branch)
        props.setdefault("os", self._os)
        return props

    def track(self, event: str, properties: Optional[Dict[str, Any]] = None):
        """Send a telemetry event to PostHog. Non-blocking, safe to call from anywhere."""
        if not self._is_enabled():
            return
        try:
            import posthog as ph
            distinct_id = self._distinct_id()
            if not ph.api_key or not distinct_id:
                return
            ph.capture(
                distinct_id=distinct_id,
                event=event,
                properties=self._build_props(properties),
                disable_geoip=False,
            )
        except Exception:
            pass

    def capture_exception(
        self,
        exc: BaseException,
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send an exception to PostHog Error Tracking.

        Non-blocking, safe to call from anywhere. Honors the telemetry opt-out.
        """
        if not self._is_enabled():
            return
        try:
            import posthog as ph
            distinct_id = self._distinct_id()
            if not ph.api_key or not distinct_id:
                return
            ph.capture_exception(
                exc,
                distinct_id=distinct_id,
                properties=self._build_props(properties),
            )
        except Exception:
            pass

    def _init_posthog(self) -> None:
        """Initialize PostHog SDK and install crash hooks.

        Idempotent — safe to call multiple times. Caller should ensure install_id
        is set before calling.
        """
        try:
            import posthog as ph
            if ph.api_key:
                return  # already initialized
            ph.api_key = POSTHOG_PROJECT_KEY
            ph.host = POSTHOG_HOST

            install_id = self._install_id
            if not install_id:
                return

            # Set stable person properties (one row per install in PostHog).
            # posthog-python 7.x replaced `identify` with `set`.
            try:
                ph.set(
                    distinct_id=install_id,
                    properties={
                        "appVersion": self._app_version,
                        "appBranch": self._app_branch,
                        "os": self._os,
                    },
                )
            except Exception:
                pass

            # sys.excepthook — top-level synchronous crashes
            prev_excepthook = sys.excepthook

            def _excepthook(exc_type, exc, tb):
                if self._is_enabled() and self._install_id:
                    try:
                        ph.capture_exception(exc, distinct_id=self._install_id)
                    except Exception:
                        pass
                prev_excepthook(exc_type, exc, tb)

            sys.excepthook = _excepthook

            # threading.excepthook — uncaught exceptions in threads
            prev_thread_hook = threading.excepthook

            def _thread_excepthook(args):
                if self._is_enabled() and self._install_id and args.exc_value is not None:
                    try:
                        ph.capture_exception(args.exc_value, distinct_id=self._install_id)
                    except Exception:
                        pass
                prev_thread_hook(args)

            threading.excepthook = _thread_excepthook

            log.info("posthog initialized")
        except Exception as e:
            log.info(f"posthog init failed: {e}")

    async def _get_library_stats(self) -> dict:
        """Query rich app state snapshot across all profiles."""
        try:
            from database_registry import get_database_registry
            from database import Board, MediaItem, Marker, MediaMarker, Chat
            from utils.query_builder import (
                IMAGE_FORMATS, VIDEO_FORMATS, AUDIO_FORMATS,
                TEXT_FORMATS, SET_FORMATS, GRID_FORMATS,
            )
            from sqlalchemy import func, select, case, and_

            registry = get_database_registry()
            profiles = registry.list_profiles()

            stats: Dict[str, Any] = {"profileCount": len(profiles)}
            total_media = 0
            total_images = 0
            total_videos = 0
            total_audio = 0
            total_documents = 0
            total_sets = 0
            total_grids = 0
            total_boards = 0
            total_chats = 0
            markers_breakdown: Dict[str, int] = {}

            for profile_info in profiles:
                db = registry.get_database(profile_info["id"])
                async with db.async_session_maker() as session:
                    # Media count with type breakdown in one query
                    alive = MediaItem.deleted_at.is_(None)
                    result = await session.execute(
                        select(
                            func.count().label("total"),
                            func.sum(case((MediaItem.file_format.in_(IMAGE_FORMATS), 1), else_=0)).label("images"),
                            func.sum(case((MediaItem.file_format.in_(VIDEO_FORMATS), 1), else_=0)).label("videos"),
                            func.sum(case((MediaItem.file_format.in_(AUDIO_FORMATS), 1), else_=0)).label("audio"),
                            func.sum(case((MediaItem.file_format.in_(TEXT_FORMATS), 1), else_=0)).label("documents"),
                            func.sum(case((MediaItem.file_format.in_(SET_FORMATS), 1), else_=0)).label("sets"),
                            func.sum(case((MediaItem.file_format.in_(GRID_FORMATS), 1), else_=0)).label("grids"),
                        ).where(alive)
                    )
                    row = result.one()
                    total_media += row.total or 0
                    total_images += row.images or 0
                    total_videos += row.videos or 0
                    total_audio += row.audio or 0
                    total_documents += row.documents or 0
                    total_sets += row.sets or 0
                    total_grids += row.grids or 0

                    # Boards
                    result = await session.execute(
                        select(func.count()).select_from(Board).where(Board.deleted_at.is_(None))
                    )
                    total_boards += result.scalar() or 0

                    # Chats
                    result = await session.execute(
                        select(func.count()).select_from(Chat).where(Chat.deleted_at.is_(None))
                    )
                    total_chats += result.scalar() or 0

                    # Markers with per-marker item counts
                    result = await session.execute(
                        select(Marker.name, func.count(MediaMarker.media_id))
                        .outerjoin(MediaMarker, and_(
                            MediaMarker.marker_id == Marker.id,
                            MediaMarker.source != 'suppressed',
                        ))
                        .group_by(Marker.id, Marker.name)
                    )
                    for marker_name, count in result.all():
                        markers_breakdown[marker_name] = markers_breakdown.get(marker_name, 0) + (count or 0)

            stats["mediaCount"] = total_media
            stats["mediaByType"] = {
                "images": total_images,
                "videos": total_videos,
                "audio": total_audio,
                "documents": total_documents,
                "sets": total_sets,
                "grids": total_grids,
            }
            stats["boardCount"] = total_boards
            stats["chatCount"] = total_chats
            stats["markers"] = markers_breakdown

            # Tool providers and tools per provider
            try:
                from providers import ProviderRegistry
                from providers.base import ProviderStatus
                pr = ProviderRegistry.get_instance()
                providers_info = []
                for provider in pr.list_providers():
                    tools = pr.list_tools_by_provider(provider.id)
                    info: Dict[str, Any] = {
                        "id": provider.provider_id,
                        "name": provider.provider_name,
                        "type": getattr(provider, 'provider_type', 'unknown'),
                        "toolCount": len(tools),
                        "connected": provider.status == ProviderStatus.CONNECTED,
                    }
                    if hasattr(provider, 'reported_name') and provider.reported_name:
                        info["reportedName"] = provider.reported_name
                    if hasattr(provider, 'reported_version') and provider.reported_version:
                        info["reportedVersion"] = provider.reported_version
                    providers_info.append(info)
                stats["providers"] = providers_info
                stats["providerCount"] = len(providers_info)
                stats["toolsByProvider"] = {p["id"]: p["toolCount"] for p in providers_info}
            except Exception:
                pass

            # LLM configuration snapshot
            try:
                from config import get_settings
                from urllib.parse import urlparse
                settings = get_settings()
                llm_snapshot: Dict[str, Any] = {}
                for role, role_config in settings.llms.items():
                    role_info: Dict[str, Any] = {"source": role_config.source}
                    if role_config.source == "endpoint" and role_config.endpoint:
                        parsed = urlparse(role_config.endpoint.url)
                        role_info["endpointDomain"] = parsed.hostname or "unknown"
                        role_info["endpointPort"] = parsed.port
                        role_info["model"] = role_config.endpoint.model or "unknown"
                    llm_snapshot[role] = role_info
                stats["llmConfig"] = llm_snapshot
            except Exception:
                pass

            return stats
        except Exception as e:
            log.info(f"telemetry: failed to get library stats: {e}")
            return {}

    async def _check_and_emit_app_updated(self) -> None:
        """Detect app version change and emit ``app_updated`` event.

        Compares the current app version against the one persisted on the
        first profile's database, then upserts the current value.
        """
        try:
            from database_registry import get_database_registry
            from database import UserPreference
            from sqlalchemy import select

            registry = get_database_registry()
            profiles = registry.list_profiles()
            if not profiles:
                return

            db = registry.get_database(profiles[0]["id"])
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(UserPreference).where(UserPreference.key == "telemetry_last_app_version")
                )
                pref = result.scalar_one_or_none()
                previous_version = pref.value if pref else None

                if previous_version is not None and previous_version != self._app_version:
                    self.track(
                        "app_updated",
                        {
                            "previousVersion": previous_version,
                            "newVersion": self._app_version,
                        },
                    )

                if pref:
                    pref.value = self._app_version
                else:
                    session.add(UserPreference(key="telemetry_last_app_version", value=self._app_version))
                await session.commit()
        except Exception as e:
            log.info(f"telemetry: failed to check app version: {e}")

    async def _on_session_change(self, previous: Optional[str], current: str) -> None:
        """Fired by ``core.session_context`` whenever the frontend's
        ``$session_id`` changes. Emits a fresh ``session_started`` event with
        rich library stats; the first time per launch, also runs the
        ``app_updated`` version-change check.
        """
        if not self._is_enabled():
            return
        try:
            stats = await self._get_library_stats()
            self.track("session_started", stats)
            if not self._first_session_handled:
                self._first_session_handled = True
                await self._check_and_emit_app_updated()
        except Exception:
            log.exception("telemetry: session-change handler failed")

    async def start(self):
        """Initialize PostHog and subscribe to session changes."""
        if self._started:
            return
        self._ensure_install_id()
        self._init_posthog()
        on_session_change(self._on_session_change)
        self._started = True
        log.info(
            "telemetry started",
            install_id=self._install_id[:8] if self._install_id else "?",
        )

    async def stop(self):
        """Flush PostHog's background queue so the last batch isn't dropped."""
        try:
            import posthog as ph
            if ph.api_key:
                ph.shutdown()
        except Exception:
            pass
        log.info("telemetry stopped")


_client: Optional[TelemetryClient] = None


def get_telemetry_client() -> TelemetryClient:
    global _client
    if _client is None:
        _client = TelemetryClient()
    return _client
