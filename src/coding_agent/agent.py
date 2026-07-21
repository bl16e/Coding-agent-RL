from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import uuid
from pathlib import Path

from coding_agent.budgets import BudgetTracker
from coding_agent.model_backends.base import AgentAction, AgentActionType, ModelBackend, TurnResult
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
    TestStatus,
    utc_now,
)
from coding_agent.swebench.prediction import write_prediction_jsonl
from coding_agent.tools import LocalToolExecutor, ToolExecutionResult, ToolExecutor
from coding_agent.tools.schemas import TOOL_SCHEMAS
from coding_agent.trajectory.converter import convert_trajectory_to_summary_format
from coding_agent.trajectory.patch import generate_workspace_patch, snapshot_workspace
from coding_agent.trajectory.summary import write_summary
from coding_agent.trajectory.writer import TrajectoryWriter


class ArtifactPersistenceError(RuntimeError):
    """必需运行产物无法可靠写入时抛出。

    这里单独定义错误类型，是为了让 CLI 能把"任务运行失败"和"产物落盘失败"
    映射成不同退出码。后者通常需要调用方优先处理，因为没有完整产物就无法审计
    代理到底做了什么。
    """

    pass


ACTION_TOOL_MAP = {
    AgentActionType.READ_FILE: ToolName.READ_FILE,
    AgentActionType.APPLY_PATCH: ToolName.APPLY_PATCH,
    AgentActionType.SEARCH_CODE: ToolName.SEARCH_CODE,
    AgentActionType.RUN_TESTS: ToolName.RUN_TESTS,
}


def _system_prompt(task: BenchmarkTask) -> str:
    """生成面向单个 SWE-Bench 任务的系统提示词。"""
    allowed_tests = "\n".join(f"  {command}" for command in task.allowed_test_commands)
    return (
        "You are a coding agent that solves repository issues by using the provided tools.\n\n"
        "Your task:\n"
        f"{task.problem_statement}\n\n"
        "You may use run_tests for focused repository tests and small diagnostics.\n"
        "Examples of allowed self-test commands:\n"
        f"{allowed_tests}\n\n"
        "Final benchmark validation is run automatically after you finish.\n\n"
        "Before claiming solved, compare your implementation with nearby project contracts, especially exact "
        "error messages, exception types, warnings, check IDs, and CLI output. Tests you add yourself are useful, "
        "but they are not enough on their own; also run existing adjacent tests or focused diagnostics when possible.\n\n"
        "Work systematically: read relevant files, understand the issue, make changes, and verify with tests. "
        "When you have solved the issue or determined it cannot be solved, explain your conclusion and stop calling tools."
    )


def _action_message(action: AgentAction) -> dict[str, str]:
    """把模型动作重新压回对话历史。

    OpenAI-compatible 后端可能返回原生 tool-call 消息，也可能返回规范化后的动作。
    这里保留 raw_message 优先级，避免丢失供应商返回的 tool_call_id 等协议细节。
    """
    if action.raw_message is not None:
        return action.raw_message
    payload = {
        "action": action.action.value,
        "tool_input": action.tool_input,
        "reasoning_summary": action.reasoning_summary,
        "next_intent": action.next_intent,
        "tool_selection_reason": action.tool_selection_reason,
    }
    return {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)}


def _tool_observation_message(result: ToolExecutionResult) -> dict[str, str]:
    """为不支持原生 tool role 的后端构造普通用户观察消息。"""
    if result.tool_name is ToolName.READ_FILE:
        return {"role": "user", "content": _read_file_observation_content(result)}
    payload = {
        "tool_name": result.tool_name.value,
        "status": result.status.value,
        "output_summary": result.output_summary,
        "output": result.output,
        "modifications": result.modifications,
    }
    return {"role": "user", "content": "Tool observation: " + json.dumps(payload, ensure_ascii=False, default=str)}


def _read_file_observation_content(result: ToolExecutionResult) -> str:
    """Format read_file output as source text, not JSON-escaped string content."""
    header = (
        f"Tool observation: {result.tool_name.value} {result.status.value}\n"
        f"Summary: {result.output_summary}"
    )
    content = result.output.get("content")
    if not isinstance(content, str):
        return header
    return f"{header}\n\n<file>\n{content}</file>"


def _tool_history_message(action: AgentAction, result: ToolExecutionResult) -> dict[str, object]:
    """把工具结果加入模型上下文。

    如果模型动作带有 tool_call_id，就按原生 tool 消息回复；否则退化为普通 user
    消息。这样同一条 agent loop 能同时服务真实 function calling 后端和 mock 后端。
    """
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
            "content": (
                _read_file_observation_content(result)
                if result.tool_name is ToolName.READ_FILE
                else json.dumps(payload, ensure_ascii=False, default=str)
            ),
        }
    return _tool_observation_message(result)


