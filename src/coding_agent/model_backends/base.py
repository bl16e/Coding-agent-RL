from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class AgentActionType(str, Enum):
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    SEARCH_CODE = "search_code"
    RUN_TESTS = "run_tests"
    FINAL = "final"


@dataclass(frozen=True)
class AgentAction:
    action: AgentActionType
    tool_input: dict[str, Any] = field(default_factory=dict)
    reasoning_summary: str = ""
    next_intent: str = ""
    tool_selection_reason: str = ""
    final_status: str | None = None
    final_message: str | None = None
    tool_call_id: str | None = None
    raw_message: dict[str, Any] | None = None


class ModelBackendError(RuntimeError):
    pass


class ModelBackend(Protocol):
    def next_action(self, messages: list[dict[str, Any]]) -> AgentAction:
        ...
