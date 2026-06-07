"""Filesystem projection of the STP tool catalog.

The agent was trained to explore a filesystem with read/grep/glob and to act by
running code. Historically the main agent discovered tools through an RPC funnel
(``list_task_types`` -> ``list_tools`` -> ``get_schema`` -> ``search_options``)
whose results evaporated into the transcript, and called them through three
different shapes. That is illegible to a code model, so it guessed.

This module projects the *entire* tool catalog into the workspace as a read-only
``.stimma/`` tree of body-less, typed Python stubs — one file per (tool, task
type) — plus an importable runtime namespace with the *identical* signature. The
stub you ``cat`` is generated from the same manifest that binds the function you
``await``, so they can never drift.

Two consumers, one source of truth (:func:`build_manifest`):

* :func:`materialize_tool_fs` writes the readable ``.stimma/`` tree.
* :func:`build_tools_namespace` builds the live ``stimma.tools.<task>`` modules
  injected into the ``run_code`` / ``run_file`` sandbox.

Both compute names with the same helpers, so ``.stimma/tools/text-to-image/
flux_klein_9b.py`` and ``from stimma.tools.text_to_image import flux_klein_9b``
always refer to the same tool.
"""

from __future__ import annotations

import hashlib
import json
import keyword
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from core.logging import get_logger

log = get_logger(__name__)

# Enums with more than this many options are not inlined into the signature.
# Most enums are small (~20 samplers); only pathological catalogs (thousands of
# loras/checkpoints) hit this and get spilled to a greppable ``.stimma/enums``
# file referenced from the docstring.
ENUM_INLINE_THRESHOLD = 100

# Params the model should not fill in unprompted. Shown in the signature with
# their default, grouped under one docstring line rather than hidden — the agent
# can see they exist without being tempted to override them.
_AUTO_DEFAULT_PARAMS = ("steps", "cfg", "guidance", "sampler", "scheduler")

_CONTROLNET_DESCRIPTIONS = {
    "canny": "edge detection — preserves outlines/boundaries",
    "depth": "depth — preserves spatial layout, fg/bg separation",
    "lineart": "line art extraction — basic structural lines",
    "lineart_realistic": "realistic line art — best for photographic sources",
    "lineart_anime": "anime line art — optimized for illustration",
    "pose": "body pose — preserves posture/body position",
    "pose_hands": "pose with hands — body position plus hand skeleton",
}


# ── naming ──────────────────────────────────────────────────────────────────

def module_for_task(task_type: str) -> str:
    """``text-to-image`` -> ``text_to_image`` (a valid Python module name)."""
    name = re.sub(r"[^0-9a-zA-Z]+", "_", task_type or "misc").strip("_").lower()
    if not name:
        name = "misc"
    if name[0].isdigit():
        name = f"t_{name}"
    return name


def _base_pyname(tool_id: str) -> str:
    """Derive a readable function name from a tool_id.

    Drops the provider prefix for readability (``comfyui:flux-klein-9b`` ->
    ``flux_klein_9b``); collisions within a task module are disambiguated by
    :func:`build_manifest`, never silently.
    """
    local = tool_id.split(":", 1)[1] if ":" in tool_id else tool_id
    name = re.sub(r"[^0-9a-zA-Z]+", "_", local).strip("_").lower()
    if not name:
        name = re.sub(r"[^0-9a-zA-Z]+", "_", tool_id).strip("_").lower() or "tool"
    if name[0].isdigit():
        name = f"t_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


# ── manifest (single source of truth) ───────────────────────────────────────

@dataclass
class ToolBinding:
    func_name: str
    module: str  # python module name, e.g. "text_to_image"
    task_type: str  # original, e.g. "text-to-image"
    tool_id: str
    descriptor: Any = field(repr=False, default=None)


@dataclass
class Manifest:
    # module -> func_name -> ToolBinding
    by_module: dict[str, dict[str, ToolBinding]]

    def iter_bindings(self):
        for funcs in self.by_module.values():
            yield from funcs.values()

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "tools": {
                module: {
                    fn: {"tool_id": b.tool_id, "task_type": b.task_type}
                    for fn, b in funcs.items()
                }
                for module, funcs in sorted(self.by_module.items())
            },
        }


