"""Shape taxonomy and static analysis helpers for cross-equation validation.

The DSL already rejects a handful of misuses at graph-build time
(``NodeUsageError``, unknown tool ids, wrong output type strings). That layer
catches surface-level mistakes but doesn't track what shape each NodeRef
will resolve to — so a recipe whose upstream ``llm(response_format=…)``
returns a dict can still wire the node straight into ``hitl.select``
(which needs a list) and the error surfaces at evaluation time.

This module adds a small shape vocabulary that every primitive attaches to
its returned NodeRef, plus the helpers two v1 validators need:

- ``code()`` subscript-key checks — if an upstream is ``Dict(closed=True,
  fields={…})``, we parse pure-expression sources and reject
  ``data['missing_key']`` at build time.
- Tool-input conformance — the tool's JSON-schema ``parameter_schema`` is
  compared against the shapes bound to each tool param (required missing,
  scalar-vs-array mismatch, literal-type mismatch).

Design: see docs/RECIPES_SHAPE_VALIDATION.md. The taxonomy is intentionally
small. ``Unknown`` is the escape hatch — we never raise on an Unknown
mismatch, so programs only break if we *positively* detect a wrong handoff.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from typing import Any, Optional


log = logging.getLogger(__name__)


# ----- Shape taxonomy ------------------------------------------------------


# Scalar kinds we care about distinguishing. ``media`` is an int media-id by
# convention; ``json`` is "an arbitrary JSON-able value with unknown
# internal structure" (distinct from a Dict whose keys we know). ``any`` is
# the lowest-precision scalar — matches anything.
_SCALAR_KINDS = frozenset({
    "str", "int", "float", "bool", "media", "json", "any",
})


@dataclass(frozen=True)
class Scalar:
    kind: str

    def __post_init__(self) -> None:
        if self.kind not in _SCALAR_KINDS:
            # Don't raise — fall back to 'any' so upstream typos become
            # permissive rather than breaking the build.
            object.__setattr__(self, "kind", "any")

    def describe(self) -> str:
        return self.kind


@dataclass(frozen=True)
class ListShape:
    element: "Shape"

    def describe(self) -> str:
        return f"list[{describe(self.element)}]"


@dataclass(frozen=True)
class DictShape:
    # Known fields: name → shape. Empty when schema was undeclared.
    fields: tuple[tuple[str, "Shape"], ...] = ()
    # ``closed`` means these are all the fields (declared-by-schema). Open
    # dicts have at least these fields but may have more.
    closed: bool = False

    @property
    def field_map(self) -> dict[str, "Shape"]:
        return {name: shape for name, shape in self.fields}

    def describe(self) -> str:
        inner = ", ".join(f"{n}: {describe(s)}" for n, s in self.fields)
        body = f"{{{inner}}}" if self.fields else "{}"
        return f"dict{body}" if self.closed else f"dict{body}(open)"


@dataclass(frozen=True)
class TupleShape:
    """Fixed-arity heterogeneous record. ``zip_nodes`` emits these — pair[0],
    pair[1] etc. read distinct element shapes from the matching index.
    """
    elements: tuple["Shape", ...] = ()

    def describe(self) -> str:
        inner = ", ".join(describe(e) for e in self.elements)
        return f"tuple[{inner}]"


@dataclass(frozen=True)
class Unknown:
    def describe(self) -> str:
        return "unknown"


Shape = object  # structural alias — any of the dataclasses above


UNKNOWN: Unknown = Unknown()


def describe(shape: Optional[Shape]) -> str:
    if shape is None:
        return "unknown"
    try:
        return shape.describe()  # type: ignore[attr-defined]
    except AttributeError:
        return repr(shape)


# ----- Type-string parsing -------------------------------------------------


# Maps the DSL's type vocabulary (used in ``input(type=…)``, ``output(type=…)``,
# simplified response_format schemas to
# scalar kinds. Anything not here falls through to ``Unknown``.
_SCALAR_TYPE_MAP = {
    "str": "str",
    "string": "str",
    "text": "str",
    "prompt": "str",
    "markdown": "str",
    "int": "int",
    "integer": "int",
    "float": "float",
    "number": "float",
    "bool": "bool",
    "boolean": "bool",
    "media": "media",
    "json": "json",
    "dict": "json",
    "any": "any",
    "enum": "str",
}


def shape_from_type_string(type_str: Optional[str]) -> Shape:
    """Map a DSL type string (``"list[str]"``, ``"media"``) into a Shape.

    Permissive — unknown types become ``Unknown`` so nothing breaks when
    the type vocabulary grows.
    """
    if not isinstance(type_str, str) or not type_str.strip():
        return UNKNOWN
    s = type_str.strip().lower()
    if s.startswith("list[") and s.endswith("]"):
        inner = s[5:-1].strip()
        return ListShape(element=shape_from_type_string(inner))
    kind = _SCALAR_TYPE_MAP.get(s)
    if kind is None:
        return UNKNOWN
    return Scalar(kind=kind)


def web_search_result_shape(kind: str) -> Shape:
    """Shape for one element of a ``web_search(kind=...)`` result list.

    Image results expose ``title``, ``image_url``, ``source``, ``width``,
    ``height``, and ``media``. ``media`` is a URL media descriptor: it is
    previewable by the UI, but it is not a library asset until it is selected
    or otherwise promoted by the runtime. Text results expose ``title``,
    ``url``, ``snippet``. Closed so subscript misses (``r['source_url']``
    instead of ``r['source']``) surface at build time.
    """
    if kind == "images":
        return DictShape(
            fields=(
                ("title", Scalar(kind="str")),
                ("image_url", Scalar(kind="str")),
                ("source", Scalar(kind="str")),
                ("width", Scalar(kind="int")),
                ("height", Scalar(kind="int")),
                (
                    "media",
                    DictShape(
                        fields=(
                            ("type", Scalar(kind="str")),
                            ("url", Scalar(kind="str")),
                            ("mime_type", Scalar(kind="str")),
                            ("title", Scalar(kind="str")),
                            ("source", Scalar(kind="str")),
                        ),
                        closed=True,
                    ),
                ),
            ),
            closed=True,
        )
    return DictShape(
        fields=(
            ("title", Scalar(kind="str")),
            ("url", Scalar(kind="str")),
            ("snippet", Scalar(kind="str")),
        ),
        closed=True,
    )


def shape_from_response_format(response_format: Any) -> Shape:
    """Map an ``llm(response_format=…)`` spec into a Shape.

    Accepts two shapes the DSL documents / uses in practice:

    - ``{"type": "json", "schema": {field: type_string}}`` — the simplified
      DSL form (each field value is a DSL type string).
    - ``{"type": "json", "schema": {"type": "object", "properties": {…}}}``
      — a JSON-schema-shaped block. We read ``properties``.

    Everything else (None, unrecognized shape) yields ``Unknown`` or an
    open ``Dict`` depending on whether we at least know it's a dict.
    """
    if response_format is None:
        return Scalar(kind="str")
    if not isinstance(response_format, dict):
        return UNKNOWN

    schema = response_format.get("schema")
    if schema is None:
        # Declared JSON response but no schema — we know it's a dict, not
        # its fields.
        return DictShape(fields=(), closed=False)

    # Case 1: schema is a JSON-schema-style block with 'properties'.
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        fields: list[tuple[str, Shape]] = []
        for name, prop in schema["properties"].items():
            if isinstance(prop, dict):
                fields.append((name, _shape_from_jsonschema_prop(prop)))
            elif isinstance(prop, str):
                fields.append((name, shape_from_type_string(prop)))
            else:
                fields.append((name, UNKNOWN))
        return DictShape(fields=tuple(fields), closed=True)

    # Case 2: schema is {field: type_string} directly.
    if isinstance(schema, dict):
        fields = []
        for name, type_str in schema.items():
            if isinstance(type_str, str):
                fields.append((name, shape_from_type_string(type_str)))
            elif isinstance(type_str, dict):
                fields.append((name, _shape_from_jsonschema_prop(type_str)))
            else:
                fields.append((name, UNKNOWN))
        return DictShape(fields=tuple(fields), closed=True)

    return UNKNOWN


def _shape_from_jsonschema_prop(prop: dict) -> Shape:
    """Turn a single JSON-schema ``properties.<name>`` block into a Shape."""
    t = prop.get("type")
    if t == "array":
        items = prop.get("items") or {}
        if isinstance(items, dict):
            return ListShape(element=_shape_from_jsonschema_prop(items))
        return ListShape(element=UNKNOWN)
    if t == "object":
        props = prop.get("properties") or {}
        if isinstance(props, dict):
            fields = tuple(
                (name, _shape_from_jsonschema_prop(p) if isinstance(p, dict) else UNKNOWN)
                for name, p in props.items()
            )
            return DictShape(fields=fields, closed=True)
        return DictShape(fields=(), closed=False)
    if isinstance(t, str):
        return shape_from_type_string(t)
    return UNKNOWN


def shape_from_code_output_type(output_type: str) -> Shape:
    """Derive the top-level shape for a ``code(output_type=…)`` return."""
    if output_type.startswith("list[") and output_type.endswith("]"):
        inner = output_type[5:-1].strip()
        return ListShape(element=shape_from_type_string(inner))
    return shape_from_type_string(output_type)


def shape_from_literal(value: Any) -> Shape:
    """Infer a shape from a plain Python literal (used for code() inputs)."""
    if isinstance(value, str):
        return Scalar(kind="str")
    if isinstance(value, bool):
        return Scalar(kind="bool")
    if isinstance(value, int):
        return Scalar(kind="int")
    if isinstance(value, float):
        return Scalar(kind="float")
    if isinstance(value, list):
        if not value:
            return ListShape(element=UNKNOWN)
        # Element shape = shape of first element; good enough for agent help.
        return ListShape(element=shape_from_literal(value[0]))
    if isinstance(value, tuple):
        return TupleShape(
            elements=tuple(shape_from_literal(v) for v in value),
        )
    if isinstance(value, dict):
        fields = tuple((str(k), shape_from_literal(v)) for k, v in value.items())
        return DictShape(fields=fields, closed=True)
    if value is None:
        return UNKNOWN
    return UNKNOWN


# ----- code() source static analysis ---------------------------------------


@dataclass
class BadSubscript:
    """Positively-detected bad subscript access in a code() source.

    ``binding_name`` is the code-inputs key (e.g., ``"data"``). ``key`` is
    the literal string used in ``data['key']`` / ``data["key"]``.
    ``available`` is the sorted list of keys the upstream dict declared.
    """
    binding_name: str
    key: str
    available: tuple[str, ...]


def find_bad_subscripts(
    source: str,
    binding_shapes: dict[str, Shape],
) -> list[BadSubscript]:
    """Scan a code() source for subscript accesses that miss a declared key.

    Only triggers when the binding's shape is ``DictShape(closed=True)`` —
    open dicts and Unknown shapes are never flagged. Non-expression sources
    are skipped (we don't walk arbitrary statements). Subscript keys that
    aren't string literals are skipped too (dynamic keys could be anything).

    This is intentionally conservative: false positives are worse than
    false negatives here, because the whole point is to flag the agent's
    obvious mistakes without blocking legitimate-but-opaque usage.
    """
    stripped = source.strip()
    if not stripped:
        return []
    try:
        tree = ast.parse(stripped, mode="eval")
    except SyntaxError:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

    out: list[BadSubscript] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        if not isinstance(node.value, ast.Name):
            continue
        binding = node.value.id
        shape = binding_shapes.get(binding)
        if not isinstance(shape, DictShape) or not shape.closed:
            continue
        slice_node = node.slice
        # Py3.9+: ast.Subscript.slice is the expr directly.
        key = _literal_string(slice_node)
        if key is None:
            continue
        if key not in shape.field_map:
            out.append(BadSubscript(
                binding_name=binding,
                key=key,
                available=tuple(sorted(shape.field_map.keys())),
            ))
    return out


def _literal_string(node: Any) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # Older ASTs wrap in ast.Index — tolerate it.
    index = getattr(ast, "Index", None)
    if index is not None and isinstance(node, index):
        return _literal_string(node.value)
    return None


# ----- Tool input-schema analysis -----------------------------------------


@dataclass
class ToolParamExpectation:
    """What a tool's parameter_schema says about a single parameter.

    ``kind`` is the coarse bucket we check against: ``scalar`` (one value,
    kind tracked in ``scalar_kind``), ``array`` (a list of things), or
    ``unknown`` (schema didn't tell us).
    """
    kind: str                          # 'scalar' | 'array' | 'unknown'
    scalar_kind: Optional[str] = None  # for kind='scalar'
    array_element_kind: Optional[str] = None  # for kind='array'
    required: bool = False


_MEDIA_ARRAY_CONTROLS = frozenset({"image_picker", "video_frame_picker"})


def parse_tool_param_expectations(
    parameter_schema: Optional[dict],
) -> dict[str, ToolParamExpectation]:
    """Extract per-param expectations from a tool's JSON-schema parameter_schema.

    Returns an empty dict if the schema is missing or malformed.
    """
    out: dict[str, ToolParamExpectation] = {}
    if not isinstance(parameter_schema, dict):
        return out
    props = parameter_schema.get("properties") or {}
    required = set(parameter_schema.get("required") or [])
    for name, prop in props.items():
        if not isinstance(prop, dict):
            continue
        t = prop.get("type")
        if t == "array":
            items = prop.get("items") or {}
            element_kind = _scalar_kind_from_jsonschema(items) if isinstance(items, dict) else None
            # Treat file-path arrays (image pickers etc.) as media arrays.
            if (
                isinstance(items, dict)
                and items.get("type") == "string"
                and items.get("format") == "file-path"
            ):
                element_kind = "media"
            # Many tool schemas declare array items as plain strings and convey
            # "this is a media picker" only via `x-control`. STP's wire layer
            # resolves media → path for these keys (input_images/input_videos)
            # at dispatch time, so a NodeRef of shape `media` is a valid input
            # even though the items type is string. Recognize the picker
            # controls so build-time validation doesn't reject it.
            if prop.get("x-control") in _MEDIA_ARRAY_CONTROLS:
                element_kind = "media"
            out[name] = ToolParamExpectation(
                kind="array",
                array_element_kind=element_kind,
                required=name in required,
            )
            continue
        scalar_kind = _scalar_kind_from_jsonschema(prop)
        # Single media input surfaces as {type: string, format: file-path}.
        if prop.get("type") == "string" and prop.get("format") == "file-path":
            scalar_kind = "media"
        if scalar_kind is None:
            out[name] = ToolParamExpectation(
                kind="unknown",
                required=name in required,
            )
        else:
            out[name] = ToolParamExpectation(
                kind="scalar",
                scalar_kind=scalar_kind,
                required=name in required,
            )
    return out


def _scalar_kind_from_jsonschema(prop: dict) -> Optional[str]:
    t = prop.get("type")
    if t == "string":
        return "str"
    if t == "integer":
        return "int"
    if t == "number":
        return "float"
    if t == "boolean":
        return "bool"
    return None


def shape_matches_scalar_kind(shape: Shape, kind: str) -> bool:
    """Does ``shape`` resolve to a single value of ``kind``?

    Returns True for permissive matches (Unknown, 'any') so we don't
    generate false positives on opaque upstreams.
    """
    if isinstance(shape, Unknown):
        return True
    if isinstance(shape, Scalar):
        if shape.kind in ("any", kind):
            return True
        # Media ids are ints at wire level; accept int↔media crossovers
        # defensively because some tools parameterize media as an id int.
        if kind == "media" and shape.kind == "int":
            return True
        if kind == "int" and shape.kind == "media":
            return True
        # JSON can be anything serializable.
        if shape.kind == "json":
            return True
        return False
    # DictShape / ListShape definitely aren't a scalar.
    return False


def shape_matches_array(shape: Shape, element_kind: Optional[str]) -> bool:
    """Does ``shape`` resolve to a list whose elements match ``element_kind``?"""
    if isinstance(shape, Unknown):
        return True
    if not isinstance(shape, ListShape):
        return False
    if element_kind is None:
        return True
    return shape_matches_scalar_kind(shape.element, element_kind)


__all__ = [
    "Scalar",
    "ListShape",
    "DictShape",
    "TupleShape",
    "Unknown",
    "UNKNOWN",
    "Shape",
    "describe",
    "shape_from_type_string",
    "shape_from_response_format",
    "shape_from_code_output_type",
    "web_search_result_shape",
    "shape_from_literal",
    "BadSubscript",
    "find_bad_subscripts",
    "ToolParamExpectation",
    "parse_tool_param_expectations",
    "shape_matches_scalar_kind",
    "shape_matches_array",
]
