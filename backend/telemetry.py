"""
First-party anonymous usage telemetry client.

Official builds only: the client constructs as a permanent no-op unless
``STIMMA_DISTRIBUTION == official`` — source/self-built installs emit
nothing, structurally (no buffering, no network).

Mechanics (official builds):
- Buffered HTTP client posting batches to ``POST {cloud.base_url}/api/telemetry``.
- Body: ``{sessionId, userId?, events[]}``; each event is
  ``{event, category, properties, timestamp}`` (client occurrence time,
  epoch ms). The body carries NO install id — identity/platform ride the
  User-Agent (user_agent.py), the single sanctioned install-id egress.
- Flush every 60 s / 50 events / on shutdown; ≤200 events per batch;
  3 retries with backoff; fire-and-forget (failures never affect the app).
- Pre-consent buffering (D14): while consent is undetermined (onboarding
  in progress) events buffer locally with ZERO network; the buffer flushes
  if consent lands on, and is discarded if it lands off.
- ``DO_NOT_TRACK=1`` is absolute (D11): no buffering, no sending,
  regardless of consent state.
- Carve-out: the single ``telemetry_enabled {enabled: false}`` transition
  event fired by the toggle-off itself is the last thing sent (only when
  transitioning from consented-on).

Sessions are owned by the frontend (a plain UUID, rotated on app start and
30 min inactivity), propagated via ``X-Stimma-Session-Id`` on every sidecar
call (see ``core.session_middleware``); batches are stamped with the
current session id at flush time.
"""
import asyncio
import hashlib
import sys
import threading
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional

import httpx

from core.logging import get_logger
from core.session_context import get_session_id, on_session_change
from distribution import is_dnt, is_official

log = get_logger(__name__)

FLUSH_INTERVAL_SECONDS = 60
FLUSH_EVENT_THRESHOLD = 50
MAX_BATCH_EVENTS = 200
MAX_BUFFERED_EVENTS = 1000  # cap for the local buffer (incl. pre-consent)
SEND_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
SEND_TIMEOUT_SECONDS = 15.0

_UNSET = object()


def _stack_hash_and_module(exc: BaseException) -> tuple[str, Optional[str]]:
    """Categorical stack fingerprint: sha1 over module:function frames.

    No file paths, messages, or locals — paths can contain user content.
    Returns (stackHash, top app-frame module name or None).
    """
    frames: List[str] = []
    top_module: Optional[str] = None
    try:
        tb = exc.__traceback__
        for frame_summary in traceback.extract_tb(tb):
            # Reduce the filename to its module-ish basename (no directories).
            name = frame_summary.filename.replace("\\", "/").rsplit("/", 1)[-1]
            if name.endswith(".py"):
                name = name[:-3]
            frames.append(f"{name}:{frame_summary.name}")
            top_module = name
    except Exception:
        pass
    digest = hashlib.sha1(
        f"{type(exc).__name__}|{'|'.join(frames)}".encode("utf-8")
    ).hexdigest()
    return digest[:16], top_module


