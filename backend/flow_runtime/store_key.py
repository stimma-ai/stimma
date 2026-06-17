"""Store key derivation for the global equation store.

See docs/FLOWS_EQUATION_KEYS.md §4 and docs/FLOWS_DSL.md §7. In short:

    store_key = sha256(equation_type + ":" + definition_hash + ":"
                       + inputs_hash + ":" + attempt)

Where:
  - `equation_type` is one of 'tool_call', 'llm_call', 'code'. HITL
    equations do NOT use the global store — their results live in the
    per-flow hitl_results table keyed on (equation_key, inputs_hash).
  - `definition_hash` captures the static identity of the computation
    (tool_id + static params; model + prompt template; code source).
  - `inputs_hash` captures the resolved values flowing in from upstream
    equations (prompts after f-string substitution; media content hashes;
    etc.).
  - `attempt` starts at 1 and bumps only on direct invalidation (§4).

Static vs dynamic parameter boundary:
  - static = value known at graph-build time (literals in the program,
    flow inputs that are scalars/enums) -> contributes to definition_hash
  - dynamic = value flows from an upstream equation's result -> contributes
    to inputs_hash

The boundary is determined at graph-build time by the DSL layer marking
each parameter as static or dynamic; this module is pure hashing.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .keys import canonical_json_hash


# Equation types that participate in the global equation store.
# 'hitl' and 'control' are intentionally omitted — see module docstring.
STOREABLE_EQUATION_TYPES = frozenset({
    "tool_call",
    "llm_call",
    "llm_batch",
    "llm_slot",
    "code",
    "info",
    "create_set",
    "create_grid",
    "create_document",
    "create_image",
    "create_layout",
    "rasterize_layout",
    "web_search",
    "fetch_media",
})


class StoreKeyError(ValueError):
    pass


def definition_hash_for_tool(tool_id: str, static_params: Mapping[str, Any]) -> str:
    """definition_hash for a tool_call equation.

    Static params include any parameter whose value is known at build time
    (literal boolean flags, literal strings that don't depend on upstream
    nodes). Parameter names are canonicalized via sorted JSON.
    """
    if not tool_id:
        raise StoreKeyError("tool_call definition_hash: tool_id is required")
    payload = {
        "tool_id": tool_id,
        "static_params": dict(static_params),
    }
    return canonical_json_hash(payload)


def definition_hash_for_llm(
    model: str,
    prompt_template: str,
    *,
    system_template: str | None = None,
    response_format: Any = None,
    think: bool = False,
) -> str:
    """definition_hash for an llm_call equation.

    `prompt_template` is the UNRESOLVED f-string skeleton — i.e. the static
    pieces with placeholders, not the substituted value. The DSL layer is
    responsible for passing the template (not the resolved string) here.
    """
    payload = {
        "model": model,
        "think": think,
        "prompt_template": prompt_template,
        "system_template": system_template,
        "response_format": response_format,
    }
    return canonical_json_hash(payload)


def definition_hash_for_llm_batch(
    model: str,
    prompt_template: str,
    n: int,
    *,
    system_template: str | None = None,
    response_format: Any = None,
    think: bool = False,
) -> str:
    """definition_hash for an llm_batch equation (llm() with n>1).

    Distinct from llm_call: n participates so 5-item and 10-item batches of
    otherwise-identical templates don't collide in the store.
    """
    payload = {
        "model": model,
        "think": think,
        "prompt_template": prompt_template,
        "system_template": system_template,
        "response_format": response_format,
        "n": n,
    }
    return canonical_json_hash(payload)


def definition_hash_for_llm_slot(batch_key: str, slot_index: int) -> str:
    """definition_hash for an llm_slot equation.

    Batch-scoped: includes the owning batch equation key so two different
    batches (different prompts / different flows) never share slot keys.
    """
    payload = {"batch_key": batch_key, "slot_index": slot_index}
    return canonical_json_hash(payload)


def definition_hash_for_code(source: str, output_type: str = "json") -> str:
    """definition_hash for a code() equation. Whitespace-sensitive (§4)."""
    payload = {"source": source, "output_type": output_type}
    return canonical_json_hash(payload)


def definition_hash_for_info(template: str, static_inputs: Mapping[str, Any]) -> str:
    """definition_hash for an info() equation."""
    payload = {"template": template, "static_inputs": dict(static_inputs)}
    return canonical_json_hash(payload)


def definition_hash_for_create_set(title: str, description: str) -> str:
    """definition_hash for a create_set() equation.

    Only the static fields contribute; the item list arrives as dynamic
    inputs and flows into inputs_hash (content-addressable reuse).
    """
    payload = {"title": title, "description": description}
    return canonical_json_hash(payload)


def definition_hash_for_create_grid(
    rows: int,
    cols: int,
    row_headers: Any,
    col_headers: Any,
    title: str,
) -> str:
    """definition_hash for a create_grid() equation."""
    payload = {
        "rows": rows,
        "cols": cols,
        "row_headers": list(row_headers or []),
        "col_headers": list(col_headers or []),
        "title": title,
    }
    return canonical_json_hash(payload)


def definition_hash_for_create_document(title: str, format: str) -> str:  # noqa: A002
    """definition_hash for a create_document() equation."""
    payload = {"title": title, "format": format}
    return canonical_json_hash(payload)


def definition_hash_for_create_image(
    title: str, format: str, source: str,  # noqa: A002
) -> str:
    """definition_hash for a create_image() equation.

    Includes the callable's canonical source so an edit to the image-
    composition code busts the store cache even when title / format are
    unchanged.
    """
    payload = {"title": title, "format": format, "source": source}
    return canonical_json_hash(payload)


def definition_hash_for_create_layout(
    title: str, width: int, height: int | None, source: str,
) -> str:
    """definition_hash for a create_layout() equation.

    Canvas width/height participate so resizing a layout invalidates the
    cached bundle. `height=None` (content-measured) hashes distinctly from
    any fixed height. Callable source busts the cache on HTML edits.
    """
    payload = {
        "title": title,
        "width": width,
        "height": height,
        "source": source,
    }
    return canonical_json_hash(payload)


def definition_hash_for_rasterize_layout(width: int | None) -> str:
    """definition_hash for a rasterize_layout() equation."""
    payload = {"width": width}
    return canonical_json_hash(payload)


def definition_hash_for_web_search(
    query_template: str,
    kind: str,
    n: int,
) -> str:
    """definition_hash for a web_search() equation.

    The unresolved query template (with placeholders) participates so static
    queries cache distinctly from queries built from upstream nodes.
    """
    payload = {
        "query_template": query_template,
        "kind": kind,
        "n": n,
    }
    return canonical_json_hash(payload)


def definition_hash_for_fetch_media(max_size_mb: int) -> str:
    """definition_hash for a fetch_media() equation.

    URL is dynamic (flows through inputs_hash) — only the cap participates.
    """
    payload = {"max_size_mb": max_size_mb}
    return canonical_json_hash(payload)


def inputs_hash_for_values(resolved_inputs: Mapping[str, Any]) -> str:
    """inputs_hash from the resolved values dict (§4).

    Media values must be passed as content hashes, not media IDs. The caller
    is responsible for normalizing media references before hashing, because
    IDs are installation-specific and would break cross-flow sharing.
    """
    return canonical_json_hash(dict(resolved_inputs))


def compute_store_key(
    equation_type: str,
    definition_hash: str,
    inputs_hash: str,
    attempt: int,
) -> str:
    """Final store key. See module docstring for layout.

    We keep the exact structure specified in FLOWS_EQUATION_KEYS.md §4
    ("sha256(equation_type + ":" + definition_hash + ":" + inputs_hash
    + ":" + str(attempt))") — including the explicit `:` separators — so
    store keys produced by different implementations match byte-for-byte.
    """
    if equation_type not in STOREABLE_EQUATION_TYPES:
        raise StoreKeyError(
            f"equation_type {equation_type!r} is not stored in the global "
            f"equation store (HITL and control equations are per-flow)"
        )
    if attempt < 1:
        raise StoreKeyError(f"attempt must be >= 1 (got {attempt})")
    composite = f"{equation_type}:{definition_hash}:{inputs_hash}:{attempt}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()


def derive_seed(equation_key: str, attempt: int) -> int:
    """Seed for tools that support seeds (§4).

    `seed = hash(equation_key + attempt)` per FLOWS_TECH.md §Store Keys.
    Returns an unsigned 32-bit integer (most generation tools constrain the
    seed to a 32-bit space).
    """
    if attempt < 1:
        raise StoreKeyError(f"attempt must be >= 1 (got {attempt})")
    digest = hashlib.sha256(f"{equation_key}:{attempt}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0xFFFFFFFF
