"""Equation key and iteration key derivation.

See docs/RECIPES_EQUATION_KEYS.md §3, §6, §7 for the full spec. In short:

- Equation keys are structural, human-readable, and stable under edits that
  don't change function names or the ordering of DSL calls. Format:

      {fn}:{iter}              top-level foreach iteration (wrapper)
      {fn}:{iter}/{kind}$N     nested DSL call within the body (N = position)
      {fn}:{iter}/{fn2}:{iter2}  nested foreach

- Iteration keys are derived automatically by the runtime, never provided by
  the DSL (no `key=` or `label=` kwargs). Derivation depends on the source
  collection:

      scalar list[str|int|float|bool]  -> value stringified
      list[media]                      -> media content hash
      list[json|dict]                  -> canonical-JSON sha256
      llm(n=N) / hand-built node list  -> positional index
      upstream foreach                 -> inherited from upstream

- Reserved characters in the key format are `:`, `/`, `$`, `@`. The first
  two are percent-encoded in user-provided iteration keys; `$` and `@` are
  rejected outright (in function names and iteration keys respectively).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Sequence

# Characters that split segments of an equation key.
_RESERVED_IN_ITERATION_KEY = (":", "/")
_RESERVED_ALWAYS_REJECTED = ("$",)
_SUBRECIPE_PREFIX = "@"

# Function-name validator: Python identifier rules, plus we reject leading '@'
# (reserved for sub-recipe namespace) and any '$' (reserved for positional
# nested calls, e.g. "tool$0").
_VALID_FUNCTION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


class EquationKeyError(ValueError):
    """Raised when an equation key cannot be constructed (bad input)."""


def validate_function_name(name: str) -> None:
    """Reject names that would produce ambiguous or invalid keys.

    Per RECIPES_EQUATION_KEYS.md §7: `@` is reserved for the sub-recipe
    namespace prefix and `$` is reserved as the positional-index separator.
    Function names must also be valid Python identifiers (with `.` allowed
    to support `hitl.select` et al, which we use as function-name-like
    labels for nested DSL primitive calls).
    """
    if not name:
        raise EquationKeyError("function name must not be empty")
    if name.startswith(_SUBRECIPE_PREFIX):
        raise EquationKeyError(
            f"function name {name!r} starts with reserved '@' (sub-recipe prefix)"
        )
    for ch in _RESERVED_ALWAYS_REJECTED:
        if ch in name:
            raise EquationKeyError(
                f"function name {name!r} contains reserved character {ch!r}"
            )
    if not _VALID_FUNCTION_NAME_RE.match(name):
        raise EquationKeyError(f"invalid function name: {name!r}")


def encode_iteration_key(raw: Any) -> str:
    """Render an iteration-key source into a safe string segment.

    Accepts arbitrary values from iteration-key derivation and produces a
    printable-ASCII string with the reserved separators `:` and `/`
    percent-encoded (per §3). `$` is rejected outright; it never appears in
    user-provided iteration keys because the positional-index form
    (`tool$0`) is constructed separately by the runtime.

    Input types we expect:
      - str (scalar list values, content hashes, canonical-JSON hashes)
      - int (positional indices)
      - bool, float (scalar list values)
    """
    if isinstance(raw, bool):
        # Must check before int — bool is a subclass of int in Python.
        s = "true" if raw else "false"
    elif isinstance(raw, (int, float)):
        s = repr(raw) if isinstance(raw, float) else str(raw)
    elif isinstance(raw, str):
        s = raw
    else:
        raise EquationKeyError(
            f"iteration-key value must be a scalar or str; got {type(raw).__name__}"
        )

    if "$" in s:
        raise EquationKeyError(
            f"iteration key {s!r} contains reserved '$' character"
        )
    # Percent-encode the two segment separators; leave other printable ASCII
    # as-is so keys stay human-readable ("Mojito" -> "Mojito").
    s = s.replace("%", "%25")  # must escape '%' itself first
    s = s.replace(":", "%3A")
    s = s.replace("/", "%2F")
    # Non-ASCII or control characters — percent-encode their UTF-8 bytes.
    out_chars = []
    for ch in s:
        if ch.isascii() and ch.isprintable():
            out_chars.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out_chars.append(f"%{b:02X}")
    return "".join(out_chars)


def canonical_json_hash(value: Any) -> str:
    """Stable sha256 hex of a JSON value (dict, list, scalar).

    Used for:
      - iteration keys over list[json]/list[dict] collections (§6)
      - inputs_hash canonicalization (see store_key.py)

    Keys are sorted; floats and ints preserve their Python repr via
    json.dumps defaults; whitespace is stripped.
    """
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def content_hash_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----- Equation key composition ---------------------------------------------

def make_top_level_key(function_name: str) -> str:
    """Key for a top-level equation that isn't inside any foreach."""
    validate_function_name(function_name)
    return function_name


def make_iteration_wrapper_key(function_name: str, iteration_key: Any) -> str:
    """Wrapper equation for a single foreach iteration: `fn:iter`."""
    validate_function_name(function_name)
    return f"{function_name}:{encode_iteration_key(iteration_key)}"


