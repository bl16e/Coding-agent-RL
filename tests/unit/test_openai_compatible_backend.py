import json
from urllib.error import HTTPError, URLError

import pytest

from coding_agent.models import ModelConfig
from coding_agent.model_backends.base import AgentAction, AgentActionType, ModelBackendError
from coding_agent.model_backends.openai_compatible import (
    OpenAICompatibleBackend,
    map_request_error,
    parse_agent_action,
)


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


def test_http_errors_map_to_model_backend_error():
    error = HTTPError("http://example", 429, "rate limited", hdrs=None, fp=None)

    mapped = map_request_error(error)

    assert isinstance(mapped, ModelBackendError)
    assert "HTTP 429" in str(mapped)


def test_url_errors_map_to_model_backend_error():
    mapped = map_request_error(URLError("connection refused"))

    assert isinstance(mapped, ModelBackendError)
    assert "connection refused" in str(mapped)


def test_backend_builds_openai_chat_completion_request():
    config = ModelConfig("provider", "model-a", "secret", "http://example.test/v1")
    backend = OpenAICompatibleBackend(config, timeout_seconds=5)

    request = backend.build_request([{"role": "user", "content": "next"}])

    assert request.full_url == "http://example.test/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer secret"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "model-a"
    assert "response_format" not in payload
    assert payload["tool_choice"] == "auto"
    tool_names = {tool["function"]["name"] for tool in payload["tools"]}
    assert tool_names == {"read_file", "write_file", "search_code", "run_tests", "final"}
