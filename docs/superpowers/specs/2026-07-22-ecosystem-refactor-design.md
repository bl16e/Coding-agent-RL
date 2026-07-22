# Ecosystem Refactor: Adopt mini-swe-agent + SWE-ReX + LiteLLM

## Motivation

The current `coding-agent` codebase (~40 `.py` files) was built from scratch: agent loop,
model backend (OpenAI SDK), Docker sandbox (hand-written CLI wrapper), and trajectory
management. This caused three concrete pain points:

1. **Agent loop** (`agent.py`, 520 lines): complex state machine with parallel execution,
   conflict detection, dual message construction paths, and scattered artifact writing.
2. **Docker sandbox** (`sandbox/docker_cli.py` + `manager.py`, ~240 lines): unreliable exit
   code detection, no multi-container parallelism, container leaks on error paths.
3. **Trajectory management** (`trajectory/`, 4 files): three parallel information streams
   (`self.messages`, `TrajectoryWriter`, `RunSummary`) maintained simultaneously.

The SWE ecosystem (Princeton/Stanford) now has mature, widely-adopted libraries that solve
each of these problems. This refactor replaces hand-written infrastructure with ecosystem
standards while preserving the project's structured-tool approach (4 constrained tools
rather than pure bash).

## Design Principle

> Use mature frameworks; don't reinvent the wheel.

| Concern | Was (hand-written) | Now (ecosystem) |
|---------|-------------------|-----------------|
| Agent scaffolding | `agent.py` (520 lines) | mini-swe-agent pattern (jinja2 templates, linear history) |
| Model backend | `openai_compatible.py` (329 lines) | LiteLLM via mini-swe-agent `LitellmModel` |
| Sandbox / container | `docker_cli.py` + `manager.py` | SWE-ReX `DockerDeployment` + `AbstractRuntime` |
| Trajectory | 4 files, 3 parallel streams | `self.messages` as single source of truth |

