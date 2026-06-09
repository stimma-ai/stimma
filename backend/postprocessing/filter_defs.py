"""Built-in (in-app) filter definitions for post-processing chains.

Mirrors packages/image-editor/src/filterDefs.ts and constants.ts — the editor
owns the source of truth; tests/test_postprocessing_filters.py asserts the
two sides stay in sync (ids, params, ranges, defaults, matrices).
"""

from typing import Any, Dict, List, Optional

# 5x4 color matrices applied as [R', G', B', A'] = matrix x [R, G, B, A, 1].
# Mirrors FILTER_MATRICES in packages/image-editor/src/constants.ts.
FILTER_MATRICES: Dict[str, List[float]] = {
    "none": [
        1, 0, 0, 0, 0,
        0, 1, 0, 0, 0,
        0, 0, 1, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "chrome": [
        1.2, 0.1, 0.1, 0, -20,
        0.1, 1.1, 0.1, 0, -10,
        0.1, 0.1, 1.3, 0, -20,
        0, 0, 0, 1, 0,
    ],
    "fade": [
        1, 0, 0, 0, 30,
        0, 1, 0, 0, 30,
        0, 0, 1, 0, 30,
        0, 0, 0, 0.9, 0,
    ],
    "cold": [
        0.9, 0, 0.1, 0, 0,
        0, 0.95, 0.1, 0, 0,
        0.1, 0.1, 1.2, 0, 10,
        0, 0, 0, 1, 0,
    ],
    "warm": [
        1.2, 0.1, 0, 0, 10,
        0.1, 1.05, 0, 0, 5,
        0, 0, 0.9, 0, -10,
        0, 0, 0, 1, 0,
    ],
    "pastel": [
        1.1, 0.1, 0.1, 0, 20,
        0.1, 1.1, 0.1, 0, 20,
        0.1, 0.1, 1.1, 0, 20,
        0, 0, 0, 1, 0,
    ],
    "mono": [
        0.33, 0.33, 0.33, 0, 0,
        0.33, 0.33, 0.33, 0, 0,
        0.33, 0.33, 0.33, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "noir": [
        0.4, 0.4, 0.2, 0, -20,
        0.3, 0.4, 0.2, 0, -10,
        0.2, 0.3, 0.4, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "stark": [
        0.5, 0.5, 0.5, 0, -50,
        0.5, 0.5, 0.5, 0, -50,
        0.5, 0.5, 0.5, 0, -50,
        0, 0, 0, 1, 0,
    ],
    "sepia": [
        0.393, 0.769, 0.189, 0, 0,
        0.349, 0.686, 0.168, 0, 0,
        0.272, 0.534, 0.131, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "vintage": [
        0.9, 0.2, 0.1, 0, 20,
        0.1, 0.8, 0.2, 0, 15,
        0.1, 0.1, 0.7, 0, 30,
        0, 0, 0, 1, 0,
    ],
    "vivid": [
        1.3, -0.1, -0.1, 0, 0,
        -0.1, 1.3, -0.1, 0, 0,
        -0.1, -0.1, 1.3, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "dramatic": [
        1.3, -0.1, -0.1, 0, -20,
        -0.1, 1.3, -0.1, 0, -20,
        -0.1, -0.1, 1.3, 0, -20,
        0, 0, 0, 1, 0,
    ],
    "portra-400": [
        1.05, 0.08, 0.02, 0, 8,
        0.02, 1.0, 0.05, 0, 6,
        -0.02, 0.05, 0.92, 0, 15,
        0, 0, 0, 1, 0,
    ],
    "velvia": [
        1.2, -0.05, -0.05, 0, -15,
        -0.05, 1.15, -0.05, 0, -10,
        -0.05, 0.05, 1.3, 0, -20,
        0, 0, 0, 1, 0,
    ],
    "kodachrome": [
        1.15, 0.1, -0.05, 0, 5,
        0.05, 1.05, 0.0, 0, 0,
        -0.05, 0.1, 1.1, 0, 10,
        0, 0, 0, 1, 0,
    ],
    "cinestill-800t": [
        0.95, 0.05, 0.1, 0, 10,
        0.0, 1.0, 0.1, 0, 5,
        0.1, 0.1, 1.15, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "polaroid-600": [
        1.0, 0.05, 0.0, 0, 25,
        0.02, 0.98, 0.05, 0, 20,
        0.0, 0.08, 0.9, 0, 30,
        0, 0, 0, 0.95, 0,
    ],
    "tri-x-400": [
        0.35, 0.45, 0.2, 0, 0,
        0.35, 0.45, 0.2, 0, 0,
        0.35, 0.45, 0.2, 0, 0,
        0, 0, 0, 1, 0,
    ],
}

# Color preset ids offered by the color-filter step (everything except "none").
COLOR_FILTER_IDS: List[str] = [k for k in FILTER_MATRICES if k != "none"]

# Mirrors CHAIN_FILTER_DEFS in packages/image-editor/src/filterDefs.ts.
# Terminology matches the editor's panels: Filters (presets), Levels, Effects.
CHAIN_FILTER_DEFS: List[Dict[str, Any]] = [
    {
        "id": "filter",
        "label": "Filter",
        "params": [
            {"name": "filter", "type": "enum", "default": "chrome", "options": COLOR_FILTER_IDS},
        ],
    },
    {
        "id": "levels",
        "label": "Levels",
        "params": [
            {"name": "brightness", "type": "number", "default": 0, "min": -100, "max": 100},
            {"name": "contrast", "type": "number", "default": 0, "min": -100, "max": 100},
            {"name": "saturation", "type": "number", "default": 0, "min": -100, "max": 100},
            {"name": "exposure", "type": "number", "default": 0, "min": -100, "max": 100},
            {"name": "temperature", "type": "number", "default": 0, "min": -100, "max": 100},
            {"name": "gamma", "type": "number", "default": 1, "min": 0.2, "max": 2.2},
        ],
    },
    {
        "id": "blur",
        "label": "Blur",
        "params": [{"name": "amount", "type": "number", "default": 20, "min": 0, "max": 100}],
    },
    {
        "id": "sharpen",
        "label": "Sharpen",
        "params": [{"name": "amount", "type": "number", "default": 30, "min": 0, "max": 100}],
    },
    {
        "id": "clarity",
        "label": "Clarity",
        "params": [{"name": "amount", "type": "number", "default": 30, "min": 0, "max": 100}],
    },
    {
        "id": "motion-blur",
        "label": "Motion Blur",
        "params": [
            {"name": "amount", "type": "number", "default": 30, "min": 0, "max": 100},
            {"name": "angle", "type": "number", "default": 0, "min": -180, "max": 180},
        ],
    },
    {
        "id": "glow",
        "label": "Glow",
        "params": [{"name": "amount", "type": "number", "default": 30, "min": 0, "max": 100}],
    },
    {
        "id": "noise",
        "label": "Noise",
        "params": [{"name": "amount", "type": "number", "default": 20, "min": 0, "max": 100}],
    },
    {
        "id": "pixelate",
        "label": "Pixelate",
        "params": [{"name": "amount", "type": "number", "default": 20, "min": 0, "max": 100}],
    },
    {
        "id": "chromatic-aberration",
        "label": "Chromatic",
        "params": [{"name": "amount", "type": "number", "default": 30, "min": 0, "max": 100}],
    },
    {
        "id": "vignette",
        "label": "Vignette",
        "params": [{"name": "amount", "type": "number", "default": 40, "min": 0, "max": 100}],
    },
    {
        "id": "crop",
        "label": "Crop / Aspect",
        "params": [
            {"name": "aspect", "type": "enum", "default": "1:1",
             "options": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]},
        ],
    },
    {
        "id": "resize",
        "label": "Resize",
        "params": [{"name": "long_edge", "type": "integer", "default": 2048, "min": 64, "max": 8192}],
    },
]


# Pre-release ids renamed when terminology aligned with the editor.
LEGACY_FILTER_IDS: Dict[str, str] = {
    "color-filter": "filter",
    "color-grade": "levels",
}


def get_filter_def(filter_id: str) -> Optional[Dict[str, Any]]:
    filter_id = LEGACY_FILTER_IDS.get(filter_id, filter_id)
    for d in CHAIN_FILTER_DEFS:
        if d["id"] == filter_id:
            return d
    return None


def get_filter_defaults(filter_id: str) -> Dict[str, Any]:
    d = get_filter_def(filter_id)
    return {p["name"]: p["default"] for p in (d["params"] if d else [])}
