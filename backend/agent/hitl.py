"""
Human-in-the-loop (HITL) primitives.

Defines the types and mechanisms for pausing agent execution
to wait for human input.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, List, Dict, Any, Optional

from .context import MediaRef


# Response types for HITL
@dataclass
class ToolPermissionResponse:
    """Response to a tool permission request."""
    approved: bool
    selected_tool_id: str | None = None  # User may select a different tool
    scope: str | None = None  # 'once' | 'chat' | 'always' - permission scope


@dataclass
class AskUserResponse:
    """Response to an ask_user prompt."""
    answer: str
    interrupted: bool = False


# Union type for all responses
HumanResponse = ToolPermissionResponse | AskUserResponse


@dataclass
class HumanActionRequest:
    """
    Request for human input.

    This is what gets stored in WorkingContext.pending_human_action
    and sent to the frontend to render the appropriate UI.

    Supported types:
    - v2_tool_permission: Tool execution approval
    - ask_user: Question for the user
    """
    type: Literal["v2_tool_permission", "ask_user"]
    prompt: str
    node_id: str  # Unique ID for this HITL request
    created_at: datetime = field(default_factory=datetime.now)

    # For choose/feedback: the options to present
    options: List[MediaRef] | None = None

    # For answer: optional suggested answers
    suggestions: List[str] | None = None

    # Allow multiple selections for choose?
    multi_select: bool = False

    # LLM tool_call_id - needed to create proper tool_result on resume
    tool_call_id: str | None = None

    # For v2_tool_permission: the tool arguments (e.g. bash command, search query)
    v2_tool_args: dict | None = None

    # For ask_user: structured options [{label, description}, ...]
    ask_options: List[Dict[str, str]] | None = None
    ask_questions: List[Dict[str, Any]] | None = None
    ask_question_index: int | None = None
    ask_question_total: int | None = None
    ask_question_plan: List[str] | None = None

    def to_dict(self) -> dict:
        result = {
            "type": self.type,
            "prompt": self.prompt,
            "node_id": self.node_id,
            "created_at": self.created_at.isoformat(),
            "multi_select": self.multi_select,
        }
        if self.options:
            result["options"] = [o.to_dict() for o in self.options]
        if self.suggestions:
            result["suggestions"] = self.suggestions
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.v2_tool_args:
            result["v2_tool_args"] = self.v2_tool_args
        if self.ask_options:
            result["ask_options"] = self.ask_options
        if self.ask_questions:
            result["ask_questions"] = self.ask_questions
        if self.ask_question_index is not None:
            result["ask_question_index"] = self.ask_question_index
        if self.ask_question_total is not None:
            result["ask_question_total"] = self.ask_question_total
        if self.ask_question_plan:
            result["ask_question_plan"] = self.ask_question_plan
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "HumanActionRequest":
        return cls(
            type=data["type"],
            prompt=data["prompt"],
            node_id=data["node_id"],
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            options=[MediaRef.from_dict(o) for o in data.get("options", [])] if data.get("options") else None,
            suggestions=data.get("suggestions"),
            multi_select=data.get("multi_select", False),
            tool_call_id=data.get("tool_call_id"),
            v2_tool_args=data.get("v2_tool_args"),
            ask_options=data.get("ask_options"),
            ask_questions=data.get("ask_questions"),
            ask_question_index=data.get("ask_question_index"),
            ask_question_total=data.get("ask_question_total"),
            ask_question_plan=data.get("ask_question_plan"),
        )


class HumanActionRequired(Exception):
    """
    Raised by HITL tools to signal that execution should pause.

    The agent loop catches this and saves the action request
    to WorkingContext.pending_human_action.
    """

    def __init__(self, action: HumanActionRequest):
        self.action = action
        super().__init__(f"Human action required: {action.type}")


def parse_human_response(
    action_type: Literal["v2_tool_permission", "ask_user"],
    response_data: Dict[str, Any],
) -> HumanResponse:
    """
    Parse a raw response dict into the appropriate response type.

    Args:
        action_type: The type of action being responded to
        response_data: The raw response data from the frontend

    Returns:
        The appropriate typed response object
    """
    match action_type:
        case "v2_tool_permission":
            return ToolPermissionResponse(
                approved=response_data.get("approved", False),
                scope=response_data.get("scope", "chat"),
            )

        case "ask_user":
            return AskUserResponse(
                answer=response_data.get("answer", ""),
                interrupted=response_data.get("interrupted", False),
            )

        case _:
            raise ValueError(f"Unknown action type: {action_type}")


def response_to_tool_result(response: HumanResponse) -> Dict[str, Any]:
    """
    Convert a HumanResponse to a tool result format for the LLM.

    This is what gets returned to the agent after the human responds.
    """
    match response:
        case ToolPermissionResponse(approved=approved, selected_tool_id=tool_id):
            return {
                "success": True,
                "approved": approved,
                "selected_tool_id": tool_id,
            }
