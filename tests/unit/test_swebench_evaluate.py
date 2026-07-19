"""Unit tests for swebench evaluate module."""

import json
from pathlib import Path

import pytest

from coding_agent.swebench.evaluate import (
    EvaluateInputError,
    compute_aggregate_metrics,
    load_evaluation_results,
    render_evaluation_report,
)


def _write_summary_json(run_dir: Path, **overrides) -> None:
    payload = {
        "instance_id": "django__django-11099",
        "status": "solved",
        "agent_status": "incomplete",
        "prepared_environment": {
            "repo": "django/django",
            "version": "3.0",
            "base_commit": "abc123",
            "status_transition": ["ready", "running", "used"],
        },
        "validation": {
            "source": "official_testspec",
            "mode": "fail_to_pass",
            "eval_report": {
                "resolved": True,
                "fail_to_pass_success": ["tests/test_issue.py::test_fix"],
                "fail_to_pass_failure": [],
                "pass_to_pass_success": [],
                "pass_to_pass_failure": [],
            },
        },
    }
    payload.update(overrides)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps(payload), encoding="utf-8")


def _make_resolved_result(**overrides):
    base = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "status": "solved",
        "resolved": True,
        "resolved_text": "✓ RESOLVED",
        "error": None,
        "fail_to_pass_success": 1,
        "fail_to_pass_failure": 0,
        "pass_to_pass_success": 0,
        "pass_to_pass_failure": 0,
    }
    base.update(overrides)
    return base


def _make_unresolved_result(**overrides):
    base = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "status": "incomplete",
        "resolved": False,
        "resolved_text": "✗ UNRESOLVED",
        "error": None,
        "fail_to_pass_success": 0,
        "fail_to_pass_failure": 1,
        "pass_to_pass_success": 0,
        "pass_to_pass_failure": 0,
    }
    base.update(overrides)
    return base


