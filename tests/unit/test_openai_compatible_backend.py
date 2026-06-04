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
    assert json.loads(request.data.decode("utf-8"))["model"] == "model-a"

