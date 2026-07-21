from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class AgentActionType(str, Enum):
    READ_FILE = "read_file"
    APPLY_PATCH = "apply_patch"
    SEARCH_CODE = "search_code"
    RUN_TESTS = "run_tests"


@dataclass(frozen=True)
class AgentAction:
    action: AgentActionType
    tool_input: dict[str, Any] = field(default_factory=dict)
    reasoning_summary: str = ""
    next_intent: str = ""
    tool_selection_reason: str = ""
    tool_call_id: str | None = None
    raw_message: dict[str, Any] | None = None


@dataclass(frozen=True)
class TurnResult:
    """The result of one model reasoning turn.

    *actions* are the tool calls the model wants to execute.  When *actions*
    is empty the model has nothing more to do — it stopped naturally.
    *assistant_messages* are the raw assistant messages (text and/or
    tool_calls) that should be appended to the conversation history.
    """

    actions: list[AgentAction]
    assistant_messages: list[dict[str, Any]]


class ModelBackendError(RuntimeError):
    pass


class ModelBackend(Protocol):
    def next_action(self, messages: list[dict[str, Any]]) -> TurnResult:
        ...
