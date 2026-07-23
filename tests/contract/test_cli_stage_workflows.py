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
    exit_code = main([*_stage1_args(tmp_path), "--registry", "registry.json"])

    assert exit_code == 2
    assert "registry" in capsys.readouterr().err


def test_stage2_help_lists_teacher_trajectory_command(capsys):
    exit_code = main(["stage2", "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "generate-teacher-trajectories" in captured.out


def test_stage2_generate_teacher_trajectories_uses_stage2_config_and_pipeline(tmp_path, monkeypatch):
    subset = tmp_path / "subset.json"
    subset.write_text("[]", encoding="utf-8")
    captured_config = {}
    captured_run = {}
    captured_eval = {}
    captured_export = {}

    def fake_load_stage_model_config(stage, model_override=None):
        captured_config["stage"] = stage
        captured_config["model_override"] = model_override

        class Config:
            model = "teacher-model"

        return Config()

    def fake_run_swesmith_subset(**kwargs):
        captured_run.update(kwargs)
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "preds.jsonl").write_text("", encoding="utf-8")
        return 0

    def fake_run_official_eval(**kwargs):
        captured_eval.update(kwargs)
        return 0

    def fake_export_sft(**kwargs):
        captured_export.update(kwargs)
        return 12

    monkeypatch.setattr("coding_agent.cli.load_stage_model_config", fake_load_stage_model_config)
    monkeypatch.setattr("coding_agent.cli.run_swesmith_subset", fake_run_swesmith_subset)
    monkeypatch.setattr("coding_agent.cli.run_official_eval", fake_run_official_eval)
    monkeypatch.setattr("coding_agent.cli.export_sft", fake_export_sft)

    exit_code = main(
        [
            "stage2",
            "generate-teacher-trajectories",
            "--subset",
            str(subset),
            "--output-dir",
            str(tmp_path / "runs"),
            "--reference-path",
            str(tmp_path / "Reference" / "SWE-smith"),
            "--max-steps",
            "80",
            "--timeout-seconds",
            "1200",
            "--test-timeout-seconds",
            "180",
            "--jobs",
            "4",
            "--eval-workers",
            "3",
            "--run-id",
            "stage2_teacher",
            "--sft-output",
            str(tmp_path / "sft.jsonl"),
            "--model",
            "teacher-override",
        ]
    )

    assert exit_code == 0
    assert captured_config == {"stage": "stage2", "model_override": "teacher-override"}
    assert captured_run["subset_path"] == str(subset)
    assert captured_run["model_name"] == "teacher-model"
    assert captured_run["jobs"] == 4
    assert captured_eval["dataset_path"] == str(subset)
    assert captured_eval["run_id"] == "stage2_teacher"
    assert captured_eval["workers"] == 3
    assert captured_export["runs_dir"] == str(tmp_path / "runs")
    assert captured_export["output"] == str(tmp_path / "sft.jsonl")


def test_stage2_generate_teacher_trajectories_requires_subset_or_create_args(tmp_path, capsys):
    exit_code = main(
        [
            "stage2",
            "generate-teacher-trajectories",
            "--output-dir",
            str(tmp_path / "runs"),
            "--max-steps",
            "1",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--run-id",
            "stage2_teacher",
            "--sft-output",
            str(tmp_path / "sft.jsonl"),
        ]
    )

    assert exit_code == 2
    assert "subset" in capsys.readouterr().err.lower()
