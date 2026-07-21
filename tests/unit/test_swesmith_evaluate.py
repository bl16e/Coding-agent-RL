import json
from pathlib import Path

import pytest

from coding_agent.swesmith.evaluate import read_eval_reports, read_resolved_ids, run_official_eval


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
        reference_path=tmp_path / "Reference" / "SWE-smith",
        log_dir=tmp_path / "logs" / "run_evaluation" / "run-1",
        runner=fake_runner,
    )

    assert exit_code == 0
    assert any("swesmith.harness.eval" in part for part in calls["command"])
    assert "--dataset_path" in calls["command"]
    assert str(tmp_path / "subset.json") in calls["command"]
    assert "--timeout" not in calls["command"]
    assert calls["kwargs"]["text"] is True
    assert calls["kwargs"]["check"] is False
    assert calls["kwargs"]["capture_output"] is True
    assert (tmp_path / "logs" / "run_evaluation" / "run-1" / "wrapper.stdout.log").read_text(encoding="utf-8") == "ok"
    assert (tmp_path / "logs" / "run_evaluation" / "run-1" / "wrapper.stderr.log").read_text(encoding="utf-8") == ""


def test_run_official_eval_records_failed_wrapper_output(tmp_path: Path):
    def fake_runner(command, **kwargs):
        class Completed:
            returncode = 2
            stdout = "starting eval\n"
            stderr = "missing dataset\n"

        return Completed()

    exit_code = run_official_eval(
        dataset_path=tmp_path / "missing.json",
        predictions_path=tmp_path / "preds.jsonl",
        run_id="run-2",
        workers=1,
        reference_path=None,
        log_dir=tmp_path / "eval_logs",
        runner=fake_runner,
    )

    assert exit_code == 2
    assert (tmp_path / "eval_logs" / "wrapper.stdout.log").read_text(encoding="utf-8") == "starting eval\n"
    assert (tmp_path / "eval_logs" / "wrapper.stderr.log").read_text(encoding="utf-8") == "missing dataset\n"


def test_run_official_eval_writes_wrapper_report_summary(tmp_path: Path):
    def fake_runner(command, **kwargs):
        report_dir = tmp_path / "eval_logs" / "inst-1"
        report_dir.mkdir(parents=True)
        (report_dir / "report.json").write_text(json.dumps({"resolved": True}), encoding="utf-8")
        (report_dir / "test_output.txt").write_text("pytest output\n", encoding="utf-8")

        class Completed:
            returncode = 0
            stdout = "Resolved 1/1\n"
            stderr = ""

        return Completed()

    assert (
        run_official_eval(
            dataset_path=tmp_path / "subset.json",
            predictions_path=tmp_path / "preds.jsonl",
            run_id="run-3",
            workers=1,
            reference_path=None,
            log_dir=tmp_path / "eval_logs",
            runner=fake_runner,
        )
        == 0
    )

    summary = json.loads((tmp_path / "eval_logs" / "wrapper.report.json").read_text(encoding="utf-8"))
    assert summary["returncode"] == 0
    assert summary["resolved_count"] == 1
    assert summary["total_reports"] == 1
    assert summary["reports"]["inst-1"]["resolved"] is True
    assert "test_output.txt" in summary["artifacts"]["inst-1"]


def test_run_official_eval_uses_resource_shim_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls = {}

    def fake_runner(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs

        class Completed:
            returncode = 0

        return Completed()

    monkeypatch.setattr("coding_agent.swesmith.evaluate.os.name", "nt")

    assert (
        run_official_eval(
            dataset_path=tmp_path / "subset.json",
            predictions_path=tmp_path / "preds.jsonl",
            run_id="run-1",
            workers=1,
            reference_path=tmp_path / "Reference" / "SWE-smith",
            log_dir=tmp_path / "logs" / "run_evaluation" / "run-1",
            runner=fake_runner,
        )
        == 0
    )

    assert calls["command"][1] == "-c"
    assert "sys.modules.setdefault('resource'" in calls["command"][2]
    assert "_ca_du.copy_to_container = _ca_copy_to_container" in calls["command"][2]
    assert "_ca_su.copy_to_container = _ca_copy_to_container" in calls["command"][2]
    assert "runpy.run_module('swesmith.harness.eval'" in calls["command"][2]


def test_read_resolved_ids_reads_per_instance_reports(tmp_path: Path):
    eval_dir = tmp_path / "logs" / "run_evaluation" / "run-1"
    (eval_dir / "inst-1").mkdir(parents=True)
    (eval_dir / "inst-2").mkdir(parents=True)
    (eval_dir / "inst-1" / "report.json").write_text(json.dumps({"resolved": True}), encoding="utf-8")
    (eval_dir / "inst-2" / "report.json").write_text(json.dumps({"resolved": False}), encoding="utf-8")

    assert read_resolved_ids(eval_dir) == {"inst-1"}


def test_read_eval_reports_supports_official_nested_report_shape(tmp_path: Path):
    eval_dir = tmp_path / "logs" / "run_evaluation" / "run-1"
    (eval_dir / "inst-1").mkdir(parents=True)
    (eval_dir / "inst-1" / "report.json").write_text(
        json.dumps({"inst-1": {"resolved": True, "tests_status": {"FAIL_TO_PASS": {"success": ["a"], "failure": []}}}}),
        encoding="utf-8",
    )

    reports = read_eval_reports(eval_dir)

    assert reports["inst-1"]["resolved"] is True
    assert reports["inst-1"]["fail_to_pass_success"] == ["a"]
