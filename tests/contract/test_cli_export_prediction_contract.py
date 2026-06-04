import json
from pathlib import Path

from coding_agent.cli import main


def test_export_prediction_writes_swebench_jsonl(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text('{"instance_id":"example__repo-1"}', encoding="utf-8")
    (run_dir / "final.patch").write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
    output = tmp_path / "prediction.jsonl"

    exit_code = main(
        ["export-prediction", "--run-dir", str(run_dir), "--model-name", "model-a", "--output", str(output)]
    )

    assert exit_code == 0
    row = json.loads(output.read_text(encoding="utf-8"))
    assert set(row) == {"instance_id", "model_name_or_path", "model_patch"}
    assert row == {
        "instance_id": "example__repo-1",
        "model_name_or_path": "model-a",
        "model_patch": "diff --git a/app.py b/app.py\n",
    }


def test_export_prediction_rejects_missing_artifacts(tmp_path: Path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    exit_code = main(
        ["export-prediction", "--run-dir", str(run_dir), "--model-name", "model-a", "--output", str(tmp_path / "p.jsonl")]
    )

    assert exit_code == 2
    assert "summary" in capsys.readouterr().err
