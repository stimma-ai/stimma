"""
Shared STP (Stimma Tools Protocol) utility functions.

Helpers for LoRA resolution, dimension snapping, and tool schema inspection.
Used by v2 agent tools (call_tool, discover).
"""

import math
import os
import re
from collections import defaultdict
from difflib import get_close_matches
from typing import List, Dict, Any, Optional, Tuple

from core.logging import get_logger
from providers.registry import ProviderRegistry

log = get_logger(__name__)


def _normalize_lora_name(s: str) -> str:
    """
    Normalize a LoRA name for fuzzy comparison.

    Strips directory, removes known extensions, lowercases,
    and collapses all separators (spaces, underscores, hyphens, dots) to single spaces.
    """
    s = os.path.basename(s)
    # Strip known extensions
    for ext in (".safetensors", ".ckpt", ".pt"):
        if s.lower().endswith(ext):
            s = s[: -len(ext)]
            break
    s = s.lower()
    s = re.sub(r"[\s_\-\.]+", " ", s).strip()
    return s


class AmbiguousLoraError(ValueError):
    """A LoRA query matched more than one available path at the same tier."""

    def __init__(self, query: str, candidates: List[str]):
        self.query = query
        self.candidates = candidates
        shown = ", ".join(repr(c) for c in candidates[:8])
        more = f" (and {len(candidates) - 8} more)" if len(candidates) > 8 else ""
        super().__init__(
            f"LoRA {query!r} is ambiguous — it matches {len(candidates)} available "
            f"paths: {shown}{more}. Pass the full path verbatim."
        )


def _find_lora_match(
    query: str,
    available_loras: List[str],
    normalized_index: Dict[str, List[str]],
) -> Optional[Tuple[str, int]]:
    """
    Find the LoRA path a query unambiguously identifies, using a 3-tier cascade.

    Returns (matched_path, tier), or None if nothing matched.
    Tier 1: exact endswith + extension fallback
    Tier 2: normalized exact match
    Tier 3: normalized substring (query in name or name in query)

    Every tier requires a UNIQUE match. Multiple matches raise AmbiguousLoraError
    rather than picking one, and a query that matches nothing returns None rather
    than falling back to a nearest neighbour.

    There is deliberately no fuzzy tier. Checkpoint families differ only in a step
    number (``lora_v1_000001400`` vs ``lora_v1_000000400``), so any similarity
    metric scores every sibling near-identically. A fuzzy match there does not
    recover from a typo — it silently swaps one checkpoint for another and
    invalidates the comparison the caller was making. Guessing wrong is strictly
    worse than failing, so unmatched queries must raise.
    """
    filename = os.path.basename(query)

    # --- Tier 1: Exact endswith + extension fallback ---
    matches = [p for p in available_loras if p.endswith(filename)]
    if not matches and "." not in filename:
        for ext in (".safetensors", ".ckpt", ".pt"):
            matches = [p for p in available_loras if p.endswith(filename + ext)]
            if matches:
                break
    if len(matches) == 1:
        return matches[0], 1
    if matches:
        raise AmbiguousLoraError(query, sorted(matches))

    # --- Tier 2: Normalized exact match ---
    norm_query = _normalize_lora_name(query)
    tier2 = normalized_index.get(norm_query, [])
    if len(tier2) == 1:
        return tier2[0], 2
    if tier2:
        raise AmbiguousLoraError(query, sorted(tier2))

    # --- Tier 3: Normalized substring (query ⊂ name or name ⊂ query) ---
    tier3 = []
    for norm_name, paths in normalized_index.items():
        if norm_query in norm_name or norm_name in norm_query:
            tier3.extend(paths)
    if len(tier3) == 1:
        return tier3[0], 3
    if tier3:
        raise AmbiguousLoraError(query, sorted(tier3))

    return None


