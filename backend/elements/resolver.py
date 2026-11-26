"""The element resolver: which reference images and LoRAs the attached elements put on a tool.

ToolView sends the attached elements, the tool, the prompt and what the user owns
(their own reference images, and picks they kept or removed). The answer is a plan:
the references and LoRAs to place, guidance for the prompt writer, and each element's
instructions rendered for Enhance, Fluent and the tool's agent.

Three ways to a plan, cheapest first:

1. **Deterministic** (no model): nothing needs judging. Every element's references fit
   the free slots, none is one of several alternatives, and each element has at most
   one LoRA for this tool. The prompt isn't part of the answer, so it's instant.
2. **Cached**: the same inputs were judged before (``store``, keyed by everything that
   shaped the answer, prompt included).
3. **Resolved**: one model call sees all the elements together, so they share the slot
   budget coherently. A reply that can't be used, a timeout or no model at all falls
   back to a deterministic plan: a bad reply never stops a run.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from core.logging import get_logger
from elements import template
from elements.bundle import ElementError, bundle_instructions, element_asset, element_detail, strip_frontmatter
from prompt_programs.store import ProgramStore, program_key

log = get_logger(__name__)

RESOLVER_VERSION = 2   # 2: guidance names chosen images as {ref:N} (ToolView numbers them as placed)
SURFACES = ("enhance", "fluent", "tool_agent")
LLM_TIMEOUT_SECONDS = 40.0
_MAX_REASON = 160

AskModel = Callable[[list[dict[str, Any]]], Awaitable[str]]


# --------------------------------------------------------------------------- inputs

@dataclass
class ToolInfo:
    tool_id: str
    model_family: str = "unknown"
    task_type: str = ""
    media_kind: str = "image"
    max_ref_images: int = 0
    # The tool's LoRA values (paths) and, when the provider reports them, their fingerprints.
    lora_values: list[str] = field(default_factory=list)
    lora_fingerprints: dict[str, Optional[str]] = field(default_factory=dict)


@dataclass
class Overrides:
    user_ref_count: int = 0
    pinned_refs: list[tuple[int, str]] = field(default_factory=list)
    excluded_refs: list[tuple[int, str]] = field(default_factory=list)
    pinned_loras: list[tuple[int, str]] = field(default_factory=list)
    excluded_loras: list[tuple[int, str]] = field(default_factory=list)

    @classmethod
    def parse(cls, raw: Optional[dict[str, Any]]) -> "Overrides":
        raw = raw or {}

        def pairs(name: str, key_field: str) -> list[tuple[int, str]]:
            out = []
            for item in raw.get(name) or []:
                try:
                    out.append((int(item["element_asset_id"]), str(item[key_field])))
                except (KeyError, TypeError, ValueError):
                    continue
            return sorted(set(out))

        try:
            user = max(0, int(raw.get("user_ref_count") or 0))
        except (TypeError, ValueError):
            user = 0
        return cls(
            user_ref_count=user,
            pinned_refs=pairs("pinned_refs", "member_key"),
            excluded_refs=pairs("excluded_refs", "member_key"),
            pinned_loras=pairs("pinned_loras", "lora_key"),
            excluded_loras=pairs("excluded_loras", "lora_key"),
        )

    def as_key(self) -> dict[str, Any]:
        return {
            "user": self.user_ref_count,
            "pr": self.pinned_refs, "xr": self.excluded_refs,
            "pl": self.pinned_loras, "xl": self.excluded_loras,
        }


@dataclass
class LoraMatch:
    key: str
    path: str
    weight: float
    trigger: str = ""
    notes: str = ""


@dataclass
class Element:
    """One attached element, as the resolver sees it."""
    asset_id: int
    revision_id: int
    name: str
    kind: str = ""
    instructions: str = ""          # ELEMENT.md source, front matter removed
    media: list[dict[str, Any]] = field(default_factory=list)   # usable canonical menu entries
    cover_key: Optional[str] = None
    loras: list[LoraMatch] = field(default_factory=list)        # matching this tool, not excluded
    lora_elsewhere: bool = False    # has LoRAs, none for this tool
    referenced_vars: frozenset[str] = frozenset()


# --------------------------------------------------------------------------- tool facts

def _max_items(prop: dict[str, Any]) -> int:
    for name in ("x-max-items", "maxItems"):
        value = prop.get(name)
        if isinstance(value, int) and not isinstance(value, bool):
            return max(0, value)
    return 0


async def tool_info(tool_id: str, task_type: Optional[str] = None) -> ToolInfo:
    """What the resolver needs to know about a tool. Never raises: an unknown tool has no slots."""
    from lora_notes import LORAS_PARAMETER, _fetch_fingerprints, _lora_values
    from model_family import model_family
    from routes.generation import _prompt_pipeline_context

    info = ToolInfo(tool_id=tool_id)
    try:
        model, _vendor, effective_task, schema_props = _prompt_pipeline_context(tool_id, task_type, None)
        info.model_family = model_family(model)
        info.task_type = effective_task or ""
        info.media_kind = "video" if "video" in info.task_type else ("audio" if "audio" in info.task_type else "image")
        refs = schema_props.get("input_images") or {}
        info.max_ref_images = _max_items(refs) if refs else 0
        if refs and info.max_ref_images == 0:
            info.max_ref_images = 1
        from providers.registry import ProviderRegistry
        found = ProviderRegistry.get_instance().get_tool(tool_id)
        if found and LORAS_PARAMETER in schema_props:
            info.lora_values = _lora_values(found[1])
            snapshot = await _fetch_fingerprints(tool_id)
            if snapshot is not None:
                info.lora_fingerprints = dict(snapshot.fingerprints)
    except Exception as exc:  # the plan degrades to "no slots", never fails
        log.warning(f"[elements] No tool facts for {tool_id}: {exc}")
    return info


def _norm(text: Any) -> str:
    return re.sub(r"[\s_-]+", " ", str(text or "")).strip().lower()


def match_loras(entries: list[dict[str, Any]], info: ToolInfo) -> tuple[list[LoraMatch], bool]:
    """The element's LoRAs this tool has: same file (fingerprint) first, else the same name.

    Returns (matches, has_loras_for_other_models).
    """
    from lora_notes import display_name

    by_fingerprint = {fp: value for value, fp in info.lora_fingerprints.items() if fp}
    by_name: dict[str, str] = {}
    for value in info.lora_values:
        by_name.setdefault(_norm(display_name(value)), value)
        by_name.setdefault(_norm(value), value)
    matches: list[LoraMatch] = []
    other_family = False
    for entry in entries:
        family = _norm(entry.get("model_family"))
        if family and info.model_family not in ("unknown", "other") and family != _norm(info.model_family):
            other_family = True
            continue
        path = by_fingerprint.get(entry.get("fingerprint") or "")
        if path is None and entry.get("display_name"):
            path = by_name.get(_norm(entry["display_name"])) or by_name.get(_norm(display_name(entry["display_name"])))
        if path is None:
            other_family = other_family or bool(family)
            continue
        weight = entry.get("default_weight")
        matches.append(LoraMatch(
            key=str(entry.get("key")),
            path=path,
            weight=float(weight) if isinstance(weight, (int, float)) and not isinstance(weight, bool) else 1.0,
            trigger=str(entry.get("trigger") or ""),
            notes=str(entry.get("notes") or ""),
        ))
    return matches, other_family and not matches


# --------------------------------------------------------------------------- loading

async def load_elements(session, specs: list[dict[str, Any]], info: ToolInfo, overrides: Overrides) -> tuple[list[Element], list[str]]:
    """The attached elements at their current versions. Missing ones are skipped with a warning."""
    out: list[Element] = []
    warnings: list[str] = []
    seen: set[int] = set()
    for spec in specs:
        try:
            asset_id = int(spec["asset_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if asset_id in seen:
            continue
        seen.add(asset_id)
        try:
            detail = await element_detail(session, asset_id)
            _asset, _revision, bundle = await element_asset(session, asset_id)
        except ElementError:
            warnings.append("An attached element is no longer in the library.")
            continue
        excluded_refs = {k for a, k in overrides.excluded_refs if a == asset_id}
        pinned_refs = {k for a, k in overrides.pinned_refs if a == asset_id}
        media = [
            m for m in detail["media"]
            if m["status"] == "canonical" and not m["missing"] and m["media_id"] is not None
            and m["key"] not in excluded_refs and m["key"] not in pinned_refs
        ]
        excluded_loras = {k for a, k in overrides.excluded_loras if a == asset_id}
        pinned_loras = {k for a, k in overrides.pinned_loras if a == asset_id}
        entries = [e for e in detail["loras"] if e.get("key") not in excluded_loras and e.get("key") not in pinned_loras]
        loras, elsewhere = match_loras(entries, info)
        source = strip_frontmatter(bundle_instructions(bundle))
        out.append(Element(
            asset_id=asset_id,
            revision_id=detail["revision_id"],
            name=detail["name"],
            kind=detail["kind"],
            instructions=source,
            media=media,
            cover_key=(detail.get("cover") or {}).get("key"),
            loras=loras,
            lora_elsewhere=elsewhere and not pinned_loras,
            referenced_vars=template.referenced_vars(source),
        ))
    return out, warnings


# --------------------------------------------------------------------------- rendering

def _orientation(parameters: dict[str, Any]) -> Optional[str]:
    try:
        w, h = float(parameters.get("width") or 0), float(parameters.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return "landscape" if w > h * 1.05 else ("portrait" if h > w * 1.05 else "square")


def template_context(info: ToolInfo, parameters: dict[str, Any], surface: str, *,
                     lora_available: bool, lora_active: Optional[bool]) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "model_family": info.model_family,
        "task_type": info.task_type,
        "media_kind": info.media_kind,
        "supports_images": info.max_ref_images > 0,
        "max_ref_images": info.max_ref_images,
        "lora_available": lora_available,
        "lora_active": lora_active,
        "surface": surface,
        "orientation": _orientation(parameters),
    }
    if isinstance(parameters.get("aspect_ratio"), str):
        ctx["aspect_ratio"] = parameters["aspect_ratio"]
    return ctx


def render_for(element: Element, info: ToolInfo, parameters: dict[str, Any], surface: str,
               lora_active: Optional[bool]) -> str:
    ctx = template_context(info, parameters, surface, lora_available=bool(element.loras), lora_active=lora_active)
    return template.render(element.instructions, ctx).text


def _param_key(elements: list[Element], parameters: dict[str, Any]) -> dict[str, Any]:
    """Only the tool parameters some element's instructions ask about."""
    wanted = set().union(*(e.referenced_vars for e in elements)) if elements else set()
    out: dict[str, Any] = {}
    if "aspect_ratio" in wanted and isinstance(parameters.get("aspect_ratio"), str):
        out["aspect_ratio"] = parameters["aspect_ratio"]
    if "orientation" in wanted:
        out["orientation"] = _orientation(parameters)
    return out


