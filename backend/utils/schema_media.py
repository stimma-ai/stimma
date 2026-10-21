"""Media fields nested inside structured tool parameters (STP `x-media`).

Top-level media pickers (`x-control: image_picker`, …) are handled where they
always were. This module finds media *leaves* declared with `x-media` at any
depth — e.g. `keyframes[].media` — so every media path (provider upload,
library-id resolution, lineage, agent and MCP calls) treats them the same way.
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional, Tuple, Union

Path = Tuple[Union[str, int], ...]

# Top-level picker controls and the media kind each one carries.
PICKER_KINDS: Dict[str, Tuple[str, ...]] = {
    "image_picker": ("image",),
    "video_frame_picker": ("image",),
    "video_picker": ("video",),
    "audio_picker": ("audio",),
    "mask_editor": ("image",),
}


def media_kinds(prop: Any) -> Tuple[str, ...]:
    """Media kinds a property carries: from `x-media`, else from a picker `x-control`."""
    if not isinstance(prop, dict):
        return ()
    declared = prop.get("x-media")
    if isinstance(declared, str):
        return (declared,)
    if isinstance(declared, list):
        return tuple(k for k in declared if isinstance(k, str))
    return PICKER_KINDS.get(prop.get("x-control") or "", ())


def _is_leaf(prop: Any) -> bool:
    return isinstance(prop, dict) and prop.get("x-media") is not None


def iter_media_leaves(params: Dict[str, Any], schema: Optional[Dict[str, Any]]) -> Iterator[Tuple[Path, Any, Dict[str, Any]]]:
    """Yield `(path, value, leaf_schema)` for every `x-media` value present in `params`."""

    def walk(prop: Any, value: Any, path: Path):
        if not isinstance(prop, dict) or value is None:
            return
        if _is_leaf(prop):
            if isinstance(value, list):
                for i, v in enumerate(value):
                    if v is not None:
                        yield path + (i,), v, prop
            else:
                yield path, value, prop
            return
        if isinstance(value, list) and isinstance(prop.get("items"), dict):
            for i, v in enumerate(value):
                yield from walk(prop["items"], v, path + (i,))
        elif isinstance(value, dict) and isinstance(prop.get("properties"), dict):
            for key, sub in prop["properties"].items():
                if key in value:
                    yield from walk(sub, value[key], path + (key,))

    props = (schema or {}).get("properties") or {}
    if not isinstance(props, dict) or not isinstance(params, dict):
        return
    for name, prop in props.items():
        if name in params:
            yield from walk(prop, params[name], (name,))


def has_media_leaves(schema: Optional[Dict[str, Any]]) -> bool:
    def scan(prop: Any) -> bool:
        if not isinstance(prop, dict):
            return False
        if _is_leaf(prop):
            return True
        if scan(prop.get("items")):
            return True
        return any(scan(p) for p in (prop.get("properties") or {}).values())

    return any(scan(p) for p in ((schema or {}).get("properties") or {}).values())


def _copy_path(params: Dict[str, Any], path: Path) -> Any:
    """Copy containers along `path` so writes never mutate the caller's params."""
    node = params
    for key in path[:-1]:
        child = node[key]
        child = list(child) if isinstance(child, list) else dict(child)
        node[key] = child
        node = child
    return node


def set_at(params: Dict[str, Any], path: Path, value: Any) -> None:
    _copy_path(params, path)[path[-1]] = value


async def map_media_leaves(
    params: Dict[str, Any],
    schema: Optional[Dict[str, Any]],
    fn: Callable[[Any, Dict[str, Any], Path], Union[Any, Awaitable[Any]]],
) -> Dict[str, Any]:
    """Return a copy of `params` with `fn(value, leaf_schema, path)` applied to every media leaf."""
    out = dict(params)
    for path, value, leaf in list(iter_media_leaves(params, schema)):
        result = fn(value, leaf, path)
        if inspect.isawaitable(result):
            result = await result
        set_at(out, path, result)
    return out


def media_param_names(schema: Optional[Dict[str, Any]]) -> List[str]:
    """Top-level parameter names that contain `x-media` leaves."""
    names = []
    for name, prop in ((schema or {}).get("properties") or {}).items():
        if has_media_leaves({"properties": {name: prop}}):
            names.append(name)
    return names


def lineage_id_key(param_name: str) -> str:
    """Parameter carrying library ids for a structured media param, positional by leaf order."""
    return f"{param_name}_media_ids"
