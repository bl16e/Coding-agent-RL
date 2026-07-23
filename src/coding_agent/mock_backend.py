from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from coding_agent.models import ToolName


@dataclass(frozen=True)
class MockToolCall:
    tool_name: ToolName
    tool_input: dict[str, Any]
    tool_call_id: str | None = None


class MockBackend:
    def __init__(self, calls: list[MockToolCall] | None = None, *, final: str = "Task complete.") -> None:
        self._calls = list(calls or [])
        self._index = 0
        self.final = final
        self.model_name = "mock-model"

    def query(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if self._index >= len(self._calls):
            return {"role": "assistant", "content": self.final, "extra": {}}
        call = self._calls[self._index]
        self._index += 1
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call.tool_call_id or f"mock_call_{self._index}",
                    "type": "function",
                    "function": {
                        "name": call.tool_name.value,
                        "arguments": json.dumps(call.tool_input),
                    },
                }
            ],
            "extra": {},
        }
