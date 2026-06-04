from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from coding_agent.models import FileModification, Outcome, TestResult, ToolName


@dataclass(frozen=True)
class ToolExecutionResult:
    tool_name: ToolName
    status: Outcome
    output_summary: str
    output: dict[str, Any] = field(default_factory=dict)
    modifications: list[FileModification] = field(default_factory=list)
    test_result: TestResult | None = None

