"""
Generation queue system for managing image generation jobs.
"""

import os
import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import GenerationJob, MediaItem, ChatItem, ControlFlag, MediaLineage
from database_registry import get_database_registry
from utils.background_tasks import clear_auto_delete_for_media
from utils.lineage import record_lineage_from_inputs, propagate_tool_lineage
from generation_metadata import build_generation_metadata, build_parameters
from core.profile_context import get_current_profile, set_current_profile, set_thread_profile, ProfileScope
from core.logging import get_logger
from providers import ProviderRegistry
from generation_scheduler import get_scheduler
from config import get_settings
from config_version import get_config_version_manager
from pathlib import Path
from PIL import Image
import math


log = get_logger(__name__)

PENDING_REQUEST_TTL = 30  # seconds — generous for WS→frontend→HTTP roundtrip

# Prompt warm pool: how long a generator instance's "keep N enhanced variants
# warm" intent survives without a refresh ping before it's treated as
# abandoned. Mirrors PENDING_REQUEST_TTL's self-healing role — the primary
# teardown paths are explicit (forever-mode unregister, WS disconnect), this
# is only the backstop for a client that vanishes without either.
PROMPT_WARM_POOL_TTL = 30  # seconds
PROMPT_WARM_POOL_MAX_CONCURRENCY = 8  # sane ceiling regardless of client input


def resolve_recorded_seed(requested_seed, actual_seed):
    """Prefer the provider's actual seed, but fall back when it is absent."""
    return actual_seed if actual_seed is not None else requested_seed


def compute_size_from_image(image_path: str, megapixels: float, step: int = 64) -> tuple[int, int]:
    """Compute output size from input image aspect ratio and target megapixels.

    Args:
        image_path: Path to the input image
        megapixels: Target megapixels for output
        step: Round dimensions to this value (default 64 for most models, use 16 for video)

    Returns:
        Tuple of (width, height) rounded to nearest step
    """
    from utils.image_ops import open_oriented
    with open_oriented(image_path) as img:
        src_width, src_height = img.size

    aspect_ratio = src_width / src_height
    target_pixels = megapixels * 1_000_000

    # Calculate dimensions that maintain aspect ratio and hit target megapixels
    width = math.sqrt(target_pixels * aspect_ratio)
    height = width / aspect_ratio

    # Round to nearest step
    width = round(width / step) * step
    height = round(height / step) * step

    # Ensure minimum dimensions
    min_dim = step * 4
    width = max(min_dim, int(width))
    height = max(min_dim, int(height))

    return width, height


def parse_duration(duration_str: str) -> Optional[timedelta]:
    """
    Parse duration string into timedelta.

    Args:
        duration_str: Duration string like "1h", "24h", "3d", "7d", "never"

    Returns:
        timedelta object or None if "never"
    """
    if not duration_str or duration_str == "never":
        return None

    # Extract number and unit
    try:
        if duration_str.endswith('m'):
            return timedelta(minutes=int(duration_str[:-1]))
        elif duration_str.endswith('h'):
            return timedelta(hours=int(duration_str[:-1]))
        elif duration_str.endswith('d'):
            return timedelta(days=int(duration_str[:-1]))
        else:
            # Default to hours if no unit specified
            return timedelta(hours=int(duration_str))
    except (ValueError, IndexError):
        return None


def _compute_generated_file_metadata(output_path: str, is_video: bool, is_audio: bool, generation_metadata: Optional[str]) -> dict:
    """Blocking metadata extraction for a just-generated file: hash, dimensions/duration
    (ffprobe for video, PIL for images), and embedded EXIF/PNG generation metadata.

    Must be called via asyncio.to_thread/run_in_executor - never awaited directly on the
    event loop, since ffprobe subprocess calls and whole-file hashing can take seconds.

    DIAGNOSTIC INSTRUMENTATION (2026-07-06): logs are temporary, added to pin down an
    8-30s stall reported opening the slideshow during heavy generate-forever. Remove once
    confirmed/fixed.
    """
    import hashlib
    import subprocess
    import time as _time
    from exif_extractor import extract_stimma_metadata

    file_path = Path(output_path)
    _t_start = _time.time()

    _t_hash0 = _time.time()
    sha256 = hashlib.sha256()
    with open(output_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):  # 64KB chunks for speed
            sha256.update(chunk)
    file_hash = sha256.hexdigest()
    _hash_ms = (_time.time() - _t_hash0) * 1000
    if _hash_ms > 200:
        log.warning(f"SLOWTRACE_METADATA: hashing {output_path} took {_hash_ms:.0f}ms")

    duration = None
    has_alpha = None
    audio_sample_rate = None
    audio_channels = None
    audio_bit_depth = None
    audio_bitrate = None
    audio_codec = None
    if is_audio:
        # Audio has no visual dimensions but has audio-specific metadata.
        # Use the same extractor the scan/ingestion path uses so generated
        # audio is a first-class media item (duration + codec + waveform
        # thumbnail) exactly like imported library audio.
        width, height = 0, 0
        _t_audio0 = _time.time()
        try:
            from media_scanner import get_audio_metadata
            audio_meta = get_audio_metadata(file_path)
            duration = audio_meta.get('duration')
            audio_sample_rate = audio_meta.get('sample_rate')
            audio_channels = audio_meta.get('channels')
            audio_bit_depth = audio_meta.get('bit_depth')
            audio_bitrate = audio_meta.get('bitrate')
            audio_codec = audio_meta.get('codec')
        except Exception as e:
            log.warning(f"Failed to extract audio metadata from {output_path}: {e}")
        has_alpha = False
        _audio_ms = (_time.time() - _t_audio0) * 1000
        if _audio_ms > 200:
            log.warning(f"SLOWTRACE_METADATA: audio metadata {output_path} took {_audio_ms:.0f}ms")
    elif is_video:
        # Use ffprobe for video dimensions and duration
        _t_ffprobe0 = _time.time()
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height,duration', '-of', 'csv=p=0', output_path],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(',')
                width, height = int(parts[0]), int(parts[1])
                # Duration may be in stream or format - try stream first
                if len(parts) > 2 and parts[2]:
                    try:
                        duration = float(parts[2])
                    except (ValueError, IndexError):
                        pass
            else:
                width, height = 0, 0

            # If duration not in stream, try format duration
            if duration is None:
                result = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'csv=p=0', output_path],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    try:
                        duration = float(result.stdout.strip())
                    except ValueError:
                        pass
        except Exception:
            width, height = 0, 0
        has_alpha = False
        _ffprobe_ms = (_time.time() - _t_ffprobe0) * 1000
        if _ffprobe_ms > 200:
            log.warning(f"SLOWTRACE_METADATA: ffprobe {output_path} took {_ffprobe_ms:.0f}ms")
    else:
        # Use PIL for image dimensions
        _t_pil0 = _time.time()
        try:
            from utils.image_ops import open_oriented, has_alpha_channel
            with open_oriented(output_path) as img:
                width, height = img.size
                has_alpha = has_alpha_channel(img)
        except Exception:
            width, height = 0, 0
        _pil_ms = (_time.time() - _t_pil0) * 1000
        if _pil_ms > 200:
            log.warning(f"SLOWTRACE_METADATA: PIL decode {output_path} took {_pil_ms:.0f}ms")

    megapixels = (width * height) / 1_000_000

    # For images, extract generation metadata from embedded EXIF/PNG chunks
    # (Videos pass generation_metadata directly since it can't be embedded)
    if not is_video and generation_metadata is None:
        _t_exif0 = _time.time()
        try:
            generation_metadata = extract_stimma_metadata(file_path)
        except Exception as e:
            log.warning(f"Failed to extract stimma metadata from {output_path}: {e}")
        _exif_ms = (_time.time() - _t_exif0) * 1000
        if _exif_ms > 200:
            log.warning(f"SLOWTRACE_METADATA: EXIF extract {output_path} took {_exif_ms:.0f}ms")

    _total_ms = (_time.time() - _t_start) * 1000
    log.info(f"SLOWTRACE_METADATA_TOTAL: {output_path} thread-side metadata computation took {_total_ms:.0f}ms")

    return {
        'file_hash': file_hash,
        'width': width,
        'height': height,
        'has_alpha': has_alpha,
        'duration': duration,
        'audio_sample_rate': audio_sample_rate,
        'audio_channels': audio_channels,
        'audio_bit_depth': audio_bit_depth,
        'audio_bitrate': audio_bitrate,
        'audio_codec': audio_codec,
        'megapixels': megapixels,
        'generation_metadata': generation_metadata,
    }


