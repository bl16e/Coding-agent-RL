from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from coding_agent.swesmith.compat import windows_official_eval_prelude


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _pythonpath_with(paths: list[Path], current: str) -> str:
    parts = [str(path.resolve()) for path in paths]
    if current:
        parts.append(current)
    return os.pathsep.join(parts)


def run_official_eval(
    *,
    dataset_path: str | Path,
    predictions_path: str | Path,
    run_id: str,
    workers: int,
    reference_path: str | Path | None,
    swebench_path: str | Path | None = None,
    log_dir: str | Path | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> int:
    eval_args = [
        "--dataset_path",
        str(dataset_path),
        "--predictions_path",
        str(predictions_path),
        "--run_id",
        run_id,
        "--workers",
        str(workers),
    ]
    if os.name == "nt":
        command = [
            sys.executable,
            "-c",
            windows_official_eval_prelude()
            + "import runpy, sys; sys.argv=['swesmith.harness.eval'] + sys.argv[1:]; "
            + "runpy.run_module('swesmith.harness.eval', run_name='__main__')",
            *eval_args,
        ]
    else:
        command = [sys.executable, "-m", "swesmith.harness.eval", *eval_args]
    env = dict(os.environ)
    python_paths: list[Path] = []
    if reference_path is not None:
        python_paths.append(Path(reference_path))
    swebench_root = Path(swebench_path) if swebench_path is not None else _project_root() / "SWE-bench"
    python_paths.append(swebench_root)
    env["PYTHONPATH"] = _pythonpath_with(python_paths, env.get("PYTHONPATH", ""))
    completed = runner(command, text=True, check=False, env=env, capture_output=True)
    output_dir = Path(log_dir) if log_dir is not None else Path("logs") / "run_evaluation" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout = getattr(completed, "stdout", "") or ""
    stderr = getattr(completed, "stderr", "") or ""
    (output_dir / "wrapper.stdout.log").write_text(str(stdout), encoding="utf-8")
    (output_dir / "wrapper.stderr.log").write_text(str(stderr), encoding="utf-8")
    (output_dir / "wrapper.command.json").write_text(
        json.dumps({"command": [str(part) for part in command], "returncode": int(completed.returncode)}, indent=2),
        encoding="utf-8",
    )
    reports = read_eval_reports(output_dir)
    artifacts = _collect_eval_artifacts(output_dir)
    (output_dir / "wrapper.report.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "returncode": int(completed.returncode),
                "resolved_count": sum(1 for report in reports.values() if report.get("resolved")),
                "total_reports": len(reports),
                "reports": reports,
                "artifacts": artifacts,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return int(completed.returncode)


def _instance_report_payload(payload: dict[str, Any], instance_id: str) -> dict[str, Any]:
    nested = payload.get(instance_id)
    if isinstance(nested, dict):
        return nested
    return payload


def _test_status(payload: dict[str, Any], group: str, bucket: str) -> list[str]:
    tests_status = payload.get("tests_status")
    if not isinstance(tests_status, dict):
        return []
    group_status = tests_status.get(group)
    if not isinstance(group_status, dict):
        return []
    values = group_status.get(bucket, [])
    return [str(item) for item in values] if isinstance(values, list) else []


def _normalize_report(payload: dict[str, Any], instance_id: str) -> dict[str, Any]:
    report = _instance_report_payload(payload, instance_id)
    normalized: dict[str, Any] = {"resolved": bool(report.get("resolved", False))}
    normalized["fail_to_pass_success"] = _test_status(report, "FAIL_TO_PASS", "success")
    normalized["fail_to_pass_failure"] = _test_status(report, "FAIL_TO_PASS", "failure")
    normalized["pass_to_pass_success"] = _test_status(report, "PASS_TO_PASS", "success")
    normalized["pass_to_pass_failure"] = _test_status(report, "PASS_TO_PASS", "failure")
    return normalized


def _collect_eval_artifacts(eval_dir: Path) -> dict[str, list[str]]:
    artifacts: dict[str, list[str]] = {}
    if not eval_dir.is_dir():
        return artifacts
    for child in sorted(path for path in eval_dir.iterdir() if path.is_dir()):
        files = [
            item.name
            for item in sorted(child.iterdir())
            if item.is_file() and item.name in {"report.json", "test_output.txt", "run_instance.log"}
        ]
        if files:
            artifacts[child.name] = files
    return artifacts


def read_eval_reports(eval_dir: str | Path) -> dict[str, dict[str, Any]]:
    root = Path(eval_dir)
    reports: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return reports
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        report_path = child / "report.json"
        if not report_path.is_file():
            continue
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        reports[child.name] = _normalize_report(payload, child.name)
    return reports


def read_resolved_ids(eval_dir: str | Path) -> set[str]:
    return {instance_id for instance_id, report in read_eval_reports(eval_dir).items() if report.get("resolved")}
