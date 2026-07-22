"""Adapter between the vendored ComfyUI-Darkroom nodes and Stimma tools.

The vendored node classes (darkroom/vendor/nodes/*) each declare their
parameters via ComfyUI's ``INPUT_TYPES`` classmethod and process numpy
(B, H, W, C) float32 batches (see vendor/utils/image.py). This module:

- converts a node's INPUT_TYPES declaration into STP parameter-schema
  properties, so tool schemas track upstream parameter changes on re-vendor;
- runs an ordered pipeline of node stages over a PIL image, gated by
  toggle/mode parameters.

Each stage's parameters are exposed prefixed with ``<stage key>_`` to keep
multi-node tool schemas collision-free (every node declares ``strength``).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Stage:
    """One vendored node exposed as a gated section of a tool schema."""

    key: str                  # param prefix and stage identity
    label: str                # UI label for the section toggle / mode option
    module: str               # module name under the source package
    cls: str                  # node class name
    source: str = "vendor"    # "vendor" (darkroom.vendor.nodes) or "port" (darkroom.ports)
    exclude: Tuple[str, ...] = ()          # params not exposed in the schema
    fixed: Dict[str, Any] = field(default_factory=dict)  # forced param values
    # Gating — exactly one of:
    toggle: bool = False      # expose an "<key>_enabled" boolean, off by default
    mode_value: Optional[str] = None       # active when the tool's mode == value
    # (neither set: stage is always active)


_SOURCE_PACKAGES = {
    "vendor": "darkroom.vendor.nodes",
    "port": "darkroom.ports",
}


def _node_class(stage: Stage):
    mod = importlib.import_module(f"{_SOURCE_PACKAGES[stage.source]}.{stage.module}")
    return getattr(mod, stage.cls)


def _iter_input_params(stage: Stage):
    """Yield (name, comfy_type, opts) for a stage's exposed parameters."""
    input_types = _node_class(stage).INPUT_TYPES()
    for section in ("required", "optional"):
        for name, spec in (input_types.get(section) or {}).items():
            comfy_type = spec[0]
            opts = spec[1] if len(spec) > 1 else {}
            if comfy_type == "IMAGE":
                continue
            if name in stage.exclude or name in stage.fixed:
                continue
            yield name, comfy_type, opts


def _prop_from_comfy(comfy_type, opts: Dict[str, Any], label: str) -> Dict[str, Any]:
    prop: Dict[str, Any] = {"x-label": label}
    tooltip = opts.get("tooltip")
    if tooltip:
        prop["description"] = tooltip
    if isinstance(comfy_type, list):
        prop["type"] = "string"
        prop["enum"] = list(comfy_type)
        prop["default"] = opts.get("default", comfy_type[0])
        return prop
    if comfy_type == "BOOLEAN":
        prop["type"] = "boolean"
        prop["default"] = bool(opts.get("default", False))
        return prop
    prop["type"] = "integer" if comfy_type == "INT" else "number"
    if "default" in opts:
        prop["default"] = opts["default"]
    if opts.get("min") is not None:
        prop["minimum"] = opts["min"]
    if opts.get("max") is not None:
        prop["maximum"] = opts["max"]
    if opts.get("step") is not None:
        prop["x-step"] = opts["step"]
    return prop


def _label_from_name(name: str) -> str:
    return name.replace("_", " ").title().replace("Iso", "ISO")


def build_tool_schema(
    stages: List[Stage],
    mode_param: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an STP parameter_schema for a pipeline of stages.

    ``mode_param``, when given, is ``{"name", "label", "description",
    "options": {value: label}, "default"}`` — an enum rendered first; stages
    with ``mode_value`` set are shown only when it matches.
    """
    properties: Dict[str, Any] = {
        "input_images": {
            "type": "array",
            "items": {"type": "string", "format": "file-path"},
            "minItems": 1,
            "maxItems": 1,
            "x-control": "image_picker",
            "x-accept-media": ["image"],
            "description": "Image to process",
        },
    }

    if mode_param:
        properties[mode_param["name"]] = {
            "type": "string",
            "enum": list(mode_param["options"].keys()),
            "x-enum-labels": dict(mode_param["options"]),
            "default": mode_param["default"],
            "x-label": mode_param["label"],
            "description": mode_param.get("description", ""),
        }

    for stage in stages:
        hide_when: Optional[Dict[str, Any]] = None
        if stage.toggle:
            toggle_name = f"{stage.key}_enabled"
            properties[toggle_name] = {
                "type": "boolean",
                "default": False,
                "x-label": stage.label,
                "description": f"Enable the {stage.label} stage",
            }
            hide_when = {"param": toggle_name, "op": "falsy"}
        elif stage.mode_value is not None:
            hide_when = {
                "param": mode_param["name"],
                "op": "not_equals",
                "value": stage.mode_value,
            }

        for name, comfy_type, opts in _iter_input_params(stage):
            prop = _prop_from_comfy(comfy_type, opts, _label_from_name(name))
            if hide_when:
                prop["x-constraints"] = [{"when": hide_when, "effect": "hide"}]
            properties[f"{stage.key}_{name}"] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": ["input_images"],
    }


def _stage_active(stage: Stage, params: Dict[str, Any], mode_name: Optional[str]) -> bool:
    if stage.toggle:
        return bool(params.get(f"{stage.key}_enabled", False))
    if stage.mode_value is not None:
        return params.get(mode_name) == stage.mode_value
    return True


def _coerce(comfy_type, value):
    if isinstance(comfy_type, list):
        return str(value)
    if comfy_type == "BOOLEAN":
        return bool(value)
    if comfy_type == "INT":
        return int(round(float(value)))
    return float(value)


def run_pipeline(
    stages: List[Stage],
    params: Dict[str, Any],
    image: Image.Image,
    mode_name: Optional[str] = None,
) -> Image.Image:
    """Run the active stages over a PIL image and return the result."""
    arr = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    batch = arr[np.newaxis, ...]

    for stage in stages:
        if not _stage_active(stage, params, mode_name):
            continue
        node = _node_class(stage)()
        kwargs: Dict[str, Any] = dict(stage.fixed)
        input_types = _node_class(stage).INPUT_TYPES()
        for section in ("required", "optional"):
            for name, spec in (input_types.get(section) or {}).items():
                comfy_type = spec[0]
                if comfy_type == "IMAGE" or name in kwargs:
                    continue
                opts = spec[1] if len(spec) > 1 else {}
                value = params.get(f"{stage.key}_{name}", opts.get("default"))
                if value is not None:
                    kwargs[name] = _coerce(comfy_type, value)
        batch = node.execute(image=batch, **kwargs)[0]

    out = np.clip(np.asarray(batch[0], dtype=np.float32), 0.0, 1.0)
    return Image.fromarray((out * 255.0 + 0.5).astype(np.uint8), mode="RGB")
