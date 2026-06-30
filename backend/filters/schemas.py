"""Generate STP tool schemas from the built-in filter definitions.

Each filter def becomes one tool on the built-in lightweight provider
(task type "filter": image + params → image), so filters are ordinary
catalog tools — usable from the chat agent, flows, ToolView, and
post-processing chains alike.
"""

from typing import Any, Dict


def build_filter_parameter_schema(filter_def: Dict[str, Any]) -> Dict[str, Any]:
    """Build a parameter_schema (JSON Schema) for one filter definition."""
    # Which media types this filter can natively process. Filters currently
    # apply to both stills and (per-frame) video, so the default is both. A
    # future filter that only makes sense on one (e.g. a temporal/video-only
    # effect, or a still-only operation) declares ``"accepts": ["video"]`` /
    # ``["image"]`` on its def. The frontend reads ``x-accept-media`` to gate
    # which library items can be sent to the tool — see getToolDeclaredAcceptMedia.
    accepts = filter_def.get("accepts") or ["image", "video"]
    properties: Dict[str, Any] = {
        "input_images": {
            "type": "array",
            "items": {"type": "string", "format": "file-path"},
            "minItems": 1,
            "maxItems": 1,
            "x-control": "image_picker",
            "x-accept-media": list(accepts),
            "description": "Image or video to process (filters apply per-frame to video)",
        },
    }

    for param in filter_def["params"]:
        name = param["name"]
        prop: Dict[str, Any] = {"x-label": param.get("label") or name}
        if param["type"] == "enum":
            prop["type"] = "string"
            prop["enum"] = list(param["options"])
            prop["default"] = param["default"]
        else:
            prop["type"] = param["type"]  # "number" | "integer"
            prop["default"] = param["default"]
            if param.get("min") is not None:
                prop["minimum"] = param["min"]
            if param.get("max") is not None:
                prop["maximum"] = param["max"]
            if param.get("step") is not None:
                prop["x-step"] = param["step"]
        properties[name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": ["input_images"],
    }


FILTER_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "assets": {
            "type": "array",
            "description": "The filtered image or video",
        },
    },
}
