"""Telling the editor which step a submit's prompt is on, so its tile says what is happening.

A Tool View submit names its tile (client_ref). While the submit route works on the prompt,
`for_tile` holds that name, and the steps that take time say when they start: `picking` (a
prompt's slots and lists drawn for this image, and checked to fit together) and `writing` (the
chat model writing the prompt out: the improver, a translation, Ideogram JSON). A step that is
skipped says nothing, so a prompt with nothing to do goes straight to its queued job. A tile
only moves forward: a batch's images share one tile, and one still picking never takes it
back from writing.

One event, `generation_prompt_stage` {client_ref, stage}. Outside a tile's submit (the agent,
flows) nothing is sent. Never raises.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, Iterator, Literal, Optional

from core.logging import get_logger

log = get_logger(__name__)

EVENT = "generation_prompt_stage"
Stage = Literal["picking", "writing"]
_ORDER = {"picking": 0, "writing": 1}

# The tile being worked on and the step it was last told, shared by the tasks the submit
# starts (a batch's children copy the context).
_tile: ContextVar[Optional[Dict[str, Optional[str]]]] = ContextVar("prompt_stage_tile", default=None)


@contextmanager
def for_tile(client_ref: Optional[str]) -> Iterator[None]:
    """The prompt work inside is for this tile."""
    token = _tile.set({"ref": client_ref, "said": None} if client_ref else None)
    try:
        yield
    finally:
        _tile.reset(token)


async def say(stage: Stage) -> None:
    """This tile's prompt is starting `stage` (once, and never back to an earlier one)."""
    tile = _tile.get()
    if not tile or (tile["said"] is not None and _ORDER[tile["said"]] >= _ORDER[stage]):
        return
    tile["said"] = stage
    try:
        from utils import websocket
        await websocket.ws_manager.broadcast(EVENT, {"client_ref": tile["ref"], "stage": stage})
    except Exception as e:
        log.debug(f"[prompt-stage] couldn't send {stage} for {tile['ref']}: {e}")


__all__ = ["EVENT", "Stage", "for_tile", "say"]