def build_manifest(registry) -> Manifest:
    """Enumerate the live registry into a name-stable manifest.

    This is the single source of truth: both the materialized stubs and the
    runtime import namespace are derived from it, so the readable catalog and
    the callable surface are guaranteed identical.
    """
    by_module: dict[str, dict[str, ToolBinding]] = {}
    try:
        all_tools = registry.list_all_tools()
    except Exception as e:  # pragma: no cover - defensive
        log.warning(f"tool_fs: failed to enumerate registry: {e}")
        return Manifest(by_module={})

    # Deterministic order so disambiguation suffixes are stable across runs.
    for full_id, _provider, descriptor in sorted(all_tools, key=lambda t: t[0]):
        task_types = list(getattr(descriptor, "task_types", None) or [])
        if not task_types:
            primary = getattr(descriptor, "task_type", None)
            task_types = [primary] if primary else ["misc"]
        for task_type in task_types:
            module = module_for_task(task_type)
            base = _base_pyname(full_id)
            funcs = by_module.setdefault(module, {})
            name = base
            if name in funcs and funcs[name].tool_id != full_id:
                # Disambiguate deterministically with a provider-derived suffix.
                provider_prefix = full_id.split(":", 1)[0] if ":" in full_id else "x"
                suffix = re.sub(r"[^0-9a-z]+", "", provider_prefix.lower()) or "alt"
                name = f"{base}_{suffix}"
                counter = 2
                while name in funcs and funcs[name].tool_id != full_id:
                    name = f"{base}_{suffix}{counter}"
                    counter += 1
            funcs[name] = ToolBinding(
                func_name=name,
                module=module,
                task_type=task_type,
                tool_id=full_id,
                descriptor=descriptor,
            )
    return Manifest(by_module=by_module)


# ── JSON Schema -> Python type rendering ────────────────────────────────────

_MEDIA_HINTS = ("input_image", "image", "media", "mask", "audio", "video")


def _py_type_for(prop: dict[str, Any], prop_name: str, *, enum_inline: bool) -> str:
    """Render a JSON-schema property as a Python type annotation string."""
    enum = prop.get("enum")
    if isinstance(enum, list) and enum:
        if enum_inline:
            rendered = ", ".join(repr(v) for v in enum)
            return f"Literal[{rendered}]"
        # large enum: fall back to the base type, value list lives in a file
        # referenced from the docstring.
    jtype = prop.get("type")
    if isinstance(jtype, list):
        jtype = next((t for t in jtype if t != "null"), jtype[0] if jtype else None)
    if jtype == "string":
        return "str"
    if jtype == "integer":
        return "int"
    if jtype == "number":
        return "float"
    if jtype == "boolean":
        return "bool"
    if jtype == "array":
        items = prop.get("items")
        if isinstance(items, dict):
            inner = _py_type_for(items, prop_name, enum_inline=enum_inline)
            return f"list[{inner}]"
        return "list"
    if jtype == "object":
        return "dict"
    # Heuristic for media-bearing params lacking explicit types.
    low = prop_name.lower()
    if any(h in low for h in _MEDIA_HINTS):
        return "int | str"
    return "Any"


def _is_media_param(prop_name: str, prop: dict[str, Any]) -> bool:
    low = prop_name.lower()
    return any(h in low for h in _MEDIA_HINTS)


@dataclass
class _RenderedParam:
    name: str
    annotation: str
    default: str | None  # repr string or None if required
    doc: str | None
    is_auto_default: bool = False