def _resolve_lora_paths(tool_id: str, loras: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Resolve short LoRA filenames to full paths using a multi-tier matching cascade.

    Matching tiers (each requires a unique match):
    1. Exact endswith + extension fallback
    2. Normalized exact (case/separator insensitive)
    3. Normalized substring

    Raises ValueError if a name matches nothing, and AmbiguousLoraError if it
    matches several. Never substitutes a near neighbour — see _find_lora_match.

    Args:
        tool_id: The tool ID to query for available LoRAs
        loras: List of lora dicts with 'path' and optional 'weight'

    Returns:
        List of lora dicts with resolved paths
    """
    if not loras:
        return loras

    registry = ProviderRegistry.get_instance()
    provider_tool = registry.get_tool(tool_id)

    if not provider_tool:
        log.warning(f"[resolve_lora_paths] Tool {tool_id} not found, cannot resolve LoRA paths")
        return loras

    provider, tool_descriptor = provider_tool

    # Get available LoRA paths from the tool's parameter schema
    param_schema = tool_descriptor.parameter_schema or {}
    properties = param_schema.get("properties", {})
    lora_schema = properties.get("loras", {})
    items_schema = lora_schema.get("items", {})
    path_schema = items_schema.get("properties", {}).get("path", {})
    available_loras = path_schema.get("enum", [])

    if not available_loras:
        log.warning(f"[resolve_lora_paths] No available LoRAs found in tool schema for {tool_id}")
        return loras

    # Build normalized index once: normalized_name -> [full_paths]
    normalized_index: Dict[str, List[str]] = defaultdict(list)
    for path in available_loras:
        normalized_index[_normalize_lora_name(path)].append(path)

    # Resolve each LoRA path
    resolved_loras = []
    for lora in loras:
        if not lora or not lora.get("path"):
            continue

        original_path = lora["path"]

        # If path contains "/" and exists verbatim in available list, use it directly
        if "/" in original_path and original_path in available_loras:
            resolved_loras.append(lora)
            continue

        # Run the matching cascade
        result = _find_lora_match(original_path, available_loras, normalized_index)

        if result is None:
            # Suggestions go in the message only — never auto-applied. A near
            # neighbour is a hint for the caller, not a substitute for the
            # thing they asked for.
            near = get_close_matches(original_path, available_loras, n=5, cutoff=0.5)
            hint = (
                " Closest available: " + ", ".join(repr(p) for p in near) + "."
                if near
                else ""
            )
            raise ValueError(
                f"LoRA '{original_path}' not found among the {len(available_loras)} "
                f"LoRAs available for this tool.{hint}"
            )

        resolved_path, tier = result
        log.info(
            f"[resolve_lora_paths] Resolved '{original_path}' -> '{resolved_path}' "
            f"(tier {tier})"
        )
        resolved_loras.append({
            "path": resolved_path,
            "weight": lora.get("weight", 1.0),
        })

    return resolved_loras


def _get_allowed_dimensions(tool_descriptor) -> Optional[List[List[int]]]:
    """Read x-allowed-dimensions from the tool's parameter_schema.properties.width."""
    parameter_schema = tool_descriptor.parameter_schema or {}
    width_schema = parameter_schema.get("properties", {}).get("width", {})
    dims = width_schema.get("x-allowed-dimensions")
    if dims and isinstance(dims, list) and len(dims) > 0:
        return dims
    return None


def _snap_to_allowed(w: int, h: int, allowed: List[List[int]]) -> Tuple[int, int]:
    """Find the nearest allowed dimension pair by aspect ratio similarity."""
    target_ratio = w / h if h else 1.0
    best = allowed[0]
    best_diff = float("inf")
    for pair in allowed:
        pw, ph = pair[0], pair[1]
        ratio = pw / ph if ph else 1.0
        diff = abs(ratio - target_ratio)
        if diff < best_diff:
            best_diff = diff
            best = pair
    return best[0], best[1]


def snap_dims_to_schema(tool_descriptor, width: float, height: float) -> Tuple[int, int]:
    """Snap (width, height) onto the tool's legal grid: nearest allowed pair by
    aspect-ratio similarity for constrained tools (same rule call_tool applies,
    so a portrait source lands on the portrait pair, not a same-area square),
    otherwise clamp+round each axis to the schema's min/max/x-step."""
    allowed = _get_allowed_dimensions(tool_descriptor)
    if allowed:
        return _snap_to_allowed(int(round(width)), int(round(height)), allowed)

    props = (tool_descriptor.parameter_schema or {}).get("properties", {})

    def snap_axis(v: float, p: Dict[str, Any]) -> int:
        step = p.get("x-step") or 1
        x = round(v / step) * step
        if p.get("minimum") is not None:
            x = max(p["minimum"], x)
        if p.get("maximum") is not None:
            x = min(p["maximum"], x)
        return int(x)

    return (
        snap_axis(width, props.get("width", {})),
        snap_axis(height, props.get("height", props.get("width", {}))),
    )


def follow_input_dims(tool_descriptor, src_w: float, src_h: float) -> Tuple[int, int]:
    """Output size for a call that left width/height to the tool, given the
    input that sets the frame. Mirrors ToolView's default resolution policy:
    the shape always follows the input; a tool with a fixed size list keeps
    the size of its default pair, while a freeform tool also follows the
    input's size, scaled uniformly into the schema's bounds."""
    props = (tool_descriptor.parameter_schema or {}).get("properties", {})
    allowed = _get_allowed_dimensions(tool_descriptor)
    if allowed:
        target = math.log(src_w / src_h)

        def dist(pair):
            return abs(math.log(pair[0] / pair[1]) - target)

        best = min(dist(p) for p in allowed)
        shape = [p for p in allowed if dist(p) - best < 0.02]
        try:
            base_area = float(props["width"]["default"]) * float(props["height"]["default"])
        except (KeyError, TypeError, ValueError):
            base_area = float(shape[0][0] * shape[0][1])
        pick = min(shape, key=lambda p: abs(p[0] * p[1] - base_area))
        return int(pick[0]), int(pick[1])

    w_p = props.get("width", {})
    h_p = props.get("height", w_p)
    low = max((w_p.get("minimum") or 0) / src_w, (h_p.get("minimum") or 0) / src_h)
    high = min(
        (w_p.get("maximum") or math.inf) / src_w,
        (h_p.get("maximum") or math.inf) / src_h,
    )
    scale = min(high, max(low, 1.0))
    return snap_dims_to_schema(tool_descriptor, src_w * scale, src_h * scale)


def nearest_aspect_choice(choices: List[Any], width: float, height: float) -> Optional[str]:
    """Pick the "W:H" choice closest to width/height. Mirrors ToolView's
    findNearestAspectRatio; returns None when no choice is parseable."""
    if not height:
        return None
    target = width / height
    best: Optional[str] = None
    best_diff = float("inf")
    for choice in choices or []:
        if not isinstance(choice, str) or ":" not in choice:
            continue
        try:
            w_s, h_s = choice.split(":", 1)
            ratio = float(w_s) / float(h_s)
        except (ValueError, ZeroDivisionError):
            continue
        diff = abs(target - ratio)
        if diff < best_diff:
            best_diff = diff
            best = choice
    return best
