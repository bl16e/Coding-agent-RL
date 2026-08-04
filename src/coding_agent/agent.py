# src/coding_agent/agent.py
from __future__ import annotations

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined, Template
from pydantic import BaseModel

from coding_agent.models import (
    BenchmarkTask,
    Outcome,
    RunBudget,
    RunStatus,
    RunSummary,
    ToolName,
    _json_value,
)
from coding_agent.tools.executor import ToolExecutor
from coding_agent.tools.schemas import TOOL_SCHEMAS
from coding_agent.trajectory_exporter import TrajectoryExporter

logger = logging.getLogger(__name__)

TOOL_INTENT_FIELDS = {"reasoning_summary", "next_intent", "tool_selection_reason"}

class ArtifactPersistenceError(RuntimeError):
    """Raised when required run artifacts cannot be reliably written."""

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FormatError(Exception):
    """Raised when model output cannot be parsed."""


class InterruptAgentFlow(Exception):
    """Raised to signal agent exit (success or failure)."""

    def __init__(self, messages: list[dict]):
        self.messages = messages


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class AgentConfig(BaseModel):
    system_template: str
    instance_template: str
    step_limit: int = 30
    cost_limit: float = 5.0
    time_limit_seconds: int = 0
    test_timeout_seconds: int = 120
    output_path: Path | None = None
    max_consecutive_format_errors: int = 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ToolAction:
    tool_name: ToolName
    tool_input: dict[str, Any]
    tool_call_id: str = ""


def _detect_conflicts(actions: list[_ToolAction]) -> list[list[int]]:
    """Group action indices that conflict (same file path with a write)."""
    write_targets: dict[str, list[int]] = {}
    for i, a in enumerate(actions):
        if a.tool_name is ToolName.APPLY_PATCH:
            fp = a.tool_input.get("path", "")
            if fp:
                write_targets.setdefault(fp, []).append(i)

    read_targets: dict[str, list[int]] = {}
    for i, a in enumerate(actions):
        if a.tool_name is ToolName.READ_FILE:
            fp = a.tool_input.get("file_path", "")
            if fp and fp in write_targets:
                read_targets.setdefault(fp, []).append(i)

    conflicting: set[int] = set()
    for indices in write_targets.values():
        if len(indices) > 1:
            conflicting.update(indices)
    for _fp, read_indices in read_targets.items():
        conflicting.update(read_indices)

    if not conflicting:
        return [list(range(len(actions)))]

    parallel_group = [i for i in range(len(actions)) if i not in conflicting]
    groups: list[list[int]] = []
    if parallel_group:
        groups.append(parallel_group)
    for i in sorted(conflicting):
        groups.append([i])
    return groups


def _parallel_execute(
    executor: ToolExecutor,
    actions: list[_ToolAction],
) -> list[Any]:
    """Execute actions concurrently where safe (no file conflicts)."""
    if len(actions) == 1:
        return [executor.execute(actions[0].tool_name, actions[0].tool_input)]

    groups = _detect_conflicts(actions)
    results: list[Any] = [None] * len(actions)

    for group in groups:
        if len(group) == 1:
            idx = group[0]
            results[idx] = executor.execute(
                actions[idx].tool_name, actions[idx].tool_input
            )
        else:
            def _run_one(idx: int) -> tuple[int, Any]:
                return idx, executor.execute(
                    actions[idx].tool_name, actions[idx].tool_input
                )

            with ThreadPoolExecutor(max_workers=len(group)) as pool:
                futures = {pool.submit(_run_one, i): i for i in group}
                for future in as_completed(futures):
                    idx, result = future.result()
                    results[idx] = result

    return results


def _format_tool_result_content(payload: dict[str, Any]) -> str:
    """Format tool result for LLM consumption.

    Produces clean, readable output tailored to each tool type.
    """
    tool_name = payload.get("tool_name", "")
    status = payload.get("status", "")
    output = payload.get("output") or {}

    if tool_name == "read_file":
        # Content may be in "content" (local executor) or "stdout" (Docker CLI)
        content = ""
        if isinstance(output, dict):
            content = output.get("content") or output.get("stdout") or ""
        return content or f"[read_file: {status}]"

    if tool_name == "apply_patch":
        stdout = output.get("stdout") if isinstance(output, dict) else ""
        return stdout or f"[apply_patch: {status}]"

    if tool_name == "search_code":
        if isinstance(output, dict):
            matches = output.get("matches", [])
            truncated = output.get("truncated", False)
            if not matches:
                return "[search_code: 0 matches — try a broader pattern or remove glob filter]"
            lines = [f"[search_code: {len(matches)} matches{' (truncated)' if truncated else ''}]"]
            for m in matches[:10]:
                lines.append(f"  {m.get('path', '')}:{m.get('line', '')}: {m.get('text', '')}")
            return "\n".join(lines)
        return f"[search_code: {status}]"

    if tool_name == "execute_bash":
        stdout = output.get("stdout") if isinstance(output, dict) else str(output)
        stderr = output.get("stderr") if isinstance(output, dict) else ""
        exit_code = output.get("exit_code") if isinstance(output, dict) else None
        parts: list[str] = []
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(f"[stderr]\n{stderr}")
        if exit_code is not None and exit_code != 0:
            parts.insert(0, f"[exit {exit_code}]")
        return "\n".join(parts) or f"[execute_bash: {status}]"

    if tool_name == "finish":
        submission = output.get("submission") if isinstance(output, dict) else ""
        return submission or "task submitted"

    # Fallback: generic format
    output_summary = payload.get("output_summary", "")
    return output_summary or f"[{tool_name}: {status}]"


