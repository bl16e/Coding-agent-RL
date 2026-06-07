from __future__ import annotations

import json
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
    ToolCall,
    ToolName,
    utc_now,
)
from coding_agent.swebench.prediction import write_prediction_jsonl
from coding_agent.tools import LocalToolExecutor, ToolExecutionResult, ToolExecutor
from coding_agent.tools.schemas import FINAL_ACTION_SCHEMA, TOOL_SCHEMAS
from coding_agent.trajectory.converter import convert_trajectory_to_summary_format
from coding_agent.trajectory.patch import generate_unified_patch, snapshot_workspace
from coding_agent.trajectory.summary import write_summary
from coding_agent.trajectory.writer import TrajectoryWriter


class ArtifactPersistenceError(RuntimeError):
    """Raised when required run artifacts cannot be written durably."""

    pass


# Final status values are produced by the model, while RunStatus is the
# internal persisted contract. Keep the mapping explicit so unsupported model
# output fails fast instead of being silently normalized.
FINAL_STATUS_MAP = {
    "solved": RunStatus.SOLVED,
    "failed": RunStatus.FAILED,
    "incomplete": RunStatus.INCOMPLETE,
    "errored": RunStatus.ERRORED,
}

ACTION_TOOL_MAP = {
    AgentActionType.READ_FILE: ToolName.READ_FILE,
    AgentActionType.APPLY_PATCH: ToolName.APPLY_PATCH,
    AgentActionType.SEARCH_CODE: ToolName.SEARCH_CODE,
    AgentActionType.RUN_TESTS: ToolName.RUN_TESTS,
}


def _system_prompt(task: BenchmarkTask) -> str:
    """Generate a task-focused system prompt that relies on native function calling."""
    allowed_tests = "\n".join(f"  {command}" for command in task.allowed_test_commands)
    return (
        "You are a coding agent that solves repository issues by using the provided tools.\n\n"
        "Your task:\n"
        f"{task.problem_statement}\n\n"
        "Allowed test commands (use these exact strings with run_tests):\n"
        f"{allowed_tests}\n\n"
        "Work systematically: read relevant files, understand the issue, make changes, and verify with tests. "
        "Call the 'final' tool when you have solved the issue or determined it cannot be solved."
    )


def _action_message(action: AgentAction) -> dict[str, str]:
    if action.raw_message is not None:
        return action.raw_message
    payload = {
        "action": action.action.value,
        "tool_input": action.tool_input,
        "reasoning_summary": action.reasoning_summary,
        "next_intent": action.next_intent,
        "tool_selection_reason": action.tool_selection_reason,
        "final_status": action.final_status,
        "final_message": action.final_message,
    }
    return {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)}


def _tool_observation_message(result: ToolExecutionResult) -> dict[str, str]:
    payload = {
        "tool_name": result.tool_name.value,
        "status": result.status.value,
        "output_summary": result.output_summary,
        "output": result.output,
        "modifications": result.modifications,
    }
    return {"role": "user", "content": "Tool observation: " + json.dumps(payload, ensure_ascii=False, default=str)}


def _tool_history_message(action: AgentAction, result: ToolExecutionResult) -> dict[str, object]:
    payload = {
        "tool_name": result.tool_name.value,
        "status": result.status.value,
        "output_summary": result.output_summary,
        "output": result.output,
        "modifications": result.modifications,
        "test_result": result.test_result,
    }
    if action.tool_call_id:
        return {
            "role": "tool",
            "tool_call_id": action.tool_call_id,
            "content": json.dumps(payload, ensure_ascii=False, default=str),
        }
    return _tool_observation_message(result)


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
    """Capture the model decision before any tool side effect happens."""

    return TrajectoryStep(
        step_index=step_index,
        timestamp=utc_now(),
        action_type=StepActionType.MODEL,
        outcome=Outcome.OK,
        reasoning_summary=action.reasoning_summary,
        next_intent=action.next_intent,
        tool_selection_reason=action.tool_selection_reason,
    )


