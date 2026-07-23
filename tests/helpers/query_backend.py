from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coding_agent.agent import AgentConfig, ToolAgent
from coding_agent.models import BenchmarkTask, RunBudget, RunSummary, ToolName
from coding_agent.tools.executor import LocalToolExecutor, ToolExecutor


@dataclass(frozen=True)
class ToolCallSpec:
    tool_name: ToolName
    tool_input: dict[str, Any]
    tool_call_id: str | None = None


class ScriptedQueryBackend:
    def __init__(self, calls: list[ToolCallSpec] | None = None, *, final: str = "Task complete.") -> None:
        self.calls = list(calls or [])
        self.final = final
        self.index = 0
        self.model_name = "mock-model"
        self.messages_by_call: list[list[dict[str, Any]]] = []

    def query(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        self.messages_by_call.append([dict(message) for message in messages])
        if self.index >= len(self.calls):
            return {"role": "assistant", "content": self.final, "extra": {}}
        call = self.calls[self.index]
        self.index += 1
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call.tool_call_id or f"mock_call_{self.index}",
                    "type": "function",
                    "function": {
                        "name": call.tool_name.value,
                        "arguments": json.dumps(call.tool_input),
                    },
                }
            ],
            "extra": {},
        }


def make_task(
    tmp_path: Path,
    *,
    workspace: Path | None = None,
    problem_statement: str = "Fix it.",
    allowed_test_commands: tuple[str, ...] = ("test/test_file.py::test_name",),
) -> BenchmarkTask:
    workspace_path = workspace or tmp_path / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)
    return BenchmarkTask(
        instance_id="example__repo-1",
        workspace=workspace_path,
        problem_statement=problem_statement,
        allowed_test_commands=allowed_test_commands,
    )


def run_agent_for_test(
    *,
    task: BenchmarkTask,
    budget: RunBudget,
    backend: ScriptedQueryBackend,
    output_dir: Path,
    tool_executor: ToolExecutor | None = None,
) -> RunSummary:
    template_dir = Path("src/coding_agent/config/templates")
    agent = ToolAgent(
        model=backend,
        executor=tool_executor or LocalToolExecutor(
            workspace=task.workspace,
            test_timeout_seconds=budget.test_timeout_seconds,
        ),
        config=AgentConfig(
            system_template=(template_dir / "system.j2").read_text(encoding="utf-8"),
            instance_template=(template_dir / "instance.j2").read_text(encoding="utf-8"),
            step_limit=budget.max_steps,
            time_limit_seconds=budget.timeout_seconds,
            test_timeout_seconds=budget.test_timeout_seconds,
            output_path=output_dir,
        ),
    )
    return agent.run(task)
