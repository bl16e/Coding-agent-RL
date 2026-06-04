from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SOLVED = "solved"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    ERRORED = "errored"


class ToolName(str, Enum):
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    SEARCH_CODE = "search_code"
    RUN_TESTS = "run_tests"


class StepActionType(str, Enum):
    MODEL = "model"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL = "final"
    ERROR = "error"


class Outcome(str, Enum):
    OK = "ok"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    EXECUTION_ERROR = "execution_error"
    REJECTED = "rejected"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class BenchmarkTask:
    instance_id: str
    workspace: Path
    problem_statement: str
    allowed_test_commands: tuple[str, ...]
    repo: str | None = None
    base_commit: str | None = None

    def __post_init__(self) -> None:
        if not self.instance_id:
            raise ValueError("instance_id is required")
        if not self.problem_statement:
            raise ValueError("problem_statement is required")
        workspace = Path(self.workspace)
        if not workspace.is_dir():
            raise ValueError("workspace must exist and be a directory")
        if not self.allowed_test_commands:
            raise ValueError("allowed_test_commands must not be empty")
        object.__setattr__(self, "workspace", workspace.resolve())
        object.__setattr__(self, "allowed_test_commands", tuple(self.allowed_test_commands))


@dataclass(frozen=True)
class RunBudget:
    max_steps: int
    timeout_seconds: int
    test_timeout_seconds: int

    def __post_init__(self) -> None:
        for field_name in ("max_steps", "timeout_seconds", "test_timeout_seconds"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    api_key: str
    base_url: str

    def __post_init__(self) -> None:
        for field_name in ("provider", "model", "api_key", "base_url"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")


@dataclass
class AgentRun:
    run_id: str
    task: BenchmarkTask
    budget: RunBudget
    model_name: str
    output_dir: Path
    status: RunStatus = RunStatus.PENDING
    model_config: ModelConfig | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    def start(self) -> None:
        if self.status is not RunStatus.PENDING:
            raise ValueError("run can only start from pending")
        self.status = RunStatus.RUNNING
        self.started_at = utc_now()

    def finish(self, status: RunStatus) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError("run can only finish from running")
        if status not in {RunStatus.SOLVED, RunStatus.FAILED, RunStatus.INCOMPLETE, RunStatus.ERRORED}:
            raise ValueError("finish status must be terminal")
        self.status = status
        self.ended_at = utc_now()


@dataclass(frozen=True)
class ToolCall:
    tool_name: ToolName
    input: dict[str, Any]
    output_summary: str
    status: Outcome
    started_at: datetime
    ended_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class TrajectoryStep:
    step_index: int
    timestamp: datetime
    action_type: StepActionType
    outcome: Outcome
    reasoning_summary: str | None = None
    next_intent: str | None = None
    tool_selection_reason: str | None = None
    tool_call: ToolCall | None = None

    def __post_init__(self) -> None:
        if self.step_index < 0:
            raise ValueError("step_index must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class FileModification:
    path: str
    write_status: Outcome
    before_hash: str | None = None
    after_hash: str | None = None


@dataclass(frozen=True)
class TestResult:
    command: str
    status: TestStatus
    duration_seconds: float
    exit_code: int | None = None
    output_summary: str = ""


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    instance_id: str
    model_name: str
    status: RunStatus
    budget: RunBudget
    changed_files: list[str] = field(default_factory=list)
    test_summary: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class Prediction:
    instance_id: str
    model_name_or_path: str
    model_patch: str

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)