# --------------------------------------------------------------------------- planning

def remaining_slots(info: ToolInfo, overrides: Overrides) -> int:
    return max(0, info.max_ref_images - overrides.user_ref_count - len(overrides.pinned_refs))


def needs_judgment(elements: list[Element], remaining: int) -> bool:
    """Whether a model must choose. Structural only: counts and flags, never the prompt's words."""
    refs = [m for e in elements for m in e.media] if remaining > 0 else []
    if any(m.get("conditional") for m in refs):
        return True
    if len(refs) > remaining:
        return True
    return any(len(e.loras) > 1 for e in elements)


def _ref_out(element: Element, entry: dict[str, Any], reason: str = "") -> dict[str, Any]:
    return {
        "element_asset_id": element.asset_id,
        "member_key": entry["key"],
        "asset_id": entry.get("asset_id"),
        "media_id": entry.get("media_id"),
        "file_hash": entry.get("file_hash"),
        "file_format": entry.get("file_format"),
        "width": entry.get("width"),
        "height": entry.get("height"),
        "title": entry.get("title") or "",
        "reason": reason,
    }


def _lora_out(element: Element, lora: LoraMatch, weight: Optional[float] = None, reason: str = "") -> dict[str, Any]:
    return {
        "element_asset_id": element.asset_id,
        "lora_key": lora.key,
        "path": lora.path,
        "weight": round(float(weight if weight is not None else lora.weight), 3),
        "trigger": lora.trigger,
        "reason": reason,
    }


