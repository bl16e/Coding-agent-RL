"""Aggregate evaluation reporting for SWE-Bench batch runs.

Reads per-instance ``summary.json`` files from a batch output directory and
computes aggregate resolution metrics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class EvaluateInputError(ValueError):
    """Raised when the batch directory is missing or contains no valid runs."""


@dataclass(frozen=True)
class InstanceResult:
    instance_id: str
    repo: str
    status: str
    resolved: bool | None
    error: str | None
    fail_to_pass_success: int
    fail_to_pass_failure: int
    pass_to_pass_success: int
    pass_to_pass_failure: int

    @property
    def resolved_text(self) -> str:
        if self.resolved is True:
            return "✓ RESOLVED"
        if self.resolved is False:
            return "✗ UNRESOLVED"
        return "ERROR"


def _safe_read_summary(summary_path: Path) -> dict[str, Any] | None:
    """Read and parse a summary.json, returning None on any failure."""
    if not summary_path.is_file():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _extract_instance_result(summary: dict[str, Any]) -> InstanceResult:
    instance_id = str(summary.get("instance_id", ""))
    prepared = summary.get("prepared_environment") or {}
    repo = str(prepared.get("repo", ""))
    status = str(summary.get("status", "errored"))
    validation = summary.get("validation") or {}
    eval_report = validation.get("eval_report") or {}
    resolved = eval_report.get("resolved")
    agent_status = summary.get("agent_status")
    agent_error = summary.get("agent_error")
    error = summary.get("error") or agent_error or None
    if resolved is not None and not isinstance(resolved, bool):
        resolved = None
    return InstanceResult(
        instance_id=instance_id,
        repo=repo or _infer_repo_from_instance_id(instance_id),
        status=status,
        resolved=resolved,
        error=error,
        fail_to_pass_success=len(eval_report.get("fail_to_pass_success", ())),
        fail_to_pass_failure=len(eval_report.get("fail_to_pass_failure", ())),
        pass_to_pass_success=len(eval_report.get("pass_to_pass_success", ())),
        pass_to_pass_failure=len(eval_report.get("pass_to_pass_failure", ())),
    )


def _infer_repo_from_instance_id(instance_id: str) -> str:
    """Fallback repo extraction when prepared_environment is missing."""
    parts = instance_id.split("__", 1)
    if len(parts) == 2:
        owner_repo, _rest = parts[0], parts[1]
        parts2 = _rest.rsplit("-", 1)
        if len(parts2) == 2 and parts2[1].isdigit():
            return f"{parts[0]}/{parts2[0]}"
    return "unknown"


def _load_instance_ids_from_batch_state(batch_dir: Path) -> dict[str, Path] | None:
    """Return {instance_id: run_dir} from batch_state.json, or None."""
    state_path = batch_dir / "batch_state.json"
    if not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tasks = state.get("tasks") or {}
    if not tasks:
        return None
    result: dict[str, Path] = {}
    for instance_id, entry in tasks.items():
        run_dir = entry.get("run_dir")
        if run_dir:
            result[str(instance_id)] = Path(str(run_dir))
    return result if result else None


def _discover_run_dirs(batch_dir: Path) -> dict[str, Path]:
    """Scan batch_dir for subdirectories containing run/summary.json."""
    result: dict[str, Path] = {}
    if not batch_dir.is_dir():
        return result
    for entry in sorted(batch_dir.iterdir()):
        if not entry.is_dir():
            continue
        run_dir = entry / "run"
        summary_path = run_dir / "summary.json"
        if summary_path.is_file():
            result[entry.name] = run_dir
    return result


def load_evaluation_results(batch_dir: Path) -> list[dict[str, Any]]:
    """Load per-instance evaluation results from a batch output directory.

    Returns a list of dicts suitable for :func:`compute_aggregate_metrics`.
    Each dict contains the InstanceResult fields plus a ``resolved_text`` key.
    """
    if not batch_dir.is_dir():
        raise EvaluateInputError(f"batch directory does not exist: {batch_dir}")

    run_dirs = _load_instance_ids_from_batch_state(batch_dir)
    if run_dirs is None:
        run_dirs = _discover_run_dirs(batch_dir)

    if not run_dirs:
        raise EvaluateInputError(f"no run directories found in {batch_dir}")

    results: list[dict[str, Any]] = []
    for instance_id, run_dir in sorted(run_dirs.items()):
        summary = _safe_read_summary(run_dir / "summary.json")
        if summary is None:
            results.append(
                {
                    "instance_id": instance_id,
                    "repo": _infer_repo_from_instance_id(instance_id),
                    "status": "missing_summary",
                    "resolved": None,
                    "resolved_text": "ERROR",
                    "error": "summary.json not found or unreadable",
                    "fail_to_pass_success": 0,
                    "fail_to_pass_failure": 0,
                    "pass_to_pass_success": 0,
                    "pass_to_pass_failure": 0,
                }
            )
            continue
        instance_result = _extract_instance_result(summary)
        results.append(
            {
                "instance_id": instance_result.instance_id or instance_id,
                "repo": instance_result.repo,
                "status": instance_result.status,
                "resolved": instance_result.resolved,
                "resolved_text": instance_result.resolved_text,
                "error": instance_result.error,
                "fail_to_pass_success": instance_result.fail_to_pass_success,
                "fail_to_pass_failure": instance_result.fail_to_pass_failure,
                "pass_to_pass_success": instance_result.pass_to_pass_success,
                "pass_to_pass_failure": instance_result.pass_to_pass_failure,
            }
        )
    return results


def compute_aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate evaluation metrics from per-instance results.

    Errored instances (no eval_report) are excluded from the resolve rate
    denominator so that infrastructure failures do not distort the score.
    """
    total = len(results)
    resolved = sum(1 for r in results if r["resolved"] is True)
    unresolved = sum(1 for r in results if r["resolved"] is False)
    errored = total - resolved - unresolved

    evaluable = total - errored
    resolve_rate = resolved / evaluable if evaluable > 0 else 0.0

    per_repo: dict[str, dict[str, Any]] = {}
    for r in results:
        repo = r["repo"]
        entry = per_repo.setdefault(repo, {"total": 0, "resolved": 0, "unresolved": 0, "errored": 0})
        entry["total"] += 1
        if r["resolved"] is True:
            entry["resolved"] += 1
        elif r["resolved"] is False:
            entry["unresolved"] += 1
        else:
            entry["errored"] += 1
    for repo, entry in per_repo.items():
        evaluable_repo = entry["total"] - entry["errored"]
        entry["resolve_rate"] = entry["resolved"] / evaluable_repo if evaluable_repo > 0 else 0.0

    per_status: dict[str, int] = {}
    for r in results:
        status = r["status"]
        per_status[status] = per_status.get(status, 0) + 1

    return {
        "total": total,
        "resolved": resolved,
        "unresolved": unresolved,
        "errored": errored,
        "resolve_rate": round(resolve_rate, 4),
        "per_repo": {repo: dict(entry) for repo, entry in sorted(per_repo.items())},
        "per_status": dict(sorted(per_status.items())),
        "instances": results,
    }