class TestLoadEvaluationResults:
    def test_loads_from_batch_state_json(self, tmp_path: Path):
        batch_dir = tmp_path / "batch"
        run_dir = batch_dir / "django__django-11099" / "run"
        _write_summary_json(run_dir)
        (batch_dir / "batch_state.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": {
                        "django__django-11099": {
                            "instance_id": "django__django-11099",
                            "run_dir": str(run_dir),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        results = load_evaluation_results(batch_dir)

        assert len(results) == 1
        assert results[0]["instance_id"] == "django__django-11099"
        assert results[0]["repo"] == "django/django"
        assert results[0]["resolved"] is True
        assert results[0]["resolved_text"] == "✓ RESOLVED"

    def test_falls_back_to_directory_scan(self, tmp_path: Path):
        batch_dir = tmp_path / "batch"
        run_dir = batch_dir / "django__django-11099" / "run"
        _write_summary_json(run_dir)

        results = load_evaluation_results(batch_dir)

        assert len(results) == 1
        assert results[0]["instance_id"] == "django__django-11099"

    def test_handles_missing_summary_json(self, tmp_path: Path):
        batch_dir = tmp_path / "batch"
        run_dir = batch_dir / "django__django-11099" / "run"
        run_dir.mkdir(parents=True)
        (batch_dir / "batch_state.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": {
                        "django__django-11099": {
                            "instance_id": "django__django-11099",
                            "run_dir": str(run_dir),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        results = load_evaluation_results(batch_dir)

        assert len(results) == 1
        assert results[0]["resolved"] is None
        assert results[0]["resolved_text"] == "ERROR"

    def test_raises_for_missing_batch_dir(self, tmp_path: Path):
        with pytest.raises(EvaluateInputError, match="batch directory does not exist"):
            load_evaluation_results(tmp_path / "nonexistent")

    def test_raises_for_empty_batch_dir(self, tmp_path: Path):
        batch_dir = tmp_path / "batch"
        batch_dir.mkdir()

        with pytest.raises(EvaluateInputError, match="no run directories found"):
            load_evaluation_results(batch_dir)

    def test_loads_multiple_instances(self, tmp_path: Path):
        batch_dir = tmp_path / "batch"
        _write_summary_json(
            batch_dir / "django__django-11099" / "run",
            instance_id="django__django-11099",
            prepared_environment={"repo": "django/django"},
        )
        _write_summary_json(
            batch_dir / "django__django-11100" / "run",
            instance_id="django__django-11100",
            status="incomplete",
            prepared_environment={"repo": "django/django"},
            validation={
                "source": "official_testspec",
                "mode": "fail_to_pass",
                "eval_report": {
                    "resolved": False,
                    "fail_to_pass_success": [],
                    "fail_to_pass_failure": ["tests/test_issue.py::test_fix"],
                    "pass_to_pass_success": [],
                    "pass_to_pass_failure": [],
                },
            },
        )

        results = load_evaluation_results(batch_dir)

        assert len(results) == 2
        assert results[0]["resolved"] is True
        assert results[1]["resolved"] is False

    def test_handles_missing_eval_report(self, tmp_path: Path):
        batch_dir = tmp_path / "batch"
        run_dir = batch_dir / "django__django-11099" / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "summary.json").write_text(
            json.dumps(
                {
                    "instance_id": "django__django-11099",
                    "status": "errored",
                    "error": "container failed",
                    "prepared_environment": {"repo": "django/django"},
                    "validation": {"source": "official_testspec"},
                }
            ),
            encoding="utf-8",
        )

        results = load_evaluation_results(batch_dir)

        assert len(results) == 1
        assert results[0]["resolved"] is None
        assert results[0]["resolved_text"] == "ERROR"
        assert results[0]["error"] == "container failed"


class TestComputeAggregateMetrics:
    def test_all_resolved(self):
        results = [
            _make_resolved_result(instance_id="a__a-1"),
            _make_resolved_result(instance_id="b__b-2"),
        ]

        report = compute_aggregate_metrics(results)

        assert report["total"] == 2
        assert report["resolved"] == 2
        assert report["unresolved"] == 0
        assert report["errored"] == 0
        assert report["resolve_rate"] == 1.0

    def test_mixed_results(self):
        results = [
            _make_resolved_result(instance_id="a__a-1"),
            _make_unresolved_result(instance_id="b__b-2"),
            {
                "instance_id": "c__c-3",
                "repo": "django/django",
                "status": "errored",
                "resolved": None,
                "resolved_text": "ERROR",
                "error": "timeout",
                "fail_to_pass_success": 0,
                "fail_to_pass_failure": 0,
                "pass_to_pass_success": 0,
                "pass_to_pass_failure": 0,
            },
        ]

        report = compute_aggregate_metrics(results)

        assert report["total"] == 3
        assert report["resolved"] == 1
        assert report["unresolved"] == 1
        assert report["errored"] == 1
        assert report["resolve_rate"] == 0.5  # 1/(3-1)

    def test_per_repo_breakdown(self):
        results = [
            _make_resolved_result(instance_id="django__django-1", repo="django/django"),
            _make_unresolved_result(instance_id="django__django-2", repo="django/django"),
            _make_resolved_result(instance_id="pytest__pytest-1", repo="pytest-dev/pytest"),
        ]

        report = compute_aggregate_metrics(results)

        per_repo = report["per_repo"]
        assert per_repo["django/django"]["total"] == 2
        assert per_repo["django/django"]["resolved"] == 1
        assert per_repo["django/django"]["resolve_rate"] == 0.5
        assert per_repo["pytest-dev/pytest"]["total"] == 1
        assert per_repo["pytest-dev/pytest"]["resolved"] == 1

    def test_empty_results(self):
        report = compute_aggregate_metrics([])

        assert report["total"] == 0
        assert report["resolved"] == 0
        assert report["resolve_rate"] == 0.0

    def test_per_status_counts(self):
        results = [
            _make_resolved_result(instance_id="a__a-1", status="solved"),
            _make_unresolved_result(instance_id="b__b-2", status="incomplete"),
            _make_unresolved_result(instance_id="c__c-3", status="failed"),
        ]

        report = compute_aggregate_metrics(results)

        assert report["per_status"] == {"failed": 1, "incomplete": 1, "solved": 1}


class TestRenderEvaluationReport:
    def test_renders_basic_report(self):
        report = {
            "total": 100,
            "resolved": 40,
            "unresolved": 55,
            "errored": 5,
            "resolve_rate": 0.4211,
            "per_repo": {
                "django/django": {
                    "total": 50,
                    "resolved": 20,
                    "unresolved": 28,
                    "errored": 2,
                    "resolve_rate": 0.4167,
                }
            },
            "instances": [
                {
                    "instance_id": "django__django-11099",
                    "repo": "django/django",
                    "status": "solved",
                    "resolved": True,
                    "resolved_text": "✓ RESOLVED",
                    "error": None,
                    "fail_to_pass_success": 2,
                    "fail_to_pass_failure": 0,
                    "pass_to_pass_success": 1,
                    "pass_to_pass_failure": 0,
                },
            ],
        }

        text = render_evaluation_report(report, batch_dir="runs/lite")

        assert "SWE-Bench Evaluation Report" in text
        assert "runs/lite" in text
        assert "Total:       100" in text
        assert "Resolved:    40 (42.1%)" in text
        assert "Unresolved:  55 (55.0%)" in text
        assert "Errored:     5 (5.0%)" in text
        assert "django/django" in text
        assert "✓ RESOLVED" in text
        assert "F2P: 2/2" in text
        assert "P2P: 1/1" in text