def deterministic_plan(elements: list[Element], remaining: int, *, fallback: bool = False) -> dict[str, Any]:
    """Refs and LoRAs without a model.

    Not a fallback: everything fits, so every reference goes on in menu order.
    Fallback: each element's first LoRA, and its main image (the cover, else its first
    reference that isn't one of several alternatives) taken in turns within the budget.
    """
    refs: list[dict[str, Any]] = []
    if remaining > 0:
        if not fallback:
            for e in elements:
                for m in e.media:
                    refs.append(_ref_out(e, m))
            refs = refs[:remaining]
        else:
            queues = []
            for e in elements:
                ordered = sorted(e.media, key=lambda m: (m["key"] != e.cover_key, bool(m.get("conditional"))))
                queues.append([(e, m) for m in ordered[:1]])
            while len(refs) < remaining and any(queues):
                for q in queues:
                    if q and len(refs) < remaining:
                        e, m = q.pop(0)
                        refs.append(_ref_out(e, m))
    loras = [_lora_out(e, e.loras[0]) for e in elements if e.loras]
    return {"selected_refs": refs, "selected_loras": loras, "resolved_guidance": ""}


_SYSTEM = """You help set up an image or video generation. The user attached elements: reusable \
characters, products, places, styles or brands. Each element has instructions, a menu of reference \
images and sometimes LoRAs (add-on model weights that draw it).

Choose, for the user's prompt:
- references: the reference images that best serve this prompt. Use each image's description and \
its "use when" note. Never choose more than the number of free slots; when elements compete, share \
the slots so each element that matters to the prompt gets its most useful image. If the prompt \
leaves something open (an expression, a pose), prefer a neutral, versatile image.
- loras: which of each element's LoRAs to switch on, and at what weight (default unless the \
instructions say otherwise). At most one per element unless its instructions ask for more.
- guidance: two to four plain sentences for the writer who turns the prompt into the final text: \
what must stay the same, what an active LoRA already draws and so must not be described, and what \
each chosen reference image is for (write [image N] for each, N being its place in your references \
list). Name things as a person would; never write keys, file names or the word LoRA. No lists, no headings.

Reply with JSON only, exactly this shape:
{"references": [{"element": 1, "key": "...", "why": "..."}], "loras": [{"element": 1, "key": "...", "weight": 0.8}], "guidance": "..."}"""


