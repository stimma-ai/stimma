"""
Working context for the agent system.

The WorkingContext is session-scoped state that tools operate on.
It provides implicit targets ("the image", "the third one") and
tracks tool outputs for verbal references.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, List, Dict, Any, Callable, Awaitable


def _ordinal(n: int) -> str:
    """Convert number to ordinal string: 1 → '1st', 2 → '2nd', etc."""
    if 11 <= (n % 100) <= 13:
        suffix = 'th'
    else:
        suffix = ['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]
    return f"{n}{suffix}"


@dataclass
class MediaRef:
    """Reference to a media item with context for verbal references."""
    media_id: int
    media_type: Literal["image", "video", "document"]
    name: str | None = None  # Friendly name assigned by planner: "background", "option_a"

    # Media dimensions (useful for calculations in plans)
    width: int | None = None
    height: int | None = None

    # Context for understanding verbal references like "the red one"
    prompt: str | None = None  # What was requested (visible in generation UI)
    ai_caption: str | None = None  # VLM description of what was actually generated

    def to_dict(self) -> dict:
        result = {
            "media_id": self.media_id,
            "media_type": self.media_type,
        }
        if self.name:
            result["name"] = self.name
        if self.width is not None:
            result["width"] = self.width
        if self.height is not None:
            result["height"] = self.height
        if self.prompt:
            result["prompt"] = self.prompt
        if self.ai_caption:
            result["ai_caption"] = self.ai_caption
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "MediaRef":
        return cls(
            media_id=data["media_id"],
            media_type=data["media_type"],
            name=data.get("name"),
            width=data.get("width"),
            height=data.get("height"),
            prompt=data.get("prompt"),
            ai_caption=data.get("ai_caption"),
        )


@dataclass
class ToolOutput:
    """
    Result from a tool invocation.

    Maps to a "box" in the UI - a logical batch of outputs.
    Enables verbal references like "the third one" → items[2].
    """
    id: str
    tool_name: str
    description: str  # "5 cats", "upscaled version" - agent-generated
    items: List[MediaRef]
    timestamp: datetime
    node_id: str | None = None  # If from a plan, which node produced this
    metadata: Dict[str, Any] | None = None  # Rich data returned to LLM
    cancelled: bool = False  # True if user cancelled the operation

    @property
    def count(self) -> int:
        return len(self.items)

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "tool_name": self.tool_name,
            "description": self.description,
            "items": [item.to_dict() for item in self.items],
            "timestamp": self.timestamp.isoformat(),
            "node_id": self.node_id,
        }
        if self.metadata:
            result["data"] = self.metadata
        if self.cancelled:
            result["cancelled"] = True
        return result

    def to_llm_dict(self) -> dict:
        """
        Coalesced representation for LLM context - matches human's view.

        The human sees a "box" with one prompt and a grid of images.
        This gives the LLM the same view: prompt once, list of media_ids.
        Avoids repeating prompt N times for N images.
        """
        if self.cancelled:
            return {
                "tool_name": self.tool_name,
                "cancelled": True,
            }

        # Group items by prompt (they're usually all the same for a batch)
        prompts = set(item.prompt for item in self.items if item.prompt)

        if len(prompts) == 0:
            # No prompts (e.g., upscale, utility tools)
            return {
                "tool_name": self.tool_name,
                "description": self.description,
                "count": len(self.items),
                "media_ids": [item.media_id for item in self.items],
            }
        elif len(prompts) == 1:
            # Single prompt batch - coalesce (most common case)
            return {
                "tool_name": self.tool_name,
                "prompt": list(prompts)[0],
                "count": len(self.items),
                "media_ids": [item.media_id for item in self.items],
            }
        else:
            # Multiple different prompts - preserve order and show ordinals
            # This is critical: user says "the first one" meaning items[0]
            results = []
            for i, item in enumerate(self.items):
                ordinal = _ordinal(i + 1)  # "1st", "2nd", etc.
                results.append({
                    "index": i,
                    "ordinal": ordinal,
                    "media_id": item.media_id,
                    "prompt": item.prompt or "(no prompt)",
                })
            return {
                "tool_name": self.tool_name,
                "count": len(self.items),
                "results": results,  # Ordered list with ordinals
            }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolOutput":
        return cls(
            id=data["id"],
            tool_name=data["tool_name"],
            description=data["description"],
            items=[MediaRef.from_dict(item) for item in data["items"]],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            node_id=data.get("node_id"),
            metadata=data.get("data"),
            cancelled=data.get("cancelled", False),
        )


# HumanAction is now defined in hitl.py as HumanActionRequest
# Import it when needed to avoid circular imports


@dataclass
class WorkingContext:
    """
    Scratch space for the current session.

    This is the agent's working memory - what it's operating on,
    what outputs have been produced, and what the user has selected.
    """

    # Plan ID - set when plan execution starts, used for trace association
    plan_id: str | None = None

    # Explicit selection - set by UI (user clicks) or HITL choice
    selected: List[MediaRef] = field(default_factory=list)

    # Named references for workflows. Planner assigns names via output_name.
    # e.g., named["background"], named["foreground"]
    named: Dict[str, MediaRef] = field(default_factory=dict)

    # Tool output history - chronological order matching UI display.
    # recent[0] = oldest (top of chat), recent[-1] = newest (bottom)
    # Each ToolOutput is a batch (like a "box" in UI)
    recent: List[ToolOutput] = field(default_factory=list)

    # Pending human response (when HITL node is active)
    # Type is HumanActionRequest from hitl.py (use Any to avoid circular import)
    pending_human_action: Any | None = None

    # Status checker callback - allows tools to check if plan is paused/cancelled
    # Returns: 'running' | 'paused' | 'interrupted' | None (if no checker set)
    # Tools should check this before submitting new work
    status_checker: Callable[[], Awaitable[str | None]] | None = None

    # Current node ID - set by executor during node execution
    # Used by tools that need to raise HITL requests with proper node_id
    current_node_id: str | None = None

    async def check_status(self) -> str | None:
        """
        Check the current plan execution status.

        Returns:
            'running' - continue normally
            'paused' - stop submitting new work, let current work finish
            'interrupted' - stop immediately, cancel in-progress work
            None - no checker set (continue normally)
        """
        if self.status_checker:
            return await self.status_checker()
        return None

    def is_cancelled(self) -> bool:
        """Synchronous check if we should stop (for use in sync code)."""
        # This is a hint based on last known state - for async code use check_status()
        return getattr(self, '_last_status', None) == 'interrupted'

    @property
    def latest(self) -> ToolOutput | None:
        """Most recent tool output batch."""
        return self.recent[-1] if self.recent else None

    def add_output(self, output: ToolOutput) -> None:
        """Add a tool output and update selected to point to it."""
        import logging
        log = logging.getLogger(__name__)
        log.info(f"add_output called: tool={output.tool_name}, items={len(output.items)}, context_id={id(self)}, selected_before={len(self.selected)}")
        self.recent.append(output)
        # Only update selection if output has items
        # This prevents error outputs (with empty items) from clearing the selection
        # which would break parallel node execution
        if output.items:
            self.selected = output.items.copy()
            log.info(f"  Updated selected to {len(self.selected)} items")

    def set_named(self, name: str, ref: MediaRef) -> None:
        """Set a named reference."""
        self.named[name] = ref

    def clear_selection(self) -> None:
        """Clear the current selection."""
        self.selected = []

    def to_dict(self) -> dict:
        result = {
            "selected": [s.to_dict() for s in self.selected],
            "named": {k: v.to_dict() for k, v in self.named.items()},
            "recent": [r.to_dict() for r in self.recent],
            "pending_human_action": None,
        }
        if self.pending_human_action:
            # HumanActionRequest has its own to_dict
            result["pending_human_action"] = self.pending_human_action.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "WorkingContext":
        ctx = cls(
            selected=[MediaRef.from_dict(s) for s in data.get("selected", [])],
            named={k: MediaRef.from_dict(v) for k, v in data.get("named", {}).items()},
            recent=[ToolOutput.from_dict(r) for r in data.get("recent", [])],
        )
        if data.get("pending_human_action"):
            # Import here to avoid circular import
            from .hitl import HumanActionRequest
            ctx.pending_human_action = HumanActionRequest.from_dict(data["pending_human_action"])
        return ctx


def resolve_target(target: str, context: WorkingContext) -> List[MediaRef]:
    """
    Resolve a target reference to actual MediaRefs.

    Supports:
    - "selected" → context.selected
    - "latest" → context.latest.items
    - "latest.items[2]" → [context.latest.items[2]]
    - "named.background" → [context.named["background"]]
    - "recent[-2]" → context.recent[-2].items
    """
    if target == "selected":
        return context.selected

    if target == "latest":
        if context.latest:
            return context.latest.items
        return []

    if target.startswith("latest.items"):
        if not context.latest:
            return []
        # Parse index like "latest.items[2]"
        if "[" in target:
            idx = int(target.split("[")[1].rstrip("]"))
            return [context.latest.items[idx]]
        return context.latest.items

    if target.startswith("named."):
        name = target.split(".", 1)[1]
        if name in context.named:
            return [context.named[name]]
        return []

    if target.startswith("recent["):
        # Parse like "recent[-2]"
        idx = int(target.split("[")[1].rstrip("]"))
        if abs(idx) <= len(context.recent):
            return context.recent[idx].items
        return []

    # Fallback - assume it's a named reference
    if target in context.named:
        return [context.named[target]]

    raise ValueError(f"Unknown target reference: {target}")