def create_task_from_paths(
    *,
    instance_id: str,
    workspace: str | Path,
    problem_statement_file: str | Path,
    allowed_test_commands: tuple[str, ...],
) -> BenchmarkTask:
    """从 CLI 路径参数创建任务对象。

    CLI 层只负责把字符串参数转换成领域对象；路径存在性和测试命令非空等约束由
    BenchmarkTask 继续校验，保证库调用和 CLI 调用得到一致行为。
    """
    problem_path = Path(problem_statement_file)
    if not problem_path.is_file():
        raise ValueError("problem_statement_file must exist")
    return BenchmarkTask(
        instance_id=instance_id,
        workspace=Path(workspace),
        problem_statement=problem_path.read_text(encoding="utf-8"),
        allowed_test_commands=allowed_test_commands,
    )


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


def _empty_self_test_coverage() -> dict[str, dict[str, int]]:
    statuses = {status.value: 0 for status in TestStatus}
    return {
        "self_authored_tests": dict(statuses),
        "existing_tests": dict(statuses),
        "diagnostics": dict(statuses),
    }


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    return normalized.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py")


def _test_path_identifiers(path: str) -> set[str]:
    normalized = path.replace("\\", "/")
    identifiers = {normalized}
    if normalized.startswith("tests/"):
        identifiers.add(normalized[len("tests/") :])
    if normalized.endswith(".py"):
        stem = normalized[:-3]
        identifiers.add(stem.replace("/", "."))
        if stem.startswith("tests/"):
            identifiers.add(stem[len("tests/") :].replace("/", "."))
    return identifiers


def _is_diagnostic_test_command(command: str) -> bool:
    stripped = command.strip()
    return stripped.startswith('python -c "') or stripped.startswith("python -c '") or stripped.startswith("python3 -c ")


def _self_test_category(command: str, authored_test_identifiers: set[str]) -> str:
    if _is_diagnostic_test_command(command):
        return "diagnostics"
    if any(identifier and identifier in command for identifier in authored_test_identifiers):
        return "self_authored_tests"
    return "existing_tests"


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

        # 额外生成汇总版轨迹，方便对接只需要 task/issue/diff/resolved 的消费方。
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


def _detect_conflicts(actions: list[AgentAction]) -> list[list[int]]:
    """Group action indices that conflict on the same file_path.

    Two actions conflict when they target the same file and at least one
    is a write (APPLY_PATCH).  Conflicting groups must run serially;
    non-conflicting actions run in parallel.

    Returns a list of groups, each group being a list of indices into *actions*.
    """
    # Build file_path -> list of indices for write operations
    write_targets: dict[str, list[int]] = {}
    for i, action in enumerate(actions):
        if action.action is AgentActionType.APPLY_PATCH:
            fp = action.tool_input.get("file_path", "")
            if fp:
                write_targets.setdefault(fp, []).append(i)

    # Build file_path -> list of indices for read operations that conflict with writes
    read_targets: dict[str, list[int]] = {}
    for i, action in enumerate(actions):
        if action.action is AgentActionType.READ_FILE:
            fp = action.tool_input.get("file_path", "")
            if fp and fp in write_targets:
                read_targets.setdefault(fp, []).append(i)

    # Collect conflicting indices
    conflicting: set[int] = set()
    for indices in write_targets.values():
        if len(indices) > 1:
            conflicting.update(indices)  # multiple writes to same file
    for fp, read_indices in read_targets.items():
        conflicting.update(read_indices)       # reads on files being written
        conflicting.update(write_targets[fp])  # writes on files being read

    if not conflicting:
        return [list(range(len(actions)))]

    # Non-conflicting indices go in one parallel group; conflicting each get their own
    parallel_group = [i for i in range(len(actions)) if i not in conflicting]
    groups: list[list[int]] = []
    if parallel_group:
        groups.append(parallel_group)
    for i in sorted(conflicting):
        groups.append([i])
    return groups


