"""
Shared STP (Stimma Tools Protocol) utility functions.

Helpers for LoRA resolution, dimension snapping, and tool schema inspection.
Used by v2 agent tools (call_tool, discover).
"""

import os
import re
from collections import defaultdict
from difflib import SequenceMatcher
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


def _find_lora_match(
    query: str,
    available_loras: List[str],
    normalized_index: Dict[str, List[str]],
) -> Optional[Tuple[str, int]]:
    """
    Find the best matching LoRA path for a query string using a 4-tier cascade.

    Returns (matched_path, tier) or None if no match found.
    Tier 1: exact endswith + extension fallback
    Tier 2: normalized exact match
    Tier 3: normalized substring (query in name or name in query)
    Tier 4: fuzzy SequenceMatcher with substring bonus
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

    # --- Tier 2: Normalized exact match ---
    norm_query = _normalize_lora_name(query)
    tier2 = normalized_index.get(norm_query, [])
    if len(tier2) == 1:
        return tier2[0], 2

    # --- Tier 3: Normalized substring (query ⊂ name or name ⊂ query) ---
    tier3 = []
    for norm_name, paths in normalized_index.items():
        if norm_query in norm_name or norm_name in norm_query:
            tier3.extend(paths)
    if len(tier3) == 1:
        return tier3[0], 3

    # --- Tier 4: Fuzzy matching with SequenceMatcher ---
    best_path = None
    best_score = 0.0
    for norm_name, paths in normalized_index.items():
        base_ratio = SequenceMatcher(None, norm_query, norm_name).ratio()
        # Substring bonus: if one is contained in the other, boost the score
        bonus = 0.3 if (norm_query in norm_name or norm_name in norm_query) else 0.0
        score = base_ratio + bonus
        if score > best_score:
            best_score = score
            best_path = paths[0]
    if best_score > 0.6 and best_path:
        return best_path, 4

    # --- Multi-match fallback: pick first from earliest tier that had results ---
    for tier_matches in (matches, tier2, tier3):
        if tier_matches:
            return tier_matches[0], -1  # -1 signals multi-match fallback

    return None


def _resolve_lora_paths(tool_id: str, loras: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Resolve short LoRA filenames to full paths using a multi-tier matching cascade.

    Matching tiers (first unique match wins):
    1. Exact endswith + extension fallback
    2. Normalized exact (case/separator insensitive)
    3. Normalized substring
    4. Fuzzy SequenceMatcher (ratio > 0.6 with substring bonus)

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
            raise ValueError(
                f"LoRA '{original_path}' not found in the {len(available_loras)} available LoRAs for this tool. "
                f"Check the LoRA name and try again."
            )
        else:
            resolved_path, tier = result
            if tier == -1:
                log.warning(
                    f"[resolve_lora_paths] Multiple matches for '{original_path}', "
                    f"using first: '{resolved_path}'"
                )
            else:
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
