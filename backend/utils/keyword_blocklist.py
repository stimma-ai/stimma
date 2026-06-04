"""
Keyword blocklist for pre-share content moderation.

Fast, local check against prompt text, titles, descriptions, and lineage
metadata for terms that indicate clearly prohibited content (CSAM-adjacent,
illegal content). Runs before the cloud moderation API call.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stimma.backend.database import MediaItem


@dataclass
class BlocklistResult:
    blocked: bool
    matched_pattern: str | None = None  # For internal logging only — never expose to user


# Leetspeak normalization map — only non-digit substitutions are safe to
# apply globally.  Digit-based leet (0→o, 1→i, 3→e …) is applied in a
# second pass so that patterns containing literal digits (e.g. "13yo")
# still match on the original text.
_LEET_MAP_SAFE = str.maketrans({
    "@": "a",
    "$": "s",
})

_LEET_MAP_DIGITS = str.maketrans({
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
})


def _normalize_base(text: str) -> str:
    """Lowercase, collapse whitespace, apply safe (non-digit) leet substitutions."""
    text = text.lower().translate(_LEET_MAP_SAFE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_leet(text: str) -> str:
    """Apply digit-based leetspeak normalization on top of base normalization."""
    return text.translate(_LEET_MAP_DIGITS)


# Pattern definitions. Each is (compiled_regex, label_for_logging).
# Patterns are designed to minimize false positives while catching common
# circumvention attempts.
_RAW_PATTERNS: list[tuple[str, str]] = [
    # Age-specific minor references
    (r"\b\d{1,2}\s*y[\s./\\-]*o\b", "age-yo"),
    (r"\b\d{1,2}\s*year\s*old\b", "age-year-old"),
    (r"\bunder\s*age[d]?\b", "underage"),
    (r"\bunder\s*18\b", "under-18"),
(r"\bpre\s*-?\s*teen\b", "preteen"),
    (r"\bjail\s*-?\s*bait\b", "jailbait"),

    # CSAM terminology
    (r"\bchild\s*(porn|sex|eroti|nude|naked)", "csam-child"),
    (r"\b(porn|sex|eroti|nude|naked)\s*child", "csam-child-rev"),
    (r"\bkid(s|die)?\s*(porn|sex|eroti|nude|naked)", "csam-kid"),
    (r"\bpedo(phile|philia)?\b", "pedo"),
    (r"\bcp\b", "cp"),

    # Anime/manga CSAM-adjacent
    (r"\bloli(con|ta)?\b", "loli"),
    (r"\bshota(con)?\b", "shota"),
    (r"\bcunny\b", "cunny"),
    (r"\btoddler(con|ler)?\b", "toddler"),
    (r"\bflat\s*chest\s*(child|girl|boy|kid|young|loli|teen)", "flat-chest-minor"),

    # Young + sexualized combinations
    (r"\byoung\s*(girl|boy|child|kid)\s*(nude|naked|sex|eroti|porn|breast|nipple)", "young-sexual"),
    (r"\b(nude|naked|sex|eroti|porn)\s*young\s*(girl|boy|child|kid)", "sexual-young"),
    (r"\blittle\s*(girl|boy)\s*(nude|naked|sex|eroti|porn|breast|nipple)", "little-sexual"),
    (r"\bteen\s*(girl|boy)?\s*(nude|naked|sex|porn)\b", "teen-sexual"),

    # Incest
    (r"\b(mom|mother|dad|father|sister|brother|daughter|son)\s*(sex|fuck|porn|eroti|incest)", "incest"),
    (r"\bincest\b", "incest-term"),

    # Bestiality
    (r"\b(bestiality|zoophil|animal\s*sex|animal\s*porn)\b", "bestiality"),

    # Non-consensual
    (r"\b(rape|raping)\b", "non-consensual"),
    (r"\bforced\s*(sex|porn|penetrat)", "forced-sexual"),
    (r"\bnon\s*-?\s*con(sensual)?\b", "non-con"),

    # Real people (deepfake-adjacent)
    (r"\bdeep\s*-?\s*fake\s*(porn|nude|naked|sex)", "deepfake-porn"),
]

# Compile patterns once at import time
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(pattern), label)
    for pattern, label in _RAW_PATTERNS
]


def check_blocklist(texts: list[str]) -> BlocklistResult:
    """Check a list of text fields against the keyword blocklist.

    Each text is checked twice: once with base normalization (preserves digits
    so patterns like "13yo" work) and once with full leetspeak normalization
    (catches "l0li" → "loli", etc.).

    Args:
        texts: List of text strings to check (title, description, prompts, etc.).
               None values are safely skipped.

    Returns:
        BlocklistResult with blocked=True if any pattern matched.
    """
    for text in texts:
        if not text:
            continue
        base = _normalize_base(text)
        leet = _normalize_leet(base)
        for variant in (base, leet):
            for pattern, label in _PATTERNS:
                if pattern.search(variant):
                    return BlocklistResult(blocked=True, matched_pattern=label)

    return BlocklistResult(blocked=False)


def gather_texts_for_blocklist(
    media_item: MediaItem,
    title: str | None = None,
    description: str | None = None,
) -> list[str]:
    """Gather all relevant text fields from a media item for blocklist checking.

    Includes title, description, extracted_prompt, vlm_caption, and prompts
    from the generation_metadata lineage_trace.
    """
    texts = [title, description]

    if hasattr(media_item, "extracted_prompt"):
        texts.append(media_item.extracted_prompt)
    if hasattr(media_item, "vlm_caption"):
        texts.append(media_item.vlm_caption)

    # Extract prompts from generation_metadata (includes lineage_trace)
    if hasattr(media_item, "generation_metadata") and media_item.generation_metadata:
        try:
            gen_meta = json.loads(media_item.generation_metadata) if isinstance(media_item.generation_metadata, str) else media_item.generation_metadata
            # Direct prompt on the item
            if gen_meta.get("prompt"):
                texts.append(gen_meta["prompt"])
            if gen_meta.get("negative_prompt"):
                texts.append(gen_meta["negative_prompt"])
            # Parameters block
            params = gen_meta.get("parameters", {})
            if params.get("prompt"):
                texts.append(params["prompt"])
            if params.get("negative_prompt"):
                texts.append(params["negative_prompt"])
            # Lineage trace — walk ancestor entries
            for ancestor in gen_meta.get("lineage_trace", []):
                if ancestor.get("prompt"):
                    texts.append(ancestor["prompt"])
                if ancestor.get("negative_prompt"):
                    texts.append(ancestor["negative_prompt"])
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

    return texts
