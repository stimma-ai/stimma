"""The recipe SDK, registry and runner.

A recipe is deterministic code: assets with declared roles plus parameters
in, a file tree out. It runs in-process as trusted code (the same trust as
stimpack ``lib/`` modules), never calls a model, a tool or the network, and
never asks a question. Judgment enters as parameters, which the manifest
records so a rebuild replays the run exactly.

Implementors write::

    from packages.recipes import recipe, Input, Param, Build

    @recipe(id="my-thing", version=1, display_name="My thing",
            description="...", inputs=[Input("master", kind="image")],
            params=[Param("size", type="integer", default=512)])
    def build(b: Build) -> None:
        img = b.image("master")
        b.derive("out/" + b.name(ext="png", slug=b.slug), png(img), source="master")

Built-in recipes live in ``packages/builtin``; stimpacks ship theirs in a
``recipes/`` directory (one module per file).
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import io
import json
import platform
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol

from PIL import Image

from core.logging import get_logger
from packages.manifest import check_bundle_path, sha256_bytes, slugify
from packages.naming import Naming, NamingError, expand_name, parse_naming

log = get_logger(__name__)

# Bump when the runner itself changes output for identical inputs (e.g. a PNG
# encoder default). Part of every run's cache key.
RECIPE_RUNTIME_VERSION = 1

RASTER_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VECTOR_EXTENSIONS = {".svg"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}

INPUT_KINDS = ("image", "raster", "vector", "video", "file")
PARAM_TYPES = ("string", "integer", "number", "boolean", "color", "choice", "multi", "naming", "renames")

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class RecipeError(ValueError):
    """A recipe cannot run: bad inputs, bad params, or the recipe declined."""


# Declarations ---------------------------------------------------------------

@dataclass
class Input:
    """One declared input role.

    ``kind``: ``image`` (raster or vector), ``raster``, ``vector``, ``video``,
    ``file``. A recipe asks for pixels with ``await b.image(role, size)``; how
    a vector becomes pixels at that size is the framework's problem, not the
    recipe's, so nothing about rendering is declared here.
    """
    name: str
    kind: str = "image"
    description: str = ""
    required: bool = True
    square: bool = False
    min_size: Optional[int] = None
    alpha: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.kind not in INPUT_KINDS:
            raise ValueError(f"Input {self.name!r}: kind must be one of {INPUT_KINDS}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "required": self.required,
            "square": self.square,
            "min_size": self.min_size,
            "alpha": self.alpha,
        }


@dataclass
class Param:
    name: str
    type: str = "string"
    description: str = ""
    default: Any = None
    options: tuple[str, ...] = ()
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    # naming only
    fields: tuple[str, ...] = ()
    case: str = "kebab"

    def __post_init__(self) -> None:
        if self.type not in PARAM_TYPES:
            raise ValueError(f"Param {self.name!r}: type must be one of {PARAM_TYPES}")
        self.options = tuple(self.options)
        self.fields = tuple(self.fields)
        if self.type == "naming" and not self.fields:
            raise ValueError(f"Param {self.name!r}: naming params must declare fields")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "default": self.default,
        }
        if self.options:
            d["options"] = list(self.options)
        if self.minimum is not None:
            d["minimum"] = self.minimum
        if self.maximum is not None:
            d["maximum"] = self.maximum
        if self.type == "naming":
            d["fields"] = list(self.fields)
            d["case"] = self.case
        return d


@dataclass
class RecipeSpec:
    id: str
    version: int
    display_name: str
    description: str
    inputs: list[Input]
    params: list[Param]
    build: Callable[["Build"], None]
    source: str = "builtin"  # "builtin" or the stimpack name
    module_path: Optional[str] = None

    def input(self, role: str) -> Optional[Input]:
        return next((i for i in self.inputs if i.name == role), None)

    def param(self, name: str) -> Optional[Param]:
        return next((p for p in self.params if p.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "source": self.source,
            "inputs": [i.to_dict() for i in self.inputs],
            "params": [p.to_dict() for p in self.params],
        }


def recipe(
    *,
    id: str,
    version: int,
    display_name: str,
    description: str,
    inputs: Iterable[Input] = (),
    params: Iterable[Param] = (),
):
    """Declare a recipe. The decorated function is the ``build`` step."""
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", id):
        raise ValueError(f"recipe id must be kebab-case: {id!r}")

    def decorate(fn: Callable[["Build"], None]) -> Callable[["Build"], None]:
        spec = RecipeSpec(
            id=id,
            version=int(version),
            display_name=display_name,
            description=description,
            inputs=list(inputs),
            params=list(params),
            build=fn,
        )
        names = [i.name for i in spec.inputs]
        if len(names) != len(set(names)):
            raise ValueError(f"recipe {id!r}: duplicate input names")
        pnames = [p.name for p in spec.params]
        if len(pnames) != len(set(pnames)):
            raise ValueError(f"recipe {id!r}: duplicate param names")
        fn._stimma_recipe = spec  # type: ignore[attr-defined]
        return fn

    return decorate


# Resolved inputs ------------------------------------------------------------

@dataclass
class ResolvedInput:
    """One input as the runner sees it: a file on disk plus facts about it."""
    role: str
    path: Path
    hash: str
    kind: str  # raster | vector | video | file
    width: int = 0
    height: int = 0
    has_alpha: Optional[bool] = None
    member_id: Optional[str] = None


def classify_file(path: Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in RASTER_EXTENSIONS:
        return "raster"
    if ext in VECTOR_EXTENSIONS:
        return "vector"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "file"


def describe_file(path: Path) -> dict[str, Any]:
    """Facts the validator needs: nominal dimensions and alpha.

    Vectors report their intrinsic size (or viewBox) so shape constraints like
    ``square`` apply to them the same way they apply to rasters. They have no
    pixel ceiling, so ``min_size`` does not constrain them.
    """
    kind = classify_file(path)
    facts: dict[str, Any] = {"kind": kind, "width": 0, "height": 0, "has_alpha": None}
    if kind == "raster":
        try:
            with Image.open(path) as img:
                facts["width"], facts["height"] = img.size
                facts["has_alpha"] = img.mode in ("RGBA", "LA", "PA") or (
                    img.mode == "P" and "transparency" in img.info
                )
        except Exception as exc:  # noqa: BLE001
            raise RecipeError(f"{path.name} is not a readable image: {exc}") from exc
    elif kind == "vector":
        try:
            from utils.svg_doc import intrinsic_size, parse_svg, read_svg_file

            facts["width"], facts["height"] = intrinsic_size(parse_svg(read_svg_file(path)))
        except Exception as exc:  # noqa: BLE001
            raise RecipeError(f"{path.name} is not a readable SVG: {exc}") from exc
        # A vector paints only what it draws; anything it leaves is transparent.
        facts["has_alpha"] = True
    return facts


def validate_inputs(spec: RecipeSpec, inputs: dict[str, ResolvedInput]) -> list[str]:
    """Check resolved inputs against the recipe's declarations. Returns problems."""
    problems: list[str] = []
    for decl in spec.inputs:
        given = inputs.get(decl.name)
        if given is None:
            if decl.required:
                problems.append(f"input {decl.name!r} is required: {decl.description or decl.kind}")
            continue
        if decl.kind == "image" and given.kind not in ("raster", "vector"):
            problems.append(f"input {decl.name!r} must be an image (PNG, JPEG, WebP or SVG)")
            continue
        if decl.kind in ("raster", "vector", "video") and given.kind != decl.kind:
            problems.append(f"input {decl.name!r} must be a {decl.kind} file")
            continue
        # Shape applies to every image, whatever it is made of.
        if given.kind in ("raster", "vector"):
            if decl.square and given.width != given.height:
                problems.append(
                    f"input {decl.name!r} must be square; got {given.width}x{given.height}"
                )
        if given.kind == "raster":
            # Only a raster has a pixel ceiling; a vector renders at any size.
            if decl.min_size and min(given.width, given.height) < decl.min_size:
                problems.append(
                    f"input {decl.name!r} must be at least {decl.min_size}px; got {given.width}x{given.height}"
                )
            if decl.alpha is True and not given.has_alpha:
                problems.append(f"input {decl.name!r} must have a transparent background")
            if decl.alpha is False and given.has_alpha:
                problems.append(f"input {decl.name!r} must be opaque (no alpha channel)")
    unknown = set(inputs) - {i.name for i in spec.inputs}
    if unknown:
        problems.append(f"unknown input role(s): {', '.join(sorted(unknown))}")
    return problems


