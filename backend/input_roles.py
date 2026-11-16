"""What each input image is for, read from the request: the picture being changed,
or a reference for a new picture the request describes.

An image tool fed input images gets two kinds of request. "Change the shirt to
blue" edits the picture it is given; "this woman on a rainy street at night"
asks for a new picture of someone in the image. One request can mix them: "put
the woman from image 1 into image 2" changes image 2 and takes the woman from
image 1. The improver writes an edit instruction for the first kind and a
description of the new picture for the second.

The intent is the user's: it is read from what they typed and how many images
they gave, once, and kept on disk. Nothing downstream changes it: a wildcard
drawn for one image, Direct's fills or the improver's own rewrites are not new
questions, so a submit asks about the prompt as typed and hands the answer down
(roles_for_submit). The images themselves are not shown: the words decide, and a
new crop or a swapped image doesn't change what the user asked for.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.logging import get_logger

log = get_logger(__name__)

# Part of every cache key: a change to how roles are asked for or read starts afresh.
ROLES_VERSION = "input-roles-2"

CHANGE = "change"
REFERENCE = "reference"

_SYSTEM_PROMPT = """\
You decide what each input image is for in a request to an image model. The model receives the request and the input images together.

Each image has one of two roles:
- "change": the picture the result is made from. Its scene and composition stay, and the request changes something in it: an object, a color, clothing, the background, the text, the style or medium, the framing, or adding or removing something. "Change the shirt to blue", "remove the man on the left", "make it a watercolor", "add a hat", "extend the sky upward" all change their image.
- "reference": the image gives something (a person or character, an object, a garment, a pose, a style or palette) to a new picture whose scene the request describes. "This woman walking down a rainy Tokyo street at night", "the same character riding a horse on a beach", "a poster in the style of this painting", "these two people sitting at a campfire" all use their images as references.

One request can use images in both roles: in "put the woman from image 1 into image 2", image 2 is the change and image 1 is a reference. You are not shown the images, only told how many there are. A request that describes a whole new scene, setting or composition makes its images references, even when it is short. A request that only says what is different about the picture as it stands makes its image the change. When it is unclear, choose "change".

For each image also say in a few words what the request uses it for: "the picture being changed", or what it gives ("the woman: her face and look", "the red jacket", "the painting's style").

Answer with JSON only, no other text:
{"images": [{"image": 1, "role": "change", "gives": "the picture being changed"}]}"""


@dataclass(frozen=True)
class InputRole:
    image: int  # 1-based position among the tool's input images
    role: str   # CHANGE or REFERENCE
    gives: str  # what the request uses it for, in a few words


def all_references(roles: Optional[Sequence[InputRole]]) -> bool:
    """Whether every input is a reference: the request describes a new picture."""
    return bool(roles) and all(r.role == REFERENCE for r in roles)


def _cache_dir() -> Path:
    from app_dirs import get_cache_dir
    return get_cache_dir() / "input_roles"


def to_json(roles: Optional[Sequence[InputRole]]) -> Optional[List[Dict[str, Any]]]:
    """Roles as they travel with a submit (plain dicts)."""
    return None if roles is None else [r.__dict__.copy() for r in roles]


def from_json(data: Any) -> Optional[List[InputRole]]:
    if not isinstance(data, list):
        return None
    try:
        return [InputRole(int(r["image"]), str(r["role"]), str(r.get("gives") or "")) for r in data]
    except (KeyError, TypeError, ValueError):
        return None


# Asked this session: the disk cache's hot front.
_memory: Dict[str, List[InputRole]] = {}
# Being asked now: callers with the same question wait on the one call.
_asking: Dict[str, "asyncio.Future[List[InputRole]]"] = {}


def _cache_key(prompt: str, instructions: Optional[str], count: int, writer: Optional[str]) -> str:
    payload = {
        "version": ROLES_VERSION,
        "system": _SYSTEM_PROMPT,
        "prompt": " ".join(prompt.split()),
        "instructions": " ".join((instructions or "").split()),
        "count": count,
        "writer": writer,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _read_cache(key: str) -> Optional[List[InputRole]]:
    try:
        data = json.loads((_cache_dir() / f"{key}.json").read_text())
        return [InputRole(int(r["image"]), str(r["role"]), str(r["gives"])) for r in data["roles"]]
    except FileNotFoundError:
        return None
    except Exception as e:
        log.warning(f"input roles: unreadable cache entry {key}: {e}")
        return None


def _write_cache(key: str, roles: Sequence[InputRole]) -> None:
    try:
        directory = _cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / f"{key}.json.tmp"
        tmp.write_text(json.dumps({"roles": [r.__dict__ for r in roles]}))
        tmp.replace(directory / f"{key}.json")
    except Exception as e:
        log.warning(f"input roles: could not cache {key}: {e}")


def parse_roles(text: str, count: int) -> Optional[List[InputRole]]:
    """The roles in a classifier answer, one per input image, or None when the
    answer doesn't give a valid role for every image."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    entries = data.get("images") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return None
    by_image: Dict[int, InputRole] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            image = int(entry.get("image"))
        except (TypeError, ValueError):
            continue
        role = str(entry.get("role") or "").strip().lower()
        if role not in (CHANGE, REFERENCE) or not 1 <= image <= count:
            continue
        gives = " ".join(str(entry.get("gives") or "").split())[:160]
        by_image.setdefault(image, InputRole(image, role, gives))
    if len(by_image) != count:
        return None
    return [by_image[n] for n in range(1, count + 1)]


