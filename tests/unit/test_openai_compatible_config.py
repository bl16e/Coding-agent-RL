from pathlib import Path

import pytest

from coding_agent.model_backends.openai_compatible import (
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