def build_messages(elements: list[Element], info: ToolInfo, prompt: str, remaining: int,
                   parameters: dict[str, Any], overrides: Overrides) -> list[dict[str, Any]]:
    parts = [
        f"Model: {info.model_family}. Task: {info.task_type or 'image'}.",
        f"Free reference image slots: {remaining}.",
        "",
        "Prompt:",
        prompt.strip() or "(empty)",
    ]
    for n, e in enumerate(elements, 1):
        parts += ["", f"## Element {n}: {e.name}" + (f" ({e.kind})" if e.kind else "")]
        rendered = render_for(e, info, parameters, "resolver", None).strip()
        if rendered:
            parts += ["Instructions:", rendered]
        if e.media and remaining > 0:
            parts.append("Reference images:")
            for m in e.media:
                bits = [f'- key "{m["key"]}"']
                if m.get("title"):
                    bits.append(m["title"])
                if m.get("labels"):
                    bits.append("labels: " + ", ".join(m["labels"]))
                if m.get("usage_hint"):
                    bits.append("use when: " + m["usage_hint"])
                if m["key"] == e.cover_key:
                    bits.append("main image")
                parts.append("; ".join(bits))
        if e.loras:
            parts.append("LoRAs:")
            for lo in e.loras:
                bits = [f'- key "{lo.key}"', f"default weight {lo.weight:g}"]
                if lo.trigger:
                    bits.append(f'trigger word "{lo.trigger}"')
                if lo.notes:
                    bits.append(lo.notes)
                parts.append("; ".join(bits))
        kept = [k for a, k in overrides.pinned_refs if a == e.asset_id]
        if kept:
            parts.append("Already placed by the user: " + ", ".join(kept))
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": "\n".join(parts)}]


