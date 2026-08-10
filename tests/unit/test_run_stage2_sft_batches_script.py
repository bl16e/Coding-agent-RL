import importlib.util
from pathlib import Path


SCRIPT_PATH = Path("scripts/run_stage2_sft_batches.py")


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_stage2_sft_batches", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_plan_batches_uses_batch_suffix_and_skips_existing_quality(tmp_path: Path):
    module = _load_script_module()
    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    first = batch_dir / "sft_candidate_batch_0001.json"
    second = batch_dir / "sft_candidate_batch_0021.json"
    first.write_text("[]", encoding="utf-8")
    second.write_text("[]", encoding="utf-8")
    sft_dir = tmp_path / "sft_data"
    sft_dir.mkdir()
    (sft_dir / "stage2_sft8000_top39_b0001.quality.json").write_text("{}", encoding="utf-8")

    plan = module.plan_batches(
        batch_dir=batch_dir,
        run_prefix="stage2_sft8000_top39_b",
        output_root=tmp_path / "runs",
        sft_root=sft_dir,
        reference_path=Path("Reference/SWE-smith"),
        max_steps=60,
        timeout_seconds=1200,
        test_timeout_seconds=180,
        jobs=1,
        eval_workers=1,
    )

    assert [(item.run_id, item.skip) for item in plan] == [
        ("stage2_sft8000_top39_b0001", True),
        ("stage2_sft8000_top39_b0021", False),
    ]
    assert plan[1].command[:3] == ["coding-agent", "stage2", "generate-teacher-trajectories"]
    assert plan[1].command[plan[1].command.index("--subset") + 1] == str(second)
    assert plan[1].command[plan[1].command.index("--run-id") + 1] == "stage2_sft8000_top39_b0021"
    assert plan[1].command[plan[1].command.index("--sft-output") + 1] == str(
        sft_dir / "stage2_sft8000_top39_b0021.jsonl"
    )


def test_main_dry_run_does_not_execute_commands(tmp_path: Path, monkeypatch):
    module = _load_script_module()
    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    (batch_dir / "sft_candidate_batch_0021.json").write_text("[]", encoding="utf-8")
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda command: calls.append(command))

    exit_code = module.main(
        [
            "--batch-dir",
            str(batch_dir),
            "--output-root",
            str(tmp_path / "runs"),
            "--sft-root",
            str(tmp_path / "sft_data"),
            "--reference-path",
            "Reference/SWE-smith",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert calls == []