def _schema_to_openai(
    params: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    properties = {}
    required = []
    for name, spec in params.items():
        prop: dict[str, Any] = {"type": spec["type"]}
        if "description" in spec:
            prop["description"] = spec["description"]
        if spec["type"] == "array":
            if "items" in spec:
                prop["items"] = spec["items"]
            if "minItems" in spec:
                prop["minItems"] = spec["minItems"]
            if "maxItems" in spec:
                prop["maxItems"] = spec["maxItems"]
        else:
            if "minimum" in spec:
                prop["minimum"] = spec["minimum"]
            if "maximum" in spec:
                prop["maximum"] = spec["maximum"]
            if "enum" in spec:
                prop["enum"] = spec["enum"]
        properties[name] = prop
        if spec.get("required"):
            required.append(name)
    return properties, required


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ToolAgent:
    """Structured-tool agent following mini-swe-agent pattern.

    Uses jinja2 templates for prompts, linear message history, and
    structured tool calling (not pure bash). Parallel tool execution
    with conflict detection is preserved.
    """

    def __init__(
        self,
        model: Any,  # ModelBackend
        executor: ToolExecutor,
        *,
        config: AgentConfig,
    ):
        self.model = model
        self.executor = executor
        self.config = config
        self.messages: list[dict] = []
        self.cost = 0.0
        self.n_calls = 0
        self.n_consecutive_format_errors = 0
        self._start_time = time.time()
        self._extra_template_vars: dict[str, Any] = {}

    # -- template helpers --

    def _render(self, template_str: str, **kwargs: Any) -> str:
        vars_dict = {
            "task": self._extra_template_vars.get("task", ""),
            "problem_statement": self._extra_template_vars.get(
                "problem_statement", ""
            ),
            "n_model_calls": self.n_calls,
            "model_cost": self.cost,
            "elapsed_seconds": int(time.time() - self._start_time),
            **kwargs,
        }
        return Template(template_str, undefined=StrictUndefined).render(**vars_dict)

    def add_messages(self, *msgs: dict) -> list[dict]:
        self.messages.extend(msgs)
        return list(msgs)

    # -- main entry point --

    def run(self, task: BenchmarkTask) -> RunSummary:
        self._extra_template_vars = {
            "task": task.problem_statement,
            "problem_statement": task.problem_statement,
        }
        self.messages = []
        self.add_messages(
            {
                "role": "system",
                "content": self._render(self.config.system_template),
            },
            {
                "role": "user",
                "content": self._render(self.config.instance_template),
            },
        )
        exit_status = "error"
        submission = ""
        test_summary: dict[str, int] = {}
        changed_files: list[str] = []

        while True:
            try:
                self.step()
                self.n_consecutive_format_errors = 0
            except FormatError:
                self.n_consecutive_format_errors += 1
                if (
                    self.config.max_consecutive_format_errors > 0
                    and self.n_consecutive_format_errors
                    >= self.config.max_consecutive_format_errors
                ):
                    exit_status = "RepeatedFormatError"
                    break
            except InterruptAgentFlow as e:
                last = e.messages[-1] if e.messages else {}
                extra = last.get("extra", {})
                exit_status = extra.get("exit_status", "error")
                submission = extra.get("submission", "")
                self.add_messages(*e.messages)
                break
            except Exception:
                logger.exception("Unhandled agent exception")
                exit_status = "AgentException"
                break

            if self.messages[-1].get("role") == "exit":
                extra = self.messages[-1].get("extra", {})
                exit_status = extra.get("exit_status", "submitted")
                submission = extra.get("submission", "")
                break

        return self._finalize(
            task=task,
            exit_status=exit_status,
            submission=submission,
            test_summary=test_summary,
            changed_files=changed_files,
        )

    # -- per-step loop --

    def step(self) -> None:
        return self.execute_actions(self.query())

    def query(self) -> dict:
        if 0 < self.config.step_limit <= self.n_calls:
            raise InterruptAgentFlow([{
                "role": "exit",
                "content": "LimitsExceeded",
                "extra": {"exit_status": "LimitsExceeded", "submission": ""},
            }])
        if 0 < self.config.cost_limit <= self.cost:
            raise InterruptAgentFlow([{
                "role": "exit",
                "content": "CostLimitExceeded",
                "extra": {"exit_status": "CostLimitExceeded", "submission": ""},
            }])
        if (
            self.config.time_limit_seconds > 0
            and int(time.time() - self._start_time)
            >= self.config.time_limit_seconds
        ):
            raise InterruptAgentFlow([{
                "role": "exit",
                "content": "TimeExceeded",
                "extra": {"exit_status": "TimeExceeded", "submission": ""},
            }])

        self.n_calls += 1
        tools = self._build_tool_definitions()
        message = self.model.query(self.messages, tools=tools)
        self.cost += float(message.get("extra", {}).get("cost", 0.0))
        self.add_messages(message)
        return message

    def execute_actions(self, message: dict) -> None:
        actions = self._parse_tool_calls(message)
        if not actions:
            content = message.get("content", "")
            raise InterruptAgentFlow([{
                "role": "exit",
                "content": content or "",
                "extra": {
                    "exit_status": "Submitted",
                    "submission": content or "",
                },
            }])

        results = _parallel_execute(self.executor, actions)

        finish_submission: str | None = None
        for action, result in zip(actions, results):
            from coding_agent.tools.result import ToolExecutionResult
            if action.tool_name is ToolName.FINISH:
                if isinstance(result, ToolExecutionResult):
                    finish_submission = str(result.output.get("submission", "") or "")

        outputs = [
            self._tool_result_output(action, result)
            for action, result in zip(actions, results)
        ]
        self.add_messages(*outputs)

        # Explicit finish: clean exit with submission message
        for action in actions:
            if action.tool_name is ToolName.FINISH:
                raise InterruptAgentFlow([{
                    "role": "exit",
                    "content": finish_submission or "task submitted via finish",
                    "extra": {
                        "exit_status": "Submitted",
                        "submission": finish_submission or "",
                    },
                }])

        return None

    # -- tool call parsing --

    def _parse_tool_calls(self, message: dict) -> list[_ToolAction]:
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            return []
        actions: list[_ToolAction] = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args_str = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                raise FormatError(
                    f"tool call arguments not valid JSON: {name}"
                )
            if not isinstance(args, dict):
                raise FormatError(
                    f"tool call arguments must be object: {name}"
                )
            args = {key: value for key, value in args.items() if key not in TOOL_INTENT_FIELDS}
            try:
                tool_name = ToolName(name)
            except ValueError:
                raise FormatError(f"unsupported tool: {name}")
            actions.append(_ToolAction(
                tool_name=tool_name,
                tool_input=args,
                tool_call_id=tc.get("id", ""),
            ))
        return actions

    def _tool_result_output(
        self, action: _ToolAction, result: Any
    ) -> dict:
        from coding_agent.tools.result import ToolExecutionResult
        if isinstance(result, ToolExecutionResult):
            payload = {
                "tool_name": result.tool_name.value,
                "tool_input": action.tool_input,
                "status": result.status.value,
                "output_summary": result.output_summary,
                "output": result.output,
                "test_result": _json_value(result.test_result) if result.test_result else None,
            }
        else:
            payload = {
                "tool_name": action.tool_name.value,
                "tool_input": action.tool_input,
                "status": "error",
            }
        return {
            "role": "tool",
            "tool_call_id": action.tool_call_id,
            "content": _format_tool_result_content(payload),
            "extra": {"tool_result": payload},
        }

    # -- tool definitions --

    def _build_tool_definitions(self) -> list[dict]:
        tools: list[dict] = []
        for tool_name, schema in TOOL_SCHEMAS.items():
            props, req = _schema_to_openai(schema["parameters"])
            tools.append({
                "type": "function",
                "function": {
                    "name": tool_name.value,
                    "description": schema["description"],
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": req,
                    },
                },
            })
        return tools

    # -- finalization --

    def _finalize(
        self,
        task: BenchmarkTask,
        exit_status: str,
        submission: str,
        test_summary: dict[str, int],
        changed_files: list[str],
    ) -> RunSummary:
        is_solved = exit_status.lower() in ("submitted",)
        status = RunStatus.SOLVED if is_solved else RunStatus.INCOMPLETE

        # For now, final.patch is empty until we integrate snapshot/patch
        # generation from the container (future Task: use SWE-ReX file ops)
        final_patch = ""
        run_id = str(uuid.uuid4())

        if self.config.output_path:
            exporter = TrajectoryExporter(self.config.output_path)
            exporter.export(
                messages=self.messages,
                run_id=run_id,
                instance_id=task.instance_id,
                model_name=self.model.model_name,
                budget=RunBudget(
                    max_steps=self.config.step_limit,
                    timeout_seconds=self.config.time_limit_seconds or 600,
                    test_timeout_seconds=self.config.test_timeout_seconds,
                ),
                final_patch=final_patch,
                error=(
                    None
                    if is_solved
                    else exit_status
                ),
                changed_files=changed_files,
                test_summary=test_summary,
            )

        return RunSummary(
            run_id=run_id,
            instance_id=task.instance_id,
            model_name=self.model.model_name,
            status=status,
            budget=RunBudget(
                max_steps=self.config.step_limit,
                timeout_seconds=self.config.time_limit_seconds or 600,
                test_timeout_seconds=self.config.test_timeout_seconds,
            ),
            changed_files=changed_files,
            test_summary=test_summary,
            error=None if is_solved else exit_status,
        )
