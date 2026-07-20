import json
from pathlib import Path

from coding_agent.swesmith.evaluate import read_resolved_ids, run_official_eval


def test_run_official_eval_invokes_swesmith_module(tmp_path: Path):
    calls = {}

    def fake_runner(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs

        class Completed:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Completed()

    exit_code = run_official_eval(
        dataset_path=tmp_path / "subset.json",
        predictions_path=tmp_path / "preds.jsonl",
        run_id="run-1",
        workers=2,
        timeout=240,
        reference_path=tmp_path / "Reference" / "SWE-smith",
        runner=fake_runner,
    )

    assert exit_code == 0
    assert calls["command"][:3][-1] == "swesmith.harness.eval"
    assert "--dataset_path" in calls["command"]
    assert str(tmp_path / "subset.json") in calls["command"]


def test_read_resolved_ids_reads_per_instance_reports(tmp_path: Path):
    eval_dir = tmp_path / "logs" / "run_evaluation" / "run-1"
    (eval_dir / "inst-1").mkdir(parents=True)
    (eval_dir / "inst-2").mkdir(parents=True)
    (eval_dir / "inst-1" / "report.json").write_text(json.dumps({"resolved": True}), encoding="utf-8")
    (eval_dir / "inst-2" / "report.json").write_text(json.dumps({"resolved": False}), encoding="utf-8")

    assert read_resolved_ids(eval_dir) == {"inst-1"}