class TelemetryClient:
    """Buffered first-party telemetry client (permanent no-op in dev builds)."""

    def __init__(self):
        self._enabled_build: bool = is_official()
        self._lock = threading.Lock()
        self._queue: List[Dict[str, Any]] = []
        self._consent_override: Any = _UNSET
        self._flush_task: Optional[asyncio.Task] = None
        self._started: bool = False
        self._first_session_handled: bool = False
        # Fallback session id for events fired before the frontend's first
        # request of this launch.
        self._fallback_session_id: str = str(uuid.uuid4())
        # Wall-clock start of the current telemetry session (rotates with the
        # frontend session id); feeds session_ended durations.
        self._session_started_monotonic: float = time.monotonic()

    # ── Gating ──────────────────────────────────────────────────────────

    def _consent_state(self) -> Optional[bool]:
        """Tri-state consent: True / False / None (undetermined)."""
        if self._consent_override is not _UNSET:
            return self._consent_override
        try:
            from config import get_settings
            return get_settings().telemetry.enabled
        except Exception:
            return None

    def _may_buffer(self) -> bool:
        """Whether events may even be buffered locally."""
        if not self._enabled_build:
            return False  # dev distribution: permanent no-op, no buffer
        if is_dnt():
            return False  # DNT: absolute, regardless of consent
        return self._consent_state() is not False

    def _may_send(self) -> bool:
        """Whether buffered events may go on the network."""
        if not self._enabled_build or is_dnt():
            return False
        return self._consent_state() is True

    # ── Public API ──────────────────────────────────────────────────────

    def track(
        self,
        event: str,
        properties: Optional[Dict[str, Any]] = None,
        category: str = "app",
    ):
        """Record a telemetry event. Non-blocking, safe from any thread.

        Dev builds: permanent no-op. DNT: no-op. Consent off: dropped.
        Consent undetermined: buffered locally, zero network (D14).
        """
        if not self._may_buffer():
            return
        try:
            entry = {
                "event": event,
                "category": category,
                "properties": dict(properties) if properties else {},
                "timestamp": int(time.time() * 1000),
            }
            with self._lock:
                self._queue.append(entry)
                if len(self._queue) > MAX_BUFFERED_EVENTS:
                    del self._queue[: len(self._queue) - MAX_BUFFERED_EVENTS]
                queued = len(self._queue)
            if queued >= FLUSH_EVENT_THRESHOLD and self._may_send():
                self._schedule_flush()
        except Exception:
            pass

    def capture_exception(
        self,
        exc: BaseException,
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an unhandled exception as a categorical ``app_error``.

        Exception type, stack hash, and top app-frame module only — no
        messages, paths, or locals (those can contain prompts/paths).
        """
        try:
            stack_hash, module = _stack_hash_and_module(exc)
            props: Dict[str, Any] = {
                "source": "backend",
                "errorType": type(exc).__name__,
                "stackHash": stack_hash,
            }
            if module:
                props["module"] = module
            self.track("app_error", props, category="app")
        except Exception:
            pass

    def on_consent_changed(self, enabled: bool) -> None:
        """Handle a consent transition (onboarding or Settings toggle).

        - -> on: the local buffer (incl. pre-consent events) flushes.
        - on -> off: the single ``telemetry_enabled {enabled: false}``
          transition event is the last thing sent (CI carve-out), followed
          by the queued events tracked while consent was on.
        - undetermined -> off: the buffer is discarded; nothing egresses.
        """
        if not self._enabled_build:
            return
        previous = self._consent_state()
        self._consent_override = enabled

        if is_dnt():
            with self._lock:
                self._queue.clear()
            return

        if enabled:
            self.track("telemetry_enabled", {"enabled": True}, category="settings")
            self._schedule_flush()
            return

        # Consent landed off.
        if previous is True:
            # Carve-out: flush what was tracked while consented, ending with
            # the toggle-off transition event.
            with self._lock:
                final_batch = list(self._queue)
                self._queue.clear()
            final_batch.append({
                "event": "telemetry_enabled",
                "category": "settings",
                "properties": {"enabled": False},
                "timestamp": int(time.time() * 1000),
            })
            self._spawn(self._send_events(final_batch))
        else:
            # Pre-consent buffer is discarded (D14); nothing egresses.
            with self._lock:
                self._queue.clear()

    # ── Flushing / sending ──────────────────────────────────────────────

    def _spawn(self, coro) -> None:
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            # No running loop (early startup / exception hook in a thread):
            # leave events queued; the periodic flush will pick them up.
            coro.close()

    def _schedule_flush(self) -> None:
        self._spawn(self.flush())

    async def flush(self) -> None:
        """Send all queued events if consent allows. Fire-and-forget."""
        if not self._may_send():
            return
        with self._lock:
            events = list(self._queue)
            self._queue.clear()
        if not events:
            return
        await self._send_events(events)

    async def _send_events(self, events: List[Dict[str, Any]]) -> None:
        try:
            from config import get_settings
            from user_agent import ua_headers
            base_url = get_settings().cloud.base_url.rstrip("/")
            url = f"{base_url}/api/telemetry"
            headers = ua_headers()
            session_id = get_session_id() or self._fallback_session_id
            user_id = self._get_user_id()

            for start in range(0, len(events), MAX_BATCH_EVENTS):
                batch = events[start:start + MAX_BATCH_EVENTS]
                body: Dict[str, Any] = {"sessionId": session_id, "events": batch}
                if user_id:
                    body["userId"] = user_id
                await self._post_with_retries(url, body, headers)
        except Exception:
            # Fire-and-forget: telemetry failures never affect the app.
            pass

    async def _post_with_retries(self, url: str, body: dict, headers: dict) -> None:
        for attempt in range(SEND_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(SEND_TIMEOUT_SECONDS)
                ) as client:
                    resp = await client.post(url, json=body, headers=headers)
                if resp.status_code < 500:
                    return  # accepted, or a non-retryable client error
            except Exception:
                pass
            if attempt < SEND_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (2 ** attempt))

    async def _flush_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
                # Keep the dead-session-recovery timestamp current so a hard
                # crash yields an accurate session_ended duration next launch.
                self._write_lifecycle_state(dirty=True)
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    # ── Identity helpers ────────────────────────────────────────────────

    def _get_user_id(self) -> Optional[str]:
        try:
            from auth_storage import load_auth_state
            auth = load_auth_state()
            if auth and auth.get("user"):
                return auth["user"].get("uid")
        except Exception:
            pass
        return None

    # ── Launch snapshot (session_started / app_updated) ─────────────────

    async def _get_library_stats(self) -> dict:
        """Query the per-launch state snapshot across all profiles.

        Counts only — no names, paths, labels, or endpoint hosts. Model and
        endpoint identity go through the classification helpers
        (model_family / endpoint_class / stp_identity).
        """
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
            # Shipped default marker names pass through literally; everything
            # else (including renamed defaults) counts under 'custom'.
            default_marker_names = {"favorite", "library"}

            for profile_info in profiles:
                db = registry.get_database(profile_info["id"])
                async with db.async_session_maker() as session:
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

                    result = await session.execute(
                        select(func.count()).select_from(Board).where(Board.deleted_at.is_(None))
                    )
                    total_boards += result.scalar() or 0

                    result = await session.execute(
                        select(func.count()).select_from(Chat).where(Chat.deleted_at.is_(None))
                    )
                    total_chats += result.scalar() or 0

                    result = await session.execute(
                        select(Marker.name, func.count(MediaMarker.media_id))
                        .outerjoin(MediaMarker, and_(
                            MediaMarker.marker_id == Marker.id,
                            MediaMarker.source != 'suppressed',
                        ))
                        .group_by(Marker.id, Marker.name)
                    )
                    for marker_name, count in result.all():
                        key = marker_name if marker_name in default_marker_names else "custom"
                        markers_breakdown[key] = markers_breakdown.get(key, 0) + (count or 0)

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
            stats["markerCounts"] = markers_breakdown

            # Tool providers: connection-kind + STP product identity only —
            # never ids, user labels, or provider-reported display names.
            try:
                from providers import ProviderRegistry
                from providers.base import ProviderStatus
                from stp_identity import parse_server_identity
                pr = ProviderRegistry.get_instance()
                providers_info = []
                for provider in pr.list_providers():
                    tools = pr.list_tools_by_provider(provider.id)
                    info: Dict[str, Any] = {
                        "providerType": getattr(provider, 'provider_type', 'unknown'),
                        "toolCount": len(tools),
                        "connected": provider.status == ProviderStatus.CONNECTED,
                    }
                    server = getattr(provider, 'server', None) or getattr(provider, '_server', None)
                    identity = parse_server_identity(server)
                    if identity.get("productName") and identity["productName"] != "unknown":
                        info["productName"] = identity["productName"]
                        if identity.get("productVersion"):
                            info["productVersion"] = identity["productVersion"]
                    providers_info.append(info)
                stats["providers"] = providers_info
                stats["providerCount"] = len(providers_info)
            except Exception:
                pass

            # LLM configuration snapshot: configured source + endpointClass +
            # modelFamily. Never endpoint hosts/ports or raw model strings.
            try:
                from config import get_settings
                from endpoint_class import endpoint_class
                from model_family import model_family
                settings = get_settings()
                llm_snapshot: Dict[str, Any] = {}
                for role, role_config in settings.llms.items():
                    role_info: Dict[str, Any] = {"source": role_config.source}
                    if role_config.source == "endpoint" and role_config.endpoint:
                        role_info["endpointClass"] = endpoint_class(role_config.endpoint.url)
                        role_info["modelFamily"] = model_family(role_config.endpoint.model)
                    llm_snapshot[role] = role_info
                stats["llmConfig"] = llm_snapshot
            except Exception:
                pass

            return stats
        except Exception as e:
            log.info(f"telemetry: failed to get library stats: {e}")
            return {}

    async def _check_and_emit_app_updated(self) -> None:
        """Detect app version change and emit ``app_updated``."""
        try:
            from database_registry import get_database_registry
            from database import UserPreference
            from sqlalchemy import select
            from user_agent import get_app_version

            registry = get_database_registry()
            profiles = registry.list_profiles()
            if not profiles:
                return

            current_version = get_app_version()
            db = registry.get_database(profiles[0]["id"])
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(UserPreference).where(UserPreference.key == "telemetry_last_app_version")
                )
                pref = result.scalar_one_or_none()
                previous_version = pref.value if pref else None

                if previous_version is not None and previous_version != current_version:
                    self.track("app_updated", {"fromVersion": previous_version}, category="app")

                if pref:
                    pref.value = current_version
                else:
                    session.add(UserPreference(key="telemetry_last_app_version", value=current_version))
                await session.commit()
        except Exception as e:
            log.info(f"telemetry: failed to check app version: {e}")

    async def _on_session_change(self, previous: Optional[str], current: str) -> None:
        """Emit ``session_started`` (with the state snapshot) per session.

        A rotation (previous session exists) also closes the old session
        with ``session_ended {durationMs}`` so depth metrics don't mix
        rotated sessions.
        """
        if not self._may_buffer():
            return
        try:
            if previous is not None:
                duration_ms = int((time.monotonic() - self._session_started_monotonic) * 1000)
                self.track("session_ended", {"durationMs": duration_ms}, category="app")
            self._session_started_monotonic = time.monotonic()
            stats = await self._get_library_stats()
            self.track("session_started", stats, category="app")
            if not self._first_session_handled:
                self._first_session_handled = True
                await self._check_and_emit_app_updated()
        except Exception:
            log.exception("telemetry: session-change handler failed")

    # ── App-lifecycle markers (app_launched / session_ended / first_run) ─

    def _lifecycle_state_path(self):
        import app_dirs
        return app_dirs.get_data_dir() / "telemetry_lifecycle.json"

    def _first_run_marker_path(self):
        import app_dirs
        return app_dirs.get_data_dir() / "telemetry_first_run"

    def _handle_launch_lifecycle(self) -> None:
        """Dirty-flag launch handling.

        The lifecycle file is written dirty at startup and cleared on orderly
        shutdown; finding it dirty on the next launch means the prior session
        died hard. Dead-session recovery: flush a buffered ``session_ended``
        for the dead session computed from its last persisted activity
        timestamp, so duration distributions don't drop crashed sessions.
        """
        import json as _json
        try:
            path = self._lifecycle_state_path()
            previous_clean = True
            if path.exists():
                try:
                    state = _json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    state = {}
                if state.get("dirty"):
                    previous_clean = False
                    started = state.get("session_started_at")
                    last_activity = state.get("last_activity_at")
                    if isinstance(started, (int, float)) and isinstance(last_activity, (int, float)):
                        dead_duration = max(0, int(last_activity - started))
                        self.track("session_ended", {"durationMs": dead_duration}, category="app")

            self.track("app_launched", {"previousExitClean": previous_clean}, category="app")

            # first_run: client-side funnel marker, once per install. The
            # authoritative install count is server-side (installs.first_seen_at).
            first_run_marker = self._first_run_marker_path()
            if not first_run_marker.exists():
                self.track("first_run", category="app")
                try:
                    first_run_marker.write_text("1", encoding="utf-8")
                except Exception:
                    pass

            self._write_lifecycle_state(dirty=True, fresh=True)
        except Exception:
            log.debug("telemetry: launch lifecycle handling failed", exc_info=True)

    def _write_lifecycle_state(self, dirty: bool, fresh: bool = False) -> None:
        import json as _json
        try:
            path = self._lifecycle_state_path()
            now_ms = int(time.time() * 1000)
            if fresh or not path.exists():
                state = {"session_started_at": now_ms}
            else:
                try:
                    state = _json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    state = {"session_started_at": now_ms}
            state["dirty"] = dirty
            state["last_activity_at"] = now_ms
            path.write_text(_json.dumps(state), encoding="utf-8")
        except Exception:
            pass

    # ── Lifecycle ───────────────────────────────────────────────────────

    def _install_exception_hooks(self) -> None:
        prev_excepthook = sys.excepthook

        def _excepthook(exc_type, exc, tb):
            try:
                self.capture_exception(exc)
            except Exception:
                pass
            prev_excepthook(exc_type, exc, tb)

        sys.excepthook = _excepthook

        prev_thread_hook = threading.excepthook

        def _thread_excepthook(args):
            if args.exc_value is not None:
                try:
                    self.capture_exception(args.exc_value)
                except Exception:
                    pass
            prev_thread_hook(args)

        threading.excepthook = _thread_excepthook

    async def start(self):
        """Start the flush loop and subscribe to session changes."""
        if self._started:
            return
        self._started = True
        if not self._enabled_build:
            log.info("telemetry disabled (dev distribution) — permanent no-op")
            return
        if is_dnt():
            log.info("telemetry disabled (DO_NOT_TRACK=1)")
            return
        self._install_exception_hooks()
        self._handle_launch_lifecycle()
        on_session_change(self._on_session_change)
        self._flush_task = asyncio.create_task(self._flush_loop())
        log.info("telemetry started", consent=str(self._consent_state()))

    async def stop(self):
        """Flush remaining events and stop the loop."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        # Orderly shutdown: close the session and clear the dirty flag so the
        # next launch reads previousExitClean: true.
        if self._enabled_build and not is_dnt():
            try:
                duration_ms = int((time.monotonic() - self._session_started_monotonic) * 1000)
                self.track("session_ended", {"durationMs": duration_ms}, category="app")
                self._write_lifecycle_state(dirty=False)
            except Exception:
                pass
        try:
            await self.flush()
        except Exception:
            pass
        log.info("telemetry stopped")


_client: Optional[TelemetryClient] = None


def get_telemetry_client() -> TelemetryClient:
    global _client
    if _client is None:
        _client = TelemetryClient()
    return _client
