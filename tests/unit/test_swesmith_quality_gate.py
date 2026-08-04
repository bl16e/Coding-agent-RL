import json
from pathlib import Path

from coding_agent.swesmith.quality_gate import run_quality_gate


def _write_eval(eval_dir: Path, instance_id: str, *, resolved: bool) -> None:
    report_dir = eval_dir / instance_id
    report_dir.mkdir(parents=True)
    report_dir.joinpath("report.json").write_text(
        json.dumps({"resolved": resolved}),
        encoding="utf-8",
    )


def _write_run(
    runs_dir: Path,
    instance_id: str,
    *,
    max_steps: int = 50,
    step_count: int = 4,
    empty_reasoning: bool = False,
    command: str = "python -m pytest tests/test_app.py -x --tb=short",
    patch_path: str = "app.py",
    patch: str | None = None,
) -> None:
    run_dir = runs_dir / instance_id
    run_dir.mkdir(parents=True)
    run_dir.joinpath("summary.json").write_text(
        json.dumps(
            {
                "instance_id": instance_id,
                "model_name": "mock-model",
                "budget": {"max_steps": max_steps},
            }
        ),
        encoding="utf-8",
    )
    patch_text = patch if patch is not None else f"diff --git a/{patch_path} b/{patch_path}\n"
    run_dir.joinpath("final.patch").write_text(patch_text, encoding="utf-8")
    events = []
    for idx in range(step_count):
        if idx % 2 == 0:
            events.append(
                {
                    "step_index": idx,
                    "action_type": "model",
                    "reasoning_summary": "" if empty_reasoning else "I will inspect and test the fix.",
                }
            )
        else:
            events.append(
                {
                    "step_index": idx,
                    "action_type": "tool_result",
                    "tool_call": {
                        "tool_name": "execute_bash",
                        "input": {"command": command},
                    },
                    "tool_result": {"status": "ok"},
                }
            )
    run_dir.joinpath("trajectory.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_quality_gate_writes_report_and_filtered_sft_for_accepted_run(tmp_path: Path):
    runs = tmp_path / "runs"
    eval_dir = tmp_path / "eval"
    _write_run(runs, "inst-1")
    _write_eval(eval_dir, "inst-1", resolved=True)
    report = tmp_path / "quality.json"
    filtered = tmp_path / "filtered.jsonl"

    result = run_quality_gate(runs_dir=runs, eval_dir=eval_dir, report_output=report, filtered_sft_output=filtered)

    assert result.accepted_count == 1
    assert result.rejected_count == 0
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    assert report_payload["accepted_count"] == 1
    assert report_payload["items"][0]["accepted"] is True
    rows = _read_jsonl(filtered)
    assert len(rows) == 1
    assert rows[0]["instance_id"] == "inst-1"
    assert rows[0]["resolved"] is True
    assert rows[0]["messages"][0]["role"] == "system"


def test_quality_gate_rejects_common_bad_trajectories(tmp_path: Path):
    runs = tmp_path / "runs"
    eval_dir = tmp_path / "eval"
    _write_run(runs, "unresolved")
    _write_eval(eval_dir, "unresolved", resolved=False)
    _write_run(runs, "empty-reasoning", empty_reasoning=True)
    _write_eval(eval_dir, "empty-reasoning", resolved=True)
    _write_run(runs, "blocked-shell", command="python -m pytest tests | tail -20")
    _write_eval(eval_dir, "blocked-shell", resolved=True)
    _write_run(runs, "touches-tests", patch_path="tests/test_app.py")
    _write_eval(eval_dir, "touches-tests", resolved=True)
    _write_run(runs, "too-long", max_steps=10, step_count=10)
    _write_eval(eval_dir, "too-long", resolved=True)
    _write_run(runs, "empty-patch", patch="")
    _write_eval(eval_dir, "empty-patch", resolved=True)
    report = tmp_path / "quality.json"
    filtered = tmp_path / "filtered.jsonl"

    result = run_quality_gate(runs_dir=runs, eval_dir=eval_dir, report_output=report, filtered_sft_output=filtered)

    assert result.accepted_count == 2
    assert result.rejected_count == 4
    items = {item["instance_id"]: item for item in json.loads(report.read_text(encoding="utf-8"))["items"]}
    assert "unresolved" in items["unresolved"]["reasons"]
    assert "empty_reasoning" in items["empty-reasoning"]["reasons"]
    assert items["blocked-shell"]["accepted"] is True
    assert "patch_touches_tests" in items["touches-tests"]["reasons"]
    assert items["too-long"]["accepted"] is True
    assert items["too-long"]["metrics"]["step_limit_near_exhausted"] is True
    assert "step_limit_near_exhausted" not in items["too-long"]["reasons"]
    assert "empty_patch" in items["empty-patch"]["reasons"]
    assert len(_read_jsonl(filtered)) == 2


def test_quality_gate_only_blocks_shell_syntax_not_python_string_contents(tmp_path: Path):
    runs = tmp_path / "runs"
    eval_dir = tmp_path / "eval"
    _write_run(
        runs,
        "python-comparison",
        command="python -c 'print(1 > 0); print(2 < 3); print(\"a|b\")'",
    )
    _write_eval(eval_dir, "python-comparison", resolved=True)
    _write_run(runs, "real-grep", command="python -m pytest tests | grep FAILED")
    _write_eval(eval_dir, "real-grep", resolved=True)
    report = tmp_path / "quality.json"
    filtered = tmp_path / "filtered.jsonl"

    result = run_quality_gate(runs_dir=runs, eval_dir=eval_dir, report_output=report, filtered_sft_output=filtered)

    items = {item["instance_id"]: item for item in json.loads(report.read_text(encoding="utf-8"))["items"]}
    assert result.accepted_count == 1
    assert items["python-comparison"]["accepted"] is True
    assert "blocked_execute_bash" not in items["python-comparison"]["reasons"]
    assert "blocked_execute_bash" in items["real-grep"]["reasons"]


def test_quality_gate_allows_head_tail_stderr_merge_and_step_limit_warning(tmp_path: Path):
    runs = tmp_path / "runs"
    eval_dir = tmp_path / "eval"
    _write_run(
        runs,
        "tail-output",
        command="python -m pytest tests -q 2>&1 | tail -20",
        max_steps=10,
        step_count=10,
    )
    _write_eval(eval_dir, "tail-output", resolved=True)
    _write_run(runs, "head-output", command="python -m pytest tests -q 2>&1 | head -20")
    _write_eval(eval_dir, "head-output", resolved=True)
    report = tmp_path / "quality.json"
    filtered = tmp_path / "filtered.jsonl"

    result = run_quality_gate(runs_dir=runs, eval_dir=eval_dir, report_output=report, filtered_sft_output=filtered)

    items = {item["instance_id"]: item for item in json.loads(report.read_text(encoding="utf-8"))["items"]}
    assert result.accepted_count == 2
    assert items["tail-output"]["accepted"] is True
    assert items["tail-output"]["metrics"]["step_limit_near_exhausted"] is True
    assert "step_limit_near_exhausted" not in items["tail-output"]["reasons"]
    assert items["head-output"]["accepted"] is True