def _collect_controlnet(schema: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for prop in (schema.get("properties") or {}).values():
        if not isinstance(prop, dict):
            continue
        cn = prop.get("x-controlnet")
        if isinstance(cn, list):
            for entry in cn:
                cid = entry.get("id") if isinstance(entry, dict) else entry
                if isinstance(cid, str) and cid not in found:
                    found.append(cid)
    return found


def _render_params(
    schema: dict[str, Any],
    tool_id: str,
    *,
    enum_threshold: int,
) -> tuple[list[_RenderedParam], dict[str, list[str]]]:
    """Return rendered params and a map of {enum_file_stem: values} for spills."""
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    params: list[_RenderedParam] = []
    enum_spills: dict[str, list[str]] = {}

    def handle_enums(prop: dict[str, Any], path: str) -> str | None:
        """Spill an over-threshold enum to a file; return its stem, else None."""
        enum = prop.get("enum")
        if not (isinstance(enum, list) and enum):
            return None
        if len(enum) <= enum_threshold:
            return None
        stem = re.sub(r"[^0-9a-zA-Z]+", "_", f"{_base_pyname(tool_id)}_{path}").strip("_")
        enum_spills[stem] = [str(v) for v in enum]
        return stem

    # Order: required first (no defaults), then optional, auto-defaults last.
    items = list(props.items())

    def sort_key(item):
        name, prop = item
        is_req = name in required
        is_auto = name in _AUTO_DEFAULT_PARAMS
        return (0 if is_req else (2 if is_auto else 1), name)

    for name, prop in sorted(items, key=sort_key):
        if not isinstance(prop, dict):
            prop = {}
        # nested enums (e.g. loras.path) live under items.properties
        own_stem = handle_enums(prop, name)
        inline = own_stem is None
        # Walk one level into array items for nested enum spill detection.
        nested_ref = ""
        items_schema = prop.get("items")
        if isinstance(items_schema, dict):
            for sub_name, sub_prop in (items_schema.get("properties") or {}).items():
                if isinstance(sub_prop, dict):
                    sub_stem = handle_enums(sub_prop, f"{name}.{sub_name}")
                    if sub_stem and not nested_ref:
                        nested_ref = sub_stem

        annotation = _py_type_for(prop, name, enum_inline=inline)
        is_required = name in required
        is_auto = name in _AUTO_DEFAULT_PARAMS

        default_repr: str | None
        if is_required:
            default_repr = None
        elif "default" in prop:
            default_repr = repr(prop["default"])
        elif annotation.startswith("list"):
            default_repr = "[]"
        elif annotation.startswith("dict"):
            default_repr = "{}"
        else:
            default_repr = "None"
            if "| None" not in annotation and not annotation.startswith("Literal"):
                annotation = f"{annotation} | None"

        doc = prop.get("description")
        if isinstance(doc, str):
            doc = " ".join(doc.split())
        else:
            doc = None
        if not inline and own_stem:
            ref = f"see .stimma/enums/{own_stem}.txt (grep it)"
            doc = f"{doc + '. ' if doc else ''}{ref}"
        elif nested_ref:
            doc = f"{doc + '. ' if doc else ''}see .stimma/enums/{nested_ref}.txt (grep it)"

        params.append(
            _RenderedParam(
                name=name,
                annotation=annotation,
                default=default_repr,
                doc=doc,
                is_auto_default=is_auto,
            )
        )

    return params, enum_spills


def render_tool_stub(
    binding: ToolBinding,
    *,
    enum_threshold: int = ENUM_INLINE_THRESHOLD,
) -> tuple[str, dict[str, list[str]]]:
    """Render a body-less typed stub for one tool. Returns (text, enum_spills)."""
    descriptor = binding.descriptor
    schema = getattr(descriptor, "parameter_schema", None) or {}
    name = getattr(descriptor, "name", None) or binding.tool_id
    description = (
        getattr(descriptor, "description", None)
        or getattr(descriptor, "subtitle", None)
        or ""
    )
    description = " ".join(str(description).split())

    params, enum_spills = _render_params(schema, binding.tool_id, enum_threshold=enum_threshold)
    controlnet_ids = _collect_controlnet(schema)

    lines: list[str] = []
    lines.append('"""AUTO-GENERATED — read-only. Regenerated when providers change."""')
    lines.append("from __future__ import annotations")
    lines.append("from typing import Any, Literal")
    lines.append("")
    lines.append("# Annotations are illustrative; pass keyword arguments.")
    lines.append("#   media params accept a library media id (int) or a workspace path (str)")
    lines.append("#   the returned ToolResult has: .media_id .path .seed .width .height")
    lines.append("")

    # Signature
    lines.append(f"async def {binding.func_name}(")
    lines.append("    *,")
    for p in params:
        if p.default is None:
            lines.append(f"    {p.name}: {p.annotation},")
        else:
            lines.append(f"    {p.name}: {p.annotation} = {p.default},")
    if controlnet_ids:
        cn_lit = ", ".join(repr(c) for c in controlnet_ids)
        lines.append(f"    controlnet: Literal[{cn_lit}] | None = None,")
    lines.append(") -> ToolResult:")

    # Docstring
    doc: list[str] = []
    title = f"{name} — {binding.task_type}."
    doc.append(title)
    if description:
        doc.append("")
        doc.append(description)
    doc.append("")
    doc.append(f'tool_id: "{binding.tool_id}"  ·  task_type: "{binding.task_type}"')
    doc.append("")
    doc.append("Call from run_code / run_file:")
    doc.append(f"    from stimma.tools.{binding.module} import {binding.func_name}")
    doc.append(f"    r = await {binding.func_name}(...)")
    doc.append("In a recipe program.py:")
    doc.append(f'    tool("{binding.tool_id}", task_type="{binding.task_type}", ...)')

    documented = [p for p in params if p.doc and not p.is_auto_default]
    if documented:
        doc.append("")
        doc.append("Parameters:")
        for p in documented:
            doc.append(f"    {p.name}: {p.doc}")
    auto = [p for p in params if p.is_auto_default]
    if auto:
        doc.append("")
        doc.append(
            "Auto-tuned (only pass to override): "
            + ", ".join(p.name for p in auto)
            + "."
        )
    if controlnet_ids:
        doc.append("")
        doc.append("controlnet preprocessors:")
        for cid in controlnet_ids:
            doc.append(f"    {cid}: {_CONTROLNET_DESCRIPTIONS.get(cid, cid)}")

    lines.append('    """')
    for d in doc:
        lines.append(f"    {d}" if d else "")
    lines.append('    """')
    lines.append("    ...")
    lines.append("")

    return "\n".join(lines), enum_spills


# ── materialization ─────────────────────────────────────────────────────────

_README = """\
# .stimma/ — your tool catalog as a filesystem (read-only, auto-generated)

This tree IS the documentation AND the exact shape of what you can call. It is
regenerated from the live provider registry; do not edit it (writes are
rejected).

## Find a tool
    ls .stimma/tools/                      # task categories
    ls .stimma/tools/text-to-image/        # tools in a category
    grep -ril upscale .stimma/tools/       # search by capability
    cat .stimma/tools/text-to-image/<tool>.py   # exact signature + docs

Each file is a body-less, typed function. Its signature is the parameter
contract; its docstring carries the tool_id, task_type, and notes. The function
name and its `from stimma.tools.<category> import <name>` path are real — they
resolve to the live tool with that exact signature.

## Call a tool (run_code / run_file — this is how you act)
Import it by the REAL function name you read from this directory (the `.py`
filename / the `def` in the stub) — never a placeholder like `gen`:

    from stimma.tools.text_to_image import <tool>   # <tool> = a real name from .stimma/tools/text-to-image/
    r = await <tool>(prompt="a cat", width=1024)
    stimma.show(r)

`r` is a ToolResult: `.media_id`, `.path`, `.seed`, `.width`, `.height`,
`.open()` -> PIL.Image. For batches, `asyncio.gather(...)` runs calls in
parallel. Category directory names use hyphens; the import module uses
underscores (`text-to-image` -> `text_to_image`).

## Large option lists
A parameter with thousands of valid values (e.g. loras) is not inlined in the
signature. Its docstring points to `.stimma/enums/<name>.txt`, one value per
line — grep it.

## In a recipe (program.py)
Use the same catalog to find the `tool_id` and `task_type`, then write
`tool("<tool_id>", task_type="<task_type>", ...)`.
"""


def _write_if_changed(path: Path, content: str) -> bool:
    try:
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return False
    except Exception:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def materialize_tool_fs(
    registry,
    workspace_dir: str | Path,
    *,
    enum_threshold: int = ENUM_INLINE_THRESHOLD,
    manifest: Manifest | None = None,
) -> Path:
    """Write the ``.stimma/`` readable catalog into ``workspace_dir``.

    Idempotent: unchanged files are not rewritten, and the whole tree is
    fingerprinted so an unchanged catalog is a cheap no-op (safe to call every
    turn). Returns the ``.stimma`` root path.
    """
    workspace_dir = Path(workspace_dir)
    root = workspace_dir / ".stimma"
    manifest = manifest or build_manifest(registry)

    # Fingerprint the catalog so we can skip the whole walk when nothing changed.
    fp_src = json.dumps(
        {
            "threshold": enum_threshold,
            "tools": {
                module: {fn: b.tool_id for fn, b in funcs.items()}
                for module, funcs in manifest.by_module.items()
            },
        },
        sort_keys=True,
    )
    # Include schema hashes so a provider editing a tool's params refreshes too.
    schema_fp = hashlib.sha256()
    for b in sorted(manifest.iter_bindings(), key=lambda b: (b.module, b.func_name)):
        schema = getattr(b.descriptor, "parameter_schema", None) or {}
        schema_fp.update(b.tool_id.encode())
        schema_fp.update(json.dumps(schema, sort_keys=True, default=str).encode())
    fingerprint = hashlib.sha256((fp_src + schema_fp.hexdigest()).encode()).hexdigest()

    fp_path = root / ".fingerprint"
    try:
        if fp_path.exists() and fp_path.read_text(encoding="utf-8").strip() == fingerprint:
            return root
    except Exception:
        pass

    # (Re)generate. Build the desired file set, then prune stale files.
    desired: dict[Path, str] = {}
    desired[root / "README.md"] = _README

    enum_files: dict[str, list[str]] = {}
    for module, funcs in manifest.by_module.items():
        task_dir = root / "tools" / next(
            (b.task_type for b in funcs.values()), module
        )
        for fn, binding in funcs.items():
            text, spills = render_tool_stub(binding, enum_threshold=enum_threshold)
            desired[task_dir / f"{fn}.py"] = text
            for stem, values in spills.items():
                enum_files[stem] = values

    for stem, values in enum_files.items():
        desired[root / "enums" / f"{stem}.txt"] = "\n".join(values) + "\n"

    desired[root / ".manifest.json"] = json.dumps(manifest.to_json(), indent=2)

    # Prune files under managed subtrees that are no longer desired.
    managed = [root / "tools", root / "enums"]
    existing: set[Path] = set()
    for base in managed:
        if base.exists():
            existing.update(p for p in base.rglob("*") if p.is_file())
    for stale in existing - set(desired):
        try:
            stale.unlink()
        except Exception:
            pass

    for path, content in desired.items():
        _write_if_changed(path, content)

    # Drop now-empty task directories.
    for base in managed:
        if base.exists():
            for d in sorted(base.rglob("*"), reverse=True):
                if d.is_dir() and not any(d.iterdir()):
                    try:
                        d.rmdir()
                    except Exception:
                        pass

    _write_if_changed(fp_path, fingerprint)
    return root


# ── runtime binding ─────────────────────────────────────────────────────────

def build_tools_namespace(sdk, manifest: Manifest) -> dict[str, ModuleType]:
    """Build ``stimma.tools.<task>`` modules bound to a live ``sdk``.

    Returns an ``extra_modules`` map for the sandbox import hook so that
    ``from stimma.tools.text_to_image import flux_klein_9b`` resolves to an async
    function that dispatches ``sdk._dispatch_tool(tool_id, _task_type=..., **kwargs)``.
    Computed from the same manifest the stubs are rendered from, so the imported
    callable and the ``cat``-able stub are the same tool.
    """
    extra: dict[str, ModuleType] = {}
    tools_pkg = ModuleType("stimma.tools")

    for module, funcs in manifest.by_module.items():
        mod = ModuleType(f"stimma.tools.{module}")
        for fn, binding in funcs.items():
            setattr(mod, fn, _make_bound_tool(sdk, binding))
        # Self-correcting failure: importing a name that isn't a real tool
        # (e.g. a placeholder like `gen`) raises an error listing the actual
        # tool function names in this category, so the model retries correctly
        # instead of guessing the same fake name again.
        task = next((b.task_type for b in funcs.values()), module)
        mod.__getattr__ = _make_missing_tool_attr(module, task, sorted(funcs))
        extra[f"stimma.tools.{module}"] = mod
        setattr(tools_pkg, module, mod)

    tools_pkg.__getattr__ = _make_missing_category_attr(sorted(manifest.by_module))
    extra["stimma.tools"] = tools_pkg
    return extra


def _make_missing_tool_attr(module: str, task_type: str, available: list[str]):
    def __getattr__(name: str):
        if name.startswith("_"):  # let import machinery probe dunders normally
            raise AttributeError(name)
        shown = ", ".join(available[:40])
        more = "" if len(available) <= 40 else f" (+{len(available) - 40} more)"
        raise ImportError(
            f"'{name}' is not a tool in stimma.tools.{module}. Tool functions are "
            f"named after the actual tool, not a generic placeholder — read "
            f".stimma/tools/{task_type}/ and import an exact name. "
            f"Available in this category: {shown}{more}"
        )

    return __getattr__


def _make_missing_category_attr(modules: list[str]):
    def __getattr__(name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        raise ImportError(
            f"'{name}' is not a task category. Categories (import as "
            f"stimma.tools.<category>): {', '.join(modules)}. Browse .stimma/tools/."
        )

    return __getattr__


def _make_bound_tool(sdk, binding: ToolBinding):
    async def _bound(**kwargs):
        return await sdk._dispatch_tool(
            binding.tool_id, _task_type=binding.task_type, **kwargs
        )

    _bound.__name__ = binding.func_name
    _bound.__qualname__ = f"stimma.tools.{binding.module}.{binding.func_name}"
    _bound.__doc__ = f'{binding.tool_id} ({binding.task_type})'
    return _bound


def tool_import_names(manifest: Manifest) -> dict[str, set[str]]:
    """Map module -> {func names}, for the linter to validate tool imports."""
    return {m: set(funcs) for m, funcs in manifest.by_module.items()}
