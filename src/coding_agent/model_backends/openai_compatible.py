from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from coding_agent.model_backends.base import AgentAction, AgentActionType, ModelBackendError
from coding_agent.models import ModelConfig

REQUIRED_ENV_KEYS = ("PROVIDER", "MODEL", "API_KEY", "BASE_URL")


class MissingModelConfigError(ValueError):
    def __init__(self, missing_keys: tuple[str, ...]) -> None:
        self.missing_keys = missing_keys
        super().__init__("missing required model environment variables: " + ", ".join(missing_keys))


def parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_model_config(
    env: dict[str, str] | None = None,
    dotenv_path: Path | str = ".env",
    model_override: str | None = None,
) -> ModelConfig:
    file_values = parse_dotenv(Path(dotenv_path))
    env_values = dict(os.environ if env is None else env)
    merged = {key: file_values.get(key, "") for key in REQUIRED_ENV_KEYS}
    merged.update({key: env_values[key] for key in REQUIRED_ENV_KEYS if env_values.get(key)})
    if model_override:
        merged["MODEL"] = model_override

    missing = tuple(key for key in REQUIRED_ENV_KEYS if not merged.get(key))
    if missing:
        raise MissingModelConfigError(missing)
    return ModelConfig(
        provider=merged["PROVIDER"],
        model=merged["MODEL"],
        api_key=merged["API_KEY"],
        base_url=merged["BASE_URL"],
    )


def _payload_to_action_dict(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ModelBackendError("model response content is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ModelBackendError("model response JSON must be an object")
        return parsed

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return _payload_to_action_dict(content)
    return payload


def parse_agent_action(payload: dict[str, Any] | str) -> AgentAction:
    action_dict = _payload_to_action_dict(payload)
    action_value = action_dict.get("action")
    try:
        action = AgentActionType(action_value)
    except ValueError as exc:
        raise ModelBackendError(f"Unsupported agent action: {action_value}") from exc
    return AgentAction(
        action=action,
        tool_input=action_dict.get("tool_input") or {},
        reasoning_summary=action_dict.get("reasoning_summary") or "",
        next_intent=action_dict.get("next_intent") or "",
        tool_selection_reason=action_dict.get("tool_selection_reason") or "",
        final_status=action_dict.get("final_status"),
        final_message=action_dict.get("final_message"),
    )


def map_request_error(error: HTTPError | URLError | TimeoutError) -> ModelBackendError:
    if isinstance(error, HTTPError):
        return ModelBackendError(f"OpenAI-compatible request failed with HTTP {error.code}: {error.reason}")
    reason = getattr(error, "reason", str(error))
    return ModelBackendError(f"OpenAI-compatible request failed: {reason}")


class OpenAICompatibleBackend:
    def __init__(self, config: ModelConfig, timeout_seconds: int = 60) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def build_request(self, messages: list[dict[str, str]]) -> Request:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        data = json.dumps({"model": self.config.model, "messages": messages}).encode("utf-8")
        return Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

    def next_action(self, messages: list[dict[str, str]]) -> AgentAction:
        request = self.build_request(messages)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise map_request_error(exc) from exc
        except json.JSONDecodeError as exc:
            raise ModelBackendError("OpenAI-compatible response body is not valid JSON") from exc
        return parse_agent_action(payload)