def validate_params(spec: RecipeSpec, params: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Apply defaults and coerce/validate. Returns the canonical params dict."""
    given = dict(params or {})
    out: dict[str, Any] = {}
    for decl in spec.params:
        value = given.pop(decl.name, decl.default)
        try:
            out[decl.name] = _coerce_param(decl, value)
        except (TypeError, ValueError, NamingError) as exc:
            raise RecipeError(f"param {decl.name!r}: {exc}") from exc
    if given:
        raise RecipeError(f"unknown param(s): {', '.join(sorted(given))}")
    return out


def _coerce_param(decl: Param, value: Any) -> Any:
    t = decl.type
    if value is None:
        if t == "naming":
            return parse_naming(None, fields=decl.fields, default_template=str(decl.default or ""), default_case=decl.case).to_dict()
        if t == "renames":
            return {}
        if t == "multi":
            return []
        return None
    if t == "string":
        return str(value)
    if t == "integer":
        v = int(value)
        _check_range(decl, v)
        return v
    if t == "number":
        v = float(value)
        _check_range(decl, v)
        return v
    if t == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if t == "color":
        s = str(value).strip()
        if not _COLOR_RE.match(s):
            raise ValueError(f"expected a hex color like #1A2B3C, got {s!r}")
        return s.upper()
    if t == "choice":
        s = str(value)
        if decl.options and s not in decl.options:
            raise ValueError(f"must be one of {', '.join(decl.options)}; got {s!r}")
        return s
    if t == "multi":
        if isinstance(value, str):
            values = [v.strip() for v in value.split(",") if v.strip()]
        else:
            values = [str(v) for v in value]
        bad = [v for v in values if decl.options and v not in decl.options]
        if bad:
            raise ValueError(f"unknown option(s) {', '.join(bad)}; allowed: {', '.join(decl.options)}")
        # Canonical order: declaration order, deduplicated. Order must not leak
        # into the cache key.
        if decl.options:
            return [o for o in decl.options if o in values]
        return sorted(set(values))
    if t == "naming":
        return parse_naming(value, fields=decl.fields, default_template=str(decl.default or ""), default_case=decl.case).to_dict()
    if t == "renames":
        if not isinstance(value, dict):
            raise ValueError("renames must be an object of {default path: new name}")
        out = {}
        for k, v in value.items():
            check_bundle_path(str(k))
            if "/" in str(v) or not str(v):
                raise ValueError(f"rename target {v!r} must be a bare filename")
            out[str(k)] = str(v)
        return out
    raise ValueError(f"unsupported param type {t!r}")


def _check_range(decl: Param, v: float) -> None:
    if decl.minimum is not None and v < decl.minimum:
        raise ValueError(f"must be >= {decl.minimum}")
    if decl.maximum is not None and v > decl.maximum:
        raise ValueError(f"must be <= {decl.maximum}")


# Build context --------------------------------------------------------------

class _Params:
    """Attribute and item access over the canonical params dict."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __getitem__(self, name: str) -> Any:
        return self._data[name]

    def get(self, name: str, default: Any = None) -> Any:
        return self._data.get(name, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)


class VectorRenderer(Protocol):
    """Renders a vector input to PNG bytes at a given longest-side size.

    Injected by whoever runs the recipe. That it is currently satisfied by the
    app's browser engine is an implementation detail: recipes ask for pixels at
    a size and never learn where they came from.
    """

    async def __call__(self, given: "ResolvedInput", size: int) -> bytes: ...


@dataclass
class WrittenFile:
    path: str
    hash: str
    size: int
    source: Optional[str] = None
    fixed: bool = False


class Build:
    """What a recipe's ``build`` receives. Writes land in ``out_dir``."""

    def __init__(
        self,
        spec: RecipeSpec,
        inputs: dict[str, ResolvedInput],
        params: dict[str, Any],
        out_dir: Path,
        *,
        slug: str = "package",
        renderer: Optional["VectorRenderer"] = None,
    ):
        self.spec = spec
        self._inputs = inputs
        self.params = _Params(params)
        self.out_dir = Path(out_dir)
        self.slug = slug
        self._renderer = renderer
        self.files: list[WrittenFile] = []
        self._naming: Optional[Naming] = None
        naming_decl = next((p for p in spec.params if p.type == "naming"), None)
        if naming_decl is not None:
            value = params.get(naming_decl.name)
            self._naming = parse_naming(
                value, fields=naming_decl.fields,
                default_template=str(naming_decl.default or ""), default_case=naming_decl.case,
            )
        renames_decl = next((p for p in spec.params if p.type == "renames"), None)
        self._renames: dict[str, str] = dict(params.get(renames_decl.name) or {}) if renames_decl else {}

    # inputs
    def has(self, role: str) -> bool:
        return role in self._inputs

    def path(self, role: str) -> Path:
        try:
            return self._inputs[role].path
        except KeyError:
            raise RecipeError(f"input {role!r} was not provided") from None

    def input(self, role: str) -> ResolvedInput:
        try:
            return self._inputs[role]
        except KeyError:
            raise RecipeError(f"input {role!r} was not provided") from None

    def text(self, role: str) -> str:
        return self.path(role).read_text(encoding="utf-8")

    async def image(self, role: str, size: Optional[int] = None) -> Image.Image:
        """Pixels for ``role``, as good as they can be at ``size``. Always RGBA.

        A vector is rendered natively at ``size`` — every size is its own
        render, which is the whole reason to author artwork as vector, so a
        16px icon is drawn at 16px rather than resampled from a large one.
        A raster has no more detail than it has, so it comes back as-is and
        the recipe resamples it.

        ``size`` is the target longest side. Omit it only when the role's own
        size is what you want.
        """
        given = self.input(role)
        if given.kind != "vector":
            img = Image.open(given.path)
            img.load()
            return img.convert("RGBA")
        if size is None:
            size = max(given.width, given.height) or 1024
        if self._renderer is None:
            raise RecipeError(
                f"input {role!r} is a vector and this run has no renderer available"
            )
        png = await self._renderer(given, int(size))
        img = Image.open(io.BytesIO(png))
        img.load()
        return img.convert("RGBA")

    # outputs
    def name(self, *, ext: str, **fields: Any) -> str:
        """Expand the recipe's naming template for one free name."""
        if self._naming is None:
            raise RecipeError(f"recipe {self.spec.id!r} declares no naming param but called b.name()")
        return expand_name(self._naming, ext=ext, **fields)

    def file(self, rel_path: str, data: bytes | str, *, fixed: bool = True) -> str:
        """Write one file into the run's subtree. Returns the final relative path."""
        return self._write(rel_path, data, source=None, fixed=fixed)

    def derive(self, rel_path: str, data: bytes | str, *, source: str, fixed: bool = False) -> str:
        """Write a file derived from input ``source`` (records the lineage edge)."""
        if source not in self._inputs:
            raise RecipeError(f"derive(): unknown source role {source!r}")
        return self._write(rel_path, data, source=source, fixed=fixed)

    def _write(self, rel_path: str, data: bytes | str, *, source: Optional[str], fixed: bool) -> str:
        rel = check_bundle_path(rel_path)
        if rel in self._renames and not fixed:
            parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
            rel = check_bundle_path(f"{parent}/{self._renames[rel]}" if parent else self._renames[rel])
        if any(f.path == rel for f in self.files):
            raise RecipeError(f"recipe wrote {rel!r} twice (naming template collision?)")
        if isinstance(data, str):
            data = data.encode("utf-8")
        target = self.out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.files.append(WrittenFile(path=rel, hash=sha256_bytes(data), size=len(data), source=source, fixed=fixed))
        return rel

    def fail(self, message: str) -> None:
        raise RecipeError(message)


# Image helpers recipes share --------------------------------------------------

def png_bytes(img: Image.Image, *, optimize: bool = True) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=optimize)
    return buf.getvalue()