def _all_change(count: int) -> List[InputRole]:
    return [InputRole(n, CHANGE, "the picture being changed") for n in range(1, count + 1)]


async def classify_input_roles(
    *,
    prompt: str,
    instructions: Optional[str],
    count: int,
    llm_config: Any,
) -> List[InputRole]:
    """The role of each of the `count` input images (1-based, in order), from the
    prompt as the user typed it. Asked once per prompt, notes, count and chat
    model. A failed or unreadable answer degrades to every image being changed
    (an edit) and is not kept, so the next submit asks again. Callers asking the
    same question at once (a batch's children) share one call and one answer."""
    if count <= 0:
        return []
    try:
        writer = llm_config.get_model() if hasattr(llm_config, "get_model") else None
    except Exception:
        writer = None
    key = _cache_key(prompt, instructions, count, writer)
    cached = _memory.get(key) or _read_cache(key)
    if cached is not None:
        _memory[key] = cached
        return cached
    pending = _asking.get(key)
    if pending is None:
        pending = asyncio.ensure_future(_ask(key, prompt, instructions, count, llm_config))
        _asking[key] = pending
        pending.add_done_callback(lambda _f: _asking.pop(key, None))
    return list(await asyncio.shield(pending))


async def _ask(key: str, prompt: str, instructions: Optional[str], count: int, llm_config: Any) -> List[InputRole]:
    from llm import llm_complete_text

    listing = ", ".join(f"image {n}" for n in range(1, count + 1))
    request = prompt.strip()
    if instructions and instructions.strip():
        request += f"\n\nThe user's notes on how to write it: {instructions.strip()}"
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"The model receives {count} input image{'s' if count != 1 else ''}: "
                                    f"{listing}.\n\nRequest:\n{request}"},
    ]
    try:
        answer = await llm_complete_text(config=llm_config, messages=messages, max_tokens=400, temperature=0.0)
    except Exception as e:
        log.warning(f"input roles: classifier call failed ({type(e).__name__}); treating inputs as edits")
        return _all_change(count)
    roles = parse_roles(answer, count)
    if roles is None:
        log.warning("input roles: unreadable classifier answer; treating inputs as edits")
        return _all_change(count)
    log.info("input roles: " + ", ".join(f"{r.image}={r.role}" for r in roles))
    _memory[key] = roles
    _write_cache(key, roles)
    return roles


async def roles_for_submit(*, prompt: str, instructions: Optional[str], count: int,
                           project_id: Optional[int]) -> Optional[List[InputRole]]:
    """What a submit's input images are for, asked once about the prompt as typed,
    before anything is drawn or filled. None when there is nothing to ask or no chat
    model to ask (the improver then fails or falls back as it always has)."""
    if count <= 0 or not prompt.strip():
        return None
    from llm_resolver import get_effective_llm_config
    try:
        llm_config = await get_effective_llm_config("tool_assistant", project_id)
    except Exception as e:
        log.info(f"input roles: no chat model to ask ({type(e).__name__})")
        return None
    return await classify_input_roles(prompt=prompt, instructions=instructions, count=count, llm_config=llm_config)
