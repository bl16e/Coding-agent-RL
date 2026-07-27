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
    APPLY_PATCH = "apply_patch"
    SEARCH_CODE = "search_code"
    EXECUTE_BASH = "execute_bash"
    FINISH = "finish"


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


class RepoSpecReviewStatus(str, Enum):
    SOURCE_BACKED = "source_backed"
    UNSUPPORTED = "unsupported"
    NEEDS_REVIEW = "needs_review"


class PreparedEnvironmentStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    USED = "used"
    STOPPED = "stopped"
    ERROR = "error"


class UnsupportedLegacySurface(str, Enum):
    REGISTRY_OPTION = "registry_option"
    SANDBOX_COMMAND = "sandbox_command"
    BATCH_COMMAND = "batch_command"


def utc_now() -> datetime:
    """统一生成带 UTC 时区的时间戳，避免持久化时出现 naive datetime。"""
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    """把 dataclass/Enum/Path/datetime 递归转换成 JSON 友好值。

    所有产物都通过这个函数保持一致序列化：枚举写 value，路径写字符串，时间写 ISO。
    这样 summary、trajectory、sandbox 和 prediction 的字段风格不会各自漂移。
    """
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


def _tuple_of_str(value: tuple[str, ...] | list[str], field_name: str) -> tuple[str, ...]:
    normalized = tuple(str(item) for item in value if str(item))
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


