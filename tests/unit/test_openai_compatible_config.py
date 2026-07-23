from pathlib import Path

import pytest

from coding_agent.openai_compatible_backend import (
    MissingModelConfigError,
    load_model_config,
)


def test_load_model_config_reports_all_missing_values(tmp_path: Path):
    with pytest.raises(MissingModelConfigError) as exc_info:
        load_model_config(env={}, dotenv_path=tmp_path / ".env")

    assert exc_info.value.missing_keys == ("PROVIDER", "MODEL", "API_KEY", "BASE_URL")


def test_load_model_config_uses_process_environment_before_dotenv(tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "PROVIDER=file-provider\nMODEL=file-model\nAPI_KEY=file-key\nBASE_URL=http://file\n",
        encoding="utf-8",
    )

    config = load_model_config(
        env={
            "PROVIDER": "env-provider",
            "MODEL": "env-model",
            "API_KEY": "env-key",
            "BASE_URL": "http://env",
        },
        dotenv_path=dotenv,
    )

    assert config.provider == "env-provider"
    assert config.model == "env-model"
    assert config.api_key == "env-key"
    assert config.base_url == "http://env"


def test_model_override_only_replaces_model(tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "PROVIDER=file-provider\nMODEL=file-model\nAPI_KEY=file-key\nBASE_URL=http://file\n",
        encoding="utf-8",
    )

    config = load_model_config(env={}, dotenv_path=dotenv, model_override="override-model")

    assert config.provider == "file-provider"
    assert config.model == "override-model"


def test_load_stage_model_config_reads_stage1_values(tmp_path: Path):
    from coding_agent.openai_compatible_backend import load_stage_model_config

    config = load_stage_model_config(
        "stage1",
        env={
            "STAGE1_PROVIDER": "openai",
            "STAGE1_MODEL": "qwen2.5-coder-7b",
            "STAGE1_API_KEY": "not-needed",
            "STAGE1_BASE_URL": "http://vllm:8000/v1",
            "PROVIDER": "generic-provider",
            "MODEL": "generic-model",
            "API_KEY": "generic-key",
            "BASE_URL": "http://generic",
        },
        dotenv_path=tmp_path / ".env",
    )

    assert config.provider == "openai"
    assert config.model == "qwen2.5-coder-7b"
    assert config.api_key == "not-needed"
    assert config.base_url == "http://vllm:8000/v1"


def test_load_stage_model_config_does_not_fallback_to_generic_env(tmp_path: Path):
    from coding_agent.openai_compatible_backend import load_stage_model_config

    with pytest.raises(MissingModelConfigError) as exc_info:
        load_stage_model_config(
            "stage1",
            env={
                "PROVIDER": "generic-provider",
                "MODEL": "generic-model",
                "API_KEY": "generic-key",
                "BASE_URL": "http://generic",
            },
            dotenv_path=tmp_path / ".env",
        )

    assert exc_info.value.missing_keys == (
        "STAGE1_PROVIDER",
        "STAGE1_MODEL",
        "STAGE1_API_KEY",
        "STAGE1_BASE_URL",
    )


def test_load_stage_model_config_model_override_only_replaces_stage_model(tmp_path: Path):
    from coding_agent.openai_compatible_backend import load_stage_model_config

    config = load_stage_model_config(
        "stage2",
        env={
            "STAGE2_PROVIDER": "openai",
            "STAGE2_MODEL": "teacher-default",
            "STAGE2_API_KEY": "teacher-key",
            "STAGE2_BASE_URL": "https://teacher.example/v1",
        },
        dotenv_path=tmp_path / ".env",
        model_override="teacher-override",
    )

    assert config.provider == "openai"
    assert config.model == "teacher-override"
    assert config.api_key == "teacher-key"
    assert config.base_url == "https://teacher.example/v1"
