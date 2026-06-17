"""Dry-run/preflight execution for flow programs.

Dry-run reuses the real graph builder and FRP scheduler, but swaps provider
evaluators for deterministic synthetic ones and runs against temporary state.
The goal is to catch structural flow bugs before spending real tool/LLM
calls: bad dynamic bindings, foreach expansion errors, code() shape mistakes,
and HITL handoff problems.
"""

from __future__ import annotations

import asyncio
import base64
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Optional

from flow_dsl.loader import build_graph_from_program_file
from flow_dsl.shapes import (
    DictShape,
    ListShape,
    Scalar,
    Shape,
    UNKNOWN,
    RESERVED_TOOL_KWARGS,
    describe as describe_shape,
    parse_tool_param_expectations,
    shape_from_literal,
    shape_matches_array,
    shape_matches_scalar_kind,
)

from .engine import FlowRun, FlowRunConfig
from .equation_store import EquationStore
from .evaluators import (
    CODE_ERROR,
    EvaluationRequest,
    EvaluationResult,
    EvaluatorError,
    EvaluatorRegistry,
    TOOL_ERROR,
)
from .graph import Equation, EquationGraph, EquationStatus, NodeRef
from .production_evaluators import (
    InfoEvaluator,
    _MAX_LAYOUT_HTML_BYTES,
    _coerce_items_list,
    _format_user_code_error,
    _invoke_code_callable,
    _media_ids_from_code_value,
    _render_template,
    _run_code_snippet,
)
from .state_db import create_flow_state_db


_ONE_BY_ONE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@dataclass(frozen=True)
class DryRunConfig:
    max_items_per_collection: int = 2
    max_equations: int = 200
    timeout_seconds: float = 5.0


@dataclass
class DryRunIssue:
    equation_key: str
    equation_type: str
    status: str
    message: str
    category: str = "error"
    phase_path: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


@dataclass
class DryRunReport:
    ok: bool
    issues: list[DryRunIssue] = field(default_factory=list)
    visited_equations: int = 0
    completed_equations: int = 0
    sampled_collections: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    truncated_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [asdict(issue) for issue in self.issues]
        return data


