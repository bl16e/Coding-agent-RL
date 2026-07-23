import json

import pytest
from openai import APIConnectionError

from coding_agent.models import ModelConfig
from coding_agent.openai_compatible_backend import (
    ModelBackendError,
    OpenAICompatibleBackend,
    map_request_error,
)


class FakeCompletion:
    def __init__(self, message: dict):
        self._message = message

    def model_dump(self) -> dict:
        return {"choices": [{"message": self._message}]}


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


def test_sdk_errors_map_to_model_backend_error():
    error = APIConnectionError(request=None)

    mapped = map_request_error(error)

    assert isinstance(mapped, ModelBackendError)
    assert "OpenAI-compatible request failed" in str(mapped)


def test_backend_query_returns_tool_call_message():
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

    result = backend.query([{"role": "user", "content": "next"}])

    assert result["role"] == "assistant"
    assert result["tool_calls"][0]["function"]["name"] == "read_file"
    call = client.chat_completions.calls[0]
    assert call["model"] == "model-a"
    assert call["messages"] == [{"role": "user", "content": "next"}]
    assert "tools" not in call


def test_backend_query_uses_caller_provided_tools_and_returns_assistant_message():
    config = ModelConfig("provider", "model-a", "secret", "http://example.test/v1")
    message = {
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
    client = FakeOpenAIClient(FakeCompletion(message))
    backend = OpenAICompatibleBackend(config, timeout_seconds=5, client=client)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "read",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    result = backend.query([{"role": "user", "content": "next"}], tools=tools)

    assert result["role"] == "assistant"
    assert result["tool_calls"] == message["tool_calls"]
    call = client.chat_completions.calls[0]
    assert call["tools"] == tools
    assert call["tool_choice"] == "auto"


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

    result = backend.query([{"role": "user", "content": "next"}])

    assert result["role"] == "assistant"
    assert "All tests should pass" in result["content"]


def test_backend_maps_sdk_errors_to_model_backend_error():
    config = ModelConfig("provider", "model-a", "secret", "http://example.test/v1")
    backend = OpenAICompatibleBackend(
        config,
        timeout_seconds=5,
        client=FakeOpenAIClient(APIConnectionError(request=None)),
    )

    with pytest.raises(ModelBackendError, match="OpenAI-compatible request failed"):
        backend.query([{"role": "user", "content": "next"}])
