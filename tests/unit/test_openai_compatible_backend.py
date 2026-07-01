import json

import pytest
from openai import APIConnectionError

from coding_agent.models import ModelConfig
from coding_agent.model_backends.base import AgentAction, AgentActionType, ModelBackendError
from coding_agent.model_backends.openai_compatible import (
    OpenAICompatibleBackend,
    map_request_error,
    parse_agent_action,
)


class FakeMessage:
    def __init__(self, payload: dict):
        self._payload = payload

    def model_dump(self) -> dict:
        return self._payload


class FakeChoice:
    def __init__(self, message: dict):
        self.message = FakeMessage(message)


class FakeCompletion:
    def __init__(self, message: dict):
        self.choices = [FakeChoice(message)]

    def model_dump(self) -> dict:
        return {"choices": [{"message": self.choices[0].message.model_dump()}]}


class FakeChatCompletions:
    def __init__(self, result: FakeCompletion | Exception):
        self.result = result
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeChat:
    def __init__(self, completions: FakeChatCompletions):
        self.completions = completions


class FakeOpenAIClient:
    def __init__(self, result: FakeCompletion | Exception):
        self.chat_completions = FakeChatCompletions(result)
        self.chat = FakeChat(self.chat_completions)


def test_parse_agent_action_from_json_content():
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "action": "read_file",
                            "tool_input": {"path": "README.md"},
                            "reasoning_summary": "Need context",
                            "next_intent": "Inspect README",
                            "tool_selection_reason": "File likely documents setup",
                        }
                    )
                }
            }
        ]
    }

    action = parse_agent_action(payload)

    assert action == AgentAction(
        action=AgentActionType.READ_FILE,
        tool_input={"path": "README.md"},
        reasoning_summary="Need context",
        next_intent="Inspect README",
        tool_selection_reason="File likely documents setup",
    )


def test_parse_agent_action_from_openai_tool_call():
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps({"path": "README.md", "offset": 2, "limit": 10}),
                            },
                        }
                    ],
                }
            }
        ]
    }

    action = parse_agent_action(payload)

    assert action.action is AgentActionType.READ_FILE
    assert action.tool_input == {"path": "README.md", "offset": 2, "limit": 10}
    assert action.tool_call_id == "call_123"
    assert action.raw_message == payload["choices"][0]["message"]


def test_parse_final_action_from_openai_tool_call():
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_final",
                            "type": "function",
                            "function": {
                                "name": "final",
                                "arguments": json.dumps(
                                    {"final_status": "solved", "final_message": "All tests pass."}
                                ),
                            },
                        }
                    ],
                }
            }
        ]
    }

    action = parse_agent_action(payload)

    assert action.action is AgentActionType.FINAL
    assert action.final_status == "solved"
    assert action.final_message == "All tests pass."
    assert action.tool_call_id == "call_final"


def test_parse_agent_action_accepts_json_inside_markdown_fence():
    payload = {
        "choices": [
            {
                "message": {
                    "content": '```json\n{"action":"final","final_status":"incomplete"}\n```'
                }
            }
        ]
    }

    action = parse_agent_action(payload)

    assert action.action is AgentActionType.FINAL
    assert action.final_status == "incomplete"


def test_parse_agent_action_error_includes_response_preview():
    with pytest.raises(ModelBackendError, match="preview: I cannot return JSON"):
        parse_agent_action("I cannot return JSON for this request.")


def test_parse_agent_action_rejects_unknown_action():
    with pytest.raises(ModelBackendError, match="Unsupported agent action"):
        parse_agent_action({"action": "shell"})


def test_sdk_errors_map_to_model_backend_error():
    error = APIConnectionError(request=None)

    mapped = map_request_error(error)

    assert isinstance(mapped, ModelBackendError)
    assert "OpenAI-compatible request failed" in str(mapped)


def test_backend_uses_official_openai_sdk_chat_completion_tools():
    config = ModelConfig("provider", "model-a", "secret", "http://example.test/v1")
    client = FakeOpenAIClient(
        FakeCompletion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": "README.md"}),
                        },
                    }
                ],
            }
        )
    )
    backend = OpenAICompatibleBackend(config, timeout_seconds=5, client=client)

    action = backend.next_action([{"role": "user", "content": "next"}])

    assert action.action is AgentActionType.READ_FILE
    assert action.tool_input == {"path": "README.md"}
    call = client.chat_completions.calls[0]
    assert call["model"] == "model-a"
    assert call["messages"] == [{"role": "user", "content": "next"}]
    assert call["tool_choice"] == "auto"
    assert "response_format" not in call
    tool_names = {tool["function"]["name"] for tool in call["tools"]}
    assert tool_names == {"read_file", "apply_patch", "search_code", "run_tests", "final"}


def test_backend_maps_sdk_errors_to_model_backend_error():
    config = ModelConfig("provider", "model-a", "secret", "http://example.test/v1")
    backend = OpenAICompatibleBackend(config, timeout_seconds=5, client=FakeOpenAIClient(APIConnectionError(request=None)))

    with pytest.raises(ModelBackendError, match="OpenAI-compatible request failed"):
        backend.next_action([{"role": "user", "content": "next"}])
