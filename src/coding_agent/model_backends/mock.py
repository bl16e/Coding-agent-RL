from __future__ import annotations

from collections.abc import Iterable

from coding_agent.model_backends.base import AgentAction, AgentActionType


class MockBackend:
    def __init__(self, actions: Iterable[AgentAction] | None = None) -> None:
        self._actions = list(actions or [])
        self._index = 0

    def next_action(self, messages: list[dict[str, str]]) -> list[AgentAction]:
        if self._index >= len(self._actions):
            return [AgentAction(
                action=AgentActionType.FINAL,
                reasoning_summary="No mock actions remain",
                next_intent="Stop run",
                final_status="incomplete",
                final_message="Mock backend exhausted",
            )]
        action = self._actions[self._index]
        self._index += 1
        return [action]