def fit_square(img: Image.Image, size: int, *, safe_area: float = 1.0, background: Optional[str] = None) -> Image.Image:
    """Resize into a size x size canvas, artwork inset by ``safe_area``."""
    img = img.convert("RGBA")
    inner = max(1, int(round(size * safe_area)))
    art = img.copy()
    art.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(art, ((size - art.width) // 2, (size - art.height) // 2), art)
    if background:
        flat = Image.new("RGBA", (size, size), background)
        flat.alpha_composite(canvas)
        return flat.convert("RGB")
    return canvas


def flatten(img: Image.Image, background: str = "#FFFFFF") -> Image.Image:
    flat = Image.new("RGBA", img.size, background)
    flat.alpha_composite(img.convert("RGBA"))
    return flat.convert("RGB")


# Registry -------------------------------------------------------------------

_BUILTIN: dict[str, RecipeSpec] = {}


def register_builtin(spec: RecipeSpec) -> None:
    _BUILTIN[spec.id] = spec


def _specs_in_module(module) -> list[RecipeSpec]:
    specs = []
    for value in vars(module).values():
        spec = getattr(value, "_stimma_recipe", None)
        if isinstance(spec, RecipeSpec):
            specs.append(spec)
    return specs


def _ensure_builtins_loaded() -> None:
    if _BUILTIN:
        return
    from packages import builtin  # noqa: F401  (registers on import)


def load_recipe_module(path: Path, *, source: str) -> list[RecipeSpec]:
    """Import one recipe module from disk and return the specs it declares."""
    path = Path(path)
    module_name = f"stimma_recipe__{slugify(source)}__{slugify(path.stem)}".replace("-", "_")
    spec_obj = importlib.util.spec_from_file_location(module_name, path)
    if spec_obj is None or spec_obj.loader is None:
        return []
    module = importlib.util.module_from_spec(spec_obj)
    sys.modules[module_name] = module
    try:
        spec_obj.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        log.warning(f"recipe module {path} failed to import: {exc}")
        sys.modules.pop(module_name, None)
        return []
    specs = _specs_in_module(module)
    for s in specs:
        s.source = source
        s.module_path = str(path)
    return specs


def stimpack_recipe_specs(profile_id: Optional[str] = None) -> list[RecipeSpec]:
    """Recipes shipped by installed stimpacks (``<pack>/recipes/*.py``)."""
    try:
        from agent.v2.stimpacks import list_stimpack_recipe_files
    except Exception:  # noqa: BLE001
        return []
    specs: list[RecipeSpec] = []
    for pack_name, path in list_stimpack_recipe_files(profile_id=profile_id):
        specs.extend(load_recipe_module(path, source=pack_name))
    return specs


def list_recipes(profile_id: Optional[str] = None) -> list[RecipeSpec]:
    """Every recipe available to this profile. Built-ins win on id collision."""
    _ensure_builtins_loaded()
    out: dict[str, RecipeSpec] = {}
    for spec in stimpack_recipe_specs(profile_id):
        out.setdefault(spec.id, spec)
    out.update(_BUILTIN)
    return sorted(out.values(), key=lambda s: s.id)


def get_recipe(recipe_id: str, profile_id: Optional[str] = None) -> Optional[RecipeSpec]:
    _ensure_builtins_loaded()
    if recipe_id in _BUILTIN:
        return _BUILTIN[recipe_id]
    for spec in stimpack_recipe_specs(profile_id):
        if spec.id == recipe_id:
            return spec
    return None


# Runner ---------------------------------------------------------------------

def runtime_fingerprint() -> str:
    return f"py{sys.version_info.major}.{sys.version_info.minor}-pil{Image.__version__}-rt{RECIPE_RUNTIME_VERSION}-{platform.system().lower()}"


def cache_key(spec: RecipeSpec, inputs: dict[str, ResolvedInput], params: dict[str, Any]) -> str:
    material = {
        "recipe": spec.id,
        "version": spec.version,
        "source": spec.source,
        "inputs": {role: inp.hash for role, inp in sorted(inputs.items())},
        "params": params,
        "runtime": runtime_fingerprint(),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass
class RunResult:
    files: list[WrittenFile]
    params: dict[str, Any]
    cache_key: str


async def run_recipe(
    spec: RecipeSpec,
    inputs: dict[str, ResolvedInput],
    params: Optional[dict[str, Any]],
    out_dir: Path,
    *,
    slug: str = "package",
    renderer: Optional[VectorRenderer] = None,
) -> RunResult:
    """Validate, then build into ``out_dir``.

    ``build`` may be sync or async; an async one can await ``b.image`` for
    natively rendered vector artwork. Determinism is unchanged by that: the
    same inputs and params still produce the same bytes.
    """
    problems = validate_inputs(spec, inputs)
    if problems:
        raise RecipeError("; ".join(problems))
    canonical = validate_params(spec, params)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    b = Build(spec, inputs, canonical, out_dir, slug=slug, renderer=renderer)
    try:
        outcome = spec.build(b)
        if inspect.isawaitable(outcome):
            await outcome
    except RecipeError:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(out_dir, ignore_errors=True)
        raise RecipeError(f"recipe {spec.id!r} failed: {exc}") from exc
    if not b.files:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise RecipeError(f"recipe {spec.id!r} produced no files")
    return RunResult(files=b.files, params=canonical, cache_key=cache_key(spec, inputs, canonical))


async def check_determinism(
    spec: RecipeSpec,
    inputs: dict[str, ResolvedInput],
    params: Optional[dict[str, Any]],
    *,
    renderer: Optional[VectorRenderer] = None,
) -> list[str]:
    """Build twice; return the paths whose bytes differed (empty means deterministic).

    Also reports files marked ``fixed`` whose names changed under a different
    naming template, which a platform-dictated name must never do.
    """
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        ra = await run_recipe(spec, inputs, params, Path(a), renderer=renderer)
        rb = await run_recipe(spec, inputs, params, Path(b), renderer=renderer)
        ha = {f.path: f.hash for f in ra.files}
        hb = {f.path: f.hash for f in rb.files}
        for path in sorted(set(ha) | set(hb)):
            if ha.get(path) != hb.get(path):
                problems.append(path)
    naming = next((p for p in spec.params if p.type == "naming"), None)
    if naming is not None:
        alt = dict(params or {})
        alt[naming.name] = {"template": "x-" + "-".join("{%s}" % f for f in naming.fields), "case": "snake"}
        with tempfile.TemporaryDirectory() as c:
            rc = await run_recipe(spec, inputs, alt, Path(c), renderer=renderer)
            fixed_a = {f.path for f in ra.files if f.fixed}
            fixed_c = {f.path for f in rc.files if f.fixed}
            for path in sorted(fixed_a ^ fixed_c):
                problems.append(f"fixed name changed under naming template: {path}")
    return problems