def render_evaluation_report(report: dict[str, Any], batch_dir: str | None = None) -> str:
    """Render an aggregate evaluation report as human-readable text."""
    lines: list[str] = []
    lines.append("SWE-Bench Evaluation Report")
    lines.append("=" * 27)
    if batch_dir:
        lines.append(f"Batch:  {batch_dir}")
    lines.append("")
    total = int(report["total"])
    resolved = int(report["resolved"])
    unresolved = int(report["unresolved"])
    errored = int(report["errored"])
    rate = float(report["resolve_rate"])
    lines.append(f"Total:       {total}")
    lines.append(f"Resolved:    {resolved} ({rate:.1%})")
    lines.append(f"Unresolved:  {unresolved} ({unresolved / total:.1%})" if total else "Unresolved:  0")
    lines.append(f"Errored:     {errored} ({errored / total:.1%})" if total else "Errored:     0")

    per_repo = report.get("per_repo") or {}
    if per_repo:
        lines.append("")
        lines.append("Per repository:")
        for repo, entry in sorted(per_repo.items()):
            repo_rate = float(entry["resolve_rate"])
            lines.append(
                f"  {repo:<30} {entry['resolved']}/{entry['total']} resolved ({repo_rate:.1%})"
            )

    instances = report.get("instances") or []
    if instances:
        lines.append("")
        lines.append("Details:")
        max_id_len = max((len(str(r["instance_id"])) for r in instances), default=0)
        id_width = max(max_id_len + 2, 30)
        for r in instances:
            f2p = f"F2P: {r['fail_to_pass_success']}/{r['fail_to_pass_success'] + r['fail_to_pass_failure']}"
            p2p = f"P2P: {r['pass_to_pass_success']}/{r['pass_to_pass_success'] + r['pass_to_pass_failure']}"
            lines.append(f"  {r['resolved_text']:<13} {r['instance_id']:<{id_width}} {f2p:<10} {p2p}")

    return "\n".join(lines)
