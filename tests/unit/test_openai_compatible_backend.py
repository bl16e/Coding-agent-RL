import json

import pytest
from openai import APIConnectionError

from coding_agent.models import ModelConfig
from coding_agent.model_backend import AgentAction, AgentActionType, ModelBackendError, TurnResult
from coding_agent.legacy_openai_backend import (
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
        self.message = message


class FakeCompletion:
    def __init__(self, message: dict):
        self._message = message

    def model_dump(self) -> dict:
        return {"choices": [{"message": self._message}]}

    @property
    def choices(self):
        return [FakeChoice(self._message)]


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
                            "tool_input": {"file_path": "README.md"},
                            "reasoning_summary": "Need context",
                            "next_intent": "Inspect README",
                            "tool_selection_reason": "File likely documents setup",
                        }
                    )
                }
            }
        ]
    }

    actions = parse_agent_action(payload)

    assert actions == [AgentAction(
        action=AgentActionType.READ_FILE,
        tool_input={"file_path": "README.md"},
        reasoning_summary="Need context",
        next_intent="Inspect README",
        tool_selection_reason="File likely documents setup",
    )]


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
                                "arguments": json.dumps({"file_path": "README.md", "offset": 2, "limit": 10}),
                            },
                        }
                    ],
                }
            }
        ]
    }

    actions = parse_agent_action(payload)

    assert actions[0].action is AgentActionType.READ_FILE
    assert actions[0].tool_input == {"file_path": "README.md", "offset": 2, "limit": 10}
    assert actions[0].tool_call_id == "call_123"


def test_natural_stop_when_final_in_json_text_mode():
    # JSON text mode with "final" action → returns empty list (natural stop)
    payload = {"choices": [{"message": {"content": '{"action":"final","final_status":"incomplete"}'}}]}

    actions = parse_agent_action(payload)

    assert actions == []


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
                            "arguments": json.dumps({"file_path": "README.md"}),
                        },
                    }
                ],
            }
        )
    )
    backend = OpenAICompatibleBackend(config, timeout_seconds=5, client=client)

    turn = backend.next_action([{"role": "user", "content": "next"}])

    assert isinstance(turn, TurnResult)
    assert len(turn.actions) == 1
    assert turn.actions[0].action is AgentActionType.READ_FILE
    assert turn.actions[0].tool_input == {"file_path": "README.md"}
    call = client.chat_completions.calls[0]
    assert call["model"] == "model-a"
    assert call["messages"] == [{"role": "user", "content": "next"}]
    assert call["tool_choice"] == "auto"
    tool_names = {tool["function"]["name"] for tool in call["tools"]}
    assert tool_names == {"read_file", "apply_patch", "search_code", "run_tests"}


def test_backend_stops_naturally_when_no_tool_calls():
    config = ModelConfig("provider", "model-a", "secret", "http://example.test/v1")
    client = FakeOpenAIClient(
        FakeCompletion(
            {
                "role": "assistant",
                "content": "The fix is applied. All tests should pass now.",
            }
        )
    )
    backend = OpenAICompatibleBackend(config, timeout_seconds=5, client=client)

    turn = backend.next_action([{"role": "user", "content": "next"}])

    assert isinstance(turn, TurnResult)
    assert turn.actions == []
    assert len(turn.assistant_messages) == 1
    assert "All tests should pass" in turn.assistant_messages[0]["content"]


def test_backend_maps_sdk_errors_to_model_backend_error():
    config = ModelConfig("provider", "model-a", "secret", "http://example.test/v1")
    backend = OpenAICompatibleBackend(config, timeout_seconds=5, client=FakeOpenAIClient(APIConnectionError(request=None)))

    with pytest.raises(ModelBackendError, match="OpenAI-compatible request failed"):
        backend.next_action([{"role": "user", "content": "next"}])