def make_nested_dsl_key(
    parent_key: str,
    primitive_kind: str,
    positional_index: int,
) -> str:
    """Nested DSL call inside a callback body: `<parent>/kind$N`.

    `primitive_kind` is one of 'tool', 'llm', 'code', 'hitl.select',
    'hitl.approve', 'zip_nodes',
    'foreach'. `positional_index` is the 0-based position of this call among
    calls of the same kind in the enclosing function body.
    """
    validate_function_name(primitive_kind)
    if positional_index < 0:
        raise EquationKeyError(f"positional_index must be >= 0 (got {positional_index})")
    return f"{parent_key}/{primitive_kind}${positional_index}"


def make_nested_foreach_iteration_key(
    parent_key: str,
    function_name: str,
    iteration_key: Any,
) -> str:
    """Nested foreach-callback wrapper: `<parent>/fn:iter` (RECIPES_EQUATION_KEYS §6 nested foreach)."""
    validate_function_name(function_name)
    return f"{parent_key}/{function_name}:{encode_iteration_key(iteration_key)}"

# ----- Iteration-key derivation (runtime, per §6) ---------------------------

class IterationKeySource:
    """Tagged value that tells the runtime how to key a foreach collection.

    The graph builder attaches an IterationKeySource to every collection node
    so downstream `foreach` expansion can look it up and produce the correct
    iteration keys. Three modes:

      - KEYED: keys come from the upstream node or the raw values (scalars,
        media hashes, canonical-JSON hashes).
      - POSITIONAL: only positional indices are meaningful (hand-built list
        of nodes, llm n=N, hitl.select count>1).
      - INHERITED: the upstream producer is another keyed foreach; iteration
        keys flow through by position-in-result.
    """

    KEYED = "keyed"
    POSITIONAL = "positional"
    INHERITED = "inherited"

    __slots__ = ("mode", "element_kind")

    def __init__(self, mode: str, element_kind: str = "") -> None:
        if mode not in (self.KEYED, self.POSITIONAL, self.INHERITED):
            raise ValueError(f"unknown IterationKeySource mode: {mode!r}")
        self.mode = mode
        # `element_kind` is advisory metadata ("scalar", "media", "json",
        # "tool_candidate", etc.) — useful for debugging and for the runtime
        # to pick the right hashing strategy at evaluation time.
        self.element_kind = element_kind

    def __repr__(self) -> str:
        return f"IterationKeySource(mode={self.mode!r}, element_kind={self.element_kind!r})"


def derive_iteration_key(value: Any, element_kind: str) -> str:
    """Derive an iteration key from a concrete resolved item at evaluation time.

    Only used when the source is KEYED (not INHERITED or POSITIONAL).

    Per §6:

        scalar list[str|int|float|bool]  -> stringified value
        list[media]                      -> media content hash (str passed in)
        list[json]/list[dict]            -> canonical-JSON hash

    `element_kind` steers which rule applies:
      - 'scalar'       -> use the raw value as its key
      - 'media'        -> `value` is already a content hash string; use it
      - 'json' | 'dict'-> canonical JSON hash
    """
    if element_kind == "scalar":
        return encode_iteration_key(value)
    if element_kind == "media":
        if not isinstance(value, str):
            raise EquationKeyError(
                f"media iteration key must be a content hash string; got {type(value).__name__}"
            )
        return encode_iteration_key(value)
    if element_kind in ("json", "dict"):
        return encode_iteration_key(canonical_json_hash(value))
    raise EquationKeyError(f"unsupported iteration-key element_kind: {element_kind!r}")


def iteration_keys_for_collection(
    values: Sequence[Any],
    source: IterationKeySource,
    inherited_keys: Sequence[str] | None = None,
) -> list[str]:
    """Produce the iteration-key list for a foreach expansion.

    `values` is the resolved collection (after upstream nodes resolve).
    `source` tells us which rule to apply. `inherited_keys` is required when
    source.mode == INHERITED — it must be the upstream foreach's
    iteration-key list, in result order.
    """
    if source.mode == IterationKeySource.POSITIONAL:
        return [str(i) for i in range(len(values))]
    if source.mode == IterationKeySource.INHERITED:
        if inherited_keys is None:
            raise EquationKeyError(
                "iteration_keys_for_collection: INHERITED source requires inherited_keys"
            )
        if len(inherited_keys) != len(values):
            raise EquationKeyError(
                f"inherited_keys length {len(inherited_keys)} != values length {len(values)}"
            )
        # Inherited keys are already encoded by their originating derivation.
        return list(inherited_keys)
    if source.mode == IterationKeySource.KEYED:
        return [derive_iteration_key(v, source.element_kind) for v in values]
    raise EquationKeyError(f"unknown source mode: {source.mode!r}")


# ----- Reserved-character checks --------------------------------------------

_EQUATION_KEY_ALLOWED_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.@]*"                 # root function name (or @sub-recipe)
    r"(:[^/$]+)?"                                # optional iteration key (no '/' or '$')
    r"(/[A-Za-z_][A-Za-z0-9_.]*(\$\d+|:[^/$]+)?)*"  # nested segments
    r"$"
)


def is_well_formed_equation_key(key: str) -> bool:
    """Heuristic validator for round-tripped equation keys.

    Not a strict grammar — the percent-encoded iteration keys can contain
    `%` and encoded bytes. This is mainly used in tests that want to
    detect accidentally truncated or garbled keys.
    """
    if not key or "$" in key.split("/", 1)[0]:
        # Root segment must never contain '$' (reserved for positional).
        return False
    return True