**Preserved:** The 4 structured tools (`read_file`, `apply_patch`, `search_code`,
`run_tests`) with their business logic, schemas, and parallel execution capability.
SWE-ReX provides the I/O layer beneath them.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     CLI Layer                        │
│         (typer, 保持现有子命令结构)                    │
├─────────────────────────────────────────────────────┤
│                   Agent Loop                         │
│   ┌─────────────────────────────────────────────┐   │
│   │  ToolAgent (mini-swe-agent DefaultAgent 模式) │   │
│   │  - jinja2 模板驱动 prompt                     │   │
│   │  - 线性 message history（无复杂状态机）        │   │
│   │  - step() → query() → execute_actions()      │   │
│   │  - 保留并行 tool_calls + 冲突检测               │   │
│   └─────────────────────────────────────────────┘   │
├──────────────┬──────────────────┬───────────────────┤
│  model_backend│   SweRexExecutor │     Tools         │
│  (LiteLLM)   │   (SWE-ReX)     │  (保留+适配)       │
│              │                  │                   │
│ • 100+ 模型  │ • Docker容器管理  │ • read_file       │
│ • vLLM 兼容  │ • exit code 检测 │ • apply_patch     │
│ • 自动重试   │ • 文件读写       │ • search_code     │
│ • cost 追踪  │ • 并行部署       │ • run_tests       │
└──────────────┴──────────────────┴───────────────────┘
```

## Module Design

### 1. Agent Loop (`agent.py`)

Follow mini-swe-agent `DefaultAgent` structure (ref: `Reference/mini-swe-agent/src/minisweagent/agents/default.py`):

- `run(task) → RunSummary`: bootstrap messages, loop step() until exit, call _finalize()
- `step()`: query() → execute_actions() → check exit; catch FormatError/InterruptAgentFlow
- `query()`: budget checks → model.query(messages, tools=TOOL_DEFINITIONS) → append to messages
- `execute_actions(message)`: parse tool_calls → _detect_conflicts → _parallel_execute → append tool results to messages
- `_finalize()`: snapshot, patch, trajectory, summary, prediction — all written once at end

**Parallel tool execution retained:**
- Model returns multiple `tool_calls` in one response → agent groups them by conflict detection
- `_detect_conflicts()`: same read/write conflict logic, but simplified
- `_parallel_execute()`: `ThreadPoolExecutor` for non-conflicting group

**Templates** (jinja2, in `config/templates/`):
- `system.j2`: system message with tool descriptions, problem context, validation hints
- `instance.j2`: first user message with task problem_statement

### 2. Model Backend (`model_backend.py`)

Thin wrapper around mini-swe-agent's `LitellmModel`:

```python
class ModelBackend:
    def __init__(self, model_name: str, config: dict | None = None):
        self._model = LitellmModel(model_name=model_name, **(config or {}))

    def query(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        return self._model.query(messages, tools=tools)
```

Configuration via standard environment variables (`OPENAI_API_KEY`,
`OPENAI_BASE_URL`, etc.) — no custom `STAGE1_*`/`STAGE2_*` prefix handling.
Stage differentiation via model name (e.g., `openai/qwen-2.5-coder-7b-instruct`
for vLLM, `anthropic/claude-sonnet-4-5` for teacher).

### 3. Sandbox (`sandbox.py`)

Uses SWE-ReX `DockerDeployment` (ref: `Reference/SWE-ReX/src/swerex/deployment/docker.py`):

```python
class SandboxManager:
    def __init__(self, image: str, **kwargs):
        self._deployment = DockerDeployment(image=image, **kwargs)

    def start(self) -> AbstractRuntime:
        """Start container + SWE-ReX runtime server. Call once per run."""
        asyncio.run(self._deployment.start())
        return self._deployment.runtime

    def stop(self):
        """Stop container. Always called in finally block."""
        asyncio.run(self._deployment.stop())
```

Container lifecycle advantages over current hand-written approach:
- Auto-cleanup via `__del__` + explicit `stop()`, no leak paths
- Exit code extracted via shell sentinel mechanism, not `docker exec` return code
- File read/write API (`read_file`/`write_file`) instead of `docker exec cat/echo`
- Multi-container parallel via independent `DockerDeployment` instances

### 4. Tool Executor (`tools/executor.py`)

`SweRexToolExecutor` implements `ToolExecutor` protocol with async-to-sync bridge:

```python
class SweRexToolExecutor:
    def __init__(self, runtime: AbstractRuntime, workspace: str):
        self._runtime = runtime
        self._workspace = workspace
        self._loop = asyncio.new_event_loop()  # Singleton per run

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        return self._loop.run_until_complete(self._execute_async(tool_name, tool_input))
```

**Why sync agent + async bridge (not full async agent):**
- RL training parallelizes at process level (multiple independent agents), not within a
  single process driving multiple containers
- Sync code is easier to debug (clean stack traces) and integrates with existing CLI
- Single `asyncio.new_event_loop()` reused for entire run → negligible overhead (~1ms per
  tool call vs 10-180s tool execution time)

**Per-tool I/O changes:**

| Tool | Before | After |
|------|--------|-------|
| `read_file` | `(workspace/f).read_text()` | `await runtime.read_file(ReadFileRequest(path=f))` |
| `apply_patch` | `(workspace/f).write_text(content)` | `await runtime.write_file(WriteFileRequest(path=f, content=c))` |
| `search_code` | `subprocess.run(["grep", ...])` | `await runtime.execute(Command(command=["grep", ...], cwd=repo))` |
| `run_tests` | `subprocess.run(cmd, timeout=...)` | `await runtime.execute(Command(command=cmd, timeout=..., cwd=repo))` |

Business logic (diff parsing, grep pattern building, pytest output parsing, schema
definitions, test command policy) is preserved unchanged.

### 5. Trajectory (`trajectory.py`)

Single-module replacement for current 4-file trajectory subsystem.

**Core principle:** `self.messages` is the single source of truth. No parallel
`TrajectoryWriter` stream, no per-step index counter.

```python
class TrajectoryExporter:
    def export(self, agent: ToolAgent, task: BenchmarkTask,
               final_patch: str) -> dict[str, Path]:
        """Called once at end of run. Derives all artifacts from agent.messages."""
        # trajectory.jsonl — expand messages into step-by-step events
        # trajectory.json — summary format for downstream consumers
        # summary.json — status, budget, test_summary, changed_files
        # prediction.jsonl — SWE-bench prediction format
```

Optional crash recovery: checkpoint `self.messages` every N steps to
`.checkpoint.json` (not per-step JSONL write).

## File Structure: Before → After

```
src/coding_agent/
├── agent.py              ← 重写 (~200 lines, was 520)
├── model_backend.py      ← 新 (~30 lines, replaces model_backends/)
├── sandbox.py            ← 新 (~40 lines, replaces sandbox/)
├── trajectory.py         ← 新 (~60 lines, replaces trajectory/)
├── models.py             ← 精简 (BenchmarkTask, RunBudget, RunSummary)
├── cli.py                ← 重写 (适配新接口)
│
├── config/               ← 新
│   ├── templates/
│   │   ├── system.j2
│   │   └── instance.j2
│   ├── stage1.yaml
│   └── stage2.yaml
│
├── tools/                ← 大部分保留
│   ├── read_file.py      ← 保留, I/O → runtime
│   ├── apply_patch.py    ← 保留, I/O → runtime
│   ├── search_code.py    ← 保留, exec → runtime
│   ├── run_tests.py      ← 保留, exec → runtime
│   ├── executor.py       ← 重写: SweRexToolExecutor
│   ├── schemas.py        ← 保留
│   ├── result.py         ← 保留
│   └── test_command_policy.py ← 保留
│
├── swebench/             ← 保留简化
└── swesmith/             ← 保留简化

REMOVED:
  sandbox/docker_cli.py, manager.py, registry.py, tools.py, __init__.py
  model_backends/base.py, openai_compatible.py, mock.py, __init__.py
  trajectory/converter.py, patch.py, summary.py, writer.py, __init__.py
  budgets.py → merged into agent.py
  workspace.py, textio.py
```

## Dependencies

Added to `pyproject.toml`:

```toml
dependencies = [
    "mini-swe-agent>=2.4.0",   # Agent pattern + LitellmModel
    "swe-rex>=1.4.0",          # DockerDeployment + AbstractRuntime
    "jinja2",                   # Prompt templates
    "pyyaml",                   # Config files
    # retained: pydantic, pyarrow, openai (transitive via litellm)
]
```

## Artifact Compatibility

All current output artifacts preserved with identical format:
- `trajectory.jsonl` — step-by-step event log
- `trajectory.json` — summary trajectory view
- `summary.json` — run status, budget, test results
- `final.patch` — workspace diff
- `prediction.jsonl` — SWE-bench prediction format
- `sandbox.json` — runtime metadata

## Migration Strategy

1. Install `mini-swe-agent` and `swe-rex` as dependencies
2. Implement `SweRexToolExecutor` + `SandboxManager` (sandbox.py + tools/executor.py)
3. Implement `ModelBackend` (model_backend.py) — validate with existing vLLM endpoint
4. Implement `ToolAgent` (agent.py) with jinja2 templates — validate against mock backend
5. Implement `TrajectoryExporter` (trajectory.py) — verify output format matches
6. Rewrite CLI — verify existing `run`/`swebench run`/`swebench batch-run` commands work
7. Remove old modules
8. Run full integration test on SWE-bench Lite

Each step produces a runnable intermediate state (not a flag-day rewrite).

## Reviews

- mini-swe-agent `DefaultAgent`: ~100 lines, battle-tested by Meta, NVIDIA, Stanford
- SWE-ReX `DockerDeployment`: production-grade container lifecycle with auto-cleanup
- LiteLLM: supports 100+ models including vLLM OpenAI-compatible endpoints
- Design adheres to principle: use ecosystem standards, keep only differentiated code (tools)
