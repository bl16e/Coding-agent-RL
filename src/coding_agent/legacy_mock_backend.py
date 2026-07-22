from __future__ import annotations

from collections.abc import Iterable

from coding_agent.model_backend import AgentAction, AgentActionType, TurnResult


class MockBackend:
    def __init__(self, actions: Iterable[AgentAction] | None = None) -> None:
        self._actions = list(actions or [])
        self._index = 0

    def next_action(self, messages: list[dict[str, str]]) -> TurnResult:
        if self._index >= len(self._actions):
            return TurnResult(
                actions=[],
                assistant_messages=[{"role": "assistant", "content": "Task complete."}],
            )
        action = self._actions[self._index]
        self._index += 1
        # Build a minimal assistant message for history
        msg: dict[str, object] = {"role": "assistant", "content": None}
        if action.tool_call_id:
            msg["tool_calls"] = [
                {"id": action.tool_call_id, "type": "function", "function": {"name": action.action.value, "arguments": "{}"}}
            ]
        return TurnResult(actions=[action], assistant_messages=[msg])
