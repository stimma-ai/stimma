"""Sandboxed Python runtime and injected Stimma SDK for agent v2."""

from __future__ import annotations

import asyncio
import base64
import builtins as py_builtins
import hashlib
import io
import json
import math
import os
import random
import re
import traceback
import base64 as _base64_mod
import collections
import colorsys
import copy
import csv
import dataclasses as _dataclasses_mod
import datetime
import functools
import io as _io_mod
import itertools
import pathlib
import statistics
import string
import struct
import textwrap
import urllib
import urllib.parse
import urllib.request

import aiohttp
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from itertools import chain, combinations, count, cycle, islice, permutations, product
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Sequence

from llm import llm_completion
import numpy
import PIL
import PIL.Image
import PIL.ImageDraw
import PIL.ImageEnhance
import PIL.ImageFilter
import PIL.ImageFont
import PIL.ImageOps
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core.profile_context import get_current_profile
from database import MediaItem
from llm_resolver import get_effective_llm_config, get_chat_llm_config

from core.logging import get_logger

from project_service import infer_project_id_from_workspace_path
from .code_lint import lint_code, format_lint_errors
from .tools.call_tool import execute_call_tool
from .tools.delegate import _run_delegate_loop
from .tools.library import get_media_for_workspace, save_workspace_file
from .tools.show import show as show_tool

log = get_logger(__name__)

ALLOWED_MODULES: dict[str, Any] = {
    "asyncio": asyncio,
    "base64": _base64_mod,
    "collections": collections,
    "colorsys": colorsys,
    "copy": copy,
    "csv": csv,
    "dataclasses": _dataclasses_mod,
    "datetime": datetime,
    "functools": functools,
    "io": _io_mod,
    "itertools": itertools,
    "json": json,
    "math": math,
    "numpy": numpy,
    "os.path": os.path,
    "pathlib": pathlib,
    "PIL": PIL,
    "random": random,
    "re": re,
    "statistics": statistics,
    "string": string,
    "struct": struct,
    "textwrap": textwrap,
    "urllib": urllib,
    "urllib.parse": urllib.parse,
    "urllib.request": urllib.request,
    "aiohttp": aiohttp,
}


# Human-readable list of the sandbox's allow-list, for embedding in agent
# prompts. Keep in sync with ``ALLOWED_MODULES`` above — both the main
# agent's ``run_code`` description and the recipe agent's ``code()`` /
# ``create_image()`` docs reference this so the model has a single source
# of truth for what it can import in sandboxed Python.
ALLOWED_MODULES_PROMPT_DESCRIPTION = (
    "Allowed imports: asyncio, base64, collections, colorsys, copy, csv, "
    "dataclasses, datetime, functools, io, itertools, json, math, numpy, "
    "os.path, pathlib, PIL (all submodules: Image, ImageDraw, ImageFilter, "
    "ImageFont, ImageOps, ImageEnhance), random, re, statistics, string, "
    "struct, textwrap, urllib / urllib.parse / urllib.request, aiohttp. "
    "tqdm is also importable (sandbox-patched for progress display)."
)


def _make_safe_import(
    skill_modules: dict[str, Path] | None = None,
    extra_modules: dict[str, Any] | None = None,
):
    """Build a safe __import__ that allows whitelisted modules + skill lib modules.

    ``extra_modules`` is a per-invocation override for callers that need to
    expose a module the global allow-list doesn't cover — e.g. the recipe
    builder needs ``stimma.recipe`` visible so ``from stimma.recipe import …``
    resolves inside the sandbox.
    """
    _skill_module_cache: dict[str, Any] = {}

    def _load_skill_module(name: str) -> Any:
        """Load a skill module by temporarily inserting its lib dir into sys.path."""
        if name in _skill_module_cache:
            return _skill_module_cache[name]
        import importlib
        import sys as _sys
        top_level = name.split(".")[0]
        lib_dir = skill_modules.get(top_level) if skill_modules else None
        if lib_dir is None:
            raise ImportError(f"Import '{name}' is not allowed in run_code")
        lib_dir_str = str(lib_dir)
        # Clear stale sys.modules entries for this skill module tree
        stale_keys = [k for k in _sys.modules if k == top_level or k.startswith(top_level + ".")]
        for k in stale_keys:
            del _sys.modules[k]
        # Temporarily insert lib dir into sys.path
        _sys.path.insert(0, lib_dir_str)
        try:
            mod = importlib.import_module(name)
        finally:
            if lib_dir_str in _sys.path:
                _sys.path.remove(lib_dir_str)
        _skill_module_cache[name] = mod
        return mod

    def _safe_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        if level != 0:
            raise ImportError("Relative imports are not allowed in run_code")
        if extra_modules and name in extra_modules:
            return extra_modules[name]
        if name in ALLOWED_MODULES:
            return ALLOWED_MODULES[name]
        if name == "os":
            return SimpleNamespace(path=os.path)
        # Check skill modules
        if skill_modules:
            top_level = name.split(".")[0]
            if top_level in skill_modules:
                return _load_skill_module(name)
        raise ImportError(f"Import '{name}' is not allowed in run_code")

    return _safe_import


def _make_safe_open(workspace_dir: Path, project_workspace_dir: Path | None = None):
    workspace_root = workspace_dir.resolve()
    project_workspace_root = project_workspace_dir.resolve() if project_workspace_dir else None

    def _safe_open(file: str | os.PathLike[str], mode: str = "r", *args, **kwargs):
        candidate = Path(file)
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        resolved = candidate.resolve()
        allowed_roots = [workspace_root]
        if project_workspace_root is not None:
            allowed_roots.append(project_workspace_root)
        if not any(root == resolved or root in resolved.parents for root in allowed_roots):
            raise PermissionError(
                "run_code open() is restricted to the chat workspace and shared project workspace"
            )
        return py_builtins.open(resolved, mode, *args, **kwargs)

    return _safe_open


def build_safe_builtins(
    workspace_dir: Path,
    printer,
    skill_modules: dict[str, Path] | None = None,
    project_workspace_dir: Path | None = None,
    extra_modules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "__import__": _make_safe_import(skill_modules, extra_modules),
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "Exception": Exception,
        "filter": filter,
        "float": float,
        "getattr": getattr,
        "hasattr": hasattr,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "open": _make_safe_open(workspace_dir, project_workspace_dir),
        "print": printer,
        "range": range,
        "reversed": reversed,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }


@dataclass
class ControlNetInput:
    """Result of controlnet preprocessing, passable as an input_images item."""
    preprocessed_path: str
    original_media_id: int
    preprocessor: str
    preprocessor_params: dict[str, Any] | None
    width: int
    height: int


