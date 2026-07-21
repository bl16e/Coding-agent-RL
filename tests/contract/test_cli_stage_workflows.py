from pathlib import Path

from coding_agent.cli import main


def _stage1_args(tmp_path: Path) -> list[str]:
    return [
        "stage1",
        "run-qwen-vllm",
        "--dataset",
        str(tmp_path / "dev.parquet"),
        "--dataset",
        str(tmp_path / "test.parquet"),
        "--output-dir",
        str(tmp_path / "stage1"),
        "--max-steps",
        "50",
        "--timeout-seconds",
        "900",
        "--test-timeout-seconds",
        "180",
        "--jobs",
        "1",
        "--resume",
    ]


def test_stage1_help_lists_qwen_vllm_command(capsys):
    exit_code = main(["stage1", "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "run-qwen-vllm" in captured.out


def test_stage1_run_qwen_vllm_uses_stage1_config_and_official_batch(tmp_path, monkeypatch):
    captured_config = {}
    captured_batch = {}

    def fake_load_stage_model_config(stage, model_override=None):
        captured_config["stage"] = stage
        captured_config["model_override"] = model_override

        class Config:
            model = "qwen2.5-coder-7b"

        return Config()

    def fake_run_official_swebench_batch(**kwargs):
        captured_batch.update(kwargs)
        return 0

    monkeypatch.setattr("coding_agent.cli.load_stage_model_config", fake_load_stage_model_config)
    monkeypatch.setattr("coding_agent.cli.run_official_swebench_batch", fake_run_official_swebench_batch)

    exit_code = main([*_stage1_args(tmp_path), "--model", "qwen-override"])

    assert exit_code == 0
    assert captured_config == {"stage": "stage1", "model_override": "qwen-override"}
    assert captured_batch["dataset_paths"] == (str(tmp_path / "dev.parquet"), str(tmp_path / "test.parquet"))
    assert captured_batch["output_dir"] == Path(tmp_path / "stage1")
    assert captured_batch["jobs"] == 1
    assert captured_batch["resume"] is True
    assert captured_batch["model_name"] == "qwen2.5-coder-7b"


def test_stage1_run_qwen_vllm_rejects_registry(tmp_path, capsys):
    exit_code = main([*_stage1_args(tmp_path), "--registry", "legacy.json"])

    assert exit_code == 2
    assert "registry" in capsys.readouterr().err
