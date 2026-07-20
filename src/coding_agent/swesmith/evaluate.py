from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


def run_official_eval(
    *,
    dataset_path: str | Path,
    predictions_path: str | Path,
    run_id: str,
    workers: int,
    timeout: int,
    reference_path: str | Path | None,
    runner: Callable[..., Any] = subprocess.run,
) -> int:
    command = [
        sys.executable,
        "-m",
        "swesmith.harness.eval",
        "--dataset_path",
        str(dataset_path),
        "--predictions_path",
        str(predictions_path),
        "--run_id",
        run_id,
        "--workers",
        str(workers),
        "--timeout",
        str(timeout),
    ]
    env = dict(os.environ)
    if reference_path is not None:
        env["PYTHONPATH"] = str(Path(reference_path).resolve()) + os.pathsep + env.get("PYTHONPATH", "")
    completed = runner(command, text=True, capture_output=True, check=False, env=env)
    return int(completed.returncode)


def _report_resolved(payload: dict[str, Any], instance_id: str) -> bool:
    if "resolved" in payload:
        return bool(payload["resolved"])
    nested = payload.get(instance_id)
    if isinstance(nested, dict):
        return bool(nested.get("resolved", False))
    return False


def read_resolved_ids(eval_dir: str | Path) -> set[str]:
    root = Path(eval_dir)
    resolved: set[str] = set()
    if not root.is_dir():
        return resolved
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        report_path = child / "report.json"
        if not report_path.is_file():
            continue
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if _report_resolved(payload, child.name):
            resolved.add(child.name)
    return resolved
