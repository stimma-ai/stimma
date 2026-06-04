"""
Agent state management for controlling agent execution.
"""
from core.logging import get_logger
from typing import Dict
from dataclasses import dataclass
from enum import Enum

log = get_logger(__name__)


class AgentState(Enum):
    """Agent execution states."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class ChatAgentState:
    """Represents the state of an agent for a specific chat."""
    state: AgentState = AgentState.IDLE
    should_cancel: bool = False
    should_pause: bool = False


class AgentStateManager:
    """Manages agent states for all chats."""

    def __init__(self):
        self._states: Dict[int, ChatAgentState] = {}

    def get_state(self, chat_id: int) -> ChatAgentState:
        """Get the state for a chat, creating if it doesn't exist."""
        if chat_id not in self._states:
            self._states[chat_id] = ChatAgentState()
        return self._states[chat_id]

    def set_running(self, chat_id: int):
        """Mark agent as running for this chat."""
        state = self.get_state(chat_id)
        state.state = AgentState.RUNNING
        state.should_cancel = False
        state.should_pause = False
        log.info(f"Agent state set to RUNNING for chat_id={chat_id}")

    def set_paused(self, chat_id: int):
        """Mark agent as paused for this chat."""
        state = self.get_state(chat_id)
        state.state = AgentState.PAUSED
        state.should_pause = True
        log.info(f"Agent state set to PAUSED for chat_id={chat_id}")

    def set_idle(self, chat_id: int):
        """Mark agent as idle for this chat."""
        state = self.get_state(chat_id)
        state.state = AgentState.IDLE
        state.should_cancel = False
        state.should_pause = False
        log.info(f"Agent state set to IDLE for chat_id={chat_id}")

    def request_pause(self, chat_id: int):
        """Request pause for this agent."""
        state = self.get_state(chat_id)
        state.should_pause = True
        log.info(f"Pause requested for chat_id={chat_id}")

    def request_cancel(self, chat_id: int):
        """Request cancellation for this agent."""
        state = self.get_state(chat_id)
        state.should_cancel = True
        state.state = AgentState.CANCELLED
        log.info(f"Cancel requested for chat_id={chat_id}")

    def resume(self, chat_id: int):
        """Resume agent execution."""
        state = self.get_state(chat_id)
        if state.state == AgentState.PAUSED:
            state.state = AgentState.RUNNING
            state.should_pause = False
            log.info(f"Agent resumed for chat_id={chat_id}")

    def should_pause(self, chat_id: int) -> bool:
        """Check if agent should pause."""
        return self.get_state(chat_id).should_pause

    def should_cancel(self, chat_id: int) -> bool:
        """Check if agent should cancel."""
        return self.get_state(chat_id).should_cancel

    def is_paused(self, chat_id: int) -> bool:
        """Check if agent is paused."""
        return self.get_state(chat_id).state == AgentState.PAUSED

    def is_running(self, chat_id: int) -> bool:
        """Check if agent is running."""
        return self.get_state(chat_id).state == AgentState.RUNNING


# Global agent state manager
agent_state_manager = AgentStateManager()
