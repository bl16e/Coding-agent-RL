from __future__ import annotations

import uuid
from pathlib import Path

from coding_agent.budgets import BudgetTracker
from coding_agent.model_backends.base import AgentAction, AgentActionType, ModelBackend
from coding_agent.models import (
    AgentRun,
    BenchmarkTask,
    Outcome,
    Prediction,
    RunBudget,
    RunStatus,
    RunSummary,
    StepActionType,
    TrajectoryStep,
    utc_now,
)
from coding_agent.swebench.prediction import write_prediction_jsonl
from coding_agent.trajectory.patch import generate_unified_patch, snapshot_workspace
from coding_agent.trajectory.summary import write_summary
from coding_agent.trajectory.writer import TrajectoryWriter


class ArtifactPersistenceError(RuntimeError):
    pass


FINAL_STATUS_MAP = {
    "solved": RunStatus.SOLVED,
    "failed": RunStatus.FAILED,
    "incomplete": RunStatus.INCOMPLETE,
    "errored": RunStatus.ERRORED,
}


def create_task_from_paths(
    *,
    instance_id: str,
    workspace: str | Path,
    problem_statement_file: str | Path,
    allowed_test_commands: tuple[str, ...],
) -> BenchmarkTask:
    problem_path = Path(problem_statement_file)
    if not problem_path.is_file():
        raise ValueError("problem_statement_file must exist")
    return BenchmarkTask(
        instance_id=instance_id,
        workspace=Path(workspace),
        problem_statement=problem_path.read_text(encoding="utf-8"),
        allowed_test_commands=allowed_test_commands,
    )


def _terminal_status(action: AgentAction) -> RunStatus:
    status = action.final_status or "incomplete"
    try:
        return FINAL_STATUS_MAP[status]
    except KeyError as exc:
        raise ValueError(f"unsupported final status: {status}") from exc


def _decision_step(step_index: int, action: AgentAction) -> TrajectoryStep:
    return TrajectoryStep(
        step_index=step_index,
        timestamp=utc_now(),
        action_type=StepActionType.MODEL,
        outcome=Outcome.OK,
        reasoning_summary=action.reasoning_summary,
        next_intent=action.next_intent,
        tool_selection_reason=action.tool_selection_reason,
    )


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def _write_artifacts(
    *,
    output_dir: Path,
    summary: RunSummary,
    prediction: Prediction,
    final_patch: str,
) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "final.patch").write_text(final_patch, encoding="utf-8")
        write_summary(output_dir / "summary.json", summary)
        write_prediction_jsonl(output_dir / "prediction.jsonl", prediction)
    except OSError as exc:
        raise ArtifactPersistenceError(str(exc)) from exc


def run_task(
    *,
    task: BenchmarkTask,
    budget: RunBudget,
    backend: ModelBackend,
    model_name: str,
    output_dir: str | Path,
    run_id: str | None = None,
) -> RunSummary:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    before = snapshot_workspace(task.workspace)
    writer = TrajectoryWriter(output_path / "trajectory.jsonl")
    tracker = BudgetTracker(budget)
    agent_run = AgentRun(
        run_id=run_id or str(uuid.uuid4()),
        task=task,
        budget=budget,
        model_name=model_name,
        output_dir=output_path,
    )
    agent_run.start()
    final_error: str | None = None

    while not tracker.max_steps_reached:
        if tracker.total_timeout_reached():
            final_error = "total runtime budget reached"
            break
        step_number = tracker.consume_step()
        action = backend.next_action(
            [
                {"role": "system", "content": "Return the next AgentAction as JSON."},
                {"role": "user", "content": task.problem_statement},
            ]
        )
        try:
            writer.write_step(_decision_step(step_number, action))
        except OSError as exc:
            raise ArtifactPersistenceError(str(exc)) from exc
        if action.action is AgentActionType.FINAL:
            agent_run.finish(_terminal_status(action))
            final_error = action.final_message
            break
    else:
        final_error = "max steps budget reached"

    if agent_run.status is RunStatus.RUNNING:
        agent_run.finish(RunStatus.INCOMPLETE)

    after = snapshot_workspace(task.workspace)
    final_patch = generate_unified_patch(before, after)
    artifacts = {
        "trajectory": str(output_path / "trajectory.jsonl"),
        "final_patch": str(output_path / "final.patch"),
        "prediction": str(output_path / "prediction.jsonl"),
    }
    summary = RunSummary(
        run_id=agent_run.run_id,
        instance_id=task.instance_id,
        model_name=model_name,
        status=agent_run.status,
        budget=budget,
        changed_files=_changed_files(before, after),
        test_summary={},
        error=final_error,
        artifacts=artifacts,
    )
    prediction = Prediction(task.instance_id, model_name, final_patch)
    _write_artifacts(output_dir=output_path, summary=summary, prediction=prediction, final_patch=final_patch)
    return summary

