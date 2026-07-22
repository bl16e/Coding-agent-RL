# src/coding_agent/model_backend.py
from __future__ import annotations

from typing import Any

from minisweagent.models.litellm_model import LitellmModel


class ModelBackend:
    """Thin wrapper around mini-swe-agent's LitellmModel.

    Adds structured tool support (tool_definitions) and standardizes
    the message format for the agent loop.
    """

    def __init__(self, model_name: str, **config: Any):
        self._model = LitellmModel(model_name=model_name, **config)
        self.model_name = model_name

    def query(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> dict:
        """Query the model with optional tool definitions.

        Returns an OpenAI-compatible assistant message dict with:
        - role: "assistant"
        - content: str or None
        - tool_calls: list[dict] or absent
        - extra: dict with cost, model stats
        """
        return self._model.query(messages, tools=tools)

    def format_message(self, role: str, content: str, **extra: Any) -> dict:
        """Build a standard message dict."""
        msg: dict[str, Any] = {"role": role, "content": content}
        if extra:
            msg["extra"] = extra
        return msg

    def format_tool_results(
        self, assistant_message: dict, outputs: list[dict]
    ) -> list[dict]:
        """Build tool result messages from assistant tool_calls + execution outputs.

        Each output dict should have: tool_call_id, tool_name, content.
        """
        tool_calls = assistant_message.get("tool_calls", [])
        messages: list[dict] = []
        for i, output in enumerate(outputs):
            tc_id = ""
            if i < len(tool_calls):
                tc_id = tool_calls[i].get("id", "")
            messages.append({
                "role": "tool",
                "tool_call_id": output.get("tool_call_id", tc_id),
                "content": output.get("content", ""),
            })
        return messages

    @property
    def cost(self) -> float:
        return getattr(self._model, "cost", 0.0)

    @property
    def n_calls(self) -> int:
        return self._model.n_calls
