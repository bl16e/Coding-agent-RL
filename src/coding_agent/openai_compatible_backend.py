from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

from coding_agent.models import ModelConfig

REQUIRED_ENV_KEYS = ("PROVIDER", "MODEL", "API_KEY", "BASE_URL")
STAGE_ENV_KEYS = {
    "stage1": ("STAGE1_PROVIDER", "STAGE1_MODEL", "STAGE1_API_KEY", "STAGE1_BASE_URL"),
    "stage2": ("STAGE2_PROVIDER", "STAGE2_MODEL", "STAGE2_API_KEY", "STAGE2_BASE_URL"),
}


class MissingModelConfigError(ValueError):
    def __init__(self, missing_keys: tuple[str, ...]) -> None:
        self.missing_keys = missing_keys
        super().__init__("missing required model environment variables: " + ", ".join(missing_keys))


class ModelBackendError(RuntimeError):
    pass


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


def load_stage_model_config(
    stage: str,
    env: dict[str, str] | None = None,
    dotenv_path: Path | str = ".env",
    model_override: str | None = None,
) -> ModelConfig:
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
    """Native ToolAgent backend for OpenAI-compatible Chat Completions APIs."""

    def __init__(self, config: ModelConfig, timeout_seconds: int = 60, client: Any | None = None) -> None:
        self.config = config
        self.model_name = config.model
        self.timeout_seconds = timeout_seconds
        self.client = client or OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=timeout_seconds,
        )

    def request_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
        }
        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        try:
            completion = self.client.chat.completions.create(
                **self.request_payload(messages, tools=tools)
            )
        except APIError as exc:
            raise map_request_error(exc) from exc
        payload = completion.model_dump() if hasattr(completion, "model_dump") else completion
        choices = payload.get("choices", [])
        if not choices:
            return {"role": "assistant", "content": "", "extra": {}}
        message = dict(choices[0].get("message", {}))
        message.setdefault("extra", {})
        return message
