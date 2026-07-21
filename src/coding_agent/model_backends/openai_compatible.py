from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

from coding_agent.model_backends.base import AgentAction, AgentActionType, ModelBackendError
from coding_agent.models import ModelConfig, ToolName
from coding_agent.tools.schemas import COMMON_PROPERTIES, FINAL_ACTION_SCHEMA, TOOL_SCHEMAS

REQUIRED_ENV_KEYS = ("PROVIDER", "MODEL", "API_KEY", "BASE_URL")
STAGE_ENV_KEYS = {
    "stage1": ("STAGE1_PROVIDER", "STAGE1_MODEL", "STAGE1_API_KEY", "STAGE1_BASE_URL"),
    "stage2": ("STAGE2_PROVIDER", "STAGE2_MODEL", "STAGE2_API_KEY", "STAGE2_BASE_URL"),
}
ERROR_PREVIEW_CHARS = 160


class MissingModelConfigError(ValueError):
    def __init__(self, missing_keys: tuple[str, ...]) -> None:
        self.missing_keys = missing_keys
        super().__init__("missing required model environment variables: " + ", ".join(missing_keys))


def parse_dotenv(path: Path) -> dict[str, str]:
    """Parse the minimal root .env format needed by the model adapter.

    This intentionally supports only KEY=VALUE lines because the project avoids
    adding a dotenv dependency for the MVP. Process environment variables still
    take precedence in load_model_config().
    """

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
    """Load OpenAI-compatible model settings from env, then root .env.

    Precedence is:
    1. values supplied in the process environment or test env argument
    2. values from the root .env file
    3. --model CLI override for MODEL only

    The explicit missing-key error is part of the CLI contract for invalid
    configuration, so callers should let MissingModelConfigError propagate to
    the command boundary.
    """

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


def load_stage_model_config(
    stage: str,
    env: dict[str, str] | None = None,
    dotenv_path: Path | str = ".env",
    model_override: str | None = None,
) -> ModelConfig:
    """Load model settings from stage-specific environment variables only."""

    try:
        provider_key, model_key, api_key_key, base_url_key = STAGE_ENV_KEYS[stage]
    except KeyError as exc:
        raise ValueError(f"unknown stage model config: {stage}") from exc

    file_values = parse_dotenv(Path(dotenv_path))
    env_values = dict(os.environ if env is None else env)
    stage_keys = (provider_key, model_key, api_key_key, base_url_key)
    merged = {key: file_values.get(key, "") for key in stage_keys}
    merged.update({key: env_values[key] for key in stage_keys if env_values.get(key)})
    if model_override:
        merged[model_key] = model_override

    missing = tuple(key for key in stage_keys if not merged.get(key))
    if missing:
        raise MissingModelConfigError(missing)
    return ModelConfig(
        provider=merged[provider_key],
        model=merged[model_key],
        api_key=merged[api_key_key],
        base_url=merged[base_url_key],
    )


def _preview_response_text(value: str) -> str:
    return " ".join(value.strip().split())[:ERROR_PREVIEW_CHARS]


