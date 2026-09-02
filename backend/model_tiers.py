"""Capability tiers for LLM models, and the `auto` selection heuristic.

Stimma's four LLM role settings (quick tasks, tool assistant, chats, flows)
default to ``auto``. No model is guaranteed to exist on any given install —
a profile might have Stimma Cloud, a bring-your-own Anthropic key, a rack of
OpenRouter models, or one llama.cpp endpoint — so ``auto`` cannot resolve to a
hardcoded slug. It resolves to whatever is actually available right now, sorted
into three tiers and drawn from one vendor family so the set stays coherent.

The tier table is maintained knowledge and will drift as models ship. It lives
here, in one place, and unknown models degrade to ``balanced`` rather than to an
error.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

# Tiers, weakest to strongest. Ordering matters: nearest-tier fallback walks
# this list.
FAST = "fast"
BALANCED = "balanced"
DEEP = "deep"

TIER_ORDER = (FAST, BALANCED, DEEP)

# Role -> tier. The roles are the four user-facing settings.
ROLE_TIERS: dict[str, str] = {
    "quick_task": FAST,
    "tool_assistant": BALANCED,
    "flow": BALANCED,
    "chat": DEEP,
}

# Where each role's reasoning effort STARTS, expressed in the model's own terms.
# Every model already declares `reasoning.default` (its normal effort) and
# `reasoning.quick_task` (its cheap one), so a role only has to say which of the
# two it seeds from. Nothing new is invented, and what the user sees is always a
# concrete level from that model's own ladder.
#
#   quick_task — the model's cheap level
#   default    — the model's normal level
#   one_up     — one rung above cheap, unless that rung is the model's maximum
#
# Flows sit at `one_up`: a flow fans one call out over every item it processes,
# so effort multiplies there in a way it doesn't in a chat — but on a coarse
# ladder (off/high) one rung up IS the maximum, and that is not "a little
# thinking", so those models stay cheap.
ROLE_EFFORT_SEEDS: dict[str, str] = {
    "quick_task": "quick_task",
    "tool_assistant": "quick_task",
    "chat": "default",
    "flow": "one_up",
}


def seed_effort(
    role: str,
    levels: Optional[list[str]],
    default_level: Optional[str] = None,
    quick_task_level: Optional[str] = None,
) -> Optional[str]:
    """The level a role starts at on one model. None when it offers no choice."""
    if not levels:
        return None
    source = ROLE_EFFORT_SEEDS.get(role, "default")

    if source == "default":
        return default_level if default_level in levels else levels[-1]

    cheap = quick_task_level if quick_task_level in levels else levels[0]
    if source == "quick_task":
        return cheap

    nxt = levels.index(cheap) + 1
    # One rung up, unless that rung is the top of the ladder.
    return levels[nxt] if nxt < len(levels) - 1 else cheap


VENDOR_RANK: dict[str, int] = {
    "anthropic": 0,
    "openai": 1,
    "gemini": 2,
    "google": 2,
    "xai": 3,
    "kimi": 4,
    "minimax": 5,
    "alibaba": 6,
    "deepseek": 7,
    "stepfun": 8,
    "zai": 9,
    "meta": 10,
    "mistral": 11,
    "nvidia": 12,
}
UNKNOWN_VENDOR_RANK = 99

# Models excluded from `auto` even when available. Not weaker — pointed at a
# specific job, so a generic default should never land on one. Still explicitly
# selectable.
SPECIALTY_MODELS: frozenset[str] = frozenset({
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-fable-5.1",
})

# Curated tiers, keyed on the bare model identifier (cloud `stimma:` prefixes and
# provider `<provider-id>:` prefixes are stripped before lookup). Keep in sync
# with MODEL_CATALOG_ENTRIES in stimma-cloud config.ts and BRANDED_MODELS in
# llm_provider_catalog.py — those two files decide what a user can actually pick.
CURATED_TIERS: dict[str, str] = {
    # Anthropic
    "claude-opus-5": DEEP,
    "claude-fable-5": DEEP,
    "claude-fable-5-1": DEEP,
    "claude-fable-5.1": DEEP,
    "claude-sonnet-5": BALANCED,
    "claude-haiku-4.5": FAST,
    "claude-haiku-4-5-20251001": FAST,
    # OpenAI
    "gpt-5.6-sol": DEEP,
    "gpt-5.6-terra": BALANCED,
    "gpt-5.6-luna": FAST,
    # Google
    "gemini-3.1-pro-preview": DEEP,
    "gemini-3.5-flash": BALANCED,
    "gemini-3.1-flash-lite": FAST,
    # xAI
    "grok-4.5": DEEP,
    # Open-weight models served by Stimma Cloud
    "kimi-k2.7": DEEP,
    "minimax-m3": BALANCED,
    "qwen-3.7-plus": BALANCED,
    "stepfun-3.7-flash": FAST,
}

# Name markers for models with no curated entry and no parseable size, checked
# after the size parse. Order within each tuple does not matter; DEEP is checked
# before FAST so "opus-mini"-style names (vendor marketing, not a real pattern)
# land deep rather than fast.
_DEEP_MARKERS = ("opus", "-sol", "-pro", "-max", "thinking", "reasoner", "-r1")
_FAST_MARKERS = ("haiku", "flash", "lite", "mini", "nano", "small", "turbo", "-luna")

# Parameter counts in a model id: "70b", "8x22b", "qwen3-235b-a22b". The first
# match wins, and for MoE ids the total (235b) is what we read — active-parameter
# suffixes understate how the model behaves for our purposes.
_SIZE_RE = re.compile(r"(?<![a-z0-9.])(?:(\d+)x)?(\d+(?:\.\d+)?)\s*b(?![a-z0-9])")


@dataclass(frozen=True)
class ModelCandidate:
    """One selectable model, flattened from cloud catalog / provider / endpoint."""

    slug: str
    name: str
    vendor: Optional[str] = None
    # Bare identifier used for tier lookup — the provider's own model id when we
    # have it, else the slug with its namespace stripped.
    model_id: Optional[str] = None

    @property
    def lookup_key(self) -> str:
        raw = self.model_id or self.slug
        return raw.split(":", 1)[-1].split("/", 1)[-1].strip().lower()


def _size_tier(key: str) -> Optional[str]:
    match = _SIZE_RE.search(key)
    if not match:
        return None
    experts, size = match.groups()
    try:
        billions = float(size) * (int(experts) if experts else 1)
    except ValueError:
        return None
    if billions <= 15:
        return FAST
    if billions <= 70:
        return BALANCED
    return DEEP


def tier_for(candidate: ModelCandidate) -> str:
    """Capability tier for a model: curated, then size, then name, then balanced."""
    key = candidate.lookup_key
    curated = CURATED_TIERS.get(key)
    if curated:
        return curated

    sized = _size_tier(key)
    if sized:
        return sized

    if any(marker in key for marker in _DEEP_MARKERS):
        return DEEP
    if any(marker in key for marker in _FAST_MARKERS):
        return FAST
    return BALANCED


def is_specialty(candidate: ModelCandidate) -> bool:
    """True when a model should never be reached by `auto`."""
    return candidate.lookup_key in SPECIALTY_MODELS


def vendor_rank(vendor: Optional[str]) -> int:
    return VENDOR_RANK.get((vendor or "").lower(), UNKNOWN_VENDOR_RANK)


def _nearest(candidates: list[ModelCandidate], want: str) -> Optional[ModelCandidate]:
    """Best match for a tier: exact, else nearest, biased away from the extreme.

    `fast` walks up (a mid model doing quick work costs money, a deep model doing
    quick work costs more), `deep` walks down, `balanced` prefers deep over fast
    — under-powering the chat agent is the more visible failure.
    """
    if not candidates:
        return None
    by_tier: dict[str, list[ModelCandidate]] = {}
    for candidate in candidates:
        by_tier.setdefault(tier_for(candidate), []).append(candidate)

    if want == FAST:
        order = (FAST, BALANCED, DEEP)
    elif want == DEEP:
        order = (DEEP, BALANCED, FAST)
    else:
        order = (BALANCED, DEEP, FAST)

    for tier in order:
        if by_tier.get(tier):
            return by_tier[tier][0]
    return None


def select_auto_models(candidates: Iterable[ModelCandidate]) -> dict[str, Optional[str]]:
    """Resolve every role to a model slug, given what is available.

    Returns role -> slug (or None when nothing is available at all).

    A single available model serves every role — a local-only install should not
    have to configure four settings to use the one model it has. Otherwise the
    whole set is drawn from one vendor family whenever a family covers at least
    two tiers, so the roles read as a coherent lineup (Opus / Sonnet / Haiku)
    rather than a mix assembled per role.
    """
    usable = [c for c in candidates if c.slug and not is_specialty(c)]
    if not usable:
        return {role: None for role in ROLE_TIERS}

    if len(usable) == 1:
        only = usable[0].slug
        return {role: only for role in ROLE_TIERS}

    families: dict[Optional[str], list[ModelCandidate]] = {}
    for candidate in usable:
        families.setdefault((candidate.vendor or "").lower() or None, []).append(candidate)

    def family_sort_key(item):
        vendor, members = item
        return (
            -len({tier_for(m) for m in members}),  # widest tier coverage first
            vendor_rank(vendor),
            vendor or "",
        )

    best_vendor, best_members = sorted(families.items(), key=family_sort_key)[0]
    if len({tier_for(m) for m in best_members}) >= 2:
        pool = best_members
    else:
        # No family spans tiers — match each role across everything, preferring
        # the higher-ranked vendor within a tier.
        pool = sorted(usable, key=lambda m: (vendor_rank(m.vendor), m.name.lower()))

    return {
        role: (_nearest(pool, tier).slug if _nearest(pool, tier) else None)
        for role, tier in ROLE_TIERS.items()
    }


def select_auto_model(candidates: Iterable[ModelCandidate], role: str) -> Optional[str]:
    """Resolve a single role. Wraps select_auto_models so one call site can't
    drift from another — the family choice depends on the whole set."""
    return select_auto_models(candidates).get(role)