def _tool_result_step(step_index: int, result: ToolExecutionResult, tool_input: dict) -> TrajectoryStep:
    """Convert concrete tool output into the trajectory JSONL schema."""

    now = utc_now()
    tool_call = ToolCall(
        tool_name=result.tool_name,
        input=tool_input,
        output_summary=result.output_summary,
        status=result.status,
        started_at=now,
        ended_at=now,
    )
    return TrajectoryStep(
        step_index=step_index,
        timestamp=now,
        action_type=StepActionType.TOOL_RESULT,
        outcome=result.status,
        tool_call=tool_call,
        tool_result={
            "output": result.output,
            "modifications": result.modifications,
            "test_result": result.test_result,
        },
    )


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Return workspace-relative text files whose snapshot content changed."""

    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def _write_artifacts(
    *,
    output_dir: Path,
    summary: RunSummary,
    prediction: Prediction,
    final_patch: str,
    task: BenchmarkTask,
) -> None:
    """Write all terminal artifacts as one persistence boundary.

    The files are small enough to write synchronously. Grouping the writes here
    gives the CLI one error type to map to the documented artifact-persistence
    exit code.
    """

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "final.patch").write_text(final_patch, encoding="utf-8")
        write_summary(output_dir / "summary.json", summary)
        write_prediction_jsonl(output_dir / "prediction.jsonl", prediction)

        # Generate simplified trajectory format
        convert_trajectory_to_summary_format(
            trajectory_jsonl=output_dir / "trajectory.jsonl",
            task_id=task.instance_id,
            issue=task.problem_statement,
            final_diff=final_patch,
            resolved=summary.status == RunStatus.SOLVED,
            output_path=output_dir / "trajectory.json",
        )
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
    tool_executor: ToolExecutor | None = None,
) -> RunSummary:
    """Run one SWE-Bench Lite-style attempt against a prepared workspace.

    This orchestrator deliberately owns only the control flow: budget checks,
    model action requests, tool dispatch, trajectory streaming, and terminal
    artifact generation. Tool semantics, model transport, patch creation, and
    summary serialization stay in their focused modules to keep the agent core
    easy to audit.
    """

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    # Snapshots are text-only by design. SWE-Bench predictions are patches, and
    # binary files cannot be represented faithfully by the simple unified diff
    # format used by this MVP.
    before = snapshot_workspace(task.workspace)
    writer = TrajectoryWriter(output_path / "trajectory.jsonl")
    tracker = BudgetTracker(budget)
    executor = tool_executor or LocalToolExecutor(
        workspace=task.workspace,
        allowed_test_commands=task.allowed_test_commands,
        test_timeout_seconds=budget.test_timeout_seconds,
    )
    agent_run = AgentRun(
        run_id=run_id or str(uuid.uuid4()),
        task=task,
        budget=budget,
        model_name=model_name,
        output_dir=output_path,
    )
    agent_run.start()
    final_error: str | None = None
    test_summary: dict[str, int] = {}
    last_successful_tool_call: str | None = None
    trajectory_index = 0
    messages: list[dict[str, object]] = [
        {"role": "system", "content": _system_prompt(task)},
        {"role": "user", "content": task.problem_statement},
    ]

    while not tracker.max_steps_reached:
        if tracker.total_timeout_reached():
            final_error = "total runtime budget reached"
            break
        # One budget step is one model decision. The following tool result, if
        # any, gets its own trajectory entry but does not consume another model
        # step. This keeps max_steps aligned with agent thinking turns.
        tracker.consume_step()
        action = backend.next_action([dict(message) for message in messages])
        try:
            # Persist the decision before executing tools so a crash during a
            # filesystem write or test run still leaves an inspectable trail.
            writer.write_step(_decision_step(trajectory_index, action))
        except OSError as exc:
            raise ArtifactPersistenceError(str(exc)) from exc
        trajectory_index += 1
        messages.append(_action_message(action))
        if action.action is AgentActionType.FINAL:
            agent_run.finish(_terminal_status(action))
            final_error = action.final_message
            break
        tool_name = ACTION_TOOL_MAP[action.action]
        result = executor.execute(tool_name, action.tool_input)
        if result.status is Outcome.OK:
            last_successful_tool_call = result.tool_name.value
        if result.test_result is not None:
            # Keep summary aggregation small; the full command output remains
            # attached to the individual trajectory tool_result step.
            key = result.test_result.status.value
            test_summary[key] = test_summary.get(key, 0) + 1
        try:
            writer.write_step(_tool_result_step(trajectory_index, result, action.tool_input))
        except OSError as exc:
            raise ArtifactPersistenceError(str(exc)) from exc
        trajectory_index += 1
        messages.append(_tool_history_message(action, result))
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
        test_summary=test_summary,
        error=final_error,
        last_successful_tool_call=last_successful_tool_call,
        artifacts=artifacts,
    )
    prediction = Prediction(task.instance_id, model_name, final_patch)
    _write_artifacts(output_dir=output_path, summary=summary, prediction=prediction, final_patch=final_patch, task=task)
    return summary