class GenerationQueue:
    """Manages the generation job queue."""

    def __init__(self):
        self.scheduler = get_scheduler()
        self._workers_running = False
        self._worker_tasks = []
        self._finalize_tasks = set()  # detached post-processing tails (keep refs)
        # generator_instance_id -> count of jobs whose GPU work is done but whose
        # post-processing tail is still running. These are NOT occupying a GPU,
        # so they must not count against a forever-mode client's concurrency.
        self._finalizing_per_client: Dict[str, int] = {}
        self._websocket_manager = None
        # Forever mode: track clients that want continuous work
        # backend_name -> generator_instance_id -> max_concurrency (0 = unlimited)
        self._forever_mode_clients: Dict[str, Dict[str, int]] = {}
        # Track last served client per backend for round-robin fairness
        self._last_served_client: Dict[str, str] = {}
        # Track pending work requests per backend (timestamps for TTL-based self-healing)
        self._pending_work_requests: Dict[str, List[float]] = {}
        # Track pending work requests per client (timestamps for TTL-based self-healing)
        self._pending_work_requests_per_client: Dict[str, List[float]] = {}
        # Lock to protect forever mode slot filling from concurrent access
        self._forever_mode_lock = asyncio.Lock()
        # Event to wake workers immediately when a job is submitted
        self._job_submitted_event = asyncio.Event()

        # Prompt warm pool: server-owned, in-memory-only pre-enhancement of
        # generate-forever prompts. Scoped exactly to a generator instance's
        # forever-mode lifecycle (never persisted, never survives a restart).
        # generator_instance_id -> desired {tool_id, prompt, instructions, model,
        # is_video, is_audio, input_image_count, prompt_sources_signature,
        # concurrency, profile_id, updated_at}
        self._prompt_warm_intent: Dict[str, Dict[str, Any]] = {}
        # generator_instance_id -> list of ready preload dicts (shape matches
        # what prompt_pipeline._validated_prompt_preload expects)
        self._prompt_warm_ready: Dict[str, List[Dict[str, Any]]] = {}
        # generator_instance_id -> set of in-flight refill asyncio.Tasks
        self._prompt_warm_tasks: Dict[str, set] = {}

    def _get_db(self, profile_id: str = None):
        """Get database for the specified profile or current profile."""
        if profile_id is None:
            profile_id = get_current_profile()
        return get_database_registry().get_database(profile_id)

    def _get_all_jobs_dbs(self) -> List[tuple]:
        """
        Get all profile databases for worker polling.

        Returns:
            List of (profile_id, Database) tuples for all active profiles
        """
        registry = get_database_registry()
        profiles = registry.list_profiles()
        return [(p['id'], registry.get_database(p['id'])) for p in profiles]

    def set_websocket_manager(self, ws_manager):
        """Set the WebSocket manager for broadcasting events."""
        self._websocket_manager = ws_manager

    def get_websocket_manager(self):
        """Get the WebSocket manager (None until the app wires it)."""
        return self._websocket_manager

    def _prune_expired_pending(self):
        """Remove pending request timestamps older than PENDING_REQUEST_TTL.

        This self-heals counters when the frontend drops a work request
        without ever calling the submit API or sending a decline message.
        """
        now = time.monotonic()
        for key in list(self._pending_work_requests):
            before = len(self._pending_work_requests[key])
            self._pending_work_requests[key] = [
                t for t in self._pending_work_requests[key]
                if now - t < PENDING_REQUEST_TTL
            ]
            expired = before - len(self._pending_work_requests[key])
            if expired > 0:
                log.warning(f"Forever mode: expired {expired} stale pending request(s) for backend {key}")
        for key in list(self._pending_work_requests_per_client):
            before = len(self._pending_work_requests_per_client[key])
            self._pending_work_requests_per_client[key] = [
                t for t in self._pending_work_requests_per_client[key]
                if now - t < PENDING_REQUEST_TTL
            ]
            expired = before - len(self._pending_work_requests_per_client[key])
            if expired > 0:
                log.warning(f"Forever mode: expired {expired} stale pending request(s) for client {key}")

    async def register_forever_mode(self, generator_instance_id: str, backend_name: str, max_concurrency: int = 0):
        """Register a client as wanting continuous work.

        Args:
            generator_instance_id: Unique ID of the generator instance
            backend_name: Name of the backend to generate with
            max_concurrency: Maximum concurrent jobs for this client (0 = unlimited)
        """
        if backend_name not in self._forever_mode_clients:
            self._forever_mode_clients[backend_name] = {}
        self._forever_mode_clients[backend_name][generator_instance_id] = max_concurrency
        log.info(f"Forever mode: registered {generator_instance_id} for backend {backend_name} (max_concurrency={max_concurrency})")
        # Immediately try to fill all available slots
        await self._fill_available_slots(backend_name)

    async def unregister_forever_mode(self, generator_instance_id: str, backend_name: str):
        """Unregister a client from continuous work."""
        if backend_name in self._forever_mode_clients:
            self._forever_mode_clients[backend_name].pop(generator_instance_id, None)
            # Release pending request reservations for this client from the global counter
            client_pending_count = len(self._pending_work_requests_per_client.get(generator_instance_id, []))
            if client_pending_count > 0 and backend_name in self._pending_work_requests:
                # Remove that many entries from the backend list (oldest first)
                self._pending_work_requests[backend_name] = self._pending_work_requests[backend_name][client_pending_count:]
                log.debug(f"Forever mode: released {client_pending_count} pending requests for {backend_name}, pending now {len(self._pending_work_requests[backend_name])}")
            self._pending_work_requests_per_client.pop(generator_instance_id, None)
            log.info(f"Forever mode: unregistered {generator_instance_id} from backend {backend_name}")
        # Forever mode is the only thing that authorizes the prompt warm pool to
        # exist - stopping it (for any backend) tears the pool down immediately.
        self.teardown_prompt_warm_pool(generator_instance_id)

    async def cleanup_disconnected_client(self, generator_instance_id: str):
        """
        Clean up when a generator instance disconnects.
        - Unregister from all backends' forever mode
        - Cancel all queued jobs for this instance across all profile databases
        """
        log.info(f"Cleaning up disconnected client: {generator_instance_id}")

        # Unregister from all backends' forever mode and release pending request reservations
        client_pending_count = len(self._pending_work_requests_per_client.get(generator_instance_id, []))
        for backend_name in list(self._forever_mode_clients.keys()):
            if generator_instance_id in self._forever_mode_clients[backend_name]:
                self._forever_mode_clients[backend_name].pop(generator_instance_id, None)
                # Release all pending request reservations for this client from the backend list
                if client_pending_count > 0 and backend_name in self._pending_work_requests:
                    self._pending_work_requests[backend_name] = self._pending_work_requests[backend_name][client_pending_count:]
                    log.debug(f"Forever mode: released {client_pending_count} pending requests for {backend_name}, pending now {len(self._pending_work_requests[backend_name])}")
                log.info(f"Forever mode: unregistered {generator_instance_id} from backend {backend_name} (disconnect)")

        # Clear per-client pending list
        self._pending_work_requests_per_client.pop(generator_instance_id, None)

        # Cancel all queued jobs for this instance
        await self.cancel_queued_jobs_for_instance(generator_instance_id, error_message='Client disconnected')

        # A dropped connection means there's no one left to consume warm prompts
        # or refresh the intent - tear it down rather than let it idle to TTL.
        self.teardown_prompt_warm_pool(generator_instance_id)

    # --- Prompt warm pool ---------------------------------------------------
    #
    # Server-owned replacement for client-driven speculative prompt-enhancement
    # preloading. Exists ONLY while a generator instance's forever-mode
    # registration is live (see unregister_forever_mode/cleanup_disconnected_client
    # above for the two explicit teardown paths; _prompt_warm_pool_stale below is
    # the TTL backstop for a client that vanishes without either). Never
    # persisted - a fresh process always starts with an empty pool.

    _PROMPT_WARM_INTENT_FIELDS = (
        'tool_id', 'prompt', 'instructions', 'model', 'is_video', 'is_audio',
        'input_image_count', 'prompt_sources_signature', 'profile_id',
    )

    def _prompt_warm_pool_stale(self, generator_instance_id: str) -> bool:
        intent = self._prompt_warm_intent.get(generator_instance_id)
        if not intent:
            return True
        return (time.monotonic() - intent['updated_at']) > PROMPT_WARM_POOL_TTL

    async def update_prompt_warm_pool(
        self,
        generator_instance_id: str,
        *,
        tool_id: str,
        prompt: str,
        instructions: Optional[str],
        model: Optional[str],
        is_video: bool,
        is_audio: bool,
        input_image_count: int,
        prompt_sources_signature: str,
        concurrency: int,
        profile_id: str,
    ) -> None:
        """Set/refresh what should be kept warm for this generator instance.

        Fire-and-forget from the caller's perspective: bookkeeping only, then
        spawns background refill tasks and returns immediately without ever
        waiting on an LLM call. If the prompt/settings changed since the last
        call, whatever was warming for the old signature is discarded - that's
        by design, matching generate-forever's "throw away stale LLM work"
        contract.
        """
        concurrency = max(0, min(concurrency, PROMPT_WARM_POOL_MAX_CONCURRENCY))
        # profile_id is part of the comparable snapshot, not just bookkeeping:
        # GenerationQueue is a process-wide singleton serving multiple profiles,
        # and entries warmed under one profile's DB/wildcards/segments must
        # never be served to a submit under a different profile.
        new_snapshot = {
            'tool_id': tool_id, 'prompt': prompt, 'instructions': instructions,
            'model': model, 'is_video': is_video, 'is_audio': is_audio,
            'input_image_count': input_image_count,
            'prompt_sources_signature': prompt_sources_signature,
            'profile_id': profile_id,
        }
        existing = self._prompt_warm_intent.get(generator_instance_id)
        existing_snapshot = (
            {k: existing[k] for k in self._PROMPT_WARM_INTENT_FIELDS} if existing else None
        )
        if existing_snapshot != new_snapshot:
            self._cancel_prompt_warm_tasks(generator_instance_id)
            self._prompt_warm_ready[generator_instance_id] = []

        self._prompt_warm_intent[generator_instance_id] = {
            **new_snapshot,
            'concurrency': concurrency,
            'updated_at': time.monotonic(),
        }

        if concurrency <= 0:
            self.teardown_prompt_warm_pool(generator_instance_id)
            return

        self._top_up_prompt_warm_pool(generator_instance_id)

    def _cancel_prompt_warm_tasks(self, generator_instance_id: str) -> None:
        tasks = self._prompt_warm_tasks.pop(generator_instance_id, None)
        if not tasks:
            return
        for task in tasks:
            task.cancel()

    def _top_up_prompt_warm_pool(self, generator_instance_id: str) -> None:
        intent = self._prompt_warm_intent.get(generator_instance_id)
        if not intent:
            return
        ready = self._prompt_warm_ready.setdefault(generator_instance_id, [])
        tasks = self._prompt_warm_tasks.setdefault(generator_instance_id, set())
        needed = intent['concurrency'] - len(ready) - len(tasks)
        for _ in range(max(0, needed)):
            task = asyncio.create_task(self._refill_prompt_warm_pool(generator_instance_id, intent))
            tasks.add(task)

            def _on_refill_done(t, gid=generator_instance_id):
                self._prompt_warm_tasks.get(gid, set()).discard(t)

            task.add_done_callback(_on_refill_done)

    async def _refill_prompt_warm_pool(self, generator_instance_id: str, intent: Dict[str, Any]) -> None:
        """Background task body: enhance one variant and append it if the
        intent hasn't moved on since this task started."""
        try:
            from prompt_pipeline import (
                _improve_with_verbatim_protection,
                _profile_wildcards_and_segments,
                resolve_wildcards_for_llm,
            )
            wildcards, segments = _profile_wildcards_and_segments(intent['profile_id'])
            processed_prompt = resolve_wildcards_for_llm(intent['prompt'], wildcards, segments)
            db = self._get_db(intent['profile_id'])
            improved_prompt = await _improve_with_verbatim_protection(
                db,
                processed_prompt,
                instructions=intent['instructions'],
                model=intent['model'],
                is_video=intent['is_video'],
                is_audio=intent['is_audio'],
                input_image_count=intent['input_image_count'],
                media_id=None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"Prompt warm pool: refill failed for {generator_instance_id}: {e}")
            return

        current = self._prompt_warm_intent.get(generator_instance_id)
        current_snapshot = (
            {k: current[k] for k in self._PROMPT_WARM_INTENT_FIELDS} if current else None
        )
        target_snapshot = {k: intent[k] for k in self._PROMPT_WARM_INTENT_FIELDS}
        if current_snapshot != target_snapshot:
            # Prompt changed while this was in flight - discard (accepted waste).
            return

        self._prompt_warm_ready.setdefault(generator_instance_id, []).append({
            'originalPrompt': intent['prompt'],
            'processedPrompt': processed_prompt,
            'promptSourcesSignature': intent['prompt_sources_signature'],
            'instructions': intent['instructions'],
            'model': intent['model'],
            'isVideo': intent['is_video'],
            'isAudio': intent['is_audio'],
            'inputImageCount': intent['input_image_count'],
            'improvedPrompt': improved_prompt,
        })

    def consume_prompt_warm_pool(self, generator_instance_id: str) -> Optional[Dict[str, Any]]:
        """Pop one ready pre-enhanced prompt for this instance, if any, and
        trigger a refill to replace it. Returns None on miss/stale - callers
        must fall back to synchronous enhancement, same as when no client
        preload exists at all (no regression versus today's behavior).
        """
        if self._prompt_warm_pool_stale(generator_instance_id):
            self.teardown_prompt_warm_pool(generator_instance_id)
            return None
        ready = self._prompt_warm_ready.get(generator_instance_id)
        if not ready:
            return None
        # A successful consume proves the session is still live even if the
        # client hasn't sent an explicit update ping recently (e.g. a steady
        # forever-mode run with an unchanging prompt) - refresh the TTL clock
        # so an actively-used pool never expires out from under itself.
        self._prompt_warm_intent[generator_instance_id]['updated_at'] = time.monotonic()
        entry = ready.pop(0)
        self._top_up_prompt_warm_pool(generator_instance_id)
        return entry

    def teardown_prompt_warm_pool(self, generator_instance_id: str) -> None:
        self._cancel_prompt_warm_tasks(generator_instance_id)
        self._prompt_warm_ready.pop(generator_instance_id, None)
        self._prompt_warm_intent.pop(generator_instance_id, None)

    async def decline_work_request(self, generator_instance_id: str, backend_name: str):
        """Handle a client declining a work request (couldn't submit).

        Pops one pending timestamp for the client/backend pair and re-fills slots.
        """
        timestamps = self._pending_work_requests.get(backend_name, [])
        if timestamps:
            timestamps.pop(0)
        timestamps = self._pending_work_requests_per_client.get(generator_instance_id, [])
        if timestamps:
            timestamps.pop(0)
        log.debug(f"Forever mode: client {generator_instance_id} declined work for {backend_name}")
        # Re-fill to potentially assign the slot to another client or retry
        await self._fill_available_slots(backend_name)

    async def cancel_queued_jobs_for_instance(self, generator_instance_id: str,
                                               error_message: str = 'Cancelled - cleanup') -> int:
        """
        Cancel all queued jobs for a specific generator instance across all profile databases.
        Returns the number of jobs cancelled.
        """
        total_cancelled = 0

        for profile_id, db in self._get_all_jobs_dbs():
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(GenerationJob).where(
                        GenerationJob.generator_instance_id == generator_instance_id,
                        GenerationJob.status == 'queued'
                    )
                )
                queued_jobs = result.scalars().all()

                if not queued_jobs:
                    continue

                log.info(f"Cancelling {len(queued_jobs)} queued jobs in profile {profile_id} for instance {generator_instance_id}")
                for job in queued_jobs:
                    job.status = 'cancelled'
                    job.error = error_message
                    job.completed_at = datetime.utcnow()

                await session.commit()
                total_cancelled += len(queued_jobs)

                # Broadcast cancellation events
                if self._websocket_manager:
                    with ProfileScope(profile_id):
                        for job in queued_jobs:
                            await self._websocket_manager.broadcast('generation_job_cancelled', {
                                'job': job.to_dict(),
                                'generator_instance_id': job.generator_instance_id,
            
                            })

        return total_cancelled

    def _get_next_client(self, backend_name: str, clients_with_capacity: list) -> Optional[str]:
        """Round-robin through clients with available capacity for fairness."""
        if not clients_with_capacity:
            return None
        client_list = sorted(clients_with_capacity)  # Stable ordering
        last = self._last_served_client.get(backend_name)
        if last and last in client_list:
            idx = client_list.index(last)
            return client_list[(idx + 1) % len(client_list)]
        return client_list[0]

    async def _get_client_active_jobs(self, generator_instance_id: str) -> int:
        """Count active jobs (queued, assigned, or processing) for a specific client across all profiles."""
        total = 0
        for profile_id, db in self._get_all_jobs_dbs():
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(func.count(GenerationJob.id)).where(
                        GenerationJob.generator_instance_id == generator_instance_id,
                        GenerationJob.status.in_(['queued', 'assigned', 'processing'])
                    )
                )
                total += result.scalar() or 0
        return total

    def _get_clients_with_capacity(self, backend_name: str, client_active_jobs: dict,
                                     pending_snapshot: dict, requests_sent_this_call: dict,
                                     clients_dict: Optional[Dict[str, int]] = None) -> list:
        """
        Get list of clients that have available capacity for this backend.

        Args:
            backend_name: The backend name
            client_active_jobs: Dict of generator_instance_id -> active job count (snapshot from DB)
            pending_snapshot: Dict of generator_instance_id -> pending count at START of _fill_available_slots
                              (requests from PREVIOUS calls that haven't been fulfilled yet)
            requests_sent_this_call: Dict of generator_instance_id -> requests sent in THIS call

        Total in-flight = active_snapshot + pending_snapshot + sent_this_call
        - active_snapshot: jobs currently in DB (queued/assigned/processing)
        - pending_snapshot: requests sent by previous calls, not yet submitted as jobs
        - sent_this_call: requests we're sending in this call

        Returns:
            List of generator_instance_ids that can accept more work
        """
        clients_dict = clients_dict if clients_dict is not None else self._forever_mode_clients.get(backend_name, {})
        clients_with_capacity = []

        for client_id, max_concurrency in list(clients_dict.items()):
            active = client_active_jobs.get(client_id, 0)
            pending_prev = pending_snapshot.get(client_id, 0)
            sent_this_call = requests_sent_this_call.get(client_id, 0)
            total_in_flight = active + pending_prev + sent_this_call

            if max_concurrency == 0:  # Unlimited
                log.debug(f"Forever mode: client {client_id} unlimited (active={active}, pending_prev={pending_prev}, sent_this_call={sent_this_call})")
                clients_with_capacity.append(client_id)
            elif total_in_flight < max_concurrency:
                log.debug(f"Forever mode: client {client_id} has capacity ({total_in_flight}/{max_concurrency}, active={active}, pending_prev={pending_prev}, sent_this_call={sent_this_call})")
                clients_with_capacity.append(client_id)
            else:
                log.debug(f"Forever mode: client {client_id} at capacity ({total_in_flight}/{max_concurrency}, active={active}, pending_prev={pending_prev}, sent_this_call={sent_this_call})")

        return clients_with_capacity

    async def _fill_available_slots(self, backend_name: str):
        """Keep requesting work until all available slots are filled.

        Uses a lock to prevent race conditions when multiple calls happen
        concurrently (e.g., from job completion + registration at same time).

        Respects per-client max_concurrency limits - won't send work requests
        to clients that have reached their configured limit.
        """
        # Use lock to prevent concurrent slot filling which can cause
        # more work requests than available slots
        async with self._forever_mode_lock:
            # Prune expired pending requests (self-healing for dropped work requests)
            self._prune_expired_pending()

            # Snapshot client map up front: unregister/disconnect can mutate this dict
            # while we await DB queries and websocket broadcasts below.
            clients_dict_snapshot = dict(self._forever_mode_clients.get(backend_name, {}))
            if not clients_dict_snapshot:
                return

            # Calculate available capacity ONCE at the start
            # This avoids races where jobs get assigned during the loop
            from backend_registry import get_backend_registry
            backend_registry = get_backend_registry()

            backends = await backend_registry.list_backends()
            backend_state = backends.get(backend_name)
            if not backend_state:
                return

            # Count queued jobs across ALL profile databases for this backend
            queued_count = 0
            for profile_id, db in self._get_all_jobs_dbs():
                async with db.async_session_maker() as session:
                    result = await session.execute(
                        select(func.count(GenerationJob.id)).where(
                            GenerationJob.backend_name == backend_name,
                            GenerationJob.status == 'queued'
                        )
                    )
                    queued_count += result.scalar() or 0

            pending = len(self._pending_work_requests.get(backend_name, []))
            backend_slots_to_fill = backend_state['max_concurrent'] - backend_state['current_jobs'] - pending - queued_count

            log.debug(f"Forever mode: filling {backend_name}: max_concurrent={backend_state['max_concurrent']}, current_jobs={backend_state['current_jobs']}, pending={pending}, queued={queued_count}, backend_slots_to_fill={backend_slots_to_fill}")

            if backend_slots_to_fill <= 0:
                return

            # Build a map of active jobs per client for capacity checking (snapshot from DB).
            # Subtract jobs that are still 'processing' in the DB only because their
            # post-processing tail hasn't finished — their GPU work is done, so they
            # don't occupy a slot and must not count against the client's concurrency.
            client_active_jobs = {}
            client_ids = list(clients_dict_snapshot.keys())
            for client_id in client_ids:
                db_active = await self._get_client_active_jobs(client_id)
                finalizing = self._finalizing_per_client.get(client_id, 0)
                client_active_jobs[client_id] = max(0, db_active - finalizing)

            # Capture pending snapshot at START (requests from PREVIOUS calls not yet fulfilled)
            # This must be captured BEFORE we send any new requests
            pending_snapshot = {
                client_id: len(self._pending_work_requests_per_client.get(client_id, []))
                for client_id in client_ids
            }

            # Track requests sent per client in THIS call
            requests_sent_this_call = {}

            # Send requests until either backend is full OR no clients have capacity
            requests_sent = 0
            while requests_sent < backend_slots_to_fill:
                # Check capacity using: active_snapshot + pending_snapshot + sent_this_call
                # - active_snapshot: jobs in DB
                # - pending_snapshot: requests from previous calls (captured at start, immutable)
                # - sent_this_call: requests we're sending now
                clients_with_capacity = self._get_clients_with_capacity(
                    backend_name, client_active_jobs, pending_snapshot, requests_sent_this_call,
                    clients_dict=clients_dict_snapshot
                )

                if not clients_with_capacity:
                    log.debug(f"Forever mode: no clients with capacity for {backend_name}, stopping after {requests_sent} requests")
                    break

                next_client = self._get_next_client(backend_name, clients_with_capacity)
                if not next_client or not self._websocket_manager:
                    break

                # Track this request in our local counter (for capacity checking within this call)
                requests_sent_this_call[next_client] = requests_sent_this_call.get(next_client, 0) + 1

                # Also append timestamp to global pending lists (for other code paths)
                now = time.monotonic()
                self._pending_work_requests.setdefault(backend_name, []).append(now)
                self._pending_work_requests_per_client.setdefault(next_client, []).append(now)

                log.debug(f"Forever mode: requesting work from {next_client} for {backend_name} ({requests_sent+1}/{backend_slots_to_fill}, sent_this_call={requests_sent_this_call[next_client]})")
                await self._websocket_manager.broadcast('generation_request_work', {
                    'generator_instance_id': next_client,
                    'backend_name': backend_name,
                }, include_profile=False)
                self._last_served_client[backend_name] = next_client
                requests_sent += 1

    def _find_specific_media_id(self, params: dict, input_key: str) -> Optional[int]:
        """
        Find the most specific media_id for a given input key.

        Batch jobs set both:
        - input_media_id (generic, may be the input SET's ID)
        - {input_key}_media_id (specific to the individual item)

        We prefer the specific one to get the correct individual item lineage.
        """
        # First try the specific key (e.g., input_image_media_id, audio_file_media_id)
        specific_id = params.get(f'{input_key}_media_id')
        if specific_id is not None:
            return specific_id

        # Fall back to generic input_media_id
        return params.get('input_media_id')

    def _find_any_media_id(self, params: dict) -> Optional[int]:
        """
        Find any specific media_id in params, preferring specific keys over generic.

        Looks for keys ending in _media_id (excluding 'input_media_id') first,
        then falls back to input_media_id.
        """
        # Find all *_media_id keys except the generic one
        specific_keys = [k for k in params.keys()
                        if k.endswith('_media_id') and k != 'input_media_id']

        # Use first specific one found
        for key in specific_keys:
            value = params.get(key)
            if value is not None:
                return value

        # Fall back to generic
        return params.get('input_media_id')

    async def _resolve_lineage(self, params: dict, task_type: str, profile_id: str) -> dict:
        """
        Resolve input media IDs and build lineage data for a generation job.

        Returns dict with:
        - source_inputs: List of direct input references (media_id, file_path, role)
        - lineage_trace: Full generation history inherited from parents
        """
        source_inputs = []
        lineage_trace = []

        async with self._get_db(profile_id).async_session_maker() as session:
            # --- input_images handling (image-to-image, image-to-video, upscale-image,
            #     inpaint, outpaint, text-to-video dual-mode, etc.) ---
            input_images = params.get('input_images', [])
            input_media_ids = params.get('input_media_ids', [])

            if input_images:
                # ControlNet: use original paths for lineage when preprocessor was applied
                original_paths = params.get('_original_input_paths', [])
                input_preprocessors = params.get('_input_preprocessors', [])
                input_preprocessor_params = params.get('_input_preprocessor_params', [])
                input_paint_layers = params.get('_input_paint_layers', [])
                input_extend_padding = params.get('_input_extend_padding', [])
                input_extend_bg_colors = params.get('_input_extend_bg_colors', [])
                input_scales = params.get('_input_scales', [])
                input_flips = params.get('_input_flips', [])
                input_crops = params.get('_input_crops', [])

                # Determine role names based on task type
                is_video_task = task_type in ('image-to-video', 'text-to-video')

                for i, path in enumerate(input_images):
                    # Use original path for lineage if available (controlnet preprocessing)
                    lineage_path = original_paths[i] if i < len(original_paths) else path
                    media_id = input_media_ids[i] if i < len(input_media_ids) else None

                    # When agent passes media IDs directly in input_images (as int
                    # or digit-string — LLM tool calls sometimes JSON-serialize
                    # ints as strings), use them as media_id and resolve the file
                    # path.
                    if media_id is None:
                        if isinstance(lineage_path, int) and not isinstance(lineage_path, bool):
                            media_id = lineage_path
                        elif isinstance(lineage_path, str) and lineage_path.isdigit():
                            media_id = int(lineage_path)
                        if media_id is not None:
                            resolved_path = await self._resolve_media_id_to_path(session, media_id)
                            lineage_path = resolved_path or str(media_id)

                    # Try to resolve file path to media ID if not provided
                    if media_id is None and lineage_path:
                        media_id = await self._resolve_path_to_media_id(session, lineage_path)

                    # Assign role based on task type and position
                    if is_video_task:
                        role = "start_image" if i == 0 else "end_image"
                    else:
                        role = "input_image"

                    entry = {
                        "media_id": media_id,
                        "file_path": lineage_path,
                        "role": role
                    }
                    # Add preprocessor if applied to this image
                    preprocessor = input_preprocessors[i] if i < len(input_preprocessors) else None
                    if preprocessor:
                        entry["preprocessor"] = preprocessor
                        pp_params = input_preprocessor_params[i] if i < len(input_preprocessor_params) else None
                        if pp_params:
                            entry["preprocessor_params"] = pp_params
                    # Add paint layer if applied
                    paint_layer = input_paint_layers[i] if i < len(input_paint_layers) else None
                    if paint_layer:
                        entry["paint_layer"] = paint_layer
                    # Add extend padding if applied
                    extend_pad = input_extend_padding[i] if i < len(input_extend_padding) else None
                    if extend_pad:
                        entry["extend_padding"] = extend_pad
                    # Add extend background color if applied
                    extend_bg = input_extend_bg_colors[i] if i < len(input_extend_bg_colors) else None
                    if extend_bg:
                        entry["extend_bg_color"] = extend_bg
                    # Add scale if applied
                    scale = input_scales[i] if i < len(input_scales) else None
                    if scale:
                        entry["scale"] = scale
                    # Add flip/rotate if applied
                    flip = input_flips[i] if i < len(input_flips) else None
                    if flip:
                        entry["flip"] = flip
                    # Add crop if applied
                    crop = input_crops[i] if i < len(input_crops) else None
                    if crop:
                        entry["crop"] = crop
                    source_inputs.append(entry)

                    # Inherit lineage from all input images
                    if media_id:
                        parent_trace = await self._get_inherited_lineage(session, media_id)
                        lineage_trace = self._merge_lineage_traces(lineage_trace, parent_trace)

            # --- input_videos handling (video-to-video, video-stitch, video-extend, upscale-video) ---
            input_videos = params.get('input_videos', [])
            input_video_media_ids = params.get('input_video_media_ids', [])

            if input_videos:
                for i, path in enumerate(input_videos):
                    media_id = input_video_media_ids[i] if i < len(input_video_media_ids) else None
                    # Try to resolve file path to media ID if not provided
                    if media_id is None and path:
                        media_id = await self._resolve_path_to_media_id(session, path)
                    source_inputs.append({
                        "media_id": media_id,
                        "file_path": path,
                        "role": "input_video"
                    })

                    # Inherit lineage from all input videos
                    if media_id:
                        parent_trace = await self._get_inherited_lineage(session, media_id)
                        lineage_trace = self._merge_lineage_traces(lineage_trace, parent_trace)

        return {
            "source_inputs": source_inputs,
            "lineage_trace": lineage_trace
        }

    async def _resolve_path_to_media_id(self, session: AsyncSession, file_path: str) -> Optional[int]:
        """
        Try to find a MediaItem by file path.
        Falls back to filename matching for workspace copies.
        Returns the media ID if found, None otherwise.
        """
        if not file_path:
            return None
        # Exact path match first
        result = await session.execute(
            select(MediaItem.id).where(MediaItem.file_path == file_path)
        )
        row = result.first()
        if row:
            return row[0]
        # Fallback: match by filename (handles workspace copies)
        basename = os.path.basename(file_path)
        if basename:
            result = await session.execute(
                select(MediaItem.id).where(
                    MediaItem.file_path.like(f'%/{basename}')
                ).order_by(MediaItem.id.desc()).limit(1)
            )
            row = result.first()
            if row:
                log.debug(f"Resolved workspace path '{basename}' to media_id {row[0]} via filename fallback")
                return row[0]
        return None

    async def _resolve_media_id_to_path(self, session: AsyncSession, media_id: int) -> Optional[str]:
        """
        Get file path for a media ID.
        Returns the file path if found, None otherwise.
        """
        if not media_id:
            return None
        result = await session.execute(
            select(MediaItem.file_path).where(MediaItem.id == media_id)
        )
        row = result.first()
        return row[0] if row else None

    async def _resolve_media_ids_in_params(self, session: AsyncSession, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve any media IDs in the parameters dict to file paths.

        Accepts media IDs as either ``int`` or digit-only ``str`` — LLM tool
        calls sometimes JSON-serialize ints as strings (``input_images=["7658"]``)
        and the centralized resolver should treat both shapes the same so the
        provider always sees a real file path.

        This is needed for external providers that need file paths to upload,
        when the agent passes media IDs instead of paths.

        Keys checked: input_images, input_videos (arrays), mask (single)
        """
        # Keys that contain single values (file path or media ID)
        single_keys = {'mask'}
        # Keys that contain arrays
        array_keys = {'input_images', 'input_videos'}

        def _coerce_media_id(value: Any) -> Optional[int]:
            """Return ``value`` as int media-id, or None if it isn't one."""
            if isinstance(value, bool):  # bool is an int subclass — exclude
                return None
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
            return None

        processed = dict(parameters)

        # Process single-value keys
        for key in single_keys:
            if key in parameters:
                value = parameters[key]
                media_id = _coerce_media_id(value)
                if media_id is not None:
                    path = await self._resolve_media_id_to_path(session, media_id)
                    if path:
                        processed[key] = path
                        log.debug(f"Resolved {key} media_id {media_id} to path: {path}")
                    else:
                        log.warning(f"Could not resolve {key} media_id {media_id} to path")

        # Process array keys
        for key in array_keys:
            if key in parameters and isinstance(parameters[key], list):
                resolved = []
                for item in parameters[key]:
                    media_id = _coerce_media_id(item)
                    if media_id is not None:
                        path = await self._resolve_media_id_to_path(session, media_id)
                        if path:
                            resolved.append(path)
                            log.debug(f"Resolved {key} media_id {media_id} to path: {path}")
                        else:
                            log.warning(f"Could not resolve {key} media_id {media_id} to path")
                    else:
                        resolved.append(item)
                processed[key] = resolved

        return processed

    # Task types that create composite/container media - these don't transform media
    # and shouldn't be included in inherited lineage traces.
    # See utils/query_builder.py for COMPOSITE_FORMATS (stimmaset.json, stimmagrid.json)
    COMPOSITE_TASK_TYPES = {'set-creation', 'batch-output', 'grid-creation'}

    async def _get_inherited_lineage(self, session: AsyncSession, parent_media_id: int) -> list:
        """
        Get inherited lineage trace from a parent media item.

        Returns the parent's lineage_trace with the parent added as the last entry.
        Filters out grouping operations (set-creation, batch-output, grid-creation)
        since these don't transform the media and shouldn't pollute the lineage.
        """
        result = await session.execute(
            select(MediaItem).where(MediaItem.id == parent_media_id)
        )
        parent_media = result.scalar_one_or_none()

        if not parent_media:
            return []

        trace = []
        parent_meta = None

        # Parse parent's generation_metadata to get its lineage
        if parent_media.generation_metadata:
            try:
                parent_meta = json.loads(parent_media.generation_metadata)
                # Copy parent's existing lineage trace, filtering out grouping operations
                raw_trace = parent_meta.get('lineage_trace', [])
                trace = [
                    entry for entry in raw_trace
                    if entry.get('task_type') not in self.COMPOSITE_TASK_TYPES
                ]
            except json.JSONDecodeError:
                pass

        # Add the parent itself as the last entry in the trace (if not a grouping operation)
        parent_task_type = parent_meta.get('task_type') if parent_meta else None
        if parent_task_type not in self.COMPOSITE_TASK_TYPES:
            trace.append(self._build_lineage_entry(parent_media_id, parent_meta, parent_media.created_date))

        return trace

    @staticmethod
    def _merge_lineage_traces(existing: list, new: list) -> list:
        """Merge two lineage traces, deduplicating by media_id while preserving order."""
        seen = {entry.get('media_id') for entry in existing if entry.get('media_id')}
        merged = list(existing)
        for entry in new:
            mid = entry.get('media_id')
            if mid and mid not in seen:
                seen.add(mid)
                merged.append(entry)
            elif not mid:
                merged.append(entry)
        return merged

    def _build_lineage_entry(self, media_id: int, gen_meta: Optional[dict], created_date) -> dict:
        """Build a lineage trace entry with full metadata for history display."""
        entry = {
            "media_id": media_id,
            "task_type": gen_meta.get('task_type') if gen_meta else None,
            "generated_at": created_date.isoformat() + 'Z' if created_date else None,
        }

        # Include full metadata for complete history display
        if gen_meta:
            if gen_meta.get('model'):
                entry['model'] = gen_meta['model']
            if gen_meta.get('generator'):
                entry['generator'] = gen_meta['generator']
            if gen_meta.get('prompt'):
                entry['prompt'] = gen_meta['prompt']
            # Check both top-level and parameters dict for backward compatibility
            neg_prompt = gen_meta.get('negative_prompt') or gen_meta.get('parameters', {}).get('negative_prompt')
            if neg_prompt:
                entry['negative_prompt'] = neg_prompt
            # Include full parameters
            if gen_meta.get('parameters'):
                entry['parameters'] = dict(gen_meta['parameters'])
            if gen_meta.get('seed') is not None:
                entry['seed'] = gen_meta['seed']
                entry.setdefault('parameters', {})
                entry['parameters'].setdefault('seed', gen_meta['seed'])
            # Include source_inputs so we can show input images for each step
            if gen_meta.get('source_inputs'):
                entry['source_inputs'] = gen_meta['source_inputs']
            # Include tool_id for proper tool name resolution in history display
            if gen_meta.get('tool_id'):
                entry['tool_id'] = gen_meta['tool_id']

        return entry

    def _get_task_type_from_metadata(self, media: MediaItem) -> Optional[str]:
        """Extract task_type from a media item's generation_metadata."""
        if not media.generation_metadata:
            return None
        try:
            meta = json.loads(media.generation_metadata)
            return meta.get('task_type')
        except json.JSONDecodeError:
            return None

    async def _record_lineage(self, media_id: int, source_inputs: list, task_type: str, session: AsyncSession):
        """
        Record lineage relationships in the media_lineage table.

        Uses the provided session - caller is responsible for commit.
        If lineage already exists for this media_id, it is replaced.

        Args:
            media_id: The newly created media item ID
            source_inputs: List of source input dicts with media_id, file_path, role
            task_type: The task type that created this media
            session: Database session to use (caller commits)
        """
        await record_lineage_from_inputs(session, media_id, source_inputs, task_type)

    async def _clear_auto_delete_for_sources(self, source_inputs: list, profile_id: str):
        """
        Clear auto-delete flags on source media items.

        This is a separate operation that creates its own session since it's
        a non-critical background cleanup.

        Args:
            source_inputs: List of source input dicts with media_id
            profile_id: Profile database to use
        """
        source_media_ids = [
            source.get('media_id') for source in source_inputs
            if source.get('media_id') is not None
        ]

        if source_media_ids and self._websocket_manager:
            async with self._get_db(profile_id).async_session_maker() as session:
                await clear_auto_delete_for_media(session, source_media_ids, self._websocket_manager)

    async def _apply_auto_markers(
        self,
        media_id: int,
        marker_ids: List[int],
        profile_id: str
    ) -> None:
        """Apply auto-markers to a newly generated media item.

        Args:
            media_id: The media item to apply markers to
            marker_ids: List of marker IDs to apply
            profile_id: Profile database to use
        """
        if not marker_ids:
            return

        from database import MediaMarker

        async with self._get_db(profile_id).async_session_maker() as session:
            for marker_id in marker_ids:
                # Check if marker already exists (shouldn't happen, but be safe)
                existing = await session.execute(
                    select(MediaMarker).where(
                        MediaMarker.media_id == media_id,
                        MediaMarker.marker_id == marker_id
                    )
                )
                if not existing.scalar_one_or_none():
                    new_marker = MediaMarker(
                        media_id=media_id,
                        marker_id=marker_id,
                        source='auto'  # Mark as auto-applied
                    )
                    session.add(new_marker)

            try:
                await session.commit()
                log.info(f"Applied {len(marker_ids)} auto-markers to media {media_id}")

                # Clear auto-delete since the media is now marked
                # This prevents the impossible state of having both auto-delete AND markers
                if self._websocket_manager:
                    await clear_auto_delete_for_media(session, [media_id], self._websocket_manager)
                from database import AssetRevision
                from asset_association_service import mirror_media_associations_to_asset
                revision = await session.scalar(
                    select(AssetRevision).where(
                        AssetRevision.primary_media_id == media_id,
                        AssetRevision.deleted_at.is_(None),
                    )
                )
                if revision is not None:
                    await mirror_media_associations_to_asset(
                        session, media_id=media_id, asset_id=revision.asset_id
                    )
                    await session.commit()
            except IntegrityError as e:
                log.warning(f"Failed to apply auto-markers to media {media_id}: {e}")
                await session.rollback()

    def _resolve_backend_info(self, tool_id: Optional[str], backend_name: Optional[str],
                              generator_name: str) -> tuple:
        """Resolve backend_name and generator_type from tool_id or generator_name.

        Returns:
            (backend_name, generator_type) tuple
        """
        registry = ProviderRegistry.get_instance()
        generator_type = None

        if tool_id and ':' in str(tool_id):
            result = registry.get_tool(str(tool_id))
            if not result:
                raise ValueError(f"Tool not found: {tool_id}")
            provider, tool_descriptor = result
            generator_type = tool_descriptor.metadata.get('generator_type', 'unknown')

            if not backend_name:
                provider_id = provider.provider_id
                if provider_id.startswith("builtin:"):
                    backend_name = provider_id.split(":", 1)[1]
                else:
                    backend_name = provider_id
        else:
            if not backend_name:
                backend_name = generator_name
            if not backend_name:
                raise ValueError("No backend_name or tool_id provided")

            provider_id = f"builtin:{backend_name.lower()}"
            provider = registry._providers.get(provider_id)
            if not provider:
                raise ValueError(f"Backend not found: {backend_name}")
            if hasattr(provider, '_config'):
                generator_type = getattr(provider._config, 'type', 'unknown')
            else:
                generator_type = 'unknown'

        return backend_name, generator_type

    async def _create_job(
        self,
        generator_name: str,
        model_name: str,
        folder_path: str,
        parameters: Dict[str, Any],
        auto_delete_duration: Optional[str],
        generator_instance_id: Optional[str],
        backend_name: Optional[str],
        task_type: str,
        tool_id: Optional[str],
        preset_id: Optional[int],
        project_id: Optional[int] = None,
        batch_id: Optional[str] = None,
        batch_total: Optional[int] = None,
        batch_output_title: Optional[str] = None,
        batch_input_set_ids: Optional[List[int]] = None,
        output_disposition: str = 'asset',
        output_context_kind: Optional[str] = None,
        output_context_id: Optional[str] = None,
        consume_pending_request: bool = True,
    ) -> int:
        """Shared implementation for creating and submitting a generation job.

        Handles tool resolution, folder validation, DB commit, pending counter
        management, and WebSocket broadcast for both single and batch jobs.

        Returns:
            Job ID
        """
        if not generator_instance_id:
            generator_instance_id = "legacy-generate-tab"

        try:
            backend_name, generator_type = self._resolve_backend_info(tool_id, backend_name, generator_name)
            profile_id = get_current_profile()

            # Verify folder allows generation (profile-aware)
            settings = get_settings()
            valid_folders = settings.get_generation_folders_for_profile(profile_id)
            is_valid_generation_folder = any(f.path == folder_path for f in valid_folders)
            if not is_valid_generation_folder:
                raise ValueError(f"Folder does not allow generation: {folder_path}")

            # Store batch metadata in the flat params for use during completion (first job only)
            parameters = dict(parameters)
            if batch_id and batch_total is not None:
                if batch_output_title:
                    parameters["_batch_output_title"] = batch_output_title
                if batch_input_set_ids:
                    parameters["_batch_input_set_ids"] = batch_input_set_ids

            # Run correlation: one ephemeral runId per user-initiated pipeline.
            # Chain-step jobs arrive with the base job's _run_id already set.
            from pipeline_telemetry import new_run_id
            parameters.setdefault("_run_id", new_run_id())

            # One-shot flow-as-tool: tag this generation so the worker keeps its media
            # out of the library (ephemeral; hard-deleted when the run ends). The
            # contextvar is set by run_flow_once and inherited by the tool evaluator.
            from flow_runtime.ephemeral import current_ephemeral_run_id
            _eph_run = current_ephemeral_run_id()
            if _eph_run is not None:
                parameters["_ephemeral_run_id"] = _eph_run
                output_disposition = 'ephemeral'
                output_context_kind = None
                output_context_id = None

            from result_disposition_service import validate_output_disposition
            validate_output_disposition(
                output_disposition, output_context_kind, output_context_id
            )

            log.info(f"Creating job: backend_name={backend_name}, tool_id={tool_id}" +
                     (f", batch_id={batch_id}" if batch_id else ""))
            job = GenerationJob(
                status='queued',
                task_type=task_type,
                generator_type=generator_type,
                generator_name=generator_name,
                backend_name=backend_name,
                generator_instance_id=generator_instance_id,
                model_name=model_name,
                parameters=json.dumps(parameters),
                folder_path=folder_path,
                created_at=datetime.utcnow(),
                auto_delete_duration=auto_delete_duration,
                tool_id=tool_id,
                preset_id=preset_id,
                project_id=project_id,
                batch_id=batch_id,
                batch_total=batch_total,
                output_disposition=output_disposition,
                output_context_kind=output_context_kind,
                output_context_id=output_context_id,
            )

            async with self._get_db(profile_id).async_session_maker() as session:
                session.add(job)
                await session.commit()
                await session.refresh(job)
                job_id = job.id

            # Wake workers immediately
            self._job_submitted_event.set()

            # Broadcast job queued event
            if self._websocket_manager:
                broadcast_data = {
                    'job': job.to_dict(),
                    'generator_instance_id': generator_instance_id,
                }
                if batch_id:
                    broadcast_data['batch_id'] = batch_id
                await self._websocket_manager.broadcast('generation_job_queued', broadcast_data)

            # Track tool usage telemetry (toolRef/toolSource/modelFamily via the
            # classification helpers — raw tool ids / model strings never egress)
            from telemetry import get_telemetry_client
            from pipeline_telemetry import tool_job_props
            tool_used_props = tool_job_props(job)
            # Add controlnet preprocessor info if present
            input_preprocessors = parameters.get("_input_preprocessors", [])
            if input_preprocessors:
                # Use first preprocessor name (primary controlnet)
                tool_used_props["controlnet"] = input_preprocessors[0]
            get_telemetry_client().track("tool_used", tool_used_props, category="generation")

            return job_id
        finally:
            # Consume a forever-mode reservation only when the caller says this
            # submit was triggered by a reserved work request. Manual submits
            # and local follow-up submits can happen while pending reservations
            # exist for the same client; they must not steal those slots.
            if consume_pending_request:
                timestamps = self._pending_work_requests.get(backend_name, []) if backend_name else []
                if timestamps:
                    timestamps.pop(0)
                    log.debug(f"Forever mode: job submitted for {backend_name}, pending now {len(timestamps)}")
                timestamps = self._pending_work_requests_per_client.get(generator_instance_id, []) if generator_instance_id else []
                if timestamps:
                    timestamps.pop(0)
                    log.debug(f"Forever mode: job submitted by {generator_instance_id}, client_pending now {len(timestamps)}")

    async def submit_job(
        self,
        generator_name: str,
        model_name: str,
        folder_path: str,
        parameters: Dict[str, Any],
        auto_delete_duration: Optional[str] = None,
        generator_instance_id: Optional[str] = None,
        backend_name: Optional[str] = None,
        task_type: str = "text-to-image",
        tool_id: Optional[str] = None,
        preset_id: Optional[int] = None,
        project_id: Optional[int] = None,
        output_disposition: str = 'asset',
        output_context_kind: Optional[str] = None,
        output_context_id: Optional[str] = None,
        consume_pending_request: bool = True,
    ) -> int:
        """Submit a new generation job to the queue.

        ``parameters`` is a single flat dict holding everything (prompt,
        input_images, mask, seed, steps, cfg, loras, ...).

        Returns:
            Job ID
        """
        return await self._create_job(
            generator_name=generator_name, model_name=model_name,
            folder_path=folder_path, parameters=parameters,
            auto_delete_duration=auto_delete_duration,
            generator_instance_id=generator_instance_id,
            backend_name=backend_name, task_type=task_type,
            tool_id=tool_id, preset_id=preset_id,
            project_id=project_id,
            output_disposition=output_disposition,
            output_context_kind=output_context_kind,
            output_context_id=output_context_id,
            consume_pending_request=consume_pending_request,
        )

    async def submit_batch_job(
        self,
        generator_name: str,
        model_name: str,
        folder_path: str,
        parameters: Dict[str, Any],
        batch_id: str,
        batch_total: Optional[int] = None,
        batch_output_title: Optional[str] = None,
        batch_input_set_ids: Optional[List[int]] = None,
        auto_delete_duration: Optional[str] = None,
        generator_instance_id: Optional[str] = None,
        backend_name: Optional[str] = None,
        task_type: str = "text-to-image",
        tool_id: Optional[str] = None,
        preset_id: Optional[int] = None,
        project_id: Optional[int] = None,
        output_disposition: str = 'asset',
        output_context_kind: Optional[str] = None,
        output_context_id: Optional[str] = None,
        consume_pending_request: bool = True,
    ) -> int:
        """Submit a generation job that is part of a batch.

        Returns:
            Job ID
        """
        return await self._create_job(
            generator_name=generator_name, model_name=model_name,
            folder_path=folder_path, parameters=parameters,
            auto_delete_duration=auto_delete_duration,
            generator_instance_id=generator_instance_id,
            backend_name=backend_name, task_type=task_type,
            tool_id=tool_id, preset_id=preset_id,
            project_id=project_id,
            batch_id=batch_id, batch_total=batch_total,
            batch_output_title=batch_output_title,
            batch_input_set_ids=batch_input_set_ids,
            output_disposition=output_disposition,
            output_context_kind=output_context_kind,
            output_context_id=output_context_id,
            consume_pending_request=consume_pending_request,
        )

    async def get_job(self, job_id: int, profile_id: str = None) -> Optional[Dict[str, Any]]:
        """Get job details by ID.

        Args:
            job_id: The job ID to look up
            profile_id: Optional profile to search in. If not provided, searches all profiles.
        """
        if profile_id:
            # Fast path: known profile
            async with self._get_db(profile_id).async_session_maker() as session:
                result = await session.execute(
                    select(GenerationJob).where(GenerationJob.id == job_id)
                )
                job = result.scalar_one_or_none()
                return job.to_dict() if job else None
        else:
            # Search all profile databases
            for pid, db in self._get_all_jobs_dbs():
                async with db.async_session_maker() as session:
                    result = await session.execute(
                        select(GenerationJob).where(GenerationJob.id == job_id)
                    )
                    job = result.scalar_one_or_none()
                    if job:
                        return job.to_dict()
            return None

    async def list_jobs(
        self,
        status: Optional[str] = None,
        generator_instance_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List generation jobs for the current profile, excluding completed jobs whose media was deleted.

        Returns job dicts with inline media data (file_hash, markers, generation_time) to avoid N+1 queries.
        """
        from sqlalchemy import or_, and_, func
        from sqlalchemy.orm import selectinload

        # Filter by current profile and use that profile's database
        profile_id = get_current_profile()

        async with self._get_db(profile_id).async_session_maker() as session:
            # Use outerjoin to check if referenced media still exists and isn't deleted
            # We want to exclude completed jobs where:
            # - result_media_id is set, but the media item is deleted (deleted_at is not null)
            # - result_media_id is set, but the media item no longer exists
            # Belt-and-suspenders: a 'completed' job with a NULL result_media_id is a
            # ghost (its result was permanently deleted under an older code path).
            # The scrub now deletes the row outright, but filter defensively in case
            # any other path nulls it.
            # Select both job and media to include media data in response
            query = (
                select(GenerationJob, MediaItem)
                .outerjoin(MediaItem, GenerationJob.result_media_id == MediaItem.id)
                .where(
                    or_(
                        # Include jobs without a result_media_id that aren't completed
                        # (queued / assigned / processing / failed legitimately have no result)
                        and_(
                            GenerationJob.result_media_id.is_(None),
                            GenerationJob.status != 'completed',
                        ),
                        # Include jobs where media exists (id is not null from the join) and is not deleted
                        and_(
                            MediaItem.id.isnot(None),
                            MediaItem.deleted_at.is_(None)
                        )
                    )
                )
                # Internal one-shot flow-as-tool jobs are stamped with _ephemeral_run_id in
                # their params; they must never appear in the user's generation history/queue.
                .where(
                    func.json_extract(GenerationJob.parameters, '$._ephemeral_run_id').is_(None)
                )
            )

            if status:
                query = query.where(GenerationJob.status == status)

            if generator_instance_id:
                query = query.where(GenerationJob.generator_instance_id == generator_instance_id)

            query = query.order_by(GenerationJob.created_at.desc())
            query = query.limit(limit).offset(offset)

            result = await session.execute(query)
            rows = result.all()

            # Collect media IDs that need marker loading
            media_ids = [media.id for job, media in rows if media is not None]

            # Batch load markers for all media items
            markers_by_media = {}
            if media_ids:
                from database import MediaMarker, Marker
                marker_query = (
                    select(MediaMarker, Marker)
                    .join(Marker, MediaMarker.marker_id == Marker.id)
                    .where(MediaMarker.media_id.in_(media_ids))
                    .where(MediaMarker.source != 'suppressed')
                )
                marker_result = await session.execute(marker_query)
                for media_marker, marker in marker_result.all():
                    if media_marker.media_id not in markers_by_media:
                        markers_by_media[media_marker.media_id] = []
                    markers_by_media[media_marker.media_id].append(marker.to_dict())

            # Build response with inline media data
            jobs_list = []
            for job, media in rows:
                job_dict = job.to_dict()

                # Add inline media data if media exists
                if media:
                    job_dict['result_file_hash'] = media.file_hash

                    # Extract generation_time from generation_metadata
                    if media.generation_metadata:
                        try:
                            gen_meta = json.loads(media.generation_metadata) if isinstance(media.generation_metadata, str) else media.generation_metadata
                            gen_time = gen_meta.get('generation_time') or (gen_meta.get('parameters') or {}).get('generation_time')
                            if gen_time:
                                job_dict['result_generation_time'] = gen_time
                        except (json.JSONDecodeError, TypeError):
                            pass

                    # Add markers
                    job_dict['result_markers'] = markers_by_media.get(media.id, [])

                jobs_list.append(job_dict)

            return jobs_list

    async def cancel_job(self, job_id: int) -> bool:
        """
        Cancel a job if it's still queued, assigned, or processing.

        If the job is currently processing, this will send an interrupt
        signal to the provider to stop the generation.

        Returns:
            True if cancelled, False if job not found or already completed
        """
        from providers import ProviderRegistry

        # Search all profile databases to find the job
        for profile_id, db in self._get_all_jobs_dbs():
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(GenerationJob).where(GenerationJob.id == job_id)
                )
                job = result.scalar_one_or_none()

                if not job:
                    continue  # Try next profile

                if job.status not in ['queued', 'assigned', 'processing']:
                    return False

                # Store info before updating job status
                backend_name = job.backend_name
                tool_id = job.tool_id
                was_processing = job.status == 'processing'

                # Mark as cancelled
                job.status = 'cancelled'
                job.error = 'Cancelled by user'
                job.completed_at = datetime.utcnow()
                await session.commit()

                # Track cancellation telemetry (durationMs = elapsed-at-cancel)
                try:
                    from telemetry import get_telemetry_client
                    from pipeline_telemetry import tool_job_props, emit_pipeline_settled
                    elapsed_ms = (
                        int((job.completed_at - job.created_at).total_seconds() * 1000)
                        if job.created_at else 0
                    )
                    get_telemetry_client().track("tool_cancelled", {
                        **tool_job_props(job),
                        "durationMs": max(0, elapsed_ms),
                    }, category="generation")
                    emit_pipeline_settled(job, "cancelled", completed_at=job.completed_at)
                except Exception:
                    log.debug("cancel telemetry failed", exc_info=True)

                # If job was processing, send cancel signal to the provider
                if was_processing and tool_id:
                    try:
                        # Extract provider_id from full tool_id (format: "provider_id:tool_slug")
                        provider_id = tool_id.split(':')[0] if ':' in tool_id else tool_id
                        registry = ProviderRegistry.get_instance()
                        provider = registry.get_provider(provider_id)
                        if provider and hasattr(provider, 'cancel_execution'):
                            request_id = f"job-{job_id}"
                            log.info("sending cancel to provider", provider_id=provider_id, request_id=request_id)
                            await provider.cancel_execution(request_id)
                    except Exception as e:
                        log.warning("failed to send cancel to provider", error=str(e))

                # Release backend capacity if job was assigned/processing
                if backend_name:
                    from backend_registry import get_backend_registry
                    backend_registry = get_backend_registry()
                    await backend_registry.release_job(backend_name, job_id)

                # Broadcast job cancelled event
                if self._websocket_manager:
                    with ProfileScope(profile_id):
                        await self._websocket_manager.broadcast('generation_job_cancelled', {
                            'job': job.to_dict(),
                            'generator_instance_id': job.generator_instance_id,
        
                        })

                # Refill forever-mode slots now that capacity was freed
                if backend_name:
                    await self._fill_available_slots(backend_name)

                return True

        return False  # Job not found in any profile

    async def delete_job(self, job_id: int) -> bool:
        """
        Hard delete a job from the database.
        Only allows deleting failed or cancelled jobs.

        Returns:
            True if deleted, False if job not found or not in deletable state
        """
        # Search all profile databases to find the job
        for profile_id, db in self._get_all_jobs_dbs():
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(GenerationJob).where(GenerationJob.id == job_id)
                )
                job = result.scalar_one_or_none()

                if not job:
                    continue  # Try next profile

                # Only allow deleting failed or cancelled jobs
                if job.status not in ['failed', 'cancelled']:
                    return False

                generator_instance_id = job.generator_instance_id
                await session.delete(job)
                await session.commit()

                # Broadcast job deleted event
                if self._websocket_manager:
                    with ProfileScope(profile_id):
                        await self._websocket_manager.broadcast('generation_job_deleted', {
                            'job_id': job_id,
                            'generator_instance_id': generator_instance_id,
        
                        })

                return True

        return False  # Job not found in any profile

    async def cleanup_stale_jobs(self):
        """Clean up jobs that were interrupted by server restart across all profile databases.

        Any job not in a terminal state (completed, failed, cancelled) is stale after a restart.
        Queued jobs are deleted (clients must re-register). All other non-terminal jobs are marked failed.
        """
        terminal_statuses = {'completed', 'failed', 'cancelled'}

        for profile_id, db in self._get_all_jobs_dbs():
            try:
                async with db.async_session_maker() as session:
                    # Find ALL non-terminal jobs - these are all stale after a restart
                    result = await session.execute(
                        select(GenerationJob).where(
                            GenerationJob.status.notin_(terminal_statuses)
                        )
                    )
                    stale_jobs = result.scalars().all()

                    if not stale_jobs:
                        continue

                    queued_count = 0
                    failed_count = 0
                    for job in stale_jobs:
                        if job.status == 'queued':
                            # Queued jobs are deleted since clients need to re-register
                            await session.delete(job)
                            queued_count += 1
                        else:
                            # All other non-terminal jobs are marked failed
                            job.status = 'failed'
                            job.error = 'Interrupted by server restart'
                            job.completed_at = datetime.utcnow()
                            failed_count += 1

                    if queued_count > 0:
                        log.info(f"Deleting {queued_count} queued job(s) from profile {profile_id}")
                    if failed_count > 0:
                        log.info(f"Marking {failed_count} interrupted job(s) as failed in profile {profile_id}")

                    await session.commit()
            except Exception:
                log.exception(f"Failed to cleanup stale jobs for profile {profile_id}")

    async def cleanup_disconnected_backend(self, backend_name: str) -> int:
        """Clean up all queue state when a backend disconnects.

        Resets pending work request counters and requeues active jobs.
        """
        # Clear global pending work requests for this backend
        old_pending = self._pending_work_requests.pop(backend_name, 0)
        if old_pending > 0:
            log.info(f"Cleared {old_pending} pending work requests for disconnected backend {backend_name}")

        # Clear per-client pending counts for clients on this backend
        if backend_name in self._forever_mode_clients:
            for client_id in self._forever_mode_clients[backend_name]:
                self._pending_work_requests_per_client.pop(client_id, None)

        # Requeue any active jobs
        return await self.requeue_jobs_for_backend(backend_name)

    async def requeue_jobs_for_backend(self, backend_name: str) -> int:
        """Requeue jobs that were processing on a backend that disconnected.

        Args:
            backend_name: The backend/provider that disconnected

        Returns:
            Number of jobs requeued
        """
        requeued_count = 0

        for profile_id, db in self._get_all_jobs_dbs():
            async with db.async_session_maker() as session:
                # Find processing/assigned jobs for this backend
                result = await session.execute(
                    select(GenerationJob).where(
                        GenerationJob.backend_name == backend_name,
                        GenerationJob.status.in_(['assigned', 'processing'])
                    )
                )
                jobs = result.scalars().all()

                if jobs:
                    log.info(
                        "requeuing jobs for disconnected backend",
                        backend=backend_name,
                        count=len(jobs),
                        profile=profile_id
                    )
                    for job in jobs:
                        job.status = 'queued'
                        # Keep backend_name so job gets picked up when backend reconnects
                        job.assigned_at = None
                        job.started_at = None
                        job.worker_id = None
                        requeued_count += 1

                        # Broadcast job requeued (use 'queued' event so frontend updates)
                        if self._websocket_manager:
                            with ProfileScope(profile_id):
                                await self._websocket_manager.broadcast('generation_job_queued', {
                                    'job': job.to_dict(),
                                    'generator_instance_id': job.generator_instance_id,
                
                                })

                    await session.commit()

        return requeued_count

    async def start_workers(self, num_workers: int = 2):
        """Start worker tasks to process the queue."""
        if self._workers_running:
            return

        self._workers_running = True

        for i in range(num_workers):
            task = asyncio.create_task(self._worker_loop(i))
            self._worker_tasks.append(task)

    async def stop_workers(self):
        """Stop all worker tasks."""
        self._workers_running = False

        for task in self._worker_tasks:
            task.cancel()

        # Wait for tasks with internal timeout to avoid blocking shutdown
        if self._worker_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._worker_tasks, return_exceptions=True),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                log.warning("worker tasks did not finish in time during shutdown")
        self._worker_tasks = []

        # Let in-flight post-processing tails finish so we don't drop the DB
        # record / metadata for a generation that already completed on the GPU.
        if self._finalize_tasks:
            try:
                await asyncio.wait_for(self._await_finalizers(), timeout=10.0)
            except asyncio.TimeoutError:
                log.warning("post-processing tails did not finish in time during shutdown")

    async def _worker_loop(self, worker_id: int):
        """Worker loop that requests jobs from scheduler and processes them.

        Polls all profile databases for jobs to ensure complete profile isolation.
        Uses round-robin across profiles for fairness.
        """
        worker_id_str = f"worker-{worker_id}"
        log.info(f"Generation worker {worker_id} started")

        # Get all available backends to round-robin across them
        from backend_registry import get_backend_registry
        backend_registry = get_backend_registry()

        # Track last profile index for round-robin fairness across profiles
        last_profile_idx = 0

        while self._workers_running:
            try:
                # Get list of all backends
                backends = await backend_registry.list_backends()
                backend_names = list(backends.keys())

                if not backend_names:
                    log.warning(f"Worker {worker_id}: No backends available")
                    await asyncio.sleep(5)
                    continue

                # Log backends periodically (every ~10 seconds = 10 iterations)
                if worker_id == 0 and hasattr(self, '_last_backend_log'):
                    import time
                    if time.time() - self._last_backend_log > 10:
                        log.debug(f"Worker polling backends: {backend_names}")
                        self._last_backend_log = time.time()
                elif worker_id == 0:
                    import time
                    log.info(f"Worker polling backends: {backend_names}")
                    self._last_backend_log = time.time()

                # Get all profile databases
                profiles_dbs = self._get_all_jobs_dbs()
                if not profiles_dbs:
                    await asyncio.sleep(5)
                    continue

                # Try each profile in round-robin order for fairness
                job_found = False
                for i in range(len(profiles_dbs)):
                    profile_idx = (last_profile_idx + i) % len(profiles_dbs)
                    profile_id, db = profiles_dbs[profile_idx]

                    # Try each backend for this profile
                    for backend_name in backend_names:
                        # Request next job from scheduler for this backend and profile
                        job = await self.scheduler.assign_next_job(backend_name, worker_id_str, profile_id=profile_id)

                        if job:
                            log.info(f"Worker {worker_id} processing job {job.id} (profile={profile_id}) on backend {backend_name}")
                            await self._process_job(job, profile_id=profile_id)
                            job_found = True
                            last_profile_idx = profile_idx + 1  # Start from next profile
                            break  # Process one job at a time

                    if job_found:
                        break

                if not job_found:
                    # Wait for a job submission event, or poll after 1s timeout
                    self._job_submitted_event.clear()
                    try:
                        await asyncio.wait_for(self._job_submitted_event.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Worker {worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(5)

        log.info(f"Generation worker {worker_id} stopped")

    async def _insert_generated_file(self, output_path: str, session: AsyncSession, chat_item_id: int = None, generation_metadata: str = None, ephemeral_run_id: str = None) -> MediaItem:
        """
        Insert a generated file directly into the database with metadata already computed.

        For generated files, we compute metadata inline to avoid the latency of:
        1. IPC signaling to the ingestion worker (up to 1s)
        2. Ingestion worker re-reading the file we just wrote
        3. Polling loop waiting for metadata_status='completed'

        Uses the provided session - caller is responsible for commit.

        If the file already exists in the database (race condition with ingestion worker),
        we update the existing record instead of failing.

        Args:
            output_path: Path to the generated file
            session: Database session to use (caller commits)
            chat_item_id: Optional chat item ID to link to
            generation_metadata: Optional JSON string with generation metadata (for videos which can't embed metadata)
        """
        import os
        from pathlib import Path
        from datetime import datetime

        file_path = Path(output_path)
        stat_info = os.stat(output_path)

        # Determine file format from extension
        file_format = file_path.suffix.lstrip('.').lower() or 'png'
        is_video = file_format in ('mp4', 'webm', 'mov', 'avi', 'mkv')
        is_audio = file_format in ('mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg')

        # Hashing, ffprobe subprocess calls, and PIL decoding are all blocking
        # I/O/CPU work - run off the event loop so a slow video (double ffprobe
        # + whole-file hash) can't stall every other in-flight request.
        computed = await asyncio.to_thread(
            _compute_generated_file_metadata, output_path, is_video, is_audio, generation_metadata
        )
        file_hash = computed['file_hash']
        width = computed['width']
        height = computed['height']
        has_alpha = computed['has_alpha']
        duration = computed['duration']
        audio_sample_rate = computed['audio_sample_rate']
        audio_channels = computed['audio_channels']
        audio_bit_depth = computed['audio_bit_depth']
        audio_bitrate = computed['audio_bitrate']
        audio_codec = computed['audio_codec']
        megapixels = computed['megapixels']
        generation_metadata = computed['generation_metadata']

        # Check if the file was already inserted by the ingestion worker (race condition)
        existing_result = await session.execute(
            select(MediaItem).where(MediaItem.file_path == output_path)
        )
        media_item = existing_result.scalar_one_or_none()

        if media_item:
            # File already exists - update it with our generation-specific data
            log.info(f"Media item for {output_path} already exists (id={media_item.id}), updating with generation metadata")
            media_item.file_hash = file_hash
            media_item.file_size = stat_info.st_size
            media_item.width = width
            media_item.height = height
            media_item.has_alpha = has_alpha
            media_item.megapixels = megapixels
            if duration is not None:
                media_item.duration = duration
            if is_audio:
                media_item.audio_sample_rate = audio_sample_rate
                media_item.audio_channels = audio_channels
                media_item.audio_bit_depth = audio_bit_depth
                media_item.audio_bitrate = audio_bitrate
                media_item.audio_codec = audio_codec
            media_item.metadata_status = 'completed'
            media_item.metadata_processed_at = datetime.utcnow()
            media_item.metadata_config_version = get_config_version_manager().get_version('metadata')
            if chat_item_id:
                media_item.chat_item_id = chat_item_id
            if generation_metadata:
                media_item.generation_metadata = generation_metadata
            if ephemeral_run_id:
                media_item.ephemeral_run_id = ephemeral_run_id
                media_item.is_hidden = True
                media_item.clip_status = 'skipped'
                media_item.vlm_caption_status = 'skipped'
                media_item.face_detection_status = 'skipped'
            # Flush to ensure changes are written
            await session.flush()
        else:
            # Create new media item with metadata already completed (no ingestion worker needed)
            media_item = MediaItem(
                file_path=output_path,
                file_hash=file_hash,
                file_size=stat_info.st_size,
                file_format=file_format,
                created_date=datetime.utcfromtimestamp(stat_info.st_ctime),
                modified_date=datetime.utcfromtimestamp(stat_info.st_mtime),
                indexed_date=datetime.utcnow(),
                metadata_status='completed',  # Already done - no ingestion worker needed
                metadata_processed_at=datetime.utcnow(),
                metadata_config_version=get_config_version_manager().get_version('metadata'),
                width=width,
                height=height,
                has_alpha=has_alpha,
                megapixels=megapixels,
                duration=duration,
                # Audio-specific metadata (null for non-audio) so generated audio
                # is a first-class media item like imported library audio.
                audio_sample_rate=audio_sample_rate,
                audio_channels=audio_channels,
                audio_bit_depth=audio_bit_depth,
                audio_bitrate=audio_bitrate,
                audio_codec=audio_codec,
                # Link to chat if generated via chat system
                chat_item_id=chat_item_id,
                # For videos, we pass the generation metadata directly since it can't be embedded
                generation_metadata=generation_metadata,
                # One-shot flow-as-tool: born ephemeral — hidden, un-ingested, hard-deleted at run end.
                ephemeral_run_id=ephemeral_run_id,
                is_hidden=True if ephemeral_run_id else None,
                clip_status='skipped' if ephemeral_run_id else 'pending',
                vlm_caption_status='skipped' if ephemeral_run_id else 'pending',
                face_detection_status='skipped' if ephemeral_run_id else 'pending',
            )

            session.add(media_item)
            # Flush to get the ID without committing - caller will commit
            await session.flush()
            log.info(f"Inserted generated media item {media_item.id} with metadata (no ingestion worker)")

        # Ephemeral media are never ingested or indexed — skip the worker signal entirely.
        if ephemeral_run_id:
            return media_item

        # Signal ingestion worker to process background tasks (CLIP, face detection, etc.)
        # This doesn't trigger a filesystem scan, just wakes the worker to process pending items
        # NOTE: Use a daemon thread instead of run_in_executor. The default executor blocks
        # on shutdown waiting for all threads, but multiprocessing.Event.set() can deadlock
        # if there are IPC issues. Daemon threads are killed on exit, avoiding the hang.
        try:
            from core.app import get_process_pending_event
            import threading
            process_pending_event = get_process_pending_event()
            if process_pending_event:
                def signal_ingestion():
                    try:
                        process_pending_event.set()
                    except Exception as e:
                        log.warning(f"Failed to signal ingestion worker: {e}")
                thread = threading.Thread(target=signal_ingestion, daemon=True)
                thread.start()
                # Don't wait for it - if it blocks, the daemon thread will be killed on exit
        except Exception as e:
            log.warning(f"Failed to signal ingestion worker: {e}")

        return media_item

    async def _find_chat_item_for_job(self, job_id: int, profile_id: str = None) -> Optional[int]:
        """Find the generation_grid chat item that contains this job ID.

        Args:
            job_id: The job ID to look for
            profile_id: Profile to search in (ChatItems are per-profile)
        """
        if profile_id is None:
            profile_id = get_current_profile()

        # ChatItems are stored in the profile's database
        async with self._get_db(profile_id).async_session_maker() as session:
            # Find all generation_grid items and check if they contain this job_id
            result = await session.execute(
                select(ChatItem).where(ChatItem.item_type == 'generation_grid')
            )
            grid_items = result.scalars().all()

            log.debug(f"Looking for job_id={job_id} in {len(grid_items)} generation_grid items (profile={profile_id})")

            for grid_item in grid_items:
                if grid_item.grid_layout:
                    try:
                        grid_data = json.loads(grid_item.grid_layout)
                        job_ids = grid_data.get('job_ids', [])
                        if job_id in job_ids:
                            log.debug(f"Found job_id={job_id} in grid_item.id={grid_item.id}")
                            return grid_item.id
                    except json.JSONDecodeError:
                        continue

            log.debug(f"job_id={job_id} not found in any generation_grid")
            return None

    async def _update_grid_with_media_id(self, job_id: int, media_id: int, profile_id: str = None):
        """Update the generation_grid chat item to include the media_id for a completed job.

        This allows the LLM to see the generated media IDs in subsequent conversation turns.
        """
        if profile_id is None:
            profile_id = get_current_profile()

        async with self._get_db(profile_id).async_session_maker() as session:
            # Find the generation_grid that contains this job_id
            result = await session.execute(
                select(ChatItem).where(ChatItem.item_type == 'generation_grid')
            )
            grid_items = result.scalars().all()

            for grid_item in grid_items:
                if grid_item.grid_layout:
                    try:
                        grid_data = json.loads(grid_item.grid_layout)
                        job_ids = grid_data.get('job_ids', [])
                        if job_id in job_ids:
                            # Found the grid - add media_id mapping
                            if 'media_ids' not in grid_data:
                                grid_data['media_ids'] = {}
                            grid_data['media_ids'][str(job_id)] = media_id

                            # Update the grid_layout
                            grid_item.grid_layout = json.dumps(grid_data)
                            await session.commit()

                            log.debug(f"Updated grid_item.id={grid_item.id} with job_id={job_id} -> media_id={media_id}")

                            # Broadcast update so frontend can refresh if needed
                            if self._websocket_manager:
                                await self._websocket_manager.broadcast("chat_item_updated", {
                                    "chat_id": grid_item.chat_id,
                                    "item": grid_item.to_dict()
                                })
                            return
                    except json.JSONDecodeError:
                        continue

            log.debug(f"Could not find generation_grid for job_id={job_id} to update with media_id={media_id}")

    async def _handle_batch_job_completion(
        self,
        job: GenerationJob,
        media_item: "MediaItem",
        profile_id: str
    ):
        """Handle completion of a job that is part of a batch.

        - If first job in batch: create output set with this result
        - If subsequent job: append to existing output set
        - If all jobs complete: broadcast batch_completed event
        """
        from structured_media import create_batch_output_set, append_to_set

        batch_id = job.batch_id
        if not batch_id:
            return

        log.info(f"Handling batch job completion: job_id={job.id}, batch_id={batch_id}")

        async with self._get_db(profile_id).async_session_maker() as jobs_session:
            # Find all jobs in this batch
            result = await jobs_session.execute(
                select(GenerationJob).where(GenerationJob.batch_id == batch_id)
            )
            batch_jobs = list(result.scalars().all())

            # Find the first job (has batch_total)
            first_job = next((j for j in batch_jobs if j.batch_total is not None), None)
            if not first_job:
                log.error(f"Batch {batch_id}: Could not find first job with batch_total")
                return

            batch_total = first_job.batch_total
            output_set_id = first_job.batch_output_set_id

            # Count completed and failed jobs
            completed_count = sum(1 for j in batch_jobs if j.status == 'completed')
            failed_count = sum(1 for j in batch_jobs if j.status == 'failed')

            # Get batch metadata from first job's input data
            tool_id = first_job.tool_id or first_job.model_name
            try:
                params = json.loads(first_job.parameters)
                output_title = params.get('_batch_output_title')
                input_set_ids = params.get('_batch_input_set_ids')
                presentation_only = bool(params.get('_batch_presentation_only'))
            except (json.JSONDecodeError, TypeError):
                output_title = None
                input_set_ids = None
                presentation_only = False

            # Presentation-only (media-batch) grouping: the individual generated
            # assets stay in the library and grouping is a ToolView affordance.
            # Skip output-set creation / supersede entirely; only broadcast
            # grouped progress so the queue rail can show one batch card.
            if presentation_only:
                if self._websocket_manager:
                    await self._websocket_manager.broadcast('batch_job_completed', {
                        'batch_id': batch_id,
                        'job_id': job.id,
                        'result_media_id': media_item.id,
                        'output_set_id': None,
                        'completed': completed_count,
                        'failed': failed_count,
                        'total': batch_total,
                    })
                if completed_count + failed_count >= batch_total:
                    if failed_count == 0:
                        batch_status = 'completed'
                    elif completed_count == 0:
                        batch_status = 'failed'
                    else:
                        batch_status = 'partial'
                    log.info(
                        f"Media-batch {batch_id}: all jobs done "
                        f"(completed={completed_count}, failed={failed_count}, total={batch_total})"
                    )
                    if self._websocket_manager:
                        await self._websocket_manager.broadcast('batch_completed', {
                            'batch_id': batch_id,
                            'output_set_id': None,
                            'completed': completed_count,
                            'failed': failed_count,
                            'total': batch_total,
                            'status': batch_status,
                        })
                return

            async with self._get_db(profile_id).async_session_maker() as media_session:
                if output_set_id is None:
                    # First completed job - create the output set
                    log.info(f"Batch {batch_id}: Creating output set with first result (media_id={media_item.id})")

                    output_set = await create_batch_output_set(
                        session=media_session,
                        folder_path=job.folder_path,
                        batch_id=batch_id,
                        first_item_path=media_item.file_path,
                        title=output_title,
                    )
                    output_set_id = output_set.id

                    # Associate output set with project if job is project-scoped
                    if job.project_id:
                        from project_service import attach_media_to_project
                        await attach_media_to_project(media_session, job.project_id, output_set_id)
                        log.info(f"Batch {batch_id}: Attached output set {output_set_id} to project {job.project_id}")

                    # Store output_set_id on all batch jobs for reliability
                    await jobs_session.execute(
                        update(GenerationJob)
                        .where(GenerationJob.batch_id == batch_id)
                        .values(batch_output_set_id=output_set_id)
                    )
                    await jobs_session.commit()

                    log.info(f"Batch {batch_id}: Output set created with id={output_set_id}")

                    from telemetry import get_telemetry_client
                    get_telemetry_client().track("set_created", {
                        "count": batch_total or 1,
                        "actor": "system",
                    }, category="library")
                else:
                    # Subsequent job - append to existing set
                    log.info(f"Batch {batch_id}: Appending result to output set (set_id={output_set_id}, media_id={media_item.id})")

                    await append_to_set(
                        session=media_session,
                        set_media_id=output_set_id,
                        new_item_path=media_item.file_path,
                    )

                # Mark the result item as superseded by the output set (hides it from library)
                await media_session.execute(
                    update(MediaItem)
                    .where(MediaItem.id == media_item.id)
                    .values(superseded_by=output_set_id, is_hidden=None)
                )
                await media_session.commit()
                log.debug(f"Batch {batch_id}: Marked media {media_item.id} as superseded by set {output_set_id}")

            # Broadcast batch progress
            if self._websocket_manager:
                await self._websocket_manager.broadcast('batch_job_completed', {
                    'batch_id': batch_id,
                    'job_id': job.id,
                    'result_media_id': media_item.id,
                    'output_set_id': output_set_id,
                    'completed': completed_count,
                    'failed': failed_count,
                    'total': batch_total,
                })

            # Check if batch is complete
            if completed_count + failed_count >= batch_total:
                log.info(f"Batch {batch_id}: All jobs complete. completed={completed_count}, failed={failed_count}, total={batch_total}")

                # Determine batch status
                if failed_count == 0:
                    batch_status = 'completed'
                elif completed_count == 0:
                    batch_status = 'failed'
                else:
                    batch_status = 'partial'

                # Reorder set items to match original input order
                if output_set_id and completed_count > 1:
                    try:
                        from structured_media import reorder_set_items

                        # Collect completed jobs with their batch indices and result paths
                        job_order_info = []
                        for bj in batch_jobs:
                            if bj.status == 'completed' and bj.result_media_id:
                                try:
                                    bj_params = json.loads(bj.parameters)
                                    batch_index = bj_params.get('_batch_index')
                                    if batch_index is not None:
                                        job_order_info.append((batch_index, bj.result_media_id))
                                except (json.JSONDecodeError, TypeError):
                                    pass

                        if job_order_info:
                            # Sort by batch index
                            job_order_info.sort(key=lambda x: x[0])
                            result_media_ids = [info[1] for info in job_order_info]

                            # Get file paths for result media items
                            async with self._get_db(profile_id).async_session_maker() as reorder_session:
                                result = await reorder_session.execute(
                                    select(MediaItem).where(MediaItem.id.in_(result_media_ids))
                                )
                                media_items_map = {m.id: m.file_path for m in result.scalars().all()}

                                # Build ordered paths list
                                ordered_paths = [media_items_map[mid] for mid in result_media_ids if mid in media_items_map]

                                if ordered_paths:
                                    await reorder_set_items(
                                        session=reorder_session,
                                        set_media_id=output_set_id,
                                        ordered_paths=ordered_paths,
                                    )
                                    log.info(f"Batch {batch_id}: Reordered output set to match input order")
                    except Exception as e:
                        log.error(f"Batch {batch_id}: Failed to reorder output set: {e}", exc_info=True)

                if output_set_id and completed_count:
                    await self._finalize_batch_container_asset(
                        profile_id=profile_id,
                        batch_id=batch_id,
                        output_set_id=output_set_id,
                        batch_jobs=batch_jobs,
                    )

                # Smart title is now generated upfront at job submission time
                # (see routes/generation.py submit_batch_jobs)

                if self._websocket_manager:
                    await self._websocket_manager.broadcast('batch_completed', {
                        'batch_id': batch_id,
                        'output_set_id': output_set_id,
                        'completed': completed_count,
                        'failed': failed_count,
                        'total': batch_total,
                        'status': batch_status,
                    })

    async def _finalize_batch_container_asset(
        self,
        *,
        profile_id: str,
        batch_id: str,
        output_set_id: int,
        batch_jobs: list[GenerationJob],
    ) -> int:
        """Commit the completed compatibility set as one normalized Asset."""
        ordered: list[tuple[int, int]] = []
        for job in batch_jobs:
            if job.status != 'completed' or not job.result_media_id:
                continue
            try:
                params = json.loads(job.parameters or '{}')
            except (json.JSONDecodeError, TypeError):
                params = {}
            ordered.append((params.get('_batch_index', job.id), job.result_media_id))
        ordered.sort(key=lambda pair: pair[0])
        member_ids = [media_id for _, media_id in ordered]

        async with self._get_db(profile_id).async_session_maker() as session:
            from asset_association_service import mirror_media_associations_to_asset
            from container_service import create_container_asset_from_media
            from database import MediaOwner

            container_media = await session.get(MediaItem, output_set_id)
            if container_media is None or container_media.deleted_at is not None:
                raise RuntimeError(f"Batch {batch_id} output container is unavailable")
            asset = await create_container_asset_from_media(
                session,
                media_id=output_set_id,
                container_type='set',
                members=[{'embedded_media_id': media_id} for media_id in member_ids],
                origin_type='generation_batch',
                origin_id=batch_id,
                idempotency_key=f'generation-batch:{batch_id}:container',
            )
            await mirror_media_associations_to_asset(
                session, media_id=output_set_id, asset_id=asset.id
            )

            # ContainerRevision ownership is now authoritative. The provisional
            # batch root can be released without an ownerless gap.
            owners = list(
                await session.scalars(
                    select(MediaOwner).where(
                        MediaOwner.root_kind == 'batch',
                        MediaOwner.root_id == batch_id,
                        MediaOwner.deleted_at.is_(None),
                    )
                )
            )
            released_at = datetime.utcnow()
            for owner in owners:
                owner.deleted_at = released_at
            await session.execute(
                update(GenerationJob)
                .where(GenerationJob.batch_id == batch_id)
                .values(result_asset_id=asset.id)
            )
            await session.commit()
            return asset.id

    async def _wait_for_metadata(self, media_id: int, profile_id: str = None, timeout: int = 30):
        """Wait for metadata processing to complete for a media item."""
        if profile_id is None:
            profile_id = get_current_profile()

        start_time = datetime.utcnow()

        while True:
            async with self._get_db(profile_id).async_session_maker() as session:
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id == media_id)
                )
                media_item = result.scalar_one_or_none()

                if not media_item:
                    raise Exception(f"Media item {media_id} not found")

                if media_item.metadata_status == 'completed' and media_item.file_hash:
                    # Success - metadata is ready
                    return

                if media_item.metadata_status == 'failed':
                    raise Exception(f"Metadata processing failed for media item {media_id}")

                # Check timeout
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > timeout:
                    raise Exception(f"Timeout waiting for metadata processing (media_id={media_id})")

                # Wait a bit before checking again
                await asyncio.sleep(0.5)

    async def _process_job(self, job: GenerationJob, profile_id: str):
        """
        Process a generation job via the provider system.

        All jobs are routed through providers (JsonRpcProvider for external tools,
        LightweightProvider for in-process tools, etc.).
        """
        from providers import ProviderRegistry, ExecutionResult

        set_current_profile(profile_id)

        try:
            # Update status to processing
            async with self._get_db(profile_id).async_session_maker() as session:
                await session.execute(
                    update(GenerationJob)
                    .where(GenerationJob.id == job.id)
                    .values(status='processing', started_at=datetime.utcnow())
                )
                await session.commit()

            job_dict = await self.get_job(job.id, profile_id=profile_id)

            if self._websocket_manager:
                await self._websocket_manager.broadcast('generation_job_started', {
                    'job': job_dict,
                    'generator_instance_id': job.generator_instance_id,

                })

            # Parse parameters — a single flat dict holding everything
            params = json.loads(job.parameters)
            task_type = getattr(job, 'task_type', 'text-to-image') or 'text-to-image'

            # Resolve lineage data from the flat params dict
            import time as _time
            _pre_gen_start = _time.time()
            lineage_data = await self._resolve_lineage(params, task_type, profile_id)
            log.debug(f"Job {job.id}: TIMING - _resolve_lineage: {(_time.time() - _pre_gen_start)*1000:.0f}ms")

            # Generate output filename
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            if task_type in ["image-to-video", "text-to-video", "video-to-video", "upscale-video", "video-stitch", "video-extend"]:
                file_extension = ".mp4"
            elif task_type in ("text-to-audio", "text-to-music", "text-to-speech"):
                file_extension = ".flac"
            else:
                file_extension = ".png"
            filename = f"gen_{timestamp}_{job.id}{file_extension}"
            output_path = os.path.join(job.folder_path, filename)
            os.makedirs(job.folder_path, exist_ok=True)

            # =====================================================================
            # PROVIDER-BASED EXECUTION
            # =====================================================================
            # Route to provider based on tool_id or fall back to legacy path

            full_tool_id = job.tool_id
            registry = ProviderRegistry.get_instance()

            # Find provider and tool
            provider = None
            tool_id_in_provider = None

            if full_tool_id:
                # Provider disconnect/unregister can mutate registry._providers while
                # a job is being processed; iterate a snapshot to avoid runtime errors.
                provider_items = list(registry._providers.items())
                for pid, p in provider_items:
                    if full_tool_id.startswith(f"{pid}:"):
                        tool_id_in_provider = full_tool_id[len(pid) + 1:]
                        tool = await p.get_tool(tool_id_in_provider)
                        if tool:
                            provider = p
                            break

            if not provider:
                # Legacy fallback: construct tool_id from backend_name/model_name/task_type
                # This handles jobs submitted before the provider refactor
                backend_name = job.backend_name or job.generator_name
                provider_id = f"builtin:{backend_name.lower()}"
                provider = registry._providers.get(provider_id)

                if provider:
                    # Build tool_id: task_type:model_slug
                    model_slug = job.model_name.lower().replace(" ", "-").replace("_", "-")
                    tool_id_in_provider = f"{task_type}:{model_slug}"
                    tool = await provider.get_tool(tool_id_in_provider)
                    if not tool:
                        raise ValueError(f"Tool not found: {tool_id_in_provider} in {provider_id}")
                else:
                    raise ValueError(f"Provider not found for backend: {backend_name}")

            # Build the single parameters dict sent to the provider from the
            # stored flat job params. Filter out Stimma-internal parameters that
            # should never be sent to providers.
            internal_params = {'supersede_source', 'inspired_by_media_id'}
            exec_params = {k: v for k, v in params.items() if k not in internal_params}

            # Add tool_id for metadata embedding
            if job.tool_id:
                exec_params['tool_id'] = job.tool_id

            # Resolve any media IDs to file paths
            # This is needed for external providers that receive media IDs from agent plans
            async with self._get_db(profile_id).async_session_maker() as resolve_session:
                exec_params = await self._resolve_media_ids_in_params(resolve_session, exec_params)

            # Built-in filters are media-agnostic: a filter applied to a video
            # must emit a video, not a .png. The output extension is normally
            # keyed off task_type, but "filter" is shared by image and video —
            # so re-derive it here from the now-resolved input path.
            if task_type == 'filter':
                from utils.query_builder import VIDEO_FORMATS
                first_input = (exec_params.get('input_images') or [None])[0]
                if isinstance(first_input, str) and Path(first_input).suffix.lstrip('.').lower() in VIDEO_FORMATS:
                    output_path = os.path.join(job.folder_path, f"gen_{timestamp}_{job.id}.mp4")

            # Execute via provider
            # Note: JSON-RPC providers don't accept output_path - they return output_data instead
            log.info(f"Job {job.id}: Executing via provider {provider.provider_id}, tool {tool_id_in_provider}")
            exec_result = None

            # Check if provider accepts output_path (builtin) or returns output_data (external/jsonrpc)
            is_builtin = provider.provider_type == "builtin"

            # Use job ID as request_id for cancellation support
            request_id = f"job-{job.id}"

            if is_builtin:
                # Builtin providers write directly to output_path
                async for progress_or_result in provider.execute(
                    tool_id=tool_id_in_provider,
                    parameters=exec_params,
                    output_path=output_path,
                    request_id=request_id,
                ):
                    if isinstance(progress_or_result, ExecutionResult):
                        exec_result = progress_or_result
            else:
                # External providers (JSON-RPC, etc.) return output_data, we write to output_path
                async for progress_or_result in provider.execute(
                    tool_id=tool_id_in_provider,
                    parameters=exec_params,
                    request_id=request_id,
                ):
                    if isinstance(progress_or_result, ExecutionResult):
                        exec_result = progress_or_result
                # TODO: Could broadcast progress updates here

            if not exec_result:
                raise ValueError("Provider did not return a result")

            if not exec_result.success:
                raise ValueError(exec_result.error or "Execution failed")

            # Check if job was cancelled during execution
            async with self._get_db(profile_id).async_session_maker() as session:
                result = await session.execute(
                    select(GenerationJob.status).where(GenerationJob.id == job.id)
                )
                current_status = result.scalar_one_or_none()
                if current_status == 'cancelled':
                    log.info(f"Job {job.id}: Discarding result - job was cancelled during execution")
                    # Clean up output file if it was written (builtin providers write directly)
                    if os.path.exists(output_path):
                        try:
                            os.remove(output_path)
                            log.debug(f"Job {job.id}: Removed cancelled job output file")
                        except Exception as e:
                            log.warning(f"Job {job.id}: Failed to remove output file: {e}")
                    return  # Don't import or process results

            # Handle output - JSON-RPC providers return output_data, others write to output_path
            actual_output_path = output_path
            if exec_result.output_data:
                # Write the downloaded asset data to the output path
                with open(output_path, "wb") as f:
                    f.write(exec_result.output_data)
                log.info(f"Job {job.id}: Wrote {len(exec_result.output_data)} bytes to {output_path}")
            elif exec_result.metadata.get("output_path"):
                actual_output_path = exec_result.metadata.get("output_path")

            # A successful execution with no output file cannot be finalized —
            # post-processing would fail on ingest with a bare ENOENT. This is
            # the shape of a metadata-only tool (e.g. detect-objects) routed
            # through the queue; those run in-process via the agent instead.
            if not os.path.exists(actual_output_path):
                raise ValueError(
                    f"Tool produced no media output (expected {os.path.basename(actual_output_path)}). "
                    "Metadata-only tools cannot run through the generation queue."
                )

            # Legacy compatibility: create a result-like object for post-processing
            class ResultCompat:
                pass
            result = ResultCompat()
            result.generation_time = exec_result.generation_time
            result.actual_seed = exec_result.actual_seed
            result.output_path = actual_output_path
            if hasattr(exec_result, 'workflow'):
                result.comfy_workflow = exec_result.workflow

            # GPU compute is done and the output is written. Stamp completion time
            # HERE (at GPU-done) rather than at the end of post-processing, so the
            # job's completed_at / computeMs reflect pure compute, not the detached
            # post-processing tail that overlaps the next generation.
            completed_at = datetime.utcnow()

            # Detach post-processing (DB writes, metadata embed, broadcasts) so the
            # GPU never idles through it. Spawn FIRST so the job is counted as
            # "finalizing" (GPU-free) before we ask for more work, otherwise the
            # per-client capacity check would still see it as a running job and
            # refuse to dispatch the next one.
            self._spawn_finalize(job, profile_id, result, output_path, params,
                                 task_type, lineage_data, exec_result, provider,
                                 completed_at)

            # Free the backend slot and ask forever-mode clients for the next job
            # NOW so the next generation starts immediately.
            if job.backend_name:
                await self.scheduler.on_job_completed(job.id, job.backend_name)
                await self._fill_available_slots(job.backend_name)
            return

        except Exception as e:
            error_msg = str(e)

            # Check if this is a provider disconnection error - requeue instead of fail
            is_disconnect_error = "not connected" in error_msg.lower() or "disconnected" in error_msg.lower()

            if is_disconnect_error:
                # Requeue the job so it resumes when provider reconnects
                log.warning(f"Job {job.id} interrupted by provider disconnect, requeuing")
                async with self._get_db(profile_id).async_session_maker() as session:
                    await session.execute(
                        update(GenerationJob)
                        .where(GenerationJob.id == job.id)
                        .values(
                            status='queued',
                            assigned_at=None,
                            started_at=None,
                            worker_id=None
                        )
                    )
                    await session.commit()

                # Broadcast requeue event
                job_dict = await self.get_job(job.id, profile_id=profile_id)
                if self._websocket_manager:
                    await self._websocket_manager.broadcast('generation_job_queued', {
                        'job': job_dict,
                        'generator_instance_id': job.generator_instance_id,
    
                    })

                # Notify scheduler that job slot is free
                if job.backend_name:
                    await self.scheduler.on_job_completed(job.id, job.backend_name)
            else:
                # Check if job was already cancelled (race condition with cancel_job)
                async with self._get_db(profile_id).async_session_maker() as session:
                    result = await session.execute(
                        select(GenerationJob.status).where(GenerationJob.id == job.id)
                    )
                    current_status = result.scalar_one_or_none()

                if current_status == 'cancelled':
                    # Job was cancelled - don't treat as failure, just clean up
                    log.info(f"Job {job.id} was cancelled, skipping failure handling")
                    if job.backend_name:
                        await self.scheduler.on_job_completed(job.id, job.backend_name)
                        await self._fill_available_slots(job.backend_name)
                else:
                    # Mark job as failed (in the job's profile database)
                    log.exception(
                        "generation job failed",
                        job_id=job.id,
                        backend_name=job.backend_name,
                        generator_instance_id=job.generator_instance_id,
                        error=error_msg,
                    )

                    async with self._get_db(profile_id).async_session_maker() as session:
                        await session.execute(
                            update(GenerationJob)
                            .where(GenerationJob.id == job.id)
                            .values(
                                status='failed',
                                completed_at=datetime.utcnow(),
                                error=error_msg
                            )
                        )
                        await session.commit()

                    # Broadcast job failed event (with generator_instance_id for targeted delivery)
                    job_dict = await self.get_job(job.id, profile_id=profile_id)
                    if self._websocket_manager:
                        await self._websocket_manager.broadcast('generation_job_failed', {
                            'job': job_dict,
                            'generator_instance_id': job.generator_instance_id,
        
                        })

                    # Track failure telemetry: categorical errorType + errorHash
                    # only — the raw error text never egresses.
                    from telemetry import get_telemetry_client
                    from telemetry_props import classify_tool_error, error_hash
                    from pipeline_telemetry import tool_job_props, emit_pipeline_settled
                    get_telemetry_client().track("tool_failed", {
                        **tool_job_props(job),
                        "errorType": classify_tool_error(error_msg),
                        "errorHash": error_hash(error_msg),
                    }, category="generation")
                    emit_pipeline_settled(
                        job, "failed",
                        completed_at=datetime.utcnow(),
                        error_message=error_msg,
                    )

                    # Notify scheduler that job is complete (even if failed)
                    if job.backend_name:
                        await self.scheduler.on_job_completed(job.id, job.backend_name)
                        # Request more work from forever mode clients if capacity available
                        await self._fill_available_slots(job.backend_name)

        finally:
            # Clear thread profile context
            set_thread_profile(None)

    def _spawn_finalize(self, job, profile_id, result, output_path, params,
                        task_type, lineage_data, exec_result, provider, completed_at):
        """Run a finished job's post-processing without blocking the worker.

        The GPU slot is freed before this is called, so the worker is free to
        pick up the next job. We keep a reference to the task so it isn't
        garbage-collected before it finishes. ``completed_at`` is the GPU-done
        timestamp, passed in so completion time isn't inflated by this tail.
        """
        gid = job.generator_instance_id
        if gid:
            self._finalizing_per_client[gid] = self._finalizing_per_client.get(gid, 0) + 1

        task = asyncio.create_task(
            self._finalize_job_safe(
                job, profile_id, result, output_path, params,
                task_type, lineage_data, exec_result, provider, completed_at
            )
        )
        self._finalize_tasks.add(task)

        def _on_finalize_done(t, gid=gid):
            self._finalize_tasks.discard(t)
            if gid and self._finalizing_per_client.get(gid):
                self._finalizing_per_client[gid] -= 1
                if self._finalizing_per_client[gid] <= 0:
                    self._finalizing_per_client.pop(gid, None)

        task.add_done_callback(_on_finalize_done)

    async def _await_finalizers(self):
        """Await all in-flight detached post-processing tails.

        Used by tests (to keep job processing deterministic) and shutdown (to
        avoid dropping post-processing for a just-finished generation).
        """
        while self._finalize_tasks:
            await asyncio.gather(*list(self._finalize_tasks), return_exceptions=True)

    async def _finalize_job_safe(self, job, profile_id, result, output_path, params,
                                 task_type, lineage_data, exec_result, provider, completed_at):
        """Error-isolating wrapper for the detached post-processing tail.

        Post-processing runs after the GPU slot is freed, so a failure here must
        NOT requeue the job (the generation already succeeded). We just mark the
        job failed and notify clients.
        """
        set_current_profile(profile_id)
        try:
            await self._finalize_job(
                job, profile_id, result, output_path, params,
                task_type, lineage_data, exec_result, provider, completed_at
            )
        except Exception as e:
            log.exception("post-processing failed", job_id=job.id, error=str(e))
            try:
                async with self._get_db(profile_id).async_session_maker() as session:
                    await session.execute(
                        update(GenerationJob)
                        .where(GenerationJob.id == job.id)
                        .values(
                            status='failed',
                            completed_at=completed_at,
                            error=f"post-processing failed: {e}",
                        )
                    )
                    await session.commit()
                if self._websocket_manager:
                    job_dict = await self.get_job(job.id, profile_id=profile_id)
                    await self._websocket_manager.broadcast('generation_job_failed', {
                        'job': job_dict,
                        'generator_instance_id': job.generator_instance_id,
                    })
            except Exception:
                log.exception("failed to mark job failed after post-proc error", job_id=job.id)
        finally:
            set_thread_profile(None)

    async def _finalize_job(self, job, profile_id, result, output_path, params,
                            task_type, lineage_data, exec_result, provider, completed_at):
        """Post-processing tail for a completed generation: persist the media
        item, record lineage, embed metadata, mark the job complete, and notify
        clients. Detached from the worker so the GPU is not idle during it.

        ``completed_at`` is stamped at GPU-done by the caller, so the recorded
        completion time and computeMs telemetry exclude this tail's duration.
        """
        # =====================================================================
        # POST-PROCESSING
        # =====================================================================

        # Look up chat_item_id by finding the generation_grid that contains this job
        # This will be None for non-chat generation, which is fine
        import time as _time
        _post_gen_start = _time.time()
        # Jobs with tool_id are from standalone tool pages, not chat - skip the lookup
        if job.tool_id:
            chat_item_id = None
        else:
            try:
                chat_item_id = await self._find_chat_item_for_job(job.id, profile_id=profile_id)
            except Exception as e:
                log.warning(f"Job {job.id}: Error looking up chat_item_id: {e}")
                chat_item_id = None
        log.debug(f"Job {job.id}: TIMING - _find_chat_item_for_job: {(_time.time() - _post_gen_start)*1000:.0f}ms")

        # Build generation_metadata through the ONE canonical builder
        # (generation_metadata.build_generation_metadata) so every task type —
        # image, video, upscale, stitch, extend, and anything added later — stores
        # the identical shape. No per-task branches: parameters is just the raw
        # job params minus internal keys, plus the resolved seed and wall time.
        # See generation_metadata.py for why this is centralized.
        original_params = dict(params)

        inspired_by = None
        _inspired_by_id = params.get('inspired_by_media_id')
        if _inspired_by_id:
            try:
                inspired_by = {"media_id": int(_inspired_by_id)}
            except (TypeError, ValueError):
                inspired_by = None

        generation_metadata_json = json.dumps(build_generation_metadata(
            task_type=task_type,
            tool_id=job.tool_id,
            generator=job.backend_name or job.generator_name,
            model=job.model_name,
            prompt=original_params.get('prompt', ''),
            negative_prompt=original_params.get('negative_prompt', ''),
            parameters=build_parameters(
                original_params,
                seed=resolve_recorded_seed(
                    original_params.get('seed'),
                    getattr(result, 'actual_seed', None),
                ),
                generation_time=getattr(result, 'generation_time', None),
            ),
            prompt_metadata=original_params.get('prompt_metadata'),
            source_inputs=lineage_data.get('source_inputs', []),
            lineage_trace=lineage_data.get('lineage_trace', []),
            inspired_by=inspired_by,
        ))
        log.debug(f"Job {job.id}: Built generation_metadata for {provider.provider_id}")

        # One-shot flow-as-tool: this generation's media is ephemeral — keep it out of
        # lineage / markers / project / websocket; it is hard-deleted when the run ends.
        ephemeral_run_id = params.get('_ephemeral_run_id')

        # ALL post-generation database operations in ONE session to avoid lock contention
        # This is critical for SQLite - multiple sessions competing for write locks cause deadlocks
        _t0 = _time.time()
        async with self._get_db(profile_id).async_session_maker() as session:
            # Insert file directly into the profile's database
            media_item = await self._insert_generated_file(
                output_path,
                session=session,
                chat_item_id=chat_item_id,
                generation_metadata=generation_metadata_json,
                ephemeral_run_id=ephemeral_run_id
            )
            log.debug(f"Job {job.id}: TIMING - _insert_generated_file: {(_time.time() - _t0)*1000:.0f}ms")
            log.debug(f"Job {job.id}: Inserted media item {media_item.id} directly (chat_item_id={chat_item_id}, profile_id={profile_id})")

            if not ephemeral_run_id and media_item.file_format not in {
                'stimmaset.json', 'stimmagrid.json', 'stimmalayout'
            }:
                from storage_service import stage_managed_media
                await stage_managed_media(
                    session,
                    media=media_item,
                    profile_id=profile_id,
                    remove_source=True,
                )

            # Record lineage relationships to media_lineage table
            _t1 = _time.time()
            if not ephemeral_run_id:
                await self._record_lineage(media_item.id, lineage_data.get('source_inputs', []), task_type, session)
            log.debug(f"Job {job.id}: TIMING - _record_lineage: {(_time.time() - _t1)*1000:.0f}ms")

            # Record inspiration lineage if inspired_by_media_id is present
            # This adds an additional row (not replacing derived lineage) to track inspiration source
            inspired_by_media_id = params.get('inspired_by_media_id')
            if inspired_by_media_id and not ephemeral_run_id:
                session.add(MediaLineage(
                    media_id=media_item.id,
                    source_media_id=int(inspired_by_media_id),
                    source_order=99,  # High order to not conflict with derived lineage entries
                    task_type=task_type,
                    relationship_type='inspired',
                ))
                log.info(f"Job {job.id}: Recorded inspiration lineage from media {inspired_by_media_id}")

            # Propagate tool lineage (denormalized tool chain for filtering)
            _t1 = _time.time()
            source_ids = [s.get('media_id') for s in lineage_data.get('source_inputs', []) if s.get('media_id')]
            if not ephemeral_run_id:
                await propagate_tool_lineage(session, media_item.id, source_ids, job.tool_id)
            log.debug(f"Job {job.id}: TIMING - propagate_tool_lineage: {(_time.time() - _t1)*1000:.0f}ms")

            # NOTE: generation_metadata is now built in full (lineage + tool_id +
            # generator/model) via build_generation_metadata BEFORE insertion for
            # every task type, so the old image-only post-insertion overlay that
            # re-stamped lineage here has been removed — it was redundant and was
            # itself a source of image/video drift.

            # Calculate auto_delete_at if duration is set. completed_at was stamped
            # at GPU-done by the caller (not here) so it excludes this tail.
            _t1 = _time.time()
            auto_delete_at = None
            log.debug(f"Job {job.id}: auto_delete_duration = {repr(job.auto_delete_duration)}, media_item.id = {media_item.id}")
            if job.auto_delete_duration:
                duration = parse_duration(job.auto_delete_duration)
                log.debug(f"Job {job.id}: parsed duration = {repr(duration)}")
                if duration:
                    auto_delete_at = completed_at + duration
                    log.debug(f"Job {job.id}: Setting auto_delete_at = {auto_delete_at.isoformat()} (completed_at={completed_at.isoformat()}, duration={job.auto_delete_duration})")
                    # Update media item directly (it's in this session)
                    media_item.auto_delete_at = auto_delete_at
            else:
                log.debug(f"Job {job.id}: NO auto_delete_duration set, skipping auto_delete_at")
            log.debug(f"Job {job.id}: TIMING - auto_delete handling: {(_time.time() - _t1)*1000:.0f}ms")

            # Set tool_id and preset_id for provenance tracking
            if job.tool_id:
                media_item.tool_id = job.tool_id
            if job.preset_id:
                media_item.preset_id = job.preset_id

            # Associate generated media with project if job is project-scoped
            if job.project_id and not ephemeral_run_id:
                from project_service import attach_media_to_project
                await attach_media_to_project(session, job.project_id, media_item.id)
                log.info(f"Job {job.id}: Attached media {media_item.id} to project {job.project_id}")

            # The invocation, not the tool, decides whether this output is a
            # durable Asset or provisional/context/container-owned Media.
            persistent_job = await session.get(GenerationJob, job.id)
            if persistent_job is None:
                raise RuntimeError(f"Generation job {job.id} disappeared before finalization")
            from result_disposition_service import finalize_generation_output
            await finalize_generation_output(
                session, job=persistent_job, media=media_item
            )

            # ONE commit for all database operations
            await session.commit()
            log.info(f"Job {job.id}: Committed all post-generation DB operations for media {media_item.id}")

        if not ephemeral_run_id and media_item.storage_object_id is not None:
            try:
                from storage_service import cleanup_staged_source
                async with self._get_db(profile_id).async_session_maker() as cleanup_session:
                    await cleanup_staged_source(cleanup_session, media_id=media_item.id)
            except Exception as exc:
                # The indexed ManagedArtifact is intentionally retained for
                # startup reconciliation; the committed object is authoritative.
                log.warning(
                    f"Job {job.id}: deferred managed ingest-source cleanup: {type(exc).__name__}"
                )

        log.debug(f"Job {job.id}: TIMING - total post-gen DB ops: {(_time.time() - _t0)*1000:.0f}ms")

        # Clear auto-delete flags on source media (separate, non-critical operation)
        await self._clear_auto_delete_for_sources(lineage_data.get('source_inputs', []), profile_id)

        # Update the generation_grid chat item with the media_id
        _t0 = _time.time()
        # This allows the LLM to see generated media IDs in future conversation turns
        await self._update_grid_with_media_id(job.id, media_item.id, profile_id=profile_id)
        log.debug(f"Job {job.id}: TIMING - _update_grid_with_media_id: {(_time.time() - _t0)*1000:.0f}ms")

        # Update job as completed (in the job's profile database)
        _t0 = _time.time()
        async with self._get_db(profile_id).async_session_maker() as session:
            await session.execute(
                update(GenerationJob)
                .where(GenerationJob.id == job.id)
                .values(
                    status='completed',
                    completed_at=completed_at,
                    auto_delete_at=auto_delete_at,  # Keep for legacy tracking
                    result_media_id=media_item.id if media_item else None
                )
            )
            await session.commit()
        log.debug(f"Job {job.id}: TIMING - update job completed: {(_time.time() - _t0)*1000:.0f}ms")

        if not media_item:
            log.error(f"Job {job.id}: No media item created")
            return

        # Verify media item has file_hash before broadcasting (use profile's database)
        _t0 = _time.time()
        media_ready = False
        async with self._get_db(profile_id).async_session_maker() as session:
            result = await session.execute(
                select(MediaItem).where(MediaItem.id == media_item.id)
            )
            verified_media = result.scalar_one_or_none()
            if verified_media and verified_media.file_hash:
                media_ready = True
                log.debug(f"Job {job.id}: Verified media item {media_item.id} has file_hash: {verified_media.file_hash}")
            else:
                log.error(f"Job {job.id}: Media item {media_item.id} has no file_hash after metadata wait!")
        log.debug(f"Job {job.id}: TIMING - verify file_hash: {(_time.time() - _t0)*1000:.0f}ms")

        # Apply auto-markers if specified
        auto_marker_ids = params.get('auto_marker_ids')
        if media_ready and auto_marker_ids and not ephemeral_run_id:
            await self._apply_auto_markers(media_item.id, auto_marker_ids, profile_id)

        # Only broadcast if media is fully ready with hash
        _t0 = _time.time()
        if media_ready and not ephemeral_run_id:
            job_dict = await self.get_job(job.id, profile_id=profile_id)
            if self._websocket_manager:
                await self._websocket_manager.broadcast('generation_job_completed', {
                    'job': job_dict,
                    'generator_instance_id': job.generator_instance_id,
    
                })

                # Also broadcast media_added event so browse view refreshes
                await self._websocket_manager.broadcast('media_added', {
                    'media_id': media_item.id,
                    'file_path': verified_media.file_path
                })

            log.info(f"Job {job.id} completed successfully and broadcast to clients")

            # Track completion telemetry. durationMs = submit->result
            # (includes queue wait), queueMs = queued-before-execution,
            # computeMs = pure provider compute.
            duration_ms = int((completed_at - job.created_at).total_seconds() * 1000) if job.created_at else 0
            queue_ms = (
                int((job.started_at - job.created_at).total_seconds() * 1000)
                if job.created_at and job.started_at else 0
            )
            compute_ms = (
                int((completed_at - job.started_at).total_seconds() * 1000)
                if job.started_at else duration_ms
            )
            from telemetry import get_telemetry_client
            from pipeline_telemetry import tool_job_props
            get_telemetry_client().track("tool_completed", {
                **tool_job_props(job),
                "durationMs": duration_ms,
                "queueMs": max(0, queue_ms),
                "computeMs": max(0, compute_ms),
            }, category="generation")

            # Handle batch processing if this job is part of a batch
            if job.batch_id and media_item:
                await self._handle_batch_job_completion(
                    job=job,
                    media_item=media_item,
                    profile_id=profile_id
                )

            # Kick off the post-processing chain when the job carries one.
            # Chain-step jobs run under CHAIN_INSTANCE_ID so a chain never
            # re-triggers itself.
            chain_started = False
            post_chain = params.get('post_processing_chain')
            if post_chain:
                from postprocessing.executor import CHAIN_INSTANCE_ID, start_chain_for_job
                if job.generator_instance_id != CHAIN_INSTANCE_ID:
                    try:
                        chain_run_id = await start_chain_for_job(
                            job=job,
                            base_media_id=media_item.id,
                            chain_steps=post_chain,
                            profile_id=profile_id,
                            websocket_manager=self._websocket_manager,
                        )
                        chain_started = chain_run_id is not None
                    except Exception as e:
                        log.error(f"Job {job.id}: Failed to start post-processing chain: {e}", exc_info=True)

            # Chainless pipelines settle at job completion; chained ones
            # settle when the chain run finishes (postprocessing.executor).
            if not chain_started:
                from pipeline_telemetry import emit_pipeline_settled
                emit_pipeline_settled(job, "completed", completed_at=completed_at)

        else:
            log.error(f"Job {job.id}: Media not ready, did not broadcast to clients")
        log.debug(f"Job {job.id}: TIMING - broadcast: {(_time.time() - _t0)*1000:.0f}ms")
        log.debug(f"Job {job.id}: TIMING - TOTAL post-generation: {(_time.time() - _post_gen_start)*1000:.0f}ms")


# Global queue instance
_generation_queue: Optional[GenerationQueue] = None


def get_generation_queue() -> GenerationQueue:
    """Get or create the global generation queue instance."""
    global _generation_queue
    if _generation_queue is None:
        _generation_queue = GenerationQueue()
    return _generation_queue