def _json_object(text: str) -> Optional[dict[str, Any]]:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _element_for(raw: Any, elements: list[Element]) -> Optional[Element]:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if 1 <= n <= len(elements):
        return elements[n - 1]
    return next((e for e in elements if e.asset_id == n), None)


_MODEL_IMAGE = re.compile(r"\[image\s*(\d+)\]", re.I)
_REF_TOKEN = re.compile(r"\{ref:(\d+)\}")


def _retoken(text: str, pattern: re.Pattern, places: dict[int, int]) -> str:
    """Image references in guidance re-pointed: `places` maps an image's old place to its place in
    selected_refs (1-based), written {ref:N} for ToolView to number as the images are placed."""
    def sub(m: re.Match) -> str:
        place = places.get(int(m.group(1)))
        return f"{{ref:{place}}}" if place else "a reference image"
    return pattern.sub(sub, text)


def parse_reply(text: str, elements: list[Element], remaining: int) -> tuple[Optional[dict[str, Any]], list[str]]:
    """The model's plan, kept to what exists and what fits. None when nothing usable came back."""
    data = _json_object(text)
    if data is None:
        return None, []
    warnings: list[str] = []
    refs: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    places: dict[int, int] = {}   # the model's numbering of its references -> place in refs
    dropped = 0
    for n, item in enumerate(data.get("references") or [], 1):
        if not isinstance(item, dict):
            continue
        e = _element_for(item.get("element"), elements)
        key = str(item.get("key") or "")
        entry = next((m for m in e.media if m["key"] == key), None) if e else None
        if entry is None:
            dropped += 1
            continue
        if (e.asset_id, key) in seen:
            places[n] = next(i for i, r in enumerate(refs, 1) if (r["element_asset_id"], r["member_key"]) == (e.asset_id, key))
            continue
        seen.add((e.asset_id, key))
        refs.append(_ref_out(e, entry, str(item.get("why") or "")[:_MAX_REASON]))
        places[n] = len(refs)
    if dropped:
        log.info(f"[elements] resolver named {dropped} reference(s) that don't exist; dropped")
    refs = refs[:remaining]
    loras: list[dict[str, Any]] = []
    lseen: set[tuple[int, str]] = set()
    for item in data.get("loras") or []:
        if not isinstance(item, dict):
            continue
        e = _element_for(item.get("element"), elements)
        key = str(item.get("key") or "")
        lora = next((lo for lo in e.loras if lo.key == key), None) if e else None
        if lora is None or (e.asset_id, key) in lseen:
            continue
        lseen.add((e.asset_id, key))
        weight = item.get("weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not (-4.0 <= weight <= 4.0):
            weight = lora.weight
        loras.append(_lora_out(e, lora, weight))
    guidance = data.get("guidance")
    guidance = guidance.strip() if isinstance(guidance, str) else ""
    guidance = _retoken(guidance, _MODEL_IMAGE, {n: p for n, p in places.items() if p <= remaining})
    if not refs and not loras and not guidance:
        return None, warnings
    return {"selected_refs": refs, "selected_loras": loras, "resolved_guidance": guidance}, warnings


async def default_ask_model(messages: list[dict[str, Any]], project_id: Optional[int]) -> str:
    """The chat model Fluent and Enhance use for background work, without reasoning."""
    from llm import llm_complete_text
    from llm_correlation import llm_correlation_context
    from llm_resolver import get_effective_llm_config

    cfg = await get_effective_llm_config("tool_assistant", project_id)
    with llm_correlation_context("element-resolver"):
        return await llm_complete_text(config=cfg, messages=messages, max_tokens=2500, temperature=0.2,
                                       enable_thinking=False, retry_reasoning=False)


async def model_fingerprint(project_id: Optional[int]) -> Optional[str]:
    try:
        from llm_resolver import get_effective_llm_config
        cfg = await get_effective_llm_config("tool_assistant", project_id)
        return cfg.get_model() if cfg is not None else None
    except Exception:
        return None


# --------------------------------------------------------------------------- the store

_memory: dict[tuple[str, str], dict[str, Any]] = {}   # by (_scope, key)
_MEMORY_LIMIT = 256
_inflight: dict[tuple[str, str], asyncio.Future] = {}


def store_for(profile_id: Optional[str]) -> ProgramStore:
    import app_dirs
    from core.profile_context import get_current_profile
    return ProgramStore(app_dirs.get_profile_dir(profile_id or get_current_profile()) / "element_resolutions")


def _scope(session, profile_id: Optional[str]) -> str:
    """Whose plans these are: media and asset ids mean something only in one profile's library."""
    try:
        from core.profile_context import get_current_profile
        profile = profile_id or get_current_profile()
    except Exception:
        profile = profile_id
    bind = getattr(session, "bind", None)
    return f"{profile or ''}|{getattr(bind, 'url', '') or ''}"


def _rehydrate(plan: dict[str, Any], elements: list[Element], remaining: int) -> dict[str, Any]:
    """A stored plan's choices (by element and member key) bound to the menus as loaded now: a
    linked image follows its asset's current revision, and a choice gone from the menu (removed,
    excluded or kept since) is dropped with its guidance reference."""
    by_id = {e.asset_id: e for e in elements}
    refs: list[dict[str, Any]] = []
    places: dict[int, int] = {}
    for n, r in enumerate(plan.get("selected_refs") or [], 1):
        e = by_id.get(r.get("element_asset_id"))
        entry = next((m for m in e.media if m["key"] == r.get("member_key")), None) if e else None
        if entry is None or len(refs) >= remaining:
            continue
        refs.append(_ref_out(e, entry, str(r.get("reason") or "")))
        places[n] = len(refs)
    loras: list[dict[str, Any]] = []
    for lo in plan.get("selected_loras") or []:
        e = by_id.get(lo.get("element_asset_id"))
        match = next((x for x in e.loras if x.key == lo.get("lora_key")), None) if e else None
        if match is not None:
            loras.append(_lora_out(e, match, lo.get("weight")))
    guidance = _retoken(str(plan.get("resolved_guidance") or ""), _REF_TOKEN, places)
    return {"selected_refs": refs, "selected_loras": loras, "resolved_guidance": guidance}


def _remember(key: tuple[str, str], entry: dict[str, Any]) -> None:
    _memory[key] = entry
    while len(_memory) > _MEMORY_LIMIT:
        _memory.pop(next(iter(_memory)))


def _cached(store: Optional[ProgramStore], key: str, scope: str) -> Optional[dict[str, Any]]:
    if (scope, key) in _memory:
        return _memory[(scope, key)]
    entry = store.get(key) if store is not None else None
    if entry is not None:
        _remember((scope, key), entry)
    return entry


# --------------------------------------------------------------------------- resolve

def _finish(plan: dict[str, Any], elements: list[Element], info: ToolInfo, parameters: dict[str, Any],
            overrides: Overrides, warnings: list[str], enhance_enabled: bool) -> dict[str, Any]:
    """Stage two: each element's instructions rendered with its LoRA's actual state, per surface."""
    active = {lo["element_asset_id"] for lo in plan["selected_loras"]} | {a for a, _k in overrides.pinned_loras}
    out_elements = []
    for e in elements:
        rendered = {s: render_for(e, info, parameters, s, e.asset_id in active) for s in SURFACES}
        out_elements.append({
            "asset_id": e.asset_id, "revision_id": e.revision_id, "name": e.name, "kind": e.kind,
            "instructions": rendered,
        })
        if e.lora_elsewhere:
            warnings.append(f"{e.name}'s LoRA is for another model.")
        if not enhance_enabled and not e.media and not e.loras and rendered["enhance"].strip():
            warnings.append(f"{e.name} works through the prompt: turn on Enhance to use it.")
    guidance = plan.get("resolved_guidance") or ""
    return {**plan, "resolved_guidance": guidance, "elements": out_elements, "warnings": warnings}


async def _with_paths(session, result: dict[str, Any]) -> dict[str, Any]:
    """Each chosen reference's file, as a tool slot takes it."""
    from sqlalchemy import select

    from database import MediaItem

    ids = [r["media_id"] for r in result["selected_refs"] if r.get("media_id")]
    if not ids:
        return result
    rows = {m.id: m for m in await session.scalars(select(MediaItem).where(MediaItem.id.in_(ids)))}
    refs = []
    for r in result["selected_refs"]:
        media = rows.get(r.get("media_id"))
        if media is None:
            continue
        refs.append({**r, "file_path": media.file_path, "file_hash": media.file_hash,
                     "width": media.width, "height": media.height})
    return {**result, "selected_refs": refs}


async def resolve(
    session,
    *,
    elements: list[dict[str, Any]],
    tool_id: str,
    prompt: str,
    parameters: Optional[dict[str, Any]] = None,
    task_type: Optional[str] = None,
    enhance_enabled: bool = True,
    overrides: Optional[dict[str, Any]] = None,
    project_id: Optional[int] = None,
    profile_id: Optional[str] = None,
    info: Optional[ToolInfo] = None,
    ask_model: Optional[AskModel] = None,
    store: Optional[ProgramStore] = None,
    use_store: bool = True,
    timeout: float = LLM_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """The resolution plan. Never raises for model trouble: that is a fallback plan."""
    parameters = parameters or {}
    ov = Overrides.parse(overrides)
    info = info or await tool_info(tool_id, task_type)
    loaded, warnings = await load_elements(session, elements, info, ov)
    remaining = remaining_slots(info, ov)

    base_key = {
        "v": RESOLVER_VERSION,
        "elements": [(e.asset_id, e.revision_id) for e in loaded],
        "tool": (tool_id, info.model_family, info.task_type, remaining,
                 sorted(lo.path for e in loaded for lo in e.loras)),
        "overrides": ov.as_key(),
        "params": _param_key(loaded, parameters),
    }

    if not loaded or not needs_judgment(loaded, remaining):
        plan = deterministic_plan(loaded, remaining)
        result = _finish(plan, loaded, info, parameters, ov, warnings, enhance_enabled)
        return await _with_paths(session, {**result, "mode": "deterministic", "key": program_key(base_key)})

    model = await model_fingerprint(project_id) if ask_model is None else "injected"
    key = program_key({**base_key, "prompt": " ".join((prompt or "").split()), "model": model})
    if use_store and store is None:
        try:
            store = store_for(profile_id)
        except Exception:
            store = None
    scope = _scope(session, profile_id)
    hit = _cached(store if use_store else None, key, scope) if use_store else None
    if hit is not None:
        hit = _rehydrate(hit, loaded, remaining)
        result = _finish(hit, loaded, info, parameters, ov, list(warnings), enhance_enabled)
        return await _with_paths(session, {**result, "mode": "cached", "key": key})

    # One model call per key: a debounced re-resolve and Run's wait share it.
    flight = (scope, key)
    pending = _inflight.get(flight)
    if pending is None:
        pending = asyncio.ensure_future(_judge(loaded, info, prompt, remaining, parameters, ov, project_id,
                                               ask_model, timeout))
        _inflight[flight] = pending
        pending.add_done_callback(lambda _f, k=flight: _inflight.pop(k, None))
    plan, judged = await asyncio.shield(pending)
    if judged:
        if use_store:
            _remember(flight, plan)
            if store is not None:
                try:
                    store.put(key, plan)
                except OSError as exc:
                    log.warning(f"[elements] Could not store a resolution: {exc}")
        mode = "resolved"
    else:
        mode = "fallback"
        warnings = [*warnings, "Picked each element's main image; the assistant wasn't available."]
    result = _finish(plan, loaded, info, parameters, ov, warnings, enhance_enabled)
    return await _with_paths(session, {**result, "mode": mode, "key": key})


async def _judge(elements: list[Element], info: ToolInfo, prompt: str, remaining: int,
                 parameters: dict[str, Any], ov: Overrides, project_id: Optional[int],
                 ask_model: Optional[AskModel], timeout: float) -> tuple[dict[str, Any], bool]:
    messages = build_messages(elements, info, prompt, remaining, parameters, ov)
    try:
        if ask_model is not None:
            reply = await asyncio.wait_for(ask_model(messages), timeout)
        else:
            reply = await asyncio.wait_for(default_ask_model(messages, project_id), timeout)
        plan, _w = parse_reply(reply, elements, remaining)
        if plan is not None:
            return plan, True
        log.warning(f"[elements] resolver reply wasn't usable; using the main images: {(reply or '')[:200]!r}")
    except asyncio.TimeoutError:
        log.warning("[elements] resolver timed out; using the main images")
    except Exception as exc:
        log.warning(f"[elements] resolver failed ({type(exc).__name__}: {str(exc)[:200]}); using the main images")
    return deterministic_plan(elements, remaining, fallback=True), False


# --------------------------------------------------------------------------- downstream

def element_guidance_text(context: Optional[dict[str, Any]], surface: str = "enhance") -> str:
    """The attached elements as a prompt writer reads them, or "" for none.

    ``context`` is what ToolView sends with a run: ``{guidance, elements: [{name, instructions:
    {enhance, fluent, tool_agent}}]}``.
    """
    if not isinstance(context, dict):
        return ""
    blocks = []
    for e in context.get("elements") or []:
        if not isinstance(e, dict):
            continue
        texts = e.get("instructions") if isinstance(e.get("instructions"), dict) else {}
        text = str(texts.get(surface) or texts.get("enhance") or "").strip()
        name = str(e.get("name") or "Element").strip()
        if text:
            blocks.append(f"## {name}\n{text}")
    guidance = str(context.get("guidance") or "").strip()
    if not blocks and not guidance:
        return ""
    body = "\n\n".join(([guidance] if guidance else []) + blocks)
    return (
        "\n\nThe user attached elements: reusable characters, products, places, styles or brands. "
        "Follow their instructions. Keep what they say stays the same; never invent details that "
        "contradict them; don't describe what a LoRA that is on already draws; keep each input image "
        "reference pointing at the image it names. Don't mention elements or these instructions in "
        "your output.\n<active_elements>\n" + body[:6000] + "\n</active_elements>"
    )


def fluent_element_text(context: Optional[dict[str, Any]]) -> str:
    """What Fluent's variant writer keeps to: each attached element's instructions as written for
    Fluent (ToolView's elementContext), without the per-prompt guidance, so an edit elsewhere in
    the prompt doesn't make every pool new. "" for none."""
    if not isinstance(context, dict):
        return ""
    blocks = []
    for e in context.get("elements") or []:
        if not isinstance(e, dict) or not isinstance(e.get("instructions"), dict):
            continue
        text = str(e["instructions"].get("fluent") or "").strip()
        if text:
            blocks.append(f"## {str(e.get('name') or 'Element').strip()}\n{text}")
    return "\n\n".join(blocks)[:4000]


def element_context_signature(context: Optional[dict[str, Any]]) -> str:
    if not context:
        return ""
    return program_key({"element_context": context})