@dataclass(frozen=True)
class BenchmarkTaskRecord:
    """Source-backed SWE-Bench task record used by the new runtime path."""

    instance_id: str
    repo: str
    version: str | None
    base_commit: str
    problem_statement: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...] = ()
    test_patch: str = ""
    environment_setup_commit: str | None = None
    eval_script: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("instance_id", "repo", "base_commit", "problem_statement"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")
        object.__setattr__(self, "fail_to_pass", _tuple_of_str(self.fail_to_pass, "fail_to_pass"))
        object.__setattr__(self, "pass_to_pass", tuple(str(item) for item in self.pass_to_pass if str(item)))


@dataclass(frozen=True)
class RepoVersionSpec:
    """Source-backed repository/version metadata boundary."""

    repo: str
    version: str
    language: str
    test_command: str
    source_reference: str
    review_status: RepoSpecReviewStatus
    python_version: str | None = None
    packages: tuple[str, ...] = ()
    package_spec: str = ""
    pip_packages: tuple[str, ...] = ()
    pre_install_commands: tuple[str, ...] = ()
    install_commands: tuple[str, ...] = ()
    eval_commands: tuple[str, ...] = ()
    requirements_paths: tuple[str, ...] = ()
    environment_yml_paths: tuple[str, ...] = ()
    no_use_env: bool = False
    docker_specs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("repo", "version", "language", "test_command", "source_reference"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")
        if not isinstance(self.review_status, RepoSpecReviewStatus):
            object.__setattr__(self, "review_status", RepoSpecReviewStatus(self.review_status))
        object.__setattr__(self, "packages", tuple(str(item) for item in self.packages if str(item)))
        object.__setattr__(self, "pip_packages", tuple(str(item) for item in self.pip_packages if str(item)))
        object.__setattr__(self, "pre_install_commands", tuple(str(item) for item in self.pre_install_commands if str(item)))
        object.__setattr__(self, "install_commands", tuple(str(item) for item in self.install_commands if str(item)))
        object.__setattr__(self, "eval_commands", tuple(str(item) for item in self.eval_commands if str(item)))
        object.__setattr__(self, "requirements_paths", tuple(str(item) for item in self.requirements_paths if str(item)))
        object.__setattr__(self, "environment_yml_paths", tuple(str(item) for item in self.environment_yml_paths if str(item)))


@dataclass(frozen=True)
class AdaptedTestSpec:
    """Internal official-style TestSpec contract for one task."""

    instance_id: str
    repo: str
    version: str
    base_commit: str
    repo_path: str
    env_name: str
    fail_to_pass: tuple[str, ...]
    repo_script: str
    env_script: str
    eval_script: str
    language: str
    arch: str
    platform: str
    base_image_key: str
    env_image_key: str
    instance_image_key: str
    repo_version_source: str
    pass_to_pass: tuple[str, ...] = ()
    test_patch: str = ""

    def __post_init__(self) -> None:
        required = (
            "instance_id",
            "repo",
            "version",
            "base_commit",
            "repo_path",
            "env_name",
            "repo_script",
            "env_script",
            "eval_script",
            "language",
            "arch",
            "platform",
            "base_image_key",
            "env_image_key",
            "instance_image_key",
            "repo_version_source",
        )
        for field_name in required:
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")
        object.__setattr__(self, "fail_to_pass", _tuple_of_str(self.fail_to_pass, "fail_to_pass"))
        object.__setattr__(self, "pass_to_pass", tuple(str(item) for item in self.pass_to_pass if str(item)))


@dataclass(frozen=True)
class RuntimeLineage:
    runtime_path: str
    base_image_key: str
    env_image_key: str
    instance_image_key: str
    platform: str
    build_missing: bool
    built_images: tuple[str, ...] = ()
    reused_images: tuple[str, ...] = ()
    metadata_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.runtime_path != "official_style":
            raise ValueError("runtime_path must be official_style")
        for field_name in ("base_image_key", "env_image_key", "instance_image_key", "platform"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")
        object.__setattr__(self, "built_images", tuple(self.built_images))
        object.__setattr__(self, "reused_images", tuple(self.reused_images))
        object.__setattr__(self, "metadata_sources", tuple(self.metadata_sources))


@dataclass(frozen=True)
class PreparedTaskEnvironment:
    instance_id: str
    repo: str
    version: str
    base_commit: str
    container_name: str
    repo_path: str
    runtime_lineage: RuntimeLineage
    status: PreparedEnvironmentStatus
    ready_checks: dict[str, Any] = field(default_factory=dict)
    sandbox_json: Path | None = None

    def __post_init__(self) -> None:
        for field_name in ("instance_id", "repo", "version", "base_commit", "container_name", "repo_path"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")
        if not isinstance(self.status, PreparedEnvironmentStatus):
            object.__setattr__(self, "status", PreparedEnvironmentStatus(self.status))


@dataclass(frozen=True)
class ValidationSet:
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...] = ()
    include_pass_to_pass: bool = False
    command_source: str = "official_testspec"
    eval_script: str = ""
    allowed_commands: tuple[str, ...] = ()
    test_patch_reset_commands: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fail_to_pass", _tuple_of_str(self.fail_to_pass, "fail_to_pass"))
        object.__setattr__(self, "pass_to_pass", tuple(str(item) for item in self.pass_to_pass if str(item)))
        object.__setattr__(self, "allowed_commands", tuple(str(item) for item in self.allowed_commands if str(item)))
        object.__setattr__(
            self,
            "test_patch_reset_commands",
            tuple(str(item) for item in self.test_patch_reset_commands if str(item)),
        )
        if self.command_source not in {"official_testspec", "source_backed_repo_spec"}:
            raise ValueError("command_source must be official_testspec or source_backed_repo_spec")
        if not self.eval_script:
            raise ValueError("eval_script is required")


@dataclass(frozen=True)
class EvalReport:
    resolved: bool
    fail_to_pass_success: tuple[str, ...] = ()
    fail_to_pass_failure: tuple[str, ...] = ()
    pass_to_pass_success: tuple[str, ...] = ()
    pass_to_pass_failure: tuple[str, ...] = ()
    raw_output_artifact: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fail_to_pass_success", tuple(self.fail_to_pass_success))
        object.__setattr__(self, "fail_to_pass_failure", tuple(self.fail_to_pass_failure))
        object.__setattr__(self, "pass_to_pass_success", tuple(self.pass_to_pass_success))
        object.__setattr__(self, "pass_to_pass_failure", tuple(self.pass_to_pass_failure))


@dataclass(frozen=True)
class AgentRunArtifactSet:
    trajectory_jsonl: Path
    trajectory_json: Path
    summary_json: Path
    final_patch: Path
    prediction_jsonl: Path
    sandbox_json: Path


@dataclass(frozen=True)
class ActivePreparedEnvironmentIndex:
    instance_id: str
    container_name: str
    repo: str
    version: str
    base_commit: str
    sandbox_json: Path
    runtime_lineage: RuntimeLineage
    status: PreparedEnvironmentStatus

    def __post_init__(self) -> None:
        if not isinstance(self.status, PreparedEnvironmentStatus):
            object.__setattr__(self, "status", PreparedEnvironmentStatus(self.status))


@dataclass(frozen=True)
class UnsupportedLegacyOperation:
    operation_name: str
    legacy_surface: UnsupportedLegacySurface
    replacement: str | None
    error_message: str

    def __post_init__(self) -> None:
        if not isinstance(self.legacy_surface, UnsupportedLegacySurface):
            object.__setattr__(self, "legacy_surface", UnsupportedLegacySurface(self.legacy_surface))
        for field_name in ("operation_name", "error_message"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")


@dataclass(frozen=True)
class BenchmarkTask:
    """一次待解决任务的最小输入契约。

    workspace 可以是本地真实仓库，也可以是 Docker 模式下用于产物计算的宿主侧占位
    目录。repo/base_commit 是 SWE-Bench 元数据，本地运行时可以为空。
    """

    instance_id: str
    workspace: Path
    problem_statement: str
    allowed_test_commands: tuple[str, ...]
    fail_to_pass: tuple[str, ...] = ()
    repo: str | None = None
    base_commit: str | None = None

    def __post_init__(self) -> None:
        # 领域对象在创建时立即校验，避免 agent loop 运行到一半才发现任务不完整。
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
        object.__setattr__(self, "fail_to_pass", tuple(str(item) for item in self.fail_to_pass if str(item)))


@dataclass(frozen=True)
class RunBudget:
    """单次运行的预算。

    max_steps 约束模型决策次数；timeout_seconds 约束整次运行；test_timeout_seconds
    约束单条测试命令。三者分开可以区分“模型想太久”和“测试卡住”的失败原因。
    """

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
    """OpenAI-compatible 后端所需的最小配置。"""

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
    """运行时状态机。

    start/finish 方法显式限制状态迁移，避免 summary 中出现 pending->solved 或
    solved->running 这类不可能状态。
    """

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
    """轨迹中记录的一次工具调用摘要。"""

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
    """轨迹 JSONL 的单行数据结构。

    MODEL 步记录模型决策；TOOL_RESULT 步记录工具执行结果。二者分开后，审计者可以
    看清模型意图和实际副作用之间的关系。
    """

    step_index: int
    timestamp: datetime
    action_type: StepActionType
    outcome: Outcome
    reasoning_summary: str | None = None
    observation: str | None = None
    tool_call: ToolCall | None = None
    tool_result: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.step_index < 0:
            raise ValueError("step_index must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class FileModification:
    """工具报告的文件级变更摘要。"""

    path: str
    write_status: Outcome
    before_hash: str | None = None
    after_hash: str | None = None


@dataclass(frozen=True)
class TestResult:
    """一次测试命令的结构化结果。"""

    command: str
    status: TestStatus
    duration_seconds: float
    exit_code: int | None = None
    output_summary: str = ""


@dataclass(frozen=True)
class BaseImage:
    """已注册的仓库基础镜像。

    official_compatible 是沙箱运行的关键闸门：只有调用方明确声明镜像兼容官方
    SWE-Bench 环境时，swebench run 才允许使用它。
    """

    repo: str
    image: str
    repo_path: str
    official_compatible: bool = False
    compatibility_source: str | None = None
    validation_command_template: str | None = None
    registered_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("repo", "image", "repo_path"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")


@dataclass(frozen=True)
class ValidationTestSet:
    """由 SWE-Bench 测试标识符生成的可执行验证集合。

    fail_to_pass 是默认验证集；pass_to_pass 只有用户显式开启时才加入，避免默认运行
    变成完整回归测试。
    """

    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...] = ()
    command_source: str | None = None
    eval_script: str | None = None
    allowed_commands: tuple[str, ...] = ()
    include_pass_to_pass: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "fail_to_pass", tuple(self.fail_to_pass))
        object.__setattr__(self, "pass_to_pass", tuple(self.pass_to_pass))
        object.__setattr__(self, "allowed_commands", tuple(self.allowed_commands))
        if not self.fail_to_pass:
            raise ValueError("fail_to_pass must not be empty")
        if not self.allowed_commands:
            raise ValueError("allowed_commands must not be empty")
        if self.command_source not in {"official_testspec", "registered_template"}:
            raise ValueError("command_source must be official_testspec or registered_template")


@dataclass(frozen=True)
class TaskSandbox:
    """一次任务对应的 Docker 容器状态。"""

    container_name: str
    base_image: BaseImage
    instance_id: str
    repo: str
    base_commit: str
    repo_path: str
    status: str = "pending"

    def __post_init__(self) -> None:
        for field_name in ("container_name", "instance_id", "repo", "base_commit", "repo_path"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")
        if self.status not in {"pending", "ready", "running", "used", "stopped", "error"}:
            raise ValueError("status must be pending, ready, running, used, stopped, or error")


@dataclass(frozen=True)
class SandboxMetadata:
    """写入 summary.json 的沙箱补充元数据。"""

    task_sandbox: TaskSandbox
    validation_test_set: ValidationTestSet
    failure_state: str | None = None


@dataclass(frozen=True)
class RunSummary:
    """summary.json 的持久化契约。"""

    run_id: str
    instance_id: str
    model_name: str
    status: RunStatus
    budget: RunBudget
    changed_files: list[str] = field(default_factory=list)
    test_summary: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    last_successful_tool_call: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    sandbox: SandboxMetadata | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = _json_value(self)
        metadata = payload.pop("metadata", {}) or {}
        if isinstance(metadata, dict):
            payload.update(metadata)
        return payload


@dataclass(frozen=True)
class Prediction:
    """SWE-Bench prediction JSONL 的核心字段。"""

    instance_id: str
    model_name_or_path: str
    model_patch: str

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)