@dataclass
class ToolResult:
    path: Path
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    tool_name: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    media_id: int | None = None
    task_type: str | None = None
    input_media_ids: list[int] = field(default_factory=list)
    prompt: str | None = None

    def open(self) -> Image.Image:
        return Image.open(self.path)

    def __getitem__(self, key: str) -> Any:
        """Allow dict-style access (result['media_id']) alongside dot notation."""
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)


class ProgressTracker:
    """tqdm-compatible progress tracker that streams to the frontend.

    Supports both tqdm patterns:
      for item in tqdm(items, desc="Working"):     # wrap iterable
      pbar = tqdm(total=10, desc="Working")        # manual update

    Extended with preview= kwarg on update() for thumbnail previews.
    DB/WS creation is deferred to the first _flush_progress() call.
    """

    def __init__(
        self,
        iterable=None,
        desc: str | None = None,
        total: int | None = None,
        *,
        # Internal — set by SDK, not by user code
        _chat_id: int | None = None,
        _sdk: "StimmaSDK | None" = None,
        # Accept any other tqdm kwargs silently
        **kwargs,
    ):
        self._iterable = iterable
        self._title = desc
        if total is not None:
            self._total = total
        elif iterable is not None:
            try:
                self._total = len(iterable)
            except (TypeError, AttributeError):
                self._total = 0
        else:
            self._total = 0
        self._chat_id = _chat_id
        self._item_id: int | None = None  # set on first flush
        self._current = 0
        self._previews: list[int] = []
        self._pending_update: dict | None = None
        self._completed = False

        # Auto-register with SDK
        if _sdk is not None:
            _sdk._progress_trackers.append(self)

    def __iter__(self):
        if self._iterable is None:
            return
        for item in self._iterable:
            yield item
            self.update(1)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __len__(self):
        return self._total

    def update(self, n: int = 1, *, preview: "ToolResult | int | None" = None):
        """Increment counter. Extended with preview= for thumbnail previews."""
        self._current = min(self._current + n, self._total)
        if preview is not None:
            media_id = preview.media_id if isinstance(preview, ToolResult) else preview
            if media_id is not None:
                self._previews.append(media_id)
        self._pending_update = self._build_state()

    def set_description(self, desc: str | None = None, refresh: bool = True):
        """tqdm-compatible description setter."""
        self._title = desc
        self._pending_update = self._build_state()

    def set_postfix(self, **kwargs):
        """Accept tqdm set_postfix calls silently."""
        pass

    def close(self):
        """Accept tqdm close() calls silently."""
        pass

    def _build_state(self) -> dict:
        status = "completed" if self._completed else "in_progress"
        return {
            "item_id": self._item_id,
            "display_data": {
                "title": self._title,
                "status": status,
                "current": self._current,
                "total": self._total,
                "previews": list(self._previews),
            },
        }

    def _take_pending(self) -> dict | None:
        pending = self._pending_update
        self._pending_update = None
        return pending

    def _mark_completed(self, status: str = "completed"):
        if status == "completed":
            self._current = self._total
        self._completed = True
        self._pending_update = self._build_state()
        # Override status for cancelled/timed_out
        if status != "completed":
            self._pending_update["display_data"]["status"] = status


