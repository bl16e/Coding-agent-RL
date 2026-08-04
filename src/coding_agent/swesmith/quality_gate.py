from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coding_agent.swesmith.evaluate import read_eval_reports
from coding_agent.swesmith.export_sft import _messages_from_trajectory, _traj_id


BLOCKED_SHELL_COMMANDS = {"cat", "grep", "find", "awk", "sed", "git"}
SHELL_CONTROL_TOKENS = {"||", ">", ">>", "<", "<<", "<<<", ">&", "<&", "2>", "2>>"}
SHELL_COMMAND_SEPARATORS = {";", "&&", "||", "|", "|&"}
REDIRECTION_TOKEN_PATTERN = re.compile(r"^\d*(?:>>?|<<?|>&|<&).*$")
TEST_PATH_MARKERS = (
    "test/",
    "tests/",
    "/test/",
    "/tests/",
    "fixtures/",
    "/fixtures/",
    "snapshots/",
    "/snapshots/",
    "expected/",
    "/expected/",
)


@dataclass(frozen=True)
class QualityGateResult:
    accepted_count: int
    rejected_count: int
    report_path: Path
    filtered_sft_path: Path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _patch_files(patch: str) -> list[str]:
    files: list[str] = []
    for line in patch.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) >= 4 and parts[2].startswith("a/"):
            files.append(parts[2][2:])
    return files


def _is_test_or_expected_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.startswith(("test/", "tests/")) or any(marker in normalized for marker in TEST_PATH_MARKERS)


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return [command]


def _is_blocked_shell_command(command: str) -> bool:
    tokens = _shell_tokens(command)
    expect_command = True
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "2>&1":
            index += 1
            continue
        if token == "2" and tokens[index : index + 3] == ["2", ">&", "1"]:
            index += 3
            continue
        if token in SHELL_CONTROL_TOKENS or REDIRECTION_TOKEN_PATTERN.match(token):
            return True
        if token in SHELL_COMMAND_SEPARATORS:
            expect_command = True
            index += 1
            continue
        if token in {"cd", "env", "time", "timeout", "python", "python3", "python.exe"}:
            expect_command = False
            index += 1
            continue
        if expect_command:
            executable = Path(token).name.lower()
            if executable in BLOCKED_SHELL_COMMANDS:
                return True
            expect_command = False
        index += 1
    return False


def _max_steps(summary: dict[str, Any]) -> int | None:
    budget = summary.get("budget")
    if not isinstance(budget, dict):
        return None
    value = budget.get("max_steps")
    return int(value) if isinstance(value, int) and value > 0 else None


def _trajectory_metrics(events: list[dict[str, Any]], max_steps: int | None) -> dict[str, Any]:
    model_events = [event for event in events if event.get("action_type") == "model"]
    blocked_indices: list[int | None] = []
    for event in events:
        tool_call = event.get("tool_call")
        if not isinstance(tool_call, dict):
            continue
        if tool_call.get("tool_name") != "execute_bash":
            continue
        command = ""
        tool_input = tool_call.get("input")
        if isinstance(tool_input, dict):
            command = str(tool_input.get("command") or "")
        if _is_blocked_shell_command(command):
            blocked_indices.append(event.get("step_index"))
    near_limit = False
    if max_steps is not None:
        near_limit = len(events) >= max_steps * 0.9
    return {
        "total_steps": len(events),
        "model_steps": len(model_events),
        "tool_steps": len(events) - len(model_events),
        "empty_reasoning_model_steps": sum(
            1 for event in model_events if not str(event.get("reasoning_summary") or "").strip()
        ),
        "blocked_execute_bash_count": len(blocked_indices),
        "blocked_execute_bash_indices": blocked_indices,
        "step_limit_near_exhausted": near_limit,
    }


def _evaluate_run(run_dir: Path, runs_root: Path, eval_reports: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    reasons: list[str] = []
    summary_path = run_dir / "summary.json"
    trajectory_path = run_dir / "trajectory.jsonl"
    patch_path = run_dir / "final.patch"
    if not summary_path.is_file():
        return (
            {
                "instance_id": run_dir.name,
                "accepted": False,
                "reasons": ["missing_summary"],
                "metrics": {},
            },
            None,
        )
    summary = _load_json(summary_path)
    instance_id = str(summary.get("instance_id") or run_dir.name)
    report = eval_reports.get(instance_id)
    if not report or not report.get("resolved"):
        reasons.append("unresolved")
    if not trajectory_path.is_file():
        reasons.append("missing_trajectory")
        events: list[dict[str, Any]] = []
    else:
        events = _load_jsonl(trajectory_path)
    if not patch_path.is_file():
        reasons.append("missing_patch")
        patch = ""
    else:
        patch = patch_path.read_text(encoding="utf-8")
    files = _patch_files(patch)
    touches_tests = any(_is_test_or_expected_path(path) for path in files)
    source_files = [path for path in files if not _is_test_or_expected_path(path)]
    if not patch.strip():
        reasons.append("empty_patch")
    if touches_tests:
        reasons.append("patch_touches_tests")
    if patch.strip() and not source_files:
        reasons.append("no_source_patch")
    metrics = _trajectory_metrics(events, _max_steps(summary))
    if metrics["empty_reasoning_model_steps"]:
        reasons.append("empty_reasoning")
    if metrics["blocked_execute_bash_count"]:
        reasons.append("blocked_execute_bash")
    item = {
        "instance_id": instance_id,
        "accepted": not reasons,
        "reasons": reasons,
        "metrics": {
            **metrics,
            "patch_files": files,
            "patch_touches_tests": touches_tests,
            "source_patch_files": source_files,
        },
    }
    if reasons:
        return item, None
    row = {
        "instance_id": instance_id,
        "resolved": True,
        "model": str(summary.get("model_name", "")),
        "traj_id": _traj_id(instance_id, runs_root),
        "patch": patch,
        "messages": _messages_from_trajectory(trajectory_path),
    }
    return item, row


def run_quality_gate(
    *,
    runs_dir: str | Path,
    eval_dir: str | Path,
    report_output: str | Path,
    filtered_sft_output: str | Path,
) -> QualityGateResult:
    runs_root = Path(runs_dir)
    eval_reports = read_eval_reports(eval_dir)
    items: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        item, row = _evaluate_run(run_dir, runs_root, eval_reports)
        items.append(item)
        if row is not None:
            rows.append(row)
    report_path = Path(report_output)
    filtered_path = Path(filtered_sft_output)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    filtered_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "coding-agent.swesmith.quality-gate.v1",
        "runs_dir": str(runs_root),
        "eval_dir": str(eval_dir),
        "total": len(items),
        "accepted_count": len(rows),
        "rejected_count": len(items) - len(rows),
        "items": items,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    filtered_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return QualityGateResult(
        accepted_count=len(rows),
        rejected_count=len(items) - len(rows),
        report_path=report_path,
        filtered_sft_path=filtered_path,
    )