def _parallel_execute(
    executor: ToolExecutor,
    actions: list[AgentAction],
    action_tool_map: dict[AgentActionType, ToolName],
) -> list[ToolExecutionResult]:
    """Execute *actions* with concurrency where safe.

    Non-conflicting actions run in a ThreadPoolExecutor.  Conflicting
    actions (same file_path with a write) run sequentially.
    """
    if len(actions) == 1:
        tool_name = action_tool_map[actions[0].action]
        return [executor.execute(tool_name, actions[0].tool_input)]

    groups = _detect_conflicts(actions)
    results: list[ToolExecutionResult | None] = [None] * len(actions)

    for group in groups:
        if len(group) == 1:
            idx = group[0]
            tool_name = action_tool_map[actions[idx].action]
            results[idx] = executor.execute(tool_name, actions[idx].tool_input)
        else:
            def _run_one(idx: int) -> tuple[int, ToolExecutionResult]:
                tn = action_tool_map[actions[idx].action]
                return idx, executor.execute(tn, actions[idx].tool_input)

            with ThreadPoolExecutor(max_workers=len(group)) as pool:
                futures = {pool.submit(_run_one, i): i for i in group}
                for future in as_completed(futures):
                    idx, result = future.result()
                    results[idx] = result

    return results  # type: ignore[return-value]


def _extract_content(assistant_messages: list[dict[str, Any]]) -> str | None:
    """Return the text content from the last assistant message, if any."""
    for msg in reversed(assistant_messages):
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


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
    # 快照只记录文本文件。SWE-Bench 最终提交的是 patch，而当前 MVP 的 unified diff
    # 无法忠实表达二进制内容，因此二进制文件不会参与 changed_files/final.patch 计算。
    before = snapshot_workspace(task.workspace)
    writer = TrajectoryWriter(output_path / "trajectory.jsonl")
    tracker = BudgetTracker(budget)
    executor = tool_executor or LocalToolExecutor(
        workspace=task.workspace,
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
    self_test_coverage = _empty_self_test_coverage()
    authored_test_identifiers: set[str] = set()
    last_successful_tool_call: str | None = None
    unresolved_tool_failure = False
    trajectory_index = 0
    messages: list[dict[str, object]] = [
        {"role": "system", "content": _system_prompt(task)},
        {"role": "user", "content": task.problem_statement},
    ]

    # 主循环的最小单位是"一次模型决策"。一次决策可能包含多个并行工具调用，
    # 它们共享一个 step 预算，但各自写入独立的轨迹条目。
    while not tracker.max_steps_reached:
        if tracker.total_timeout_reached():
            final_error = "total runtime budget reached"
            break
        # 预算检查通过后才请求模型，确保超时场景不会再产生额外工具副作用。
        tracker.consume_step()
        turn = backend.next_action([dict(message) for message in messages])

        # --- 追加 assistant 消息到对话历史 ---
        for msg in turn.assistant_messages:
            messages.append(msg)

        # --- 模型自然停止：没有工具调用，返回了文本 ---
        if not turn.actions:
            final_error = _extract_content(turn.assistant_messages)
            try:
                writer.write_step(TrajectoryStep(
                    step_index=trajectory_index,
                    timestamp=utc_now(),
                    action_type=StepActionType.MODEL,
                    outcome=Outcome.OK,
                    reasoning_summary=final_error or "",
                ))
            except OSError as exc:
                raise ArtifactPersistenceError(str(exc)) from exc
            agent_run.finish(RunStatus.INCOMPLETE)
            break

        # --- 记录模型决策 ---
        try:
            writer.write_step(_decision_step(trajectory_index, turn.actions[0]))
        except OSError as exc:
            raise ArtifactPersistenceError(str(exc)) from exc
        trajectory_index += 1

        # --- 并行执行工具 ---
        results = _parallel_execute(executor, turn.actions, ACTION_TOOL_MAP)
        for action, result in zip(turn.actions, results):
            if result.status is Outcome.OK:
                last_successful_tool_call = result.tool_name.value
            else:
                unresolved_tool_failure = True
            for modification in result.modifications:
                if result.status is Outcome.OK and _is_test_path(modification.path):
                    authored_test_identifiers.update(_test_path_identifiers(modification.path))
            if result.test_result is not None:
                key = result.test_result.status.value
                test_summary[key] = test_summary.get(key, 0) + 1
                category = _self_test_category(result.test_result.command, authored_test_identifiers)
                self_test_coverage[category][key] = self_test_coverage[category].get(key, 0) + 1
                if key == "passed":
                    unresolved_tool_failure = False
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
    # final.patch 基于运行前后快照生成。Docker 沙箱模式下，传入的 workspace 是宿主侧
    # 占位目录，真正的容器变更由容器工具和后续扩展负责导出。
    final_patch = generate_workspace_patch(task.workspace, before, after)
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
        metadata={"self_test_coverage": self_test_coverage},
    )
    prediction = Prediction(task.instance_id, model_name, final_patch)
    _write_artifacts(output_dir=output_path, summary=summary, prediction=prediction, final_patch=final_patch, task=task)
    return summary