class StimmaLibraryAPI:
    def __init__(self, sdk: "StimmaSDK"):
        self._sdk = sdk

    async def search(
        self,
        query: str,
        limit: int = 20,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        from .tools.library import _search

        raw = await _search(
            self._sdk.session, query=query, search_fields=None, limit=limit,
            project_id=self._sdk.project_id,
        )
        return [] if raw == "No results found." else json.loads(raw)

    async def browse(
        self,
        limit: int = 20,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        from .tools.library import _browse

        raw = await _browse(
            self._sdk.session, query=None, tags=tags, filters=None,
            sort_by=None, random_seed=None, limit=limit, offset=0,
            project_id=self._sdk.project_id,
        )
        parsed = json.loads(raw)
        return parsed.get("items", []) if isinstance(parsed, dict) else parsed

    async def get(self, media_id: int) -> dict[str, Any]:
        raw = await get_media_for_workspace(
            session=self._sdk.session,
            media_id=media_id,
            workspace_dir=self._sdk.workspace_dir,
        )
        return json.loads(raw)

    async def lineage(self, media_id: int) -> dict[str, Any]:
        from .tools.library import _lineage

        raw = await _lineage(self._sdk.session, media_id)
        return json.loads(raw)

    async def generation_params(self, media_id: int) -> dict[str, Any]:
        """Return a call_tool-ready recipe that reproduces an existing image.

        The result is a flat dict you can spread straight into call_tool:
        tool_id, prompt, seed (top level), loras as [{path, weight}], width,
        height, and input_images for image-to-image sources. To remix, fetch
        it, change one field, and resubmit:

            p = await stimma.library.generation_params(123)
            p["loras"] = [{"path": "new_style"}]
            result = await stimma.call_tool(**p)
        """
        from .tools.library import fetch_generation_params

        return await fetch_generation_params(self._sdk.session, media_id)

    async def regenerate(self, media_id: int, **overrides: Any) -> "ToolResult":
        """Reproduce an existing image, overriding any params you pass.

        Convenience over generation_params + call_tool. Pass overrides as flat
        kwargs (loras=..., prompt=..., seed=...). Pass seed=None for a fresh
        random seed:

            result = await stimma.library.regenerate(123, loras=[{"path": "new_style"}])
        """
        from .tools.library import fetch_generation_params

        params = await fetch_generation_params(self._sdk.session, media_id)
        params.update(overrides)
        if not params.get("tool_id"):
            raise RuntimeError(
                f"Media {media_id} has no recorded generating tool (imported/external image) — "
                "pass tool_id= to regenerate it."
            )
        return await self._sdk.call_tool(**params)

    async def save(
        self,
        item: ToolResult | str | Path,
        tags: list[str] | None = None,
        inspired_by: int | Sequence[int] | None = None,
    ) -> dict[str, Any]:
        provenance = None
        if isinstance(item, ToolResult):
            provenance = {
                "task_type": item.task_type or "code",
                "tool_id": item.tool_name,
                "parameters": item.parameters,
                "seed": item.seed,
                "source_media_ids": item.input_media_ids,
            }
            # Build lineage_trace and structured source_inputs from input sources
            if item.input_media_ids:
                base = await self._sdk._build_edit_provenance(item.input_media_ids)
                provenance["lineage_trace"] = base.get("lineage_trace", [])
                provenance["source_inputs"] = base.get("source_inputs", [])
            path = item.path
        else:
            path = Path(item)

        raw = await save_workspace_file(
            session=self._sdk.session,
            path=str(path),
            workspace_dir=self._sdk.workspace_dir,
            save_tags=tags,
            provenance=provenance,
            inspired_by=inspired_by,
            project_id=self._sdk.project_id,
        )
        if isinstance(raw, str) and raw.startswith("Error:"):
            raise RuntimeError(raw[6:].strip())
        return json.loads(raw)


class StimmaSDK:
    def __init__(
        self,
        *,
        session: AsyncSession,
        chat_id: int,
        workspace_dir: Path,
        project_workspace_dir: Path | None,
        interrupt_checker,
        session_media_ids: list[int] | None = None,
        project_id: int | None = None,
        effective_model_slug: str | None = None,
    ):
        self.session = session
        self.chat_id = chat_id
        self.workspace_dir = Path(workspace_dir)
        self.project_workspace_dir = Path(project_workspace_dir) if project_workspace_dir else None
        self.interrupt_checker = interrupt_checker
        self.project_id = project_id if project_id is not None else infer_project_id_from_workspace_path(project_workspace_dir)
        self._effective_model_slug = effective_model_slug
        self.library = StimmaLibraryAPI(self)
        self._pending_display_calls: list[dict[str, Any]] = []
        self._tool_results: list[ToolResult] = []
        self._tool_failures: list[dict[str, Any]] = []
        self._session_media_ids: list[int] = session_media_ids if session_media_ids is not None else []
        self._shown_media_ids: list[int] = []
        self._progress_trackers: list[ProgressTracker] = []
        # Accumulated LLM token usage from ctx.llm() and ctx.delegate() calls
        self._llm_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0, "calls": 0, "elapsed_seconds": 0.0}

    @property
    def has_project_workspace(self) -> bool:
        return self.project_workspace_dir is not None

    def project_path(self, *parts: str) -> Path:
        """Resolve a path inside the shared project workspace."""
        if self.project_workspace_dir is None:
            raise RuntimeError("No shared project workspace is available for this chat")
        return self.project_workspace_dir.joinpath(*parts)

    def get_llm_usage(self) -> dict:
        """Return accumulated LLM usage from this SDK session."""
        return dict(self._llm_usage)

    def adjust(self, image, **kwargs) -> Image.Image:
        """Apply image adjustments, filters, and effects. Sync — no await needed."""
        if isinstance(image, (str, Path)):
            image = Image.open(self._resolve_path(image))
        elif not isinstance(image, Image.Image):
            raise TypeError(f"Expected PIL Image or path, got {type(image).__name__}")
        from .image_adjust import adjust as _adjust
        return _adjust(image, **kwargs)

    @property
    def filters(self) -> list[str]:
        """List of available filter preset names."""
        from .image_adjust import FILTER_NAMES
        return list(FILTER_NAMES)

    async def detect_faces(self, media_id: int) -> list[dict[str, Any]]:
        """Get detected faces for a media item, including bounding boxes and embeddings."""
        from database import Face, MediaItem

        result = await self.session.execute(
            select(MediaItem).where(MediaItem.id == media_id)
        )
        media = result.scalar_one_or_none()
        if not media:
            raise ValueError(f"Media item {media_id} not found")

        if media.face_detection_status == "pending":
            raise RuntimeError(
                f"Face detection is still pending for media {media_id}. "
                "Try again shortly — faces are detected automatically after ingestion."
            )
        if media.face_detection_status == "failed":
            raise RuntimeError(f"Face detection failed for media {media_id}.")

        result = await self.session.execute(
            select(Face)
            .where(Face.media_id == media_id)
            .order_by(Face.confidence.desc())
        )
        faces = result.scalars().all()

        out = []
        for face in faces:
            entry: dict[str, Any] = {
                "id": face.id,
                "bbox": {
                    "x": face.bbox_x,
                    "y": face.bbox_y,
                    "width": face.bbox_width,
                    "height": face.bbox_height,
                },
                "confidence": face.confidence,
                "embedding": face.get_embedding().tolist() if face.get_embedding() is not None else None,
            }
            out.append(entry)
        return out

    async def preprocess_controlnet(
        self,
        media_id: int,
        preprocessor: str,
        params: dict[str, Any] | None = None,
    ) -> ControlNetInput:
        """Preprocess an image for controlnet workflows (edge detection, depth, pose, etc.)."""
        from .tools.preprocess_controlnet import execute_preprocess_controlnet

        result = await execute_preprocess_controlnet(
            media_id=media_id,
            preprocessor=preprocessor,
            params=params,
            session=self.session,
            workspace_dir=self.workspace_dir,
        )
        return ControlNetInput(
            preprocessed_path=result["preprocessed_path"],
            original_media_id=result["original_media_id"],
            preprocessor=result["preprocessor"],
            preprocessor_params=result["preprocessor_params"],
            width=result["width"],
            height=result["height"],
        )

    async def call_tool(self, tool_id: str, _params_dict: dict | None = None, **kwargs) -> ToolResult:
        # Accept positional dict as convenience fallback — models often write
        # stimma.call_tool("tool", {"prompt": "..."}) instead of flat kwargs.
        if _params_dict is not None:
            if not isinstance(_params_dict, dict):
                raise TypeError(
                    f"stimma.call_tool() second argument must be a dict, got {type(_params_dict).__name__}. "
                    'Use flat keyword args: await stimma.call_tool("tool_id", prompt="...", width=1024)'
                )
            for k, v in _params_dict.items():
                kwargs.setdefault(k, v)

        # Accept tool-call style nested dicts as a convenience fallback
        if "inputs" in kwargs and isinstance(kwargs["inputs"], dict):
            nested_inputs = kwargs.pop("inputs")
            for k, v in nested_inputs.items():
                kwargs.setdefault(k, v)
        if "parameters" in kwargs and isinstance(kwargs["parameters"], dict):
            nested_params = kwargs.pop("parameters")
            for k, v in nested_params.items():
                kwargs.setdefault(k, v)

        # Unwrap ControlNetInput objects in input_images
        raw_images = kwargs.get("input_images", [])
        if isinstance(raw_images, list):
            resolved_images = []
            original_paths = []
            preprocessors = []
            preprocessor_params = []
            has_controlnet = False
            for img in raw_images:
                if isinstance(img, ControlNetInput):
                    has_controlnet = True
                    resolved_images.append(img.preprocessed_path)
                    original_paths.append(img.original_media_id)
                    preprocessors.append(img.preprocessor)
                    preprocessor_params.append(img.preprocessor_params)
                else:
                    resolved_images.append(img)
                    original_paths.append(None)
                    preprocessors.append(None)
                    preprocessor_params.append(None)
            if has_controlnet:
                kwargs["input_images"] = resolved_images
                kwargs["_original_input_paths"] = original_paths
                kwargs["_input_preprocessors"] = preprocessors
                kwargs["_input_preprocessor_params"] = preprocessor_params

        input_keys = {
            "prompt", "input_images", "width", "height", "seed", "input_media_ids",
            "controlnet", "controlnet_params",
            "_original_input_paths", "_input_preprocessors",
            "_input_preprocessor_params", "_original_input_hashes",
        }
        inputs = {k: v for k, v in kwargs.items() if k in input_keys}
        parameters = {k: v for k, v in kwargs.items() if k not in input_keys}
        prompt_for_record = inputs.get("prompt") if isinstance(inputs.get("prompt"), str) else None
        try:
            result = await execute_call_tool(
                tool_id=tool_id,
                inputs=inputs,
                parameters=parameters or None,
                session=self.session,
                chat_id=self.chat_id,
                workspace_dir=self.workspace_dir,
                interrupt_checker=self.interrupt_checker,
                project_id=self.project_id,
            )
        except Exception as e:
            self._tool_failures.append({
                "tool_id": tool_id,
                "prompt": prompt_for_record,
                "error": f"{type(e).__name__}: {e}",
            })
            raise
        tool_result = ToolResult(
            path=Path(result["path"]),
            width=result.get("width"),
            height=result.get("height"),
            seed=result.get("seed"),
            tool_name=result.get("tool_id"),
            parameters=result.get("parameters") or {},
            duration_ms=result.get("duration_ms") or 0,
            media_id=result.get("media_id"),
            task_type=result.get("task_type"),
            input_media_ids=list(result.get("input_media_ids") or []),
            prompt=prompt_for_record,
        )
        self._tool_results.append(tool_result)
        # Also propagate to session-level tracking so subsequent tool calls see it
        if tool_result.media_id is not None:
            self._session_media_ids.append(tool_result.media_id)
            # Auto-add preview to any active progress tracker
            for tracker in self._progress_trackers:
                if not tracker._completed:
                    tracker._previews.append(tool_result.media_id)
                    tracker._pending_update = tracker._build_state()
        return tool_result

    async def _gather(
        self,
        *coros,
        max_concurrent: int = 10,
        desc: str | None = None,
        return_exceptions: bool = False,
    ) -> list:
        """Internal: run coroutines with concurrency limit and progress.

        Called by the patched asyncio.gather in the sandbox.
        """
        if not coros:
            return []

        # Auto-create progress tracker for batches so the user always sees progress
        tracker = None
        effective_desc = desc if desc is not None else (f"Generating ({len(coros)})" if len(coros) > 1 else None)
        if effective_desc is not None:
            tracker = self.progress(len(coros), desc=effective_desc)

        sem = asyncio.Semaphore(max_concurrent)

        async def _limited(idx, coro):
            async with sem:
                result = await coro
                if tracker is not None:
                    tracker.update(1)
                return (idx, result)

        tasks = [_limited(i, c) for i, c in enumerate(coros)]

        raw = await asyncio.gather(*tasks, return_exceptions=return_exceptions)

        # Mark tracker as completed so subsequent call_tool results
        # don't bleed previews into this (now-finished) gather's display
        if tracker is not None:
            tracker._mark_completed("completed")
            # Queue a final flush so the UI updates immediately
            tracker._pending_update = tracker._build_state()

        # Restore input ordering
        results = [None] * len(coros)
        for item in raw:
            if return_exceptions and isinstance(item, BaseException):
                # Can't recover ordering for exceptions from gather, append at end
                for i in range(len(results)):
                    if results[i] is None:
                        results[i] = item
                        break
            else:
                idx, val = item
                results[idx] = val
        return results

    async def delegate(
        self,
        task: str,
        context: str | None = None,
        specialist: str | None = None,
        max_turns: int = 20,
    ) -> str:
        """Spawn a headless subagent that can use tools and LLM reasoning.

        Args:
            task: Instruction for the subagent — what it should accomplish.
            context: Extra context appended to the subagent's system prompt.
            specialist: Name of a specialist profile (e.g. 'layout-design').
            max_turns: Maximum LLM turns (default 20, max 30).

        Returns:
            The subagent's final text response.
        """
        effective_max_turns = min(max_turns, 30)

        # Each subagent gets its own DB session so gather() can run many concurrently
        from database_registry import get_database_registry
        db = get_database_registry().get_database(get_current_profile())
        async with db.async_session_maker() as delegate_session:
            try:
                result, delegate_usage = await _run_delegate_loop(
                    task=task,
                    context=context,
                    specialist=specialist,
                    max_turns=effective_max_turns,
                    session=delegate_session,
                    chat_id=self.chat_id,
                    workspace_dir=str(self.workspace_dir),
                    project_workspace_dir=str(self.project_workspace_dir) if self.project_workspace_dir else None,
                    interrupt_checker=self.interrupt_checker,
                    session_media_ids=list(self._session_media_ids),
                    parent_item_id=None,
                    ws_manager=None,
                )
                # Accumulate delegate usage into SDK totals
                self._llm_usage["prompt_tokens"] += delegate_usage.get("prompt_tokens", 0)
                self._llm_usage["completion_tokens"] += delegate_usage.get("completion_tokens", 0)
                self._llm_usage["total_tokens"] += delegate_usage.get("total_tokens", 0)
                self._llm_usage["reasoning_tokens"] += delegate_usage.get("reasoning_tokens", 0)
                self._llm_usage["elapsed_seconds"] += delegate_usage.get("elapsed_seconds", 0.0)
                self._llm_usage["calls"] += 1
                return result
            except asyncio.CancelledError:
                return "Subagent was interrupted."
            except Exception as e:
                log.error(f"SDK delegate error: {type(e).__name__}: {e}")
                return f"Subagent error: {type(e).__name__}: {e}"

    async def llm(self, prompt: str, images: Sequence[str | Path] | None = None) -> str:
        llm_config = await get_chat_llm_config(self._effective_model_slug, role="agent")
        text_part: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images or []:
            image_path = self._resolve_path(image)
            with Image.open(image_path) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=90)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            text_part.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        messages = [{"role": "user", "content": text_part if len(text_part) > 1 else prompt}]
        resp = await llm_completion(llm_config, messages)
        # Accumulate usage
        self._llm_usage["prompt_tokens"] += resp.usage.prompt_tokens
        self._llm_usage["completion_tokens"] += resp.usage.completion_tokens
        self._llm_usage["total_tokens"] += resp.usage.total_tokens
        self._llm_usage["reasoning_tokens"] += resp.usage.reasoning_tokens
        self._llm_usage["elapsed_seconds"] += resp.elapsed_seconds
        self._llm_usage["calls"] += 1
        return resp.content

    def show(self, item: ToolResult | str | Path | int | Iterable[ToolResult | str | Path | int] | None = None, *, title: str | None = None, media_id: int | None = None, media_ids: list[int] | None = None, path: str | None = None, paths: list[str] | None = None):
        # Accept keyword-arg style (from tool-call API confusion)
        if item is None:
            items: list[ToolResult | str | Path | int] = []
            if media_id is not None:
                items.append(media_id)
            if media_ids:
                items.extend(media_ids)
            if path:
                items.append(path)
            if paths:
                items.extend(paths)
            if not items:
                return
            item = items if len(items) > 1 else items[0]
        norm_paths, norm_media_ids = self._normalize_show_inputs(item)
        self._pending_display_calls.append({
            "media_ids": norm_media_ids or None,
            "paths": norm_paths or None,
            "title": title,
        })

    def show_grid(
        self,
        items: Iterable[ToolResult | str | Path | int],
        cols: int = 3,
        title: str | None = None,
    ):
        display_title = title or f"Grid ({cols} cols)"
        self.show(list(items), title=display_title)

    def progress(self, iterable_or_total=None, *, total=None, desc=None, title=None, message=None, **kwargs) -> ProgressTracker:
        """Create a progress tracker (tqdm-compatible, sync).

        Flexible first arg: int for total, or iterable to wrap.
          stimma.progress(10, title="Generating")       # manual mode
          stimma.progress(prompts, desc="Generating")    # iterable mode
        """
        iterable = None
        if isinstance(iterable_or_total, int):
            total = iterable_or_total
        elif iterable_or_total is not None:
            iterable = iterable_or_total
        return ProgressTracker(
            iterable=iterable,
            desc=title or desc or message,
            total=total,
            _chat_id=self.chat_id,
            _sdk=self,
            **kwargs,
        )

    async def _ensure_tracker_created(self, tracker: ProgressTracker) -> None:
        """Lazily create the DB record and broadcast initial state for a tracker.

        Uses a fresh session rather than self.session: the progress flush loop
        runs concurrently with the user's script (run_code drives both at once),
        and an AsyncSession does not allow concurrent operations.
        """
        if tracker._item_id is not None:
            return
        from database import ChatItem
        from database_registry import get_database_registry
        from utils.websocket import ws_manager

        display_data = {
            "title": tracker._title,
            "status": "in_progress",
            "current": tracker._current,
            "total": tracker._total,
            "previews": list(tracker._previews),
        }
        chat_item = ChatItem(
            chat_id=self.chat_id,
            item_type="progress_display",
            item_metadata=json.dumps({"display_data": display_data}),
        )
        db = get_database_registry().get_database(get_current_profile())
        async with db.async_session_maker() as session:
            session.add(chat_item)
            await session.commit()
            tracker._item_id = chat_item.id
            item_dict = chat_item.to_dict()

        await ws_manager.broadcast("chat_item_created", {
            "chat_id": self.chat_id,
            "item": item_dict,
        })

    async def _flush_progress(self) -> None:
        """Flush pending progress updates to the frontend via WebSocket (no DB write)."""
        from utils.websocket import ws_manager

        for tracker in self._progress_trackers:
            await self._ensure_tracker_created(tracker)
            pending = tracker._take_pending()
            if pending is None:
                continue
            await ws_manager.broadcast("chat_item_updated", {
                "chat_id": self.chat_id,
                "item": {
                    "id": tracker._item_id,
                    "item_type": "progress_display",
                    "item_metadata": {"display_data": pending["display_data"]},
                },
            })

    async def _finalize_progress(self, reason: str = "completed") -> None:
        """Mark all trackers as done, persist final state to DB, broadcast.

        Uses a fresh session (see _ensure_tracker_created) — finalize can run
        while the user's script is still touching self.session concurrently.
        """
        from database import ChatItem
        from database_registry import get_database_registry
        from utils.websocket import ws_manager
        from sqlalchemy import select

        for tracker in self._progress_trackers:
            await self._ensure_tracker_created(tracker)
            tracker._mark_completed(reason)
            state = tracker._take_pending()
            if state is None:
                continue

            # Persist final state to DB in a fresh session
            db = get_database_registry().get_database(get_current_profile())
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(ChatItem).where(ChatItem.id == tracker._item_id)
                )
                chat_item = result.scalar_one_or_none()
                if chat_item:
                    chat_item.item_metadata = json.dumps({"display_data": state["display_data"]})
                    await session.commit()

            await ws_manager.broadcast("chat_item_updated", {
                "chat_id": self.chat_id,
                "item": {
                    "id": tracker._item_id,
                    "item_type": "progress_display",
                    "item_metadata": {"display_data": state["display_data"]},
                },
            })

    async def create_parameter_sweep(
        self,
        media_ids: Sequence[ToolResult | int],
        rows: int,
        cols: int,
        row_headers: Sequence[str],
        col_headers: Sequence[str],
        title: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a parameter sweep grid from systematically varied images.

        Creates a .stimmagrid.json MediaItem in the library. Cell images are
        superseded (hidden from browse, visible in grid context).
        Use only when images were generated by varying two or more parameter
        axes (e.g. LoRA strength × prompt).

        Args:
            media_ids: Media IDs or ToolResults in row-major order. Length must == rows * cols.
            rows: Number of rows.
            cols: Number of columns.
            row_headers: Labels for each row. Length must == rows.
            col_headers: Labels for each column. Length must == cols.
            title: Grid title.
            description: Optional description.

        Returns:
            Dict with keys: "media_id" (int), "title" (str), "rows", "cols", etc.
        """
        from .tools.assemble_grid import create_parameter_sweep as _create_parameter_sweep

        # Normalize ToolResults to ints
        normalized: list[int] = []
        for item in media_ids:
            if isinstance(item, ToolResult):
                if item.media_id is None:
                    raise ValueError("ToolResult has no media_id — was it saved to library?")
                normalized.append(item.media_id)
            elif isinstance(item, int):
                normalized.append(item)
            else:
                raise TypeError(f"Expected ToolResult or int, got {type(item)}")

        raw = await _create_parameter_sweep(
            media_ids=normalized,
            rows=rows,
            cols=cols,
            row_headers=list(row_headers),
            col_headers=list(col_headers),
            title=title,
            description=description,
            session=self.session,
            chat_id=self.chat_id,
            workspace_dir=self.workspace_dir,
            project_id=self.project_id,
        )
        if isinstance(raw, str) and raw.startswith("Error:"):
            raise RuntimeError(raw[6:].strip())

        # Parse out the media_id from the result string
        import re
        match = re.search(r'media_id=(\d+)', raw)
        grid_media_id = int(match.group(1)) if match else None
        return {
            "media_id": grid_media_id,
            "title": title,
            "description": description,
            "rows": rows,
            "cols": cols,
            "row_headers": list(row_headers),
            "col_headers": list(col_headers),
            "cell_count": len(normalized),
        }

    # Backward compat aliases
    async def assemble_parameter_grid(self, *args, **kwargs):
        return await self.create_parameter_sweep(*args, **kwargs)

    async def assemble_grid(self, *args, **kwargs):
        return await self.create_parameter_sweep(*args, **kwargs)

    async def create_set(
        self,
        items: Iterable[ToolResult | int] | None = None,
        title: str | None = None,
        media_ids: Iterable[ToolResult | int] | None = None,
        description: str | None = None,
    ) -> int:
        """Group media items into a set. Returns the set's media_id.

        Items can be ToolResult objects (from call_tool) or media_id ints.
        The set appears as a single item in the library browse view.
        Members are hidden from browse individually.
        """
        if items is None:
            items = media_ids
        if items is None:
            raise ValueError("No items to group into a set")
        # Accepted for compatibility with older skills/examples. Sets currently
        # store only media IDs and a title.
        _ = description

        media_ids: list[int] = []
        for item in items:
            if isinstance(item, ToolResult):
                if item.media_id is None:
                    raise ValueError("ToolResult has no media_id — was it saved to library?")
                media_ids.append(item.media_id)
            elif isinstance(item, int):
                media_ids.append(item)
            else:
                raise TypeError(f"Expected ToolResult or int, got {type(item)}")

        if not media_ids:
            raise ValueError("No items to group into a set")

        from routes.media import create_set_from_media, CreateSetRequest
        request = CreateSetRequest(media_ids=media_ids, title=title)
        response = await create_set_from_media(request, session=self.session)
        if self.project_id is not None:
            from project_service import attach_media_to_project
            await attach_media_to_project(self.session, self.project_id, response.media_id)
            await self.session.commit()
        return response.media_id

    async def flush(self) -> None:
        if not self._pending_display_calls:
            return
        pending = list(self._pending_display_calls)
        self._pending_display_calls.clear()
        for payload in pending:
            # Auto-save workspace paths to library before displaying
            saved_media_ids = await self._auto_save_paths(payload.get("paths") or [])
            # Merge saved media_ids with any existing ones, drop the paths
            all_media_ids = list(payload.get("media_ids") or []) + saved_media_ids
            self._shown_media_ids.extend(all_media_ids)
            await show_tool(
                media_ids=all_media_ids or None,
                paths=None,
                title=payload["title"],
                session=self.session,
                chat_id=self.chat_id,
                workspace_dir=self.workspace_dir,
            )

    async def _auto_save_paths(self, paths: list[str]) -> list[int]:
        """Save workspace paths to library with lineage from tracked tool results."""
        if not paths:
            return []

        # Collect source media_ids from tool results in this run_code execution
        source_media_ids = [
            tr.media_id for tr in self._tool_results if tr.media_id is not None
        ]
        # Add session-level context from earlier tool calls in the agentic loop
        source_media_ids.extend(self._session_media_ids)
        # Deduplicate while preserving order
        source_media_ids = list(dict.fromkeys(source_media_ids))

        # Build provenance from the primary source's generation metadata
        provenance = await self._build_edit_provenance(source_media_ids)

        saved_ids: list[int] = []
        for path in paths:
            raw = await save_workspace_file(
                session=self.session,
                path=path,
                workspace_dir=self.workspace_dir,
                save_tags=None,
                provenance=provenance,
            )
            if isinstance(raw, str) and not raw.startswith("Error:"):
                data = json.loads(raw)
                saved_ids.append(data["media_id"])
            else:
                log.warning(f"[flush] Auto-save failed for {path}: {raw}")
        return saved_ids

    async def _build_edit_provenance(self, source_media_ids: list[int]) -> dict[str, Any]:
        """Build provenance for an agent-edited file with inherited lineage_trace."""
        provenance: dict[str, Any] = {
            "task_type": "agent_edit",
            "source_media_ids": source_media_ids,
        }

        if not source_media_ids:
            return provenance

        # Fetch all source items in one query
        result = await self.session.execute(
            select(MediaItem).where(MediaItem.id.in_(source_media_ids))
        )
        source_items = {item.id: item for item in result.scalars().all()}

        if not source_items:
            return provenance

        # Build lineage_trace from ALL sources (deduplicated by media_id)
        seen_trace_ids: set[int] = set()
        lineage_trace: list[dict] = []

        for mid in source_media_ids:
            source_item = source_items.get(mid)
            if not source_item:
                continue

            source_gen: dict = {}
            if source_item.generation_metadata:
                try:
                    source_gen = json.loads(source_item.generation_metadata)
                except (TypeError, json.JSONDecodeError):
                    pass

            # Inherit this parent's lineage_trace entries
            for entry in (source_gen.get("lineage_trace") or []):
                entry_id = entry.get("media_id")
                if entry_id and entry_id not in seen_trace_ids:
                    seen_trace_ids.add(entry_id)
                    lineage_trace.append(entry)

            # Append this parent itself as an ancestor entry
            if mid not in seen_trace_ids:
                seen_trace_ids.add(mid)
                source_parameters = dict(source_gen.get("parameters") or {})
                if source_parameters.get("seed") is None and source_gen.get("seed") is not None:
                    source_parameters["seed"] = source_gen["seed"]
                lineage_trace.append({
                    "media_id": mid,
                    "task_type": source_gen.get("task_type"),
                    "tool_id": source_gen.get("tool_id"),
                    "model": source_gen.get("model"),
                    "generator": source_gen.get("generator"),
                    "prompt": source_gen.get("prompt"),
                    "negative_prompt": source_gen.get("negative_prompt"),
                    "parameters": source_parameters,
                    "generated_at": source_gen.get("generated_at"),
                    "source_inputs": source_gen.get("source_inputs") if isinstance(source_gen.get("source_inputs"), list) else [],
                    "seed": source_gen.get("seed"),
                })

        provenance["lineage_trace"] = lineage_trace
        provenance["source_inputs"] = [
            {"media_id": mid, "role": "source_image", "file_path": source_items[mid].file_path}
            for mid in source_media_ids if mid in source_items
        ]

        # Inherit tool_id from primary source for tool lineage propagation
        primary_item = source_items.get(source_media_ids[0])
        if primary_item and primary_item.generation_metadata:
            try:
                primary_gen = json.loads(primary_item.generation_metadata)
                if primary_gen.get("tool_id"):
                    provenance["tool_id"] = primary_gen["tool_id"]
            except (TypeError, json.JSONDecodeError):
                pass

        return provenance

    async def _resolve_media_or_path(self, value: str | Path | int) -> Path:
        if isinstance(value, int):
            result = await self.session.execute(select(MediaItem).where(MediaItem.id == value))
            item = result.scalar_one_or_none()
            if not item or not item.file_path:
                raise FileNotFoundError(f"Media {value} not found")
            return Path(item.file_path)
        return self._resolve_path(value)

    def _resolve_path(self, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.workspace_dir / path
        return path

    def _save_pil_image(self, img: Image.Image) -> str:
        """Save a PIL Image to a temp file in the workspace, return the path."""
        self._pil_save_counter = getattr(self, "_pil_save_counter", 0) + 1
        filename = f"_adjust_{self._pil_save_counter:04d}.png"
        path = self.workspace_dir / filename
        img.save(path)
        return str(path)

    def _normalize_show_inputs(
        self,
        item: ToolResult | str | Path | int | Iterable[ToolResult | str | Path | int],
    ) -> tuple[list[str], list[int]]:
        # Unwrap dicts with media_id (e.g. create_parameter_sweep results)
        if isinstance(item, dict) and "media_id" in item:
            item = item["media_id"]
        values = list(item) if isinstance(item, Iterable) and not isinstance(item, (str, Path, ToolResult, Image.Image)) else [item]
        paths: list[str] = []
        media_ids: list[int] = []
        for value in values:
            if isinstance(value, dict) and "media_id" in value:
                media_ids.append(value["media_id"])
            elif isinstance(value, ToolResult):
                if value.media_id is not None:
                    media_ids.append(value.media_id)
                else:
                    paths.append(str(value.path))
            elif isinstance(value, Image.Image):
                paths.append(self._save_pil_image(value))
            elif isinstance(value, int):
                media_ids.append(value)
            else:
                paths.append(str(value))
        return paths, media_ids


def _format_run_code_receipt(
    successes: list[ToolResult],
    failures: list[dict[str, Any]],
) -> str | None:
    if not successes and not failures:
        return None

    def _short_prompt(p: str | None) -> str:
        if not p:
            return ""
        s = p.strip().replace("\n", " ")
        return s if len(s) <= 80 else s[:77] + "..."

    def _fmt_success(r: ToolResult) -> str:
        mid = f"media_id={r.media_id}" if r.media_id is not None else "media_id=?"
        tool = r.tool_name or "tool"
        sp = _short_prompt(r.prompt)
        return f"  - {mid} — {tool}" + (f', prompt="{sp}"' if sp else "")

    lines: list[str] = []
    if successes:
        s_word = "generation" if len(successes) == 1 else "generations"
        lines.append(f"This run produced {len(successes)} {s_word} (saved to your library):")
        if len(successes) <= 20:
            lines.extend(_fmt_success(r) for r in successes)
        else:
            lines.extend(_fmt_success(r) for r in successes[:3])
            lines.append(f"  ... ({len(successes) - 6} more)")
            lines.extend(_fmt_success(r) for r in successes[-3:])

    if failures:
        if successes:
            lines.append("")
        f_word = "call" if len(failures) == 1 else "calls"
        lines.append(f"{len(failures)} {f_word} failed:")
        for f in failures:
            tool = f.get("tool_id") or "tool"
            sp = _short_prompt(f.get("prompt"))
            err = f.get("error") or "unknown error"
            prompt_part = f' prompt="{sp}" — ' if sp else " — "
            lines.append(f"  - {tool}:{prompt_part}{err}")

    lines.append("")
    if successes and failures:
        lines.append(
            "These media IDs are still valid — if they're useful, reuse them. "
            "Only retry the failed calls; don't regenerate work that already succeeded."
        )
    elif successes:
        lines.append(
            "These media IDs are still valid — if they're useful, reuse them rather than regenerating."
        )
    else:
        lines.append("Retry only the failed calls.")

    body = "\n".join(lines)
    return f"<system-reminder>\n{body}\n</system-reminder>"


async def run_code_in_sandbox(
    *,
    code: str,
    session: AsyncSession,
    chat_id: int,
    workspace_dir: Path,
    project_workspace_dir: Path | None,
    interrupt_checker,
    session_media_ids: list[int] | None = None,
    shown_media_ids: set[int] | None = None,
    enabled_skills: list[str] | None = None,
    project_id: int | None = None,
    effective_model_slug: str | None = None,
) -> tuple[str, dict]:
    stdout = io.StringIO()

    # Coerce to Path since callers may pass strings
    workspace_dir = Path(workspace_dir) if not isinstance(workspace_dir, Path) else workspace_dir
    project_workspace_dir = Path(project_workspace_dir) if project_workspace_dir and not isinstance(project_workspace_dir, Path) else project_workspace_dir

    def _printer(*args, **kwargs):
        py_builtins.print(*args, file=stdout, **kwargs)

    sdk_instance = StimmaSDK(
        session=session,
        chat_id=chat_id,
        workspace_dir=workspace_dir,
        project_workspace_dir=project_workspace_dir,
        interrupt_checker=interrupt_checker,
        session_media_ids=session_media_ids,
        project_id=project_id,
        effective_model_slug=effective_model_slug,
    )

    # Create a tqdm class bound to this SDK instance so `from tqdm import tqdm` just works
    class _BoundTqdm(ProgressTracker):
        def __init__(self, iterable=None, desc=None, total=None, **kwargs):
            super().__init__(
                iterable=iterable, desc=desc, total=total,
                _chat_id=sdk_instance.chat_id, _sdk=sdk_instance, **kwargs,
            )

    # Module-like object so both `import tqdm` and `from tqdm import tqdm` work
    tqdm_module = SimpleNamespace(tqdm=_BoundTqdm, auto=SimpleNamespace(tqdm=_BoundTqdm))

    # Collect importable modules from enabled skills
    from .skills import get_skill_lib_modules
    skill_modules = get_skill_lib_modules(enabled_skills)
    if skill_modules:
        # Warn if any skill module collides with built-in allowed modules
        for mod_name in list(skill_modules):
            if mod_name in ALLOWED_MODULES:
                log.warning(f"Skill module '{mod_name}' shadows built-in module — skipping")
                del skill_modules[mod_name]

    builtins = build_safe_builtins(
        workspace_dir,
        _printer,
        skill_modules=skill_modules or None,
        project_workspace_dir=project_workspace_dir,
    )
    # Patch asyncio.gather so standard Python patterns get stimma's
    # progress tracking and concurrency limits transparently.
    import types as _types
    _patched_asyncio = _types.ModuleType("asyncio")
    _patched_asyncio.__dict__.update(asyncio.__dict__)
    _patched_asyncio.gather = lambda *coros, return_exceptions=False: sdk_instance._gather(
        *coros, return_exceptions=return_exceptions,
    )

    # Wrap __import__ so `import stimma`, `import tqdm`, and
    # `import asyncio` return the sandbox-patched versions.
    _original_import = builtins["__import__"]
    def _import_with_extras(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "stimma":
            return sdk_instance
        if name in ("tqdm", "tqdm.auto"):
            return tqdm_module
        if name == "asyncio":
            return _patched_asyncio
        return _original_import(name, globals, locals, fromlist, level)
    builtins["__import__"] = _import_with_extras

    globals_dict: dict[str, Any] = {
        "__builtins__": builtins,
        "__name__": "__stimma_run_code__",
        "stimma": sdk_instance,
        "ControlNetInput": ControlNetInput,
        "tqdm": _BoundTqdm,
        "asyncio": _patched_asyncio,
        "json": json,
        "math": math,
        "random": random,
        "re": re,
        "Path": Path,
        "Image": Image,
        "np": numpy,
        "numpy": numpy,
    }

    # Pre-execution lint — catch SDK misuse before running
    lint_warnings = lint_code(code)
    if lint_warnings:
        from .sdk_help import get_sdk_quick_ref
        return format_lint_errors(lint_warnings) + "\n\n" + get_sdk_quick_ref(), {}

    # Pre-flight validation — check hardcoded tool IDs and media IDs exist
    from .code_lint import validate_hardcoded_refs
    preflight_warnings = await validate_hardcoded_refs(code, session)
    if preflight_warnings:
        from .sdk_help import get_sdk_quick_ref
        return format_lint_errors(preflight_warnings) + "\n\n" + get_sdk_quick_ref(), {}

    wrapper = "async def __stimma_run__():\n"
    if code.strip():
        for line in code.splitlines():
            wrapper += f"    {line}\n"
    else:
        wrapper += "    return None\n"

    def _exec_wrapper():
        exec(compile(wrapper, "<stimma_run_code>", "exec"), globals_dict, globals_dict)
        return globals_dict["__stimma_run__"]

    try:
        fn = await asyncio.to_thread(_exec_wrapper)
        sdk: StimmaSDK = globals_dict["stimma"]
        previous_cwd = Path.cwd()
        os.chdir(workspace_dir)
        try:
            task = asyncio.create_task(fn())

            while not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
                except asyncio.TimeoutError:
                    pass  # just a polling interval
                except asyncio.CancelledError:
                    # Outer agent task was cancelled — kill the inner task too
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    await sdk._finalize_progress("cancelled")
                    raise  # re-raise so the agent loop sees the cancellation

                # Flush queued progress updates to frontend
                await sdk._flush_progress()

                # Check interrupt flag — makes sandbox cancellable
                if callable(interrupt_checker) and interrupt_checker():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    await sdk._finalize_progress("cancelled")
                    msg = "Error: execution interrupted by user"
                    receipt = _format_run_code_receipt(sdk._tool_results, sdk._tool_failures)
                    if receipt:
                        msg = f"{msg}\n\n{receipt}"
                    return msg, sdk_instance.get_llm_usage()

            result = task.result()
        finally:
            os.chdir(previous_cwd)
        await sdk.flush()
        await sdk._finalize_progress("completed")
    except asyncio.CancelledError:
        # Propagate cancellation — the agent loop handles cleanup
        try:
            sdk_ref = globals_dict.get("stimma")
            if sdk_ref is not None:
                await sdk_ref._finalize_progress("cancelled")
        except Exception:
            pass
        raise
    except Exception as e:
        # Finalize any active progress trackers so they don't stay stuck
        try:
            sdk_ref = globals_dict.get("stimma")
            if sdk_ref is not None:
                await sdk_ref._finalize_progress("error")
        except Exception:
            pass
        tb = traceback.extract_tb(e.__traceback__)
        relevant = [frame for frame in tb if frame.filename == "<stimma_run_code>"]
        location = ""
        if relevant:
            location = f" (line {max(relevant, key=lambda f: f.lineno).lineno - 1})"
        error_msg = f"Error{location}: {type(e).__name__}: {e}"
        has_specific_hint = False
        if "coroutine" in str(e).lower():
            error_msg += (
                "\n\nHint: You forgot `await`. Async methods must be awaited: "
                "`info = await stimma.library.get(...)`, not `info = stimma.library.get(...)`."
                " Code already runs inside async def — use await directly at the top level."
            )
            has_specific_hint = True
        if "can't be used in 'await'" in str(e).lower():
            error_msg += (
                "\n\nHint: You cannot await a list or comprehension directly. "
                "Use asyncio.gather to run multiple coroutines concurrently:\n"
                "  results = await asyncio.gather(*[stimma.call_tool('tool', prompt=p) for p in prompts])"
            )
            has_specific_hint = True
        # Hint for agent-only tool NameErrors (e.g. create_layout, bash)
        if isinstance(e, NameError):
            from .code_lint import AGENT_ONLY_TOOLS
            missing_name = getattr(e, "name", None)
            if missing_name and missing_name in AGENT_ONLY_TOOLS:
                error_msg += (
                    f"\n\nHint: '{missing_name}' is an agent-level tool — it cannot be called "
                    f"inside run_code. Return from run_code and use the {missing_name} tool directly."
                )
                has_specific_hint = True
        # Only append generic SDK quick reference when no specific hint was given
        if not has_specific_hint:
            from .sdk_help import get_sdk_quick_ref
            error_msg += "\n\n" + get_sdk_quick_ref()
        # Extract usage even on error — LLM calls may have happened before the crash
        err_usage = {}
        try:
            sdk_ref2 = globals_dict.get("stimma")
            if sdk_ref2 is not None:
                err_usage = sdk_ref2.get_llm_usage()
                receipt = _format_run_code_receipt(sdk_ref2._tool_results, sdk_ref2._tool_failures)
                if receipt:
                    error_msg = f"{error_msg}\n\n{receipt}"
        except Exception:
            pass
        return error_msg, err_usage

    output = stdout.getvalue().strip()
    if result is not None:
        result_text = str(result).strip()
        if result_text:
            output = f"{output}\n{result_text}".strip()
    if not output:
        output = "Code executed successfully."
    if sdk._shown_media_ids:
        output += f" Already displayed {len(sdk._shown_media_ids)} items to user via stimma.show()."
        if shown_media_ids is not None:
            shown_media_ids.update(sdk._shown_media_ids)
    receipt = _format_run_code_receipt(sdk._tool_results, sdk._tool_failures)
    if receipt:
        output = f"{output}\n\n{receipt}"
    return output, sdk_instance.get_llm_usage()


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