def sample_flow_inputs(
    inputs: Optional[dict[str, Any]],
    *,
    max_items: int,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Return inputs with top-level collections capped for preflight."""
    sampled: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for key, value in dict(inputs or {}).items():
        if isinstance(value, list) and len(value) > max_items:
            sampled[key] = value[:max_items]
            counts[f"input:{key}"] = len(value)
        else:
            sampled[key] = value
    return sampled, counts


async def dry_run_flow(
    *,
    flow_id: int,
    program_path: Path,
    inputs: Optional[dict[str, Any]] = None,
    project_id: Optional[int] = None,
    config: Optional[DryRunConfig] = None,
) -> DryRunReport:
    """Build and execute a flow against synthetic providers."""
    cfg = config or DryRunConfig()
    start = perf_counter()
    sampled_inputs, sampled_counts = sample_flow_inputs(
        inputs, max_items=cfg.max_items_per_collection,
    )

    with tempfile.TemporaryDirectory(prefix=f"stimma-flow-dry-run-{flow_id}-") as td:
        root = Path(td)
        state_db = root / "state.db"
        create_flow_state_db(state_db)
        store = EquationStore(root / "store")
        store.initialize()

        try:
            graph = build_graph_from_program_file(program_path, inputs=sampled_inputs)
        except Exception as exc:  # noqa: BLE001 - surfaced as dry-run issue
            return DryRunReport(
                ok=False,
                issues=[
                    DryRunIssue(
                        equation_key="<program>",
                        equation_type="build",
                        status="failed",
                        message=str(exc),
                        category=getattr(exc, "category", "build_error"),
                    )
                ],
                duration_ms=max(0, int((perf_counter() - start) * 1000)),
            )

        registry = build_dry_run_registry(root / "media")
        run = FlowRun(
            graph,
            FlowRunConfig(
                flow_id=flow_id,
                project_id=project_id,
                state_db_path=state_db,
                concurrency=10,
                retry_backoff_seconds=0.0,
                hitl_auto_resolve=_auto_resolve_hitl,
            ),
            evaluators=registry,
            store=store,
        )

        truncated_reason: Optional[str] = None
        try:
            await run.start()
            await _wait_with_budgets(run, cfg)
        except asyncio.TimeoutError:
            truncated_reason = f"timeout after {cfg.timeout_seconds:.1f}s"
        except _DryRunBudgetExceeded as exc:
            truncated_reason = str(exc)
        finally:
            await run.stop()

        issues = _issues_from_graph(graph)
        if truncated_reason:
            issues.append(
                DryRunIssue(
                    equation_key="<dry-run>",
                    equation_type="dry_run",
                    status="truncated",
                    message=truncated_reason,
                    category="truncated",
                )
            )
        all_eqs = list(graph.all_equations())
        completed = sum(1 for eq in all_eqs if eq.status == EquationStatus.COMPLETED)
        return DryRunReport(
            ok=not issues,
            issues=issues,
            visited_equations=len(all_eqs),
            completed_equations=completed,
            sampled_collections=sampled_counts,
            duration_ms=max(0, int((perf_counter() - start) * 1000)),
            truncated_reason=truncated_reason,
        )


class _DryRunBudgetExceeded(RuntimeError):
    pass


async def _wait_with_budgets(run: FlowRun, cfg: DryRunConfig) -> None:
    deadline = asyncio.get_event_loop().time() + cfg.timeout_seconds
    while True:
        if len(list(run.graph.all_equations())) > cfg.max_equations:
            raise _DryRunBudgetExceeded(
                f"equation budget exceeded ({cfg.max_equations})"
            )
        if run._is_quiescent():  # intentional: dry-run is scheduler-adjacent
            return
        remaining = max(0.0, deadline - asyncio.get_event_loop().time())
        if remaining <= 0:
            raise asyncio.TimeoutError
        await asyncio.sleep(min(0.05, remaining))


def _merge_tool_inputs_for_dry_run(
    definition: dict[str, Any], resolved_inputs: dict[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    static = definition.get("params") or {}
    if isinstance(static, dict):
        merged.update(static)
    merged.update(resolved_inputs)
    return merged


def _validate_tool_schema_for_dry_run(tool_id: str, params: dict[str, Any]) -> None:
    """Validate concrete dry-run tool params against live tool schemas.

    Build-time validation already catches many static and NodeRef-shape
    mistakes when the provider registry is available. Deferred foreach /
    hitl.approve callbacks are built later, during evaluation. Dry-run
    should exercise that expansion path and fail on the same class of bad
    tool shapes before real generation jobs are queued.
    """
    if not tool_id:
        return
    parameter_schema = _get_tool_schema_for_dry_run(tool_id)
    if parameter_schema is None:
        return
    expectations = parse_tool_param_expectations(parameter_schema)
    if not expectations:
        return

    unknown = [name for name in params if name not in expectations and name not in RESERVED_TOOL_KWARGS]
    if unknown:
        names = ", ".join(repr(n) for n in sorted(unknown))
        raise EvaluatorError(
            f"tool({tool_id!r}): unknown kwarg(s) {names}",
            category=TOOL_ERROR,
        )

    missing = [
        name for name, exp in expectations.items()
        if exp.required and (name not in params or params[name] is None)
    ]
    if missing:
        names = ", ".join(repr(n) for n in sorted(missing))
        raise EvaluatorError(
            f"tool({tool_id!r}): required input(s) {names} missing",
            category=TOOL_ERROR,
        )

    for name, value in params.items():
        exp = expectations.get(name)
        if exp is None or exp.kind == "unknown":
            continue
        shape = shape_from_literal(value)
        ok = True
        if exp.kind == "scalar" and exp.scalar_kind is not None:
            ok = shape_matches_scalar_kind(shape, exp.scalar_kind)
        elif exp.kind == "array":
            ok = shape_matches_array(shape, exp.array_element_kind)
        if not ok:
            raise EvaluatorError(
                f"tool({tool_id!r}): parameter {name!r} shape mismatch "
                f"(expected {_describe_tool_expectation(exp)}, got {describe_shape(shape)})",
                category=TOOL_ERROR,
            )


def _get_tool_schema_for_dry_run(
    tool_id: str,
) -> Optional[dict[str, Any]]:
    try:
        from providers.registry import ProviderRegistry
    except ImportError:
        return None
    try:
        registry = ProviderRegistry.get_instance()
        pair = registry.get_tool(tool_id)
    except Exception:  # noqa: BLE001 - no registry, no schema preflight
        return None
    if pair is None:
        return None
    _, descriptor = pair
    parameter_schema = getattr(descriptor, "parameter_schema", None) or {}
    return parameter_schema if isinstance(parameter_schema, dict) else {}


def _describe_tool_expectation(exp: Any) -> str:
    if exp.kind == "array":
        return f"list[{exp.array_element_kind or 'value'}]"
    if exp.kind == "scalar":
        return exp.scalar_kind or "value"
    return "unknown"


def build_dry_run_registry(media_dir: Path) -> EvaluatorRegistry:
    reg = EvaluatorRegistry()
    media_dir.mkdir(parents=True, exist_ok=True)
    media_path = media_dir / "dry-run-media.png"
    media_path.write_bytes(_ONE_BY_ONE_PNG)

    reg.register("tool_call", DryRunToolEvaluator())
    reg.register("llm_call", DryRunLLMEvaluator())
    reg.register("llm_batch", DryRunLLMBatchEvaluator())
    reg.register("llm_slot", DryRunLLMSlotEvaluator())
    reg.register("code", DryRunCodeEvaluator(media_path))
    reg.register("create_image", DryRunCreateImageEvaluator(media_path))
    reg.register("create_layout", DryRunCreateLayoutEvaluator(media_path))
    reg.register("create_set", DryRunCreateSetEvaluator())
    reg.register("create_grid", DryRunCreateGridEvaluator())
    reg.register("create_document", DryRunCreateDocumentEvaluator())
    reg.register("rasterize_layout", DryRunRasterizeLayoutEvaluator())
    reg.register("fetch_media", DryRunFetchMediaEvaluator())
    reg.register("info", InfoEvaluator())

    reg.register("web_search", _web_search_result)
    return reg


class DryRunToolEvaluator:
    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        merged = _merge_tool_inputs_for_dry_run(
            request.definition, request.resolved_inputs,
        )
        _validate_jsonish(merged, "tool inputs")
        _validate_tool_schema_for_dry_run(
            str(request.definition.get("tool_id") or request.definition.get("tool") or ""),
            merged,
        )
        media_id = _stable_fake_media_id(request.equation_key)
        return EvaluationResult(value=media_id, media_ids=[media_id])


class DryRunLLMEvaluator:
    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        return EvaluationResult(
            value=synthesize_response_format(request.definition.get("response_format"))
        )


class DryRunLLMBatchEvaluator:
    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        n = int(request.definition.get("n", 1) or 1)
        return EvaluationResult(
            value=[
                synthesize_response_format(
                    request.definition.get("response_format"),
                    salt=str(i),
                )
                for i in range(n)
            ]
        )


class DryRunLLMSlotEvaluator:
    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        slot_index = int(request.definition.get("slot_index", -1))
        batch = request.resolved_inputs.get("batch")
        if not isinstance(batch, list):
            raise EvaluatorError(
                f"llm_slot expected batch list, got {type(batch).__name__}",
                category=CODE_ERROR,
            )
        if slot_index < 0 or slot_index >= len(batch):
            raise EvaluatorError(
                f"llm_slot index {slot_index} out of range for batch size {len(batch)}",
                category=CODE_ERROR,
            )
        return EvaluationResult(value=batch[slot_index])


class DryRunCodeEvaluator:
    def __init__(self, media_path: Path) -> None:
        self.media_path = media_path

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        fn = request.definition.get("fn")
        source = request.definition.get("source", "")
        inputs = request.resolved_inputs.get("inputs") or {}
        output_type = request.definition.get("output_type", "json")
        dynamic = request.definition.get("_dynamic") or {}
        dynamic_inputs = dynamic.get("inputs") or {}
        resolved_inputs = self._wrap_media_inputs(inputs, dynamic_inputs)
        try:
            if fn is not None:
                value = await _invoke_code_callable(fn, resolved_inputs)
            else:
                value = await _run_code_snippet(source, resolved_inputs)
        except BaseException as exc:  # noqa: BLE001 - user-code signal
            raise EvaluatorError(
                _format_user_code_error(exc),
                category=CODE_ERROR,
            ) from exc
        if output_type.startswith("list[") and not isinstance(value, list):
            raise EvaluatorError(
                f"code() with output_type={output_type!r} must return a list, "
                f"got {type(value).__name__!r} (source: {source!r})",
                category=CODE_ERROR,
            )
        unwrapped = _unwrap_media(value)
        # Mirror production: surface declared media outputs so dry-run state
        # matches what an actual run would produce.
        media_ids = _media_ids_from_code_value(unwrapped, output_type)
        return EvaluationResult(value=unwrapped, media_ids=media_ids)

    def _wrap_media_inputs(
        self, inputs: dict[str, Any], dynamic_inputs: dict[str, Any],
    ) -> dict[str, Any]:
        return _wrap_media_inputs_for_dry_run(
            inputs, dynamic_inputs, media_path=self.media_path,
        )


class DryRunCreateImageEvaluator:
    def __init__(self, media_path: Path) -> None:
        self.media_path = media_path

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        from PIL import Image

        fn = request.definition.get("fn")
        if fn is None:
            raise EvaluatorError(
                "create_image: missing callable (fn) in definition",
                category=TOOL_ERROR,
            )
        dynamic = request.definition.get("_dynamic") or {}
        dynamic_inputs = dynamic.get("inputs") or {}
        inputs = request.resolved_inputs.get("inputs") or {}
        resolved_inputs = _wrap_media_inputs_for_dry_run(
            inputs, dynamic_inputs, media_path=self.media_path,
        )
        try:
            value = await _invoke_code_callable(fn, resolved_inputs)
        except EvaluatorError:
            raise
        except BaseException as exc:  # noqa: BLE001 - user-code signal
            raise EvaluatorError(
                _format_user_code_error(exc),
                category=CODE_ERROR,
            ) from exc

        if not isinstance(value, Image.Image):
            raise EvaluatorError(
                f"create_image: callable must return a PIL.Image.Image, "
                f"got {type(value).__name__}",
                category=CODE_ERROR,
            )

        media_id = _stable_fake_media_id(request.equation_key)
        return EvaluationResult(value=media_id, media_ids=[media_id])


class DryRunCreateLayoutEvaluator:
    def __init__(self, media_path: Path) -> None:
        self.media_path = media_path

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        from .layout_bundle import extract_all_refs

        fn = request.definition.get("fn")
        if fn is None:
            raise EvaluatorError(
                "create_layout: missing callable (fn) in definition",
                category=TOOL_ERROR,
            )
        dynamic = request.definition.get("_dynamic") or {}
        dynamic_inputs = dynamic.get("inputs") or {}
        inputs = request.resolved_inputs.get("inputs") or {}
        staged: set[str] = set()
        resolved_inputs = _wrap_media_inputs_for_dry_run(
            inputs,
            dynamic_inputs,
            media_path=self.media_path,
            layout_filenames=True,
            staged_filenames=staged,
        )
        try:
            value = await _invoke_code_callable(fn, resolved_inputs)
        except EvaluatorError:
            raise
        except BaseException as exc:  # noqa: BLE001 - user-code signal
            raise EvaluatorError(
                _format_user_code_error(exc),
                category=CODE_ERROR,
            ) from exc

        if not isinstance(value, str):
            raise EvaluatorError(
                f"create_layout: callable must return an HTML string, "
                f"got {type(value).__name__}",
                category=CODE_ERROR,
            )
        if len(value.encode("utf-8")) > _MAX_LAYOUT_HTML_BYTES:
            raise EvaluatorError(
                f"create_layout: HTML exceeds "
                f"{_MAX_LAYOUT_HTML_BYTES // (1024 * 1024)} MB limit",
                category=CODE_ERROR,
            )
        missing = [
            ref for ref in extract_all_refs(value)
            if ref not in staged and not ref.startswith(("http://", "https://", "data:"))
        ]
        if missing:
            raise EvaluatorError(
                f"create_layout: HTML references image(s) that couldn't be "
                f"resolved in dry-run: {sorted(set(missing))}. Staged files: "
                f"{sorted(staged) or '(none)'}",
                category=CODE_ERROR,
            )
        media_id = _stable_fake_media_id(request.equation_key)
        return EvaluationResult(value=media_id, media_ids=[media_id])


class DryRunCreateSetEvaluator:
    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        media_ids = _coerce_items_list(request.resolved_inputs.get("items"))
        if not media_ids:
            raise EvaluatorError("create_set: items list is empty", category=TOOL_ERROR)
        media_id = _stable_fake_media_id(request.equation_key)
        return EvaluationResult(value=media_id, media_ids=[media_id])


class DryRunCreateGridEvaluator:
    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        media_ids = _coerce_items_list(request.resolved_inputs.get("items"))
        rows = int(request.definition.get("rows", 0) or 0)
        cols = int(request.definition.get("cols", 0) or 0)
        expected = rows * cols
        if len(media_ids) != expected:
            raise EvaluatorError(
                f"create_grid: expected {expected} items ({rows}x{cols}), "
                f"got {len(media_ids)}",
                category=TOOL_ERROR,
            )
        media_id = _stable_fake_media_id(request.equation_key)
        return EvaluationResult(value=media_id, media_ids=[media_id])


class DryRunCreateDocumentEvaluator:
    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        content = request.resolved_inputs.get("content")
        if content is None:
            content = request.definition.get("static_content")
        if not isinstance(content, str):
            raise EvaluatorError(
                f"create_document: content resolved to "
                f"{type(content).__name__}, expected str",
                category=TOOL_ERROR,
            )
        media_id = _stable_fake_media_id(request.equation_key)
        return EvaluationResult(value=media_id, media_ids=[media_id])


class DryRunRasterizeLayoutEvaluator:
    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        layout = request.resolved_inputs.get("layout")
        if isinstance(layout, dict) and "media_id" in layout:
            layout = int(layout["media_id"])
        if not isinstance(layout, int) or isinstance(layout, bool):
            raise EvaluatorError(
                f"rasterize_layout: expected a media id, got "
                f"{type(layout).__name__}",
                category=TOOL_ERROR,
            )
        media_id = _stable_fake_media_id(request.equation_key)
        return EvaluationResult(value=media_id, media_ids=[media_id])


class DryRunFetchMediaEvaluator:
    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        url = request.resolved_inputs.get("url")
        if not isinstance(url, str) or not url.strip():
            raise EvaluatorError(
                f"fetch_media: url resolved to {url!r}, expected non-empty string",
                category=TOOL_ERROR,
            )
        if not url.startswith(("http://", "https://")):
            raise EvaluatorError(
                f"fetch_media: url resolved to {url!r}, expected http(s) URL",
                category=TOOL_ERROR,
            )
        media_id = _stable_fake_media_id(request.equation_key)
        return EvaluationResult(value=media_id, media_ids=[media_id])


def _wrap_media_inputs_for_dry_run(
    inputs: dict[str, Any],
    dynamic_inputs: dict[str, Any],
    *,
    media_path: Path,
    layout_filenames: bool = False,
    staged_filenames: Optional[set[str]] = None,
) -> dict[str, Any]:
    from .media_arg import Media

    out = dict(inputs)
    for name, binding in dynamic_inputs.items():
        shape = getattr(binding, "shape", None)
        raw = out.get(name)
        if _shape_is_media(shape) and _looks_like_media_id(raw):
            filename = f"{name}.png" if layout_filenames else None
            if filename and staged_filenames is not None:
                staged_filenames.add(filename)
            out[name] = Media(int(raw), path=str(media_path), filename=filename)
        elif _shape_is_media_list(shape) and isinstance(raw, list):
            items: list[Any] = []
            for i, item in enumerate(raw):
                if _looks_like_media_id(item):
                    filename = f"{name}_{i}.png" if layout_filenames else None
                    if filename and staged_filenames is not None:
                        staged_filenames.add(filename)
                    items.append(
                        Media(int(item), path=str(media_path), filename=filename)
                    )
                else:
                    items.append(item)
            out[name] = items
    return out


async def _web_search_result(request: EvaluationRequest) -> EvaluationResult:
    kind = request.definition.get("kind", "text")
    template = request.definition.get("query_template", "") or ""
    bindings = request.resolved_inputs.get("query") or {}
    query = _render_template(template, bindings).strip()
    if not query:
        raise EvaluatorError(
            "web_search: query resolved to empty string",
            category=TOOL_ERROR,
        )
    if kind == "images":
        return EvaluationResult(
            value=[
                {
                    "title": "Dry-run image",
                    "image_url": "https://example.invalid/dry-run.png",
                    "source": "example.invalid",
                    "width": 1,
                    "height": 1,
                    "media": {
                        "type": "url_media",
                        "url": "https://example.invalid/dry-run.png",
                        "mime_type": "image/*",
                        "title": "Dry-run image",
                        "source": "example.invalid",
                    },
                }
            ]
        )
    return EvaluationResult(
        value=[
            {
                "title": "Dry-run result",
                "url": "https://example.invalid/",
                "snippet": "Synthetic search result for flow dry-run.",
            }
        ]
    )


def _auto_resolve_hitl(eq: Equation, resolved_inputs: dict[str, Any]) -> Any:
    hitl_type = eq.definition.get("hitl_type")
    if hitl_type == "select":
        candidates = resolved_inputs.get("candidates")
        if not isinstance(candidates, list):
            raise TypeError(
                f"hitl.select candidates must resolve to list; got {type(candidates).__name__}"
            )
        count = int(eq.definition.get("count", 1) or 1)
        if count == 1:
            if not candidates:
                raise ValueError("hitl.select candidates are empty")
            return candidates[0]
        return candidates[:count]
    if hitl_type == "approve":
        return True
    raise ValueError(f"unknown HITL type {hitl_type!r}")


def synthesize_response_format(response_format: Any, *, salt: str = "") -> Any:
    if response_format is None:
        return f"dry-run text{salt}"
    if not isinstance(response_format, dict):
        return {"dry_run": True}
    schema = response_format.get("schema")
    if not isinstance(schema, dict):
        return {"dry_run": True}
    if schema.get("type") == "object" and isinstance(schema.get("properties"), dict):
        return {
            str(name): synthesize_jsonschema_prop(prop, salt=salt)
            for name, prop in schema["properties"].items()
        }
    return {
        str(name): (
            synthesize_jsonschema_prop(spec, salt=salt)
            if isinstance(spec, dict)
            else synthesize_type_string(str(spec), salt=salt)
        )
        for name, spec in schema.items()
    }


def synthesize_type_string(type_str: str, *, salt: str = "") -> Any:
    t = (type_str or "json").strip().lower()
    if t.startswith("list[") and t.endswith("]"):
        return [synthesize_type_string(t[5:-1], salt=salt)]
    if t in {"str", "string", "text", "enum"}:
        return f"dry-run{salt}"
    if t in {"int", "integer", "media"}:
        return 900001
    if t in {"float", "number"}:
        return 1.0
    if t in {"bool", "boolean"}:
        return True
    return {"dry_run": True}


def synthesize_jsonschema_prop(prop: Any, *, salt: str = "") -> Any:
    if not isinstance(prop, dict):
        return {"dry_run": True}
    t = prop.get("type")
    if t == "array":
        return [synthesize_jsonschema_prop(prop.get("items") or {}, salt=salt)]
    if t == "object":
        props = prop.get("properties") or {}
        if isinstance(props, dict):
            return {
                str(name): synthesize_jsonschema_prop(spec, salt=salt)
                for name, spec in props.items()
            }
        return {"dry_run": True}
    if isinstance(t, str):
        return synthesize_type_string(t, salt=salt)
    return {"dry_run": True}


def synthesize_shape(shape: Shape, *, salt: str = "") -> Any:
    if isinstance(shape, Scalar):
        return synthesize_type_string(shape.kind, salt=salt)
    if isinstance(shape, ListShape):
        return [synthesize_shape(shape.element, salt=salt)]
    if isinstance(shape, DictShape):
        return {
            name: synthesize_shape(field_shape, salt=salt)
            for name, field_shape in shape.fields
        }
    return {"dry_run": True}


def _issues_from_graph(graph: EquationGraph) -> list[DryRunIssue]:
    issues: list[DryRunIssue] = []
    for eq in graph.all_equations():
        if eq.status in (EquationStatus.FAILED, EquationStatus.WAITING_FOR_TOOL):
            category = "error"
            message = eq.error or f"equation ended with status {eq.status.value}"
            if message.startswith("[") and "]" in message:
                category = message[1:message.index("]")]
            issues.append(
                DryRunIssue(
                    equation_key=eq.key,
                    equation_type=eq.equation_type.value,
                    status=eq.status.value,
                    message=message,
                    category=category,
                    phase_path=list(eq.phase_path),
                    dependencies=list(eq.dependencies),
                )
            )
        elif eq.status == EquationStatus.AWAITING_INPUT:
            issues.append(
                DryRunIssue(
                    equation_key=eq.key,
                    equation_type=eq.equation_type.value,
                    status=eq.status.value,
                    message="dry-run left HITL equation awaiting input",
                    category="hitl",
                    phase_path=list(eq.phase_path),
                    dependencies=list(eq.dependencies),
                )
            )
    return issues


def _stable_fake_media_id(key: str) -> int:
    return 900000 + (abs(hash(key)) % 100000)


def _looks_like_media_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _shape_is_media(shape: Any) -> bool:
    if shape is UNKNOWN or shape is None:
        return False
    return isinstance(shape, Scalar) and shape.kind in {"media", "int", "any"}


def _shape_is_media_list(shape: Any) -> bool:
    return isinstance(shape, ListShape) and _shape_is_media(shape.element)


def _unwrap_media(value: Any) -> Any:
    from .media_arg import Media

    if isinstance(value, Media):
        return value.id
    if isinstance(value, list):
        return [_unwrap_media(v) for v in value]
    if isinstance(value, dict):
        return {k: _unwrap_media(v) for k, v in value.items()}
    return value


def _validate_jsonish(value: Any, label: str) -> None:
    if isinstance(value, NodeRef):
        raise EvaluatorError(f"{label} contains unresolved NodeRef", category=TOOL_ERROR)
    if isinstance(value, dict):
        for child in value.values():
            _validate_jsonish(child, label)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_jsonish(child, label)