def _parse_json_object_from_text(value: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(value):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _schema_to_openai_properties(params: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Convert internal schema format to OpenAI function parameters format."""
    properties = {}
    required = []

    for name, spec in params.items():
        prop = {"type": spec["type"]}
        if "description" in spec:
            prop["description"] = spec["description"]
        if "minimum" in spec:
            prop["minimum"] = spec["minimum"]
        if "maximum" in spec:
            prop["maximum"] = spec["maximum"]
        if "enum" in spec:
            prop["enum"] = spec["enum"]
        properties[name] = prop
        if spec.get("required"):
            required.append(name)

    return properties, required


def tool_definitions() -> list[dict[str, Any]]:
    """Return OpenAI Chat Completions function-tool schemas for the agent tools."""
    tools = []

    for tool_name, schema in TOOL_SCHEMAS.items():
        props, req = _schema_to_openai_properties(schema["parameters"])
        tools.append({
            "type": "function",
            "function": {
                "name": tool_name.value,
                "description": schema["description"],
                "parameters": {
                    "type": "object",
                    "properties": {**props, **COMMON_PROPERTIES},
                    "required": req,
                    "additionalProperties": False,
                },
            },
        })

    # Add final action
    props, req = _schema_to_openai_properties(FINAL_ACTION_SCHEMA["parameters"])
    tools.append({
        "type": "function",
        "function": {
            "name": "final",
            "description": FINAL_ACTION_SCHEMA["description"],
            "parameters": {
                "type": "object",
                "properties": {**props, **COMMON_PROPERTIES},
                "required": req,
                "additionalProperties": False,
            },
        },
    })

    return tools


def _parse_tool_call_message(message: dict[str, Any]) -> AgentAction | None:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None
    tool_call = tool_calls[0]
    function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    name = function.get("name")
    arguments_text = function.get("arguments") or "{}"
    try:
        arguments = json.loads(arguments_text)
    except json.JSONDecodeError as exc:
        raise ModelBackendError(f"tool call arguments are not valid JSON for {name}") from exc
    if not isinstance(arguments, dict):
        raise ModelBackendError(f"tool call arguments must be a JSON object for {name}")
    try:
        action = AgentActionType(name)
    except ValueError as exc:
        raise ModelBackendError(f"Unsupported agent action: {name}") from exc
    return AgentAction( 
        action=action,
        tool_input={} if action is AgentActionType.FINAL else arguments,
        reasoning_summary=arguments.get("reasoning_summary") or "",
        next_intent=arguments.get("next_intent") or "",
        tool_selection_reason=arguments.get("tool_selection_reason") or "",
        final_status=arguments.get("final_status") if action is AgentActionType.FINAL else None,
        final_message=arguments.get("final_message") if action is AgentActionType.FINAL else None,
        tool_call_id=tool_call.get("id"),
        raw_message=message,
    )


def _payload_to_action_dict(payload: dict[str, Any] | str) -> dict[str, Any]:
    """Extract the AgentAction JSON object from OpenAI-compatible responses.

    Real providers normally return choices[0].message.content as a string, but
    unit tests and mock-like adapters may pass the action object directly. Both
    forms are accepted here so the rest of the agent sees one stable contract.
    """

    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            parsed = _parse_json_object_from_text(payload)
            if parsed is None:
                preview = _preview_response_text(payload)
                raise ModelBackendError(f"model response content is not valid JSON; preview: {preview}") from exc
        if not isinstance(parsed, dict):
            raise ModelBackendError("model response JSON must be an object")
        return parsed

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        tool_action = _parse_tool_call_message(message)
        if tool_action is not None:
            return {"__agent_action__": tool_action}
        content = message.get("content")
        if isinstance(content, str):
            return _payload_to_action_dict(content)
    return payload


def parse_agent_action(payload: dict[str, Any] | str) -> AgentAction:
    """Validate provider output and convert it into an executable action."""

    action_dict = _payload_to_action_dict(payload)
    if "__agent_action__" in action_dict:
        return action_dict["__agent_action__"]
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


def map_request_error(error: APIError) -> ModelBackendError:
    if isinstance(error, RateLimitError):
        return ModelBackendError(f"OpenAI-compatible request failed with rate limit: {error}")
    if isinstance(error, APITimeoutError):
        return ModelBackendError(f"OpenAI-compatible request timed out: {error}")
    if isinstance(error, APIConnectionError):
        return ModelBackendError(f"OpenAI-compatible request failed: {error}")
    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        return ModelBackendError(f"OpenAI-compatible request failed with HTTP {status_code}: {error}")
    return ModelBackendError(f"OpenAI-compatible request failed: {error}")


class OpenAICompatibleBackend:
    def __init__(self, config: ModelConfig, timeout_seconds: int = 60, client: Any | None = None) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.client = client or OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=timeout_seconds,
        )

    def request_payload(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Build Chat Completions parameters for the official OpenAI SDK."""

        return {
            "model": self.config.model,
            "messages": messages,
            "tools": tool_definitions(),
            "tool_choice": "auto",
        }

    def next_action(self, messages: list[dict[str, Any]]) -> AgentAction:
        """Request the next tool/final action from the configured model."""

        try:
            completion = self.client.chat.completions.create(**self.request_payload(messages))
        except APIError as exc:
            raise map_request_error(exc) from exc
        payload = completion.model_dump() if hasattr(completion, "model_dump") else completion
        return parse_agent_action(payload)
