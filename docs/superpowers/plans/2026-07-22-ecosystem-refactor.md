# Ecosystem Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hand-written agent loop, model backend, Docker sandbox, and trajectory management with mini-swe-agent patterns + SWE-ReX + LiteLLM, while preserving the 4 structured tools.

**Architecture:** New 4-layer design — CLI → ToolAgent (jinja2 templates, linear history, parallel tools) → LiteLLM/model + SWE-ReX/sandbox → 4 preserved tools with SWE-ReX I/O. Async-to-sync bridge at tool executor boundary via single `asyncio.new_event_loop()`.

**Tech Stack:** Python 3.11+, mini-swe-agent >= 2.4.0, swe-rex >= 1.4.0, jinja2, pyyaml, litellm (transitive)

## Global Constraints

- All current output artifacts (trajectory.jsonl, trajectory.json, summary.json, final.patch, prediction.jsonl, sandbox.json) must preserve identical format
- CLI subcommand structure (`run`, `swebench prepare`, `swebench run`, `swebench batch-run`, `swebench evaluate`, `inspect`, `export-prediction`) preserved
- 4 tools retain same schemas, same ToolExecutionResult return type, same ToolExecutor protocol
- Each task produces a runnable intermediate state — no flag-day rewrites
- python 3.11+, use `list` not `List`, `pathlib` not `os.path`

---

### Task 1: Add dependencies and create config scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `src/coding_agent/config/templates/system.j2`
- Create: `src/coding_agent/config/templates/instance.j2`

**Interfaces:**
- Produces: jinja2 templates consumed by Task 8 (agent.py)

- [ ] **Step 1: Update pyproject.toml dependencies**

```toml
# Add to [project] dependencies list:
dependencies = [
    "mini-swe-agent>=2.4.0",
    "swe-rex>=1.4.0",
    "jinja2",
    "pyyaml",
    "pydantic>=2.0",
    "pyarrow",
]
```

- [ ] **Step 2: Install new dependencies**

Run: `.venv\Scripts\python.exe -m pip install -e ".[dev]"`

- [ ] **Step 3: Create system.j2 template**

```jinja2
{# config/templates/system.j2 #}
You are a coding agent that solves repository issues by using the provided tools.

Your task:
{{ task }}

You may use the following tools:
- read_file: Read a UTF-8 text file from the repository. Output is formatted with line numbers (cat -n style).
- apply_patch: Modify files via write (create/overwrite) or update (exact string replacement with old_string/new_string).
- search_code: Search repository text files with a regular expression. Returns matching lines.
- run_tests: Run a self-test or diagnostic command. Allowed: pytest, python -m pytest, python -c, python <script>.py, git diff/status/log.

Final benchmark validation is run automatically after you finish.

Before claiming solved, compare your implementation with nearby project contracts, especially exact error messages, exception types, warnings, check IDs, and CLI output. Tests you add yourself are useful, but they are not enough on their own; also run existing adjacent tests or focused diagnostics when possible.

Work systematically: read relevant files, understand the issue, make changes, and verify with tests. When you have solved the issue or determined it cannot be solved, explain your conclusion and stop calling tools.

{% if allowed_test_commands %}
Examples of allowed self-test commands:
{% for cmd in allowed_test_commands %}
  {{ cmd }}
{% endfor %}
{% endif %}
```

- [ ] **Step 4: Create instance.j2 template**

```jinja2
{# config/templates/instance.j2 #}
{{ problem_statement }}
```

- [ ] **Step 5: Verify templates are loadable**

```python
# Run in Python REPL:
from jinja2 import Template
t = Template(open("src/coding_agent/config/templates/system.j2").read())
result = t.render(task="test task", allowed_test_commands=["pytest tests/"])
assert "test task" in result
assert "pytest tests/" in result
print("Templates OK")
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/coding_agent/config/
git commit -m "feat: add ecosystem dependencies and jinja2 templates"
```

---

### Task 2: Implement SWE-ReX sandbox wrapper (sandbox.py)

**Files:**
- Create: `src/coding_agent/sandbox.py`
- Test: `tests/unit/test_sandbox.py`

**Interfaces:**
- Produces: `SandboxManager(start() -> AbstractRuntime, stop() -> None)`, consumed by Task 5 (executor) and Task 8 (agent)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sandbox.py
import pytest
from coding_agent.sandbox import SandboxManager

def test_sandbox_manager_requires_image():
    with pytest.raises(TypeError):
        SandboxManager()  # image is required

def test_sandbox_manager_accepts_config():
    mgr = SandboxManager(image="test-image:latest", cwd="/test")
    assert mgr._config["image"] == "test-image:latest"
    assert mgr._config["cwd"] == "/test"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_sandbox.py -v
```
Expected: FAIL with "No module named 'coding_agent.sandbox'" or similar.

- [ ] **Step 3: Write sandbox.py implementation**

```python
# src/coding_agent/sandbox.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from swe_rex.deployment.docker import DockerDeployment
from swe_rex.runtime.abstract import AbstractRuntime

logger = logging.getLogger(__name__)


class SandboxError(RuntimeError):
    """Raised when sandbox operations fail."""


class SandboxManager:
    """Manage a SWE-ReX DockerDeployment for a single agent run.

    Wraps SWE-ReX's async DockerDeployment behind a synchronous interface
    using a dedicated event loop. Callers use::

        mgr = SandboxManager(image="...")
        runtime = mgr.start()
        try:
            # use runtime for tool execution
            ...
        finally:
            mgr.stop()
    """

    def __init__(self, *, image: str, **kwargs: Any):
        self._config = {"image": image, **kwargs}
        self._deployment: DockerDeployment | None = None
        self._runtime: AbstractRuntime | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> AbstractRuntime:
        """Start the container and return the runtime. Call once per run."""
        self._loop = asyncio.new_event_loop()
        self._deployment = DockerDeployment(**self._config)
        try:
            self._loop.run_until_complete(self._deployment.start())
        except Exception as exc:
            raise SandboxError(f"failed to start sandbox: {exc}") from exc
        self._runtime = self._deployment.runtime
        logger.info("Sandbox started: %s", self._config.get("image"))
        return self._runtime

    def stop(self) -> None:
        """Stop and clean up the container. Safe to call multiple times."""
        if self._deployment is not None and self._loop is not None:
            try:
                self._loop.run_until_complete(self._deployment.stop())
            except Exception as exc:
                logger.warning("Error stopping sandbox: %s", exc)
            finally:
                self._deployment = None
                self._runtime = None
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    @property
    def runtime(self) -> AbstractRuntime:
        if self._runtime is None:
            raise SandboxError("sandbox not started")
        return self._runtime
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_sandbox.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/sandbox.py tests/unit/test_sandbox.py
git commit -m "feat: add SWE-ReX SandboxManager wrapper"
```

---

### Task 3: Implement LiteLLM model backend (model_backend.py)

**Files:**
- Create: `src/coding_agent/model_backend.py`
- Test: `tests/unit/test_model_backend.py`

**Interfaces:**
- Produces: `ModelBackend(model_name, **config).query(messages, tools=None) -> dict`, consumed by Task 8 (agent)
- Produces: `ModelBackend(model_name, **config).format_message(role, content, **extra) -> dict`, consumed by Task 8
- Produces: `ModelBackend(model_name, **config).format_tool_results(assistant_msg, outputs) -> list[dict]`, consumed by Task 8

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_model_backend.py
import os
import pytest
from coding_agent.model_backend import ModelBackend

def test_model_backend_creation():
    backend = ModelBackend(model_name="openai/test-model")
    assert backend.model_name == "openai/test-model"

def test_format_message():
    backend = ModelBackend(model_name="openai/test-model")
    msg = backend.format_message(role="system", content="Hello")
    assert msg == {"role": "system", "content": "Hello"}

def test_format_message_extra():
    backend = ModelBackend(model_name="openai/test-model")
    msg = backend.format_message(role="exit", content="Done",
                                 extra={"exit_status": "Submitted"})
    assert msg["role"] == "exit"
    assert msg["content"] == "Done"
    assert msg["extra"]["exit_status"] == "Submitted"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_model_backend.py -v
```

- [ ] **Step 3: Write model_backend.py implementation**

```python
# src/coding_agent/model_backend.py
from __future__ import annotations

from typing import Any

from minisweagent.models.litellm_model import LitellmModel


class ModelBackend:
    """Thin wrapper around mini-swe-agent's LitellmModel.

    Adds structured tool support (tool_definitions) and standardizes
    the message format for the agent loop.
    """

    def __init__(self, model_name: str, **config: Any):
        self._model = LitellmModel(model_name=model_name, **config)
        self.model_name = model_name

    def query(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Query the model with optional tool definitions.

        Returns an OpenAI-compatible assistant message dict with:
        - role: "assistant"
        - content: str or None
        - tool_calls: list[dict] or absent
        - extra: dict with cost, model stats
        """
        return self._model.query(messages, tools=tools)

    def format_message(self, role: str, content: str, **extra: Any) -> dict:
        """Build a standard message dict. Extra fields go under 'extra' key
        for exit/terminal messages."""
        msg: dict[str, Any] = {"role": role, "content": content}
        if extra:
            msg["extra"] = extra
        return msg

    def format_tool_results(
        self, assistant_message: dict, outputs: list[dict]
    ) -> list[dict]:
        """Build tool result messages from assistant tool_calls + execution outputs.

        Each output dict should have: tool_call_id, tool_name, content.
        """
        tool_calls = assistant_message.get("tool_calls", [])
        messages: list[dict] = []
        for i, output in enumerate(outputs):
            tc_id = ""
            if i < len(tool_calls):
                tc_id = tool_calls[i].get("id", "")
            messages.append({
                "role": "tool",
                "tool_call_id": output.get("tool_call_id", tc_id),
                "content": output.get("content", ""),
            })
        return messages

    @property
    def cost(self) -> float:
        return getattr(self._model, "cost", 0.0)

    @property
    def n_calls(self) -> int:
        return self._model.n_calls
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_model_backend.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/model_backend.py tests/unit/test_model_backend.py
git commit -m "feat: add LiteLLM ModelBackend wrapper"
```

---

### Task 4: Adapt read_file tool for SWE-ReX runtime

**Files:**
- Modify: `src/coding_agent/tools/read_file.py`

**Interfaces:**
- Modifies: `read_file()` now accepts `runtime: AbstractRuntime` parameter instead of `workspace: Path`
- Consumes: `AbstractRuntime.read_file(ReadFileRequest)` from SWE-ReX (via Task 2)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tools_read_file.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from coding_agent.tools.read_file import read_file
from coding_agent.models import Outcome

@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.read_file = AsyncMock()
    return runtime

def test_read_file_success(mock_runtime):
    mock_runtime.read_file.return_value.content = "line1\nline2\n"
    result = read_file(mock_runtime, workspace_path="/repo",
                       tool_input={"file_path": "src/main.py"})
    assert result.status == Outcome.OK
    mock_runtime.read_file.assert_called_once()

def test_read_file_rejects_empty_path(mock_runtime):
    result = read_file(mock_runtime, workspace_path="/repo",
                       tool_input={"file_path": ""})
    assert result.status == Outcome.REJECTED

def test_read_file_with_bounds(mock_runtime):
    mock_runtime.read_file.return_value.content = "a\nb\nc\nd\ne\n"
    result = read_file(mock_runtime, workspace_path="/repo",
                       tool_input={"file_path": "x.py", "offset": 2, "limit": 2})
    assert result.status == Outcome.OK
    # Check line range in output_summary
    assert "lines 2-3" in result.output_summary
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_tools_read_file.py -v
```
Expected: FAIL (old read_file signature incompatible with new test)

- [ ] **Step 3: Rewrite read_file.py**

```python
# src/coding_agent/tools/read_file.py
from __future__ import annotations

from typing import Any

from coding_agent.models import Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult

DEFAULT_PAGE_LINES = 200
MAX_CHARS = 50000


def _parse_bounds(tool_input: dict[str, Any]) -> tuple[int, int] | None:
    has_offset = "offset" in tool_input
    has_limit = "limit" in tool_input
    if not has_offset and not has_limit:
        return None
    start = int(tool_input.get("offset", 1))
    limit = int(tool_input.get("limit", DEFAULT_PAGE_LINES))
    if start < 1:
        raise ValueError("offset must be >= 1")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    return start, start + limit - 1


def _format_with_line_numbers(content: str, start_line: int) -> str:
    if not content:
        return ""
    lines = content.splitlines(keepends=True)
    end_line = start_line + len(lines) - 1
    width = max(4, len(str(end_line)))
    formatted: list[str] = []
    for i, line in enumerate(lines):
        num = start_line + i
        if line.endswith("\n"):
            formatted.append(f"{num:>{width}}\t{line[:-1]}\n")
        elif line.endswith("\r\n"):
            formatted.append(f"{num:>{width}}\t{line[:-2]}\r\n")
        else:
            formatted.append(f"{num:>{width}}\t{line}")
    return "".join(formatted)


def read_file(
    runtime: Any,  # AbstractRuntime
    *,
    workspace_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    """Read a UTF-8 text file from the container via SWE-ReX runtime."""
    from swe_rex.runtime.abstract import ReadFileRequest
    import asyncio

    file_path = str(tool_input.get("file_path", ""))
    if not file_path:
        return ToolExecutionResult(
            ToolName.READ_FILE, Outcome.REJECTED,
            "file_path must not be empty",
        )

    try:
        bounds = _parse_bounds(tool_input)
    except (TypeError, ValueError) as exc:
        return ToolExecutionResult(
            ToolName.READ_FILE, Outcome.REJECTED, str(exc),
        )

    full_path = f"{workspace_path.rstrip('/')}/{file_path}"

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    runtime.read_file(ReadFileRequest(path=full_path)),
                )
                response = future.result(timeout=30)
        else:
            response = asyncio.run(
                runtime.read_file(ReadFileRequest(path=full_path))
            )
    except Exception as exc:
        return ToolExecutionResult(
            ToolName.READ_FILE, Outcome.FAILED,
            f"failed to read file: {exc}",
        )

    content = response.content
    if not content:
        return ToolExecutionResult(
            ToolName.READ_FILE, Outcome.FAILED,
            f"file not found or empty: {file_path}",
        )

    lines = content.splitlines()
    total_lines = len(lines)

    if bounds is None:
        start = 1
        end = min(DEFAULT_PAGE_LINES, max(total_lines, 1))
    else:
        start, end = bounds

    actual_end = min(end, total_lines)
    selected_lines = lines[start - 1 : actual_end]
    selected = "\n".join(selected_lines)
    truncated = start > 1 or actual_end < total_lines

    if len(selected) > MAX_CHARS:
        selected = selected[:MAX_CHARS]
        truncated = True

    formatted = _format_with_line_numbers(selected, start) if selected else ""

    if truncated and total_lines > actual_end:
        remaining = total_lines - actual_end
        formatted = formatted.rstrip("\n\r") + (
            f"\n... [truncated, {remaining} lines remaining]\n"
        )

    if bounds is not None or truncated:
        output_summary = (
            f"read lines {start}-{actual_end} "
            f"({len(selected)} characters)"
        )
    else:
        output_summary = f"read {len(selected)} characters"

    return ToolExecutionResult(
        ToolName.READ_FILE,
        Outcome.OK,
        output_summary,
        output={
            "content": formatted,
            "encoding": "utf-8",
            "line_start": start if total_lines else 0,
            "line_end": actual_end,
            "total_lines": total_lines,
            "truncated": truncated,
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_tools_read_file.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/tools/read_file.py tests/unit/test_tools_read_file.py
git commit -m "ref(tools): adapt read_file for SWE-ReX runtime"
```

---

### Task 5: Adapt apply_patch tool for SWE-ReX runtime

**Files:**
- Modify: `src/coding_agent/tools/apply_patch.py`
- Test: `tests/unit/test_tools_apply_patch.py`

**Interfaces:**
- Modifies: `apply_patch()` now accepts `runtime: AbstractRuntime` instead of `workspace: Path`
- Consumes: `AbstractRuntime.read_file()` and `AbstractRuntime.write_file()` from SWE-ReX

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tools_apply_patch.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from coding_agent.tools.apply_patch import apply_patch
from coding_agent.models import Outcome

@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.read_file = AsyncMock()
    runtime.write_file = AsyncMock()
    runtime.read_file.return_value.content = "original content"
    runtime.write_file.return_value = MagicMock()
    return runtime

def test_apply_patch_write(mock_runtime):
    result = apply_patch(mock_runtime, workspace_path="/repo",
                         tool_input={"type": "write", "file_path": "new.py",
                                     "content": "print('hello')"})
    assert result.status == Outcome.OK
    mock_runtime.write_file.assert_called_once()

def test_apply_patch_update(mock_runtime):
    mock_runtime.read_file.return_value.content = "old text here"
    result = apply_patch(mock_runtime, workspace_path="/repo",
                         tool_input={"type": "update", "file_path": "f.py",
                                     "old_string": "old text", "new_string": "new text"})
    assert result.status == Outcome.OK

def test_apply_patch_update_old_not_found(mock_runtime):
    mock_runtime.read_file.return_value.content = "something else"
    result = apply_patch(mock_runtime, workspace_path="/repo",
                         tool_input={"type": "update", "file_path": "f.py",
                                     "old_string": "not there", "new_string": "x"})
    assert result.status == Outcome.FAILED
    assert "not found" in result.output_summary

def test_apply_patch_rejects_invalid_type(mock_runtime):
    result = apply_patch(mock_runtime, workspace_path="/repo",
                         tool_input={"type": "delete", "file_path": "x.py"})
    assert result.status == Outcome.REJECTED
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_tools_apply_patch.py -v
```

- [ ] **Step 3: Rewrite apply_patch.py**

```python
# src/coding_agent/tools/apply_patch.py
from __future__ import annotations

import asyncio
import difflib
from typing import Any

from swe_rex.runtime.abstract import ReadFileRequest, WriteFileRequest

from coding_agent.models import FileModification, Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult

VALID_TYPES = ("write", "update")


def _generate_diff(path: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
    )
    return "".join(diff)


def _find_similar_lines(content: str, target: str, max_hints: int = 3) -> list[str]:
    lines = content.splitlines()
    if not lines or not target.strip():
        return []
    scored = [
        (line, difflib.SequenceMatcher(None, target, line).ratio())
        for line in lines
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    hints: list[str] = []
    for line, ratio in scored:
        if ratio < 0.3:
            break
        hints.append(line[:120])
        if len(hints) >= max_hints:
            break
    return hints


def _full_path(workspace_path: str, file_path: str) -> str:
    return f"{workspace_path.rstrip('/')}/{file_path}"


def _read_content(runtime: Any, path: str) -> str:
    try:
        response = asyncio.run(runtime.read_file(ReadFileRequest(path=path)))
        return response.content
    except Exception:
        return ""


def _write_content(runtime: Any, path: str, content: str) -> None:
    asyncio.run(runtime.write_file(WriteFileRequest(path=path, content=content)))


def _apply_write(
    runtime: Any, workspace_path: str, file_path: str, tool_input: dict[str, Any]
) -> ToolExecutionResult:
    if "content" not in tool_input or not isinstance(tool_input.get("content"), str):
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            "write requires string content",
        )
    full = _full_path(workspace_path, file_path)
    try:
        _write_content(runtime, full, tool_input["content"])
    except Exception as exc:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.ERROR, str(exc),
        )
    return ToolExecutionResult(
        ToolName.APPLY_PATCH, Outcome.OK,
        f"wrote {file_path}",
        output={"encoding": "utf-8", "newline": "lf"},
        modifications=[FileModification(path=file_path, write_status=Outcome.OK)],
    )


def _apply_update(
    runtime: Any, workspace_path: str, file_path: str, tool_input: dict[str, Any]
) -> ToolExecutionResult:
    old_string = tool_input.get("old_string", "")
    new_string = tool_input.get("new_string", "")
    if not old_string:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            "update requires non-empty old_string",
        )
    if not isinstance(new_string, str):
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            "update requires new_string",
        )
    full = _full_path(workspace_path, file_path)
    content = _read_content(runtime, full)
    if not content:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.FAILED,
            f"file not found or empty: {file_path}",
        )

    count = content.count(old_string)
    if count == 0:
        hints = _find_similar_lines(content, old_string)
        msg = f"old_string not found in {file_path}"
        if hints:
            quoted = "\n".join(f"  > {h}" for h in hints)
            msg += f"\nMost similar lines in the file:\n{quoted}"
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.FAILED, msg,
        )
    if count > 1:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.FAILED,
            f"old_string appears {count} times in {file_path}. "
            "Include more surrounding context to make it unique.",
        )

    new_content = content.replace(old_string, new_string, 1)
    diff = _generate_diff(file_path, content, new_content)
    try:
        _write_content(runtime, full, new_content)
    except Exception as exc:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.ERROR, str(exc),
        )
    return ToolExecutionResult(
        ToolName.APPLY_PATCH, Outcome.OK,
        f"applied edit to {file_path}",
        output={"patch": diff, "encoding": "utf-8", "newline": "lf"},
        modifications=[FileModification(path=file_path, write_status=Outcome.OK)],
    )


def apply_patch(
    runtime: Any,
    *,
    workspace_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    """Structured file modification via SWE-ReX runtime.

    Two operations:
    - write: create or overwrite file_path with content
    - update: replace old_string with new_string via exact match
    """
    patch_type = tool_input.get("type", "")
    if patch_type not in VALID_TYPES:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            f"type must be one of {', '.join(VALID_TYPES)}, got: {patch_type}",
        )
    file_path = str(tool_input.get("file_path", ""))
    if not file_path:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            "file_path must not be empty",
        )
    if patch_type == "write":
        return _apply_write(runtime, workspace_path, file_path, tool_input)
    return _apply_update(runtime, workspace_path, file_path, tool_input)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_tools_apply_patch.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/tools/apply_patch.py tests/unit/test_tools_apply_patch.py
git commit -m "ref(tools): adapt apply_patch for SWE-ReX runtime"
```

---

### Task 6: Adapt search_code and run_tests for SWE-ReX runtime

**Files:**
- Modify: `src/coding_agent/tools/search_code.py`
- Modify: `src/coding_agent/tools/run_tests.py`
- Test: `tests/unit/test_tools_search_code.py`
- Test: `tests/unit/test_tools_run_tests.py`

**Interfaces:**
- Modifies: `search_code()` now accepts `runtime: AbstractRuntime` instead of `workspace: Path`
- Modifies: `run_tests()` now accepts `runtime: AbstractRuntime` instead of `workspace: Path`

- [ ] **Step 1: Write tests for search_code**

```python
# tests/unit/test_tools_search_code.py
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from coding_agent.tools.search_code import search_code
from coding_agent.models import Outcome

@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.execute = AsyncMock()
    return runtime

def test_search_code_rejects_empty_pattern(mock_runtime):
    result = search_code(mock_runtime, workspace_path="/repo",
                         tool_input={"pattern": ""})
    assert result.status == Outcome.REJECTED

def test_search_code_grep(mock_runtime):
    mock_runtime.execute.return_value.stdout = "src/main.py:5:def foo():\n"
    mock_runtime.execute.return_value.stderr = ""
    mock_runtime.execute.return_value.exit_code = 0
    result = search_code(mock_runtime, workspace_path="/repo",
                         tool_input={"pattern": "def foo"})
    assert result.status == Outcome.OK
    mock_runtime.execute.assert_called_once()

def test_search_code_invalid_regex(mock_runtime):
    result = search_code(mock_runtime, workspace_path="/repo",
                         tool_input={"pattern": "["})
    assert result.status == Outcome.REJECTED
```

- [ ] **Step 2: Write tests for run_tests**

```python
# tests/unit/test_tools_run_tests.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from coding_agent.tools.run_tests import run_tests
from coding_agent.models import Outcome

@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.execute = AsyncMock()
    return runtime

def test_run_tests_pass(mock_runtime):
    mock_runtime.execute.return_value.stdout = "1 passed"
    mock_runtime.execute.return_value.stderr = ""
    mock_runtime.execute.return_value.exit_code = 0
    result = run_tests(mock_runtime, workspace_path="/repo",
                       tool_input={"command": "pytest tests/test_x.py"},
                       timeout_seconds=60)
    assert result.status == Outcome.OK
    assert result.test_result is not None

def test_run_tests_fail(mock_runtime):
    mock_runtime.execute.return_value.stdout = "1 failed"
    mock_runtime.execute.return_value.stderr = ""
    mock_runtime.execute.return_value.exit_code = 1
    result = run_tests(mock_runtime, workspace_path="/repo",
                       tool_input={"command": "pytest tests/test_x.py"},
                       timeout_seconds=60)
    assert result.status == Outcome.FAILED
    assert result.test_result.status.value == "failed"

def test_run_tests_timeout(mock_runtime):
    import asyncio
    mock_runtime.execute.side_effect = asyncio.TimeoutError()
    result = run_tests(mock_runtime, workspace_path="/repo",
                       tool_input={"command": "pytest tests/test_x.py"},
                       timeout_seconds=1)
    assert result.status == Outcome.TIMEOUT

def test_run_tests_rejected_by_policy():
    from unittest.mock import MagicMock
    runtime = MagicMock()
    result = run_tests(runtime, workspace_path="/repo",
                       tool_input={"command": "rm -rf /"},
                       timeout_seconds=60)
    assert result.status == Outcome.REJECTED
```

- [ ] **Step 3: Run test to verify they fail**

```bash
python -m pytest tests/unit/test_tools_search_code.py tests/unit/test_tools_run_tests.py -v
```

- [ ] **Step 4: Rewrite search_code.py**

```python
# src/coding_agent/tools/search_code.py
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from swe_rex.runtime.abstract import Command

from coding_agent.models import Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult

DEFAULT_EXCLUDE_DIRS = "--exclude-dir=" + ",".join([
    ".git", ".venv", "venv", "node_modules", "build", "dist",
    ".tox", "__pycache__", ".pytest_cache",
])


def _build_grep_cmd(tool_input: dict[str, Any]) -> list[str]:
    pattern = str(tool_input.get("pattern", ""))
    cmd = ["grep", "-rn", "--color=never", DEFAULT_EXCLUDE_DIRS]
    if tool_input.get("ignore_case"):
        cmd.append("-i")
    head_limit = int(tool_input.get("head_limit", 250))
    cmd.extend(["-m", str(head_limit)])
    glob_pattern = tool_input.get("glob")
    if glob_pattern and glob_pattern != "**/*":
        cmd.extend(["--include", glob_pattern.replace("**/", "").lstrip("/")])
    cmd.append(pattern)
    cmd.append(".")
    return cmd


def search_code(
    runtime: Any,
    *,
    workspace_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    """Search repository files via grep in the container."""
    pattern_str = str(tool_input.get("pattern", ""))
    if not pattern_str:
        return ToolExecutionResult(
            ToolName.SEARCH_CODE, Outcome.REJECTED,
            "pattern must not be empty",
        )

    # Validate regex locally before sending to container
    flags = re.IGNORECASE if tool_input.get("ignore_case") else 0
    try:
        re.compile(pattern_str, flags)
    except re.error as exc:
        return ToolExecutionResult(
            ToolName.SEARCH_CODE, Outcome.REJECTED,
            f"invalid regular expression: {exc}",
        )

    cmd = _build_grep_cmd(tool_input)
    try:
        response = asyncio.run(runtime.execute(Command(
            command=cmd,
            cwd=workspace_path,
            timeout=30,
            check=False,
        )))
    except Exception as exc:
        return ToolExecutionResult(
            ToolName.SEARCH_CODE, Outcome.ERROR, str(exc),
        )

    output = response.stdout or ""
    matches: list[dict[str, Any]] = []
    for line in output.strip().split("\n"):
        if not line:
            continue
        # grep -n output format: path:lineno:content
        parts = line.split(":", 2)
        if len(parts) >= 3:
            matches.append({
                "path": parts[0],
                "line": int(parts[1]),
                "text": parts[2],
            })

    head_limit = int(tool_input.get("head_limit", 250))
    truncated = len(matches) >= head_limit
    return ToolExecutionResult(
        ToolName.SEARCH_CODE,
        Outcome.OK,
        f"found {len(matches)} matches",
        output={
            "matches": matches[:head_limit],
            "truncated": truncated,
            "files_searched": len(set(m["path"] for m in matches)),
        },
    )
```

- [ ] **Step 5: Rewrite run_tests.py**

```python
# src/coding_agent/tools/run_tests.py
from __future__ import annotations

import asyncio
import time
from typing import Any

from swe_rex.runtime.abstract import Command

from coding_agent.models import Outcome, TestResult, TestStatus, ToolName
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.tools.test_command_policy import validate_self_test_command


def _summarize_output(stdout: str, stderr: str, limit: int = 4000) -> str:
    out = stdout or ""
    err = stderr or ""
    combined = (out + ("\n" if out and err else "") + err).strip()
    return combined[:limit]


def run_tests(
    runtime: Any,
    *,
    workspace_path: str,
    tool_input: dict[str, Any],
    timeout_seconds: float,
) -> ToolExecutionResult:
    """Run a self-test command in the container via SWE-ReX runtime."""
    command = str(tool_input.get("command", ""))
    started = time.monotonic()

    policy = validate_self_test_command(command)
    if not policy.allowed:
        test_result = TestResult(
            command, TestStatus.REJECTED, 0.0,
            output_summary=policy.reason,
        )
        return ToolExecutionResult(
            ToolName.RUN_TESTS, Outcome.REJECTED,
            policy.reason, test_result=test_result,
        )

    argv = list(policy.argv)
    try:
        cmd_str = " ".join(argv)
        response = asyncio.run(runtime.execute(Command(
            command=cmd_str,
            cwd=workspace_path,
            timeout=timeout_seconds,
            check=False,
        )))
    except asyncio.TimeoutError:
        duration = time.monotonic() - started
        test_result = TestResult(
            command, TestStatus.TIMEOUT, duration,
            output_summary="command timed out",
        )
        return ToolExecutionResult(
            ToolName.RUN_TESTS, Outcome.TIMEOUT,
            "test command timed out", test_result=test_result,
        )
    except Exception as exc:
        duration = time.monotonic() - started
        test_result = TestResult(
            command, TestStatus.EXECUTION_ERROR, duration,
            output_summary=str(exc),
        )
        return ToolExecutionResult(
            ToolName.RUN_TESTS, Outcome.ERROR, str(exc),
            test_result=test_result,
        )

    duration = time.monotonic() - started
    status = TestStatus.PASSED if response.exit_code == 0 else TestStatus.FAILED
    outcome = Outcome.OK if response.exit_code == 0 else Outcome.FAILED
    summary = _summarize_output(response.stdout, response.stderr)
    test_result = TestResult(
        command, status, duration, response.exit_code,
        output_summary=summary,
    )
    return ToolExecutionResult(
        ToolName.RUN_TESTS, outcome,
        summary or status.value, test_result=test_result,
    )
```

- [ ] **Step 6: Run test to verify they pass**

```bash
python -m pytest tests/unit/test_tools_search_code.py tests/unit/test_tools_run_tests.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/coding_agent/tools/search_code.py src/coding_agent/tools/run_tests.py tests/unit/test_tools_search_code.py tests/unit/test_tools_run_tests.py
git commit -m "ref(tools): adapt search_code and run_tests for SWE-ReX runtime"
```

---

### Task 7: Implement SweRexToolExecutor (tools/executor.py)

**Files:**
- Modify: `src/coding_agent/tools/executor.py`
- Test: `tests/unit/test_executor.py`

**Interfaces:**
- Produces: `SweRexToolExecutor(runtime, workspace_path, test_timeout).execute(tool_name, tool_input) -> ToolExecutionResult`
- Consumes: `AbstractRuntime` from Task 2, adapted tool functions from Tasks 4-6

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_executor.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from coding_agent.tools.executor import SweRexToolExecutor
from coding_agent.models import ToolName, Outcome

@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.execute = AsyncMock()
    runtime.read_file = AsyncMock()
    runtime.write_file = AsyncMock()
    return runtime

def test_executor_read_file(mock_runtime):
    mock_runtime.read_file.return_value.content = "hello world\n"
    executor = SweRexToolExecutor(
        mock_runtime, workspace_path="/repo", test_timeout_seconds=60,
    )
    result = executor.execute(ToolName.READ_FILE,
                              {"file_path": "README.md"})
    assert result.tool_name == ToolName.READ_FILE
    assert result.status == Outcome.OK

def test_executor_apply_patch_write(mock_runtime):
    mock_runtime.write_file.return_value = MagicMock()
    executor = SweRexToolExecutor(
        mock_runtime, workspace_path="/repo", test_timeout_seconds=60,
    )
    result = executor.execute(ToolName.APPLY_PATCH,
                              {"type": "write", "file_path": "x.py",
                               "content": "x=1"})
    assert result.status == Outcome.OK

def test_executor_rejects_unknown_tool(mock_runtime):
    executor = SweRexToolExecutor(
        mock_runtime, workspace_path="/repo", test_timeout_seconds=60,
    )
    with pytest.raises(ValueError, match="unsupported tool"):
        executor.execute("invalid_tool", {})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_executor.py -v
```

- [ ] **Step 3: Rewrite executor.py**

```python
# src/coding_agent/tools/executor.py
from __future__ import annotations

from typing import Protocol

from coding_agent.models import ToolName
from coding_agent.tools.apply_patch import apply_patch
from coding_agent.tools.read_file import read_file
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.tools.run_tests import run_tests
from coding_agent.tools.search_code import search_code


class ToolExecutor(Protocol):
    """Protocol boundary between agent loop and tool execution."""
    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult: ...


class SweRexToolExecutor:
    """Execute structured tools inside a SWE-ReX container.

    All tool I/O goes through the AbstractRuntime, which ensures
    reads/writes/executions happen inside the task container.
    """

    def __init__(
        self,
        runtime,  # AbstractRuntime
        *,
        workspace_path: str,
        test_timeout_seconds: float,
    ):
        self._runtime = runtime
        self._workspace_path = workspace_path
        self._test_timeout_seconds = test_timeout_seconds

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        if tool_name is ToolName.READ_FILE:
            return read_file(
                self._runtime,
                workspace_path=self._workspace_path,
                tool_input=tool_input,
            )
        if tool_name is ToolName.APPLY_PATCH:
            return apply_patch(
                self._runtime,
                workspace_path=self._workspace_path,
                tool_input=tool_input,
            )
        if tool_name is ToolName.SEARCH_CODE:
            return search_code(
                self._runtime,
                workspace_path=self._workspace_path,
                tool_input=tool_input,
            )
        if tool_name is ToolName.RUN_TESTS:
            return run_tests(
                self._runtime,
                workspace_path=self._workspace_path,
                tool_input=tool_input,
                timeout_seconds=self._test_timeout_seconds,
            )
        raise ValueError(f"unsupported tool: {tool_name}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_executor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/tools/executor.py tests/unit/test_executor.py
git commit -m "feat: implement SweRexToolExecutor with SWE-ReX runtime backend"
```

---

### Task 8: Implement trajectory exporter (trajectory.py)

**Files:**
- Create: `src/coding_agent/trajectory.py`
- Test: `tests/unit/test_trajectory.py`

**Interfaces:**
- Produces: `TrajectoryExporter(output_dir).export(messages, run_id, instance_id, model_name, budget, final_patch) -> dict[str, Path]`
- Consumed by Task 9 (agent)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_trajectory.py
import json
from pathlib import Path
from coding_agent.trajectory import TrajectoryExporter
from coding_agent.models import RunBudget

def test_export_writes_all_artifacts(tmp_path):
    messages = [
        {"role": "system", "content": "You are an agent."},
        {"role": "user", "content": "Fix the bug."},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "function": {"name": "read_file",
             "arguments": '{"file_path": "main.py"}'}},
        ]},
        {"role": "tool", "tool_call_id": "call_1",
         "content": '{"tool_name":"read_file","status":"ok","output_summary":"read 100 chars"}'},
        {"role": "assistant", "content": "The issue is fixed.",
         "extra": {"exit_status": "Submitted", "submission": "done"}},
    ]
    exporter = TrajectoryExporter(tmp_path)
    paths = exporter.export(
        messages=messages,
        run_id="test-run-1",
        instance_id="test__repo-1",
        model_name="test-model",
        budget=RunBudget(max_steps=20, timeout_seconds=600, test_timeout_seconds=120),
        final_patch="diff --git a/main.py b/main.py\n...",
    )
    assert paths["trajectory_jsonl"].exists()
    assert paths["summary_json"].exists()
    assert paths["prediction_jsonl"].exists()

    # Verify trajectory.jsonl has correct number of steps
    with open(paths["trajectory_jsonl"]) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert len(lines) >= 2  # at least model + tool steps
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_trajectory.py -v
```

- [ ] **Step 3: Write trajectory.py**

```python
# src/coding_agent/trajectory.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coding_agent.models import (
    Outcome, Prediction, RunBudget, RunStatus, RunSummary, StepActionType,
    ToolCall, ToolName, TrajectoryStep, utc_now, _json_value,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TrajectoryExporter:
    """Derive all run artifacts from agent.messages at run end.

    Messages is the single source of truth — no parallel writer streams.
    """

    def __init__(self, output_dir: Path):
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        *,
        messages: list[dict[str, Any]],
        run_id: str,
        instance_id: str,
        model_name: str,
        budget: RunBudget,
        final_patch: str,
        error: str | None = None,
        changed_files: list[str] | None = None,
        test_summary: dict[str, int] | None = None,
    ) -> dict[str, Path]:
        changed_files = changed_files or []
        test_summary = test_summary or {}

        # --- trajectory.jsonl ---
        steps = self._messages_to_steps(messages)
        traj_jsonl_path = self._output_dir / "trajectory.jsonl"
        with open(traj_jsonl_path, "w", encoding="utf-8") as f:
            for step in steps:
                f.write(json.dumps(step.to_dict(), ensure_ascii=False) + "\n")

        # --- trajectory.json (summary format) ---
        traj_json_path = self._output_dir / "trajectory.json"
        traj_data = {
            "task_id": instance_id,
            "issue": self._find_user_message(messages),
            "final_diff": final_patch,
            "resolved": error is None,
            "trajectory": [s.to_dict() for s in steps],
        }
        with open(traj_json_path, "w", encoding="utf-8") as f:
            json.dump(traj_data, f, ensure_ascii=False, indent=2)

        # --- final.patch ---
        patch_path = self._output_dir / "final.patch"
        patch_path.write_text(final_patch, encoding="utf-8")

        # --- summary.json ---
        status = RunStatus.SOLVED if error is None else RunStatus.INCOMPLETE
        summary = RunSummary(
            run_id=run_id,
            instance_id=instance_id,
            model_name=model_name,
            status=status,
            budget=budget,
            changed_files=changed_files,
            test_summary=test_summary,
            error=error,
            artifacts={
                "trajectory": str(traj_jsonl_path),
                "trajectory_json": str(traj_json_path),
                "final_patch": str(patch_path),
            },
        )
        summary_path = self._output_dir / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, ensure_ascii=False, indent=2)

        # --- prediction.jsonl ---
        pred = Prediction(instance_id, model_name, final_patch)
        pred_path = self._output_dir / "prediction.jsonl"
        with open(pred_path, "w", encoding="utf-8") as f:
            json.dump(pred.to_dict(), f, ensure_ascii=False)
            f.write("\n")

        return {
            "trajectory_jsonl": traj_jsonl_path,
            "trajectory_json": traj_json_path,
            "final_patch": patch_path,
            "summary_json": summary_path,
            "prediction_jsonl": pred_path,
        }

    def _messages_to_steps(self, messages: list[dict]) -> list[TrajectoryStep]:
        steps: list[TrajectoryStep] = []
        step_idx = 0
        now = _utc_now()

        for msg in messages:
            role = msg.get("role", "")
            if role == "system":
                continue
            if role == "user":
                steps.append(TrajectoryStep(
                    step_index=step_idx,
                    timestamp=now,
                    action_type=StepActionType.MODEL,
                    outcome=Outcome.OK,
                ))
                step_idx += 1
            elif role == "assistant":
                content = msg.get("content")
                extra = msg.get("extra", {})
                if extra.get("exit_status"):
                    steps.append(TrajectoryStep(
                        step_index=step_idx,
                        timestamp=now,
                        action_type=StepActionType.FINAL,
                        outcome=Outcome.OK,
                        reasoning_summary=str(extra.get("submission", "")),
                    ))
                else:
                    steps.append(TrajectoryStep(
                        step_index=step_idx,
                        timestamp=now,
                        action_type=StepActionType.MODEL,
                        outcome=Outcome.OK,
                        reasoning_summary=str(content or ""),
                    ))
                step_idx += 1
            elif role == "tool":
                try:
                    data = json.loads(msg.get("content", "{}"))
                except json.JSONDecodeError:
                    data = {}
                tool_name_str = data.get("tool_name", "unknown")
                try:
                    tool_name = ToolName(tool_name_str)
                except ValueError:
                    continue
                tool_call = ToolCall(
                    tool_name=tool_name,
                    input={},
                    output_summary=data.get("output_summary", ""),
                    status=Outcome(data.get("status", "ok")),
                    started_at=now,
                    ended_at=now,
                )
                steps.append(TrajectoryStep(
                    step_index=step_idx,
                    timestamp=now,
                    action_type=StepActionType.TOOL_RESULT,
                    outcome=Outcome(data.get("status", "ok")),
                    tool_call=tool_call,
                    tool_result=data,
                ))
                step_idx += 1
        return steps

    def _find_user_message(self, messages: list[dict]) -> str:
        for msg in messages:
            if msg.get("role") == "user":
                return str(msg.get("content", ""))
        return ""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_trajectory.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/trajectory.py tests/unit/test_trajectory.py
git commit -m "feat: implement TrajectoryExporter from messages single-source"
```

---

### Task 9: Implement ToolAgent (agent.py)

**Files:**
- Modify: `src/coding_agent/agent.py` (full rewrite)
- Test: `tests/unit/test_agent.py`

**Interfaces:**
- Produces: `ToolAgent(model, executor, config).run(task) -> RunSummary`
- Consumes: `ModelBackend` (Task 3), `SweRexToolExecutor` (Task 7), `TrajectoryExporter` (Task 8), jinja2 templates (Task 1)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent.py
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from coding_agent.agent import ToolAgent, AgentConfig
from coding_agent.models import BenchmarkTask, RunBudget

@pytest.fixture
def config():
    return AgentConfig(
        system_template="You are an agent. Task: {{ task }}",
        instance_template="{{ problem_statement }}",
        step_limit=5,
        output_path=Path("/tmp/test_traj.json"),
    )

@pytest.fixture
def mock_model():
    model = MagicMock()
    model.model_name = "test-model"
    # First call: return tool call; second call: return exit
    model.query.side_effect = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "function": {"name": "read_file",
                             "arguments": '{"file_path": "test.py"}'},
            }],
        },
        {
            "role": "assistant",
            "content": "Done",
            "extra": {"exit_status": "Submitted", "submission": "fixed"},
        },
    ]
    model.format_message = lambda role, content, **extra: (
        {"role": role, "content": content, "extra": extra} if extra
        else {"role": role, "content": content}
    )
    model.format_tool_results = lambda msg, outputs: [
        {"role": "tool", "tool_call_id": "call_1",
         "content": str(outputs[0]) if outputs else "{}"},
    ]
    return model

@pytest.fixture
def mock_executor():
    executor = MagicMock()
    from coding_agent.tools.result import ToolExecutionResult
    from coding_agent.models import Outcome, ToolName
    executor.execute.return_value = ToolExecutionResult(
        ToolName.READ_FILE, Outcome.OK, "read 100 chars",
        output={"content": "test content"},
    )
    return executor

def test_agent_run_completes(config, mock_model, mock_executor, tmp_path):
    config.output_path = tmp_path / "test_traj.json"
    agent = ToolAgent(mock_model, mock_executor, config=config)
    result = agent.run(task="Fix bug", problem_statement="The bug is...")
    assert result is not None
    assert result["exit_status"] == "Submitted"

def test_agent_respects_step_limit(config, mock_model, mock_executor):
    config.step_limit = 1
    mock_model.query.side_effect = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "function": {"name": "read_file",
             "arguments": '{"file_path": "x.py"}'}},
        ]},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c2", "function": {"name": "read_file",
             "arguments": '{"file_path": "y.py"}'}},
        ]},
    ]
    agent = ToolAgent(mock_model, mock_executor, config=config)
    result = agent.run(task="Fix", problem_statement="Bug")
    assert result["exit_status"] == "LimitsExceeded"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_agent.py -v
```

- [ ] **Step 3: Write agent.py**

```python
# src/coding_agent/agent.py
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined, Template
from pydantic import BaseModel

from coding_agent.models import (
    BenchmarkTask, Outcome, RunBudget, RunStatus, RunSummary,
    ToolName, utc_now,
)
from coding_agent.tools.executor import ToolExecutor
from coding_agent.tools.schemas import TOOL_SCHEMAS
from coding_agent.trajectory import TrajectoryExporter

logger = logging.getLogger(__name__)


class FormatError(Exception):
    """Raised when model output cannot be parsed."""


class InterruptAgentFlow(Exception):
    """Raised to signal agent exit (success or failure)."""
    def __init__(self, messages: list[dict]):
        self.messages = messages


class AgentConfig(BaseModel):
    system_template: str
    instance_template: str
    step_limit: int = 30
    cost_limit: float = 5.0
    time_limit_seconds: int = 0
    output_path: Path | None = None
    max_consecutive_format_errors: int = 3
    checkpoint_every: int = 5


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
            "problem_statement": self._extra_template_vars.get("problem_statement", ""),
            "allowed_test_commands": self._extra_template_vars.get("allowed_test_commands", []),
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
            "allowed_test_commands": list(task.allowed_test_commands),
        }
        self.messages = []
        self.add_messages(
            {"role": "system", "content": self._render(self.config.system_template)},
            {"role": "user", "content": self._render(self.config.instance_template)},
        )
        exit_status = "error"
        submission = ""

        while True:
            try:
                self.step()
                self.n_consecutive_format_errors = 0
            except FormatError:
                self.n_consecutive_format_errors += 1
                if (
                    self.config.max_consecutive_format_errors > 0
                    and self.n_consecutive_format_errors >= self.config.max_consecutive_format_errors
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
            except Exception as e:
                logger.exception("Unhandled agent exception")
                self.add_messages({
                    "role": "exit",
                    "content": str(e),
                    "extra": {"exit_status": type(e).__name__, "submission": ""},
                })
                exit_status = type(e).__name__
                break
            finally:
                if self.config.output_path and self.n_calls % self.config.checkpoint_every == 0:
                    self._checkpoint()

            if self.messages[-1].get("role") == "exit":
                extra = self.messages[-1].get("extra", {})
                exit_status = extra.get("exit_status", "submitted")
                submission = extra.get("submission", "")
                break

        return self._build_summary(task, exit_status, submission)

    # -- per-step loop --

    def step(self) -> list[dict]:
        return self.execute_actions(self.query())

    def query(self) -> dict:
        if 0 < self.config.step_limit <= self.n_calls:
            raise InterruptAgentFlow([{
                "role": "exit", "content": "LimitsExceeded",
                "extra": {"exit_status": "LimitsExceeded", "submission": ""},
            }])
        if 0 < self.config.cost_limit <= self.cost:
            raise InterruptAgentFlow([{
                "role": "exit", "content": "CostLimitExceeded",
                "extra": {"exit_status": "CostLimitExceeded", "submission": ""},
            }])
        if (
            self.config.time_limit_seconds > 0
            and int(time.time() - self._start_time) >= self.config.time_limit_seconds
        ):
            raise InterruptAgentFlow([{
                "role": "exit", "content": "TimeExceeded",
                "extra": {"exit_status": "TimeExceeded", "submission": ""},
            }])

        self.n_calls += 1
        tools = self._build_tool_definitions()
        message = self.model.query(self.messages, tools=tools)
        self.cost += float(message.get("extra", {}).get("cost", 0.0))
        self.add_messages(message)
        return message

    def execute_actions(self, message: dict) -> list[dict]:
        actions = self._parse_tool_calls(message)
        if not actions:
            # Model returned text without tool calls — natural stop
            content = message.get("content", "")
            raise InterruptAgentFlow([{
                "role": "exit",
                "content": content or "",
                "extra": {"exit_status": "Submitted", "submission": content or ""},
            }])

        results = _parallel_execute(self.executor, actions)
        outputs = [self._tool_result_output(action, result) for action, result in zip(actions, results)]
        return self.add_messages(*outputs)

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
                raise FormatError(f"tool call arguments not valid JSON: {name}")
            if not isinstance(args, dict):
                raise FormatError(f"tool call arguments must be object: {name}")
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

    def _tool_result_output(self, action: _ToolAction, result: Any) -> dict:
        """Build a tool result message for the model history."""
        from coding_agent.tools.result import ToolExecutionResult
        if isinstance(result, ToolExecutionResult):
            payload = {
                "tool_name": result.tool_name.value,
                "status": result.status.value,
                "output_summary": result.output_summary,
                "output": result.output,
            }
        else:
            payload = {"tool_name": action.tool_name.value, "status": "error"}
        return {
            "role": "tool",
            "tool_call_id": action.tool_call_id,
            "content": json.dumps(payload, ensure_ascii=False, default=str),
        }

    # -- tool definitions --

    def _build_tool_definitions(self) -> list[dict]:
        """Convert internal TOOL_SCHEMAS to OpenAI function format."""
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

    def _build_summary(self, task: BenchmarkTask, exit_status: str, submission: str) -> RunSummary:
        exporter = TrajectoryExporter(Path("."))  # will be extended in CLI integration
        return exit_status, submission  # simplified; full integration in CLI task

    def _checkpoint(self) -> None:
        if self.config.output_path:
            path = Path(self.config.output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            import json as _json
            path.write_text(_json.dumps({
                "messages": self.messages,
                "n_calls": self.n_calls,
                "cost": self.cost,
            }, ensure_ascii=False, default=str), encoding="utf-8")


# -- parallel execution (preserved from current agent.py) --

from dataclasses import dataclass


@dataclass(frozen=True)
class _ToolAction:
    tool_name: ToolName
    tool_input: dict[str, Any]
    tool_call_id: str = ""


def _detect_conflicts(actions: list[_ToolAction]) -> list[list[int]]:
    """Group action indices that conflict (same file_path with a write)."""
    write_targets: dict[str, list[int]] = {}
    for i, a in enumerate(actions):
        if a.tool_name is ToolName.APPLY_PATCH:
            fp = a.tool_input.get("file_path", "")
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
    for fp, read_indices in read_targets.items():
        conflicting.update(read_indices)
        conflicting.update(write_targets[fp])

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
            results[idx] = executor.execute(actions[idx].tool_name, actions[idx].tool_input)
        else:
            def _run_one(idx: int) -> tuple[int, Any]:
                return idx, executor.execute(actions[idx].tool_name, actions[idx].tool_input)

            with ThreadPoolExecutor(max_workers=len(group)) as pool:
                futures = {pool.submit(_run_one, i): i for i in group}
                for future in as_completed(futures):
                    idx, result = future.result()
                    results[idx] = result

    return results


def _schema_to_openai(params: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    properties = {}
    required = []
    for name, spec in params.items():
        prop = {"type": spec["type"]}
        if "description" in spec:
            prop["description"] = spec["description"]
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_agent.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/agent.py tests/unit/test_agent.py
git commit -m "feat: implement ToolAgent with jinja2 + linear history + parallel tools"
```

---

### Task 10: Simplify models.py

**Files:**
- Modify: `src/coding_agent/models.py`

- Remove sandbox-specific models no longer needed: `TaskSandbox`, `BaseImage`, `SandboxMetadata`, `PreparedTaskEnvironment`, `ActivePreparedEnvironmentIndex`, `RuntimeLineage`, `PreparedEnvironmentStatus`
- Remove model-config model: `ModelConfig`
- Remove `AgentRun` (state machine now managed inside ToolAgent)
- Keep: `ToolName`, `Outcome`, `TestStatus`, `StepActionType`, `RunStatus`, `RunBudget`, `BenchmarkTask`, `ToolCall`, `TrajectoryStep`, `FileModification`, `TestResult`, `RunSummary`, `Prediction`, `ValidationSet`, `EvalReport`, `AdaptedTestSpec`, `ValidationTestSet` (used by swebench layer), utility functions
- Keep `utc_now()`, `_json_value()`, `_tuple_of_str()`

- [ ] **Step 1: Run existing unit tests to establish baseline**

```bash
python -m pytest tests/unit/ -v --tb=short -k "not sandbox and not agent"
```

- [ ] **Step 2: Edit models.py — remove sandbox/model-config models**

Remove these classes from models.py:
- `ModelConfig`
- `BaseImage`
- `TaskSandbox`
- `SandboxMetadata`
- `PreparedTaskEnvironment`
- `ActivePreparedEnvironmentIndex`
- `RuntimeLineage`
- `PreparedEnvironmentStatus`
- `AgentRun`
- `RepoSpecReviewStatus`
- `RepoVersionSpec`
- `BenchmarkTaskRecord`
- `AgentRunArtifactSet`
- `UnsupportedLegacySurface`
- `UnsupportedLegacyOperation`

- [ ] **Step 3: Run tests to verify no import breakage**

```bash
python -m pytest tests/unit/ -v --tb=short
```

- [ ] **Step 4: Commit**

```bash
git add src/coding_agent/models.py
git commit -m "ref(models): remove sandbox/model-config models superseded by ecosystem"
```

---

### Task 11: Simplify swebench/ and swesmith/ modules

**Files:**
- Modify: `src/coding_agent/swebench/*.py` — update imports
- Modify: `src/coding_agent/swesmith/*.py` — update imports

Remove dependencies on deleted modules (`sandbox/*`, `model_backends/*`, `trajectory/*`).
Update imports to point to new `sandbox.py`, `model_backend.py`, `trajectory.py`.

- [ ] **Step 1: Identify all broken imports**

```bash
grep -rn "from coding_agent.sandbox\." src/
grep -rn "from coding_agent.model_backends\." src/
grep -rn "from coding_agent.trajectory\." src/
grep -rn "from coding_agent.budgets" src/
grep -rn "from coding_agent.workspace" src/
grep -rn "from coding_agent.textio" src/
```

- [ ] **Step 2: Update imports in swebench/ and swesmith/**

Replace all broken imports with new module references. Specific changes:
- `from coding_agent.sandbox.docker_cli import DockerCli` → `from coding_agent.sandbox import SandboxManager`
- `from coding_agent.model_backends.openai_compatible import ...` → `from coding_agent.model_backend import ModelBackend`
- `from coding_agent.trajectory.writer import TrajectoryWriter` → `from coding_agent.trajectory import TrajectoryExporter`
- `from coding_agent.budgets import BudgetTracker` → inline budget tracking (now in agent.py)
- `from coding_agent.workspace import ...` → removed (paths resolved via SWE-ReX)
- `from coding_agent.textio import ...` → removed (file I/O via SWE-ReX)

- [ ] **Step 3: Run swebench/swesmith tests to verify**

```bash
python -m pytest tests/ -v --tb=short -k "swebench or swesmith"
```

- [ ] **Step 4: Commit**

```bash
git add src/coding_agent/swebench/ src/coding_agent/swesmith/
git commit -m "ref: update swebench/swesmith imports for ecosystem modules"
```

---

### Task 12: Rewrite CLI (cli.py)

**Files:**
- Modify: `src/coding_agent/cli.py`

Preserve subcommand structure and artifact compatibility.
Replace internal wiring to use new modules.

- [ ] **Step 1: Test existing CLI parsing**

```bash
.venv\Scripts\python.exe -m coding_agent.cli --help
```

- [ ] **Step 2: Rewrite CLI imports and wiring**

Replace imports from deleted modules with new module references.
Preserve all subcommand names and argument structures.

- [ ] **Step 3: Smoke test CLI**

```bash
.venv\Scripts\python.exe -m coding_agent.cli --help
.venv\Scripts\python.exe -m coding_agent.cli run --help
.venv\Scripts\python.exe -m coding_agent.cli swebench --help
```

- [ ] **Step 4: Commit**

```bash
git add src/coding_agent/cli.py
git commit -m "ref(cli): wire CLI to ecosystem modules"
```

---

### Task 13: Remove old modules

**Files:**
- Delete: `src/coding_agent/sandbox/docker_cli.py`
- Delete: `src/coding_agent/sandbox/manager.py`
- Delete: `src/coding_agent/sandbox/registry.py`
- Delete: `src/coding_agent/sandbox/tools.py`
- Delete: `src/coding_agent/sandbox/__init__.py`
- Delete: `src/coding_agent/model_backends/base.py`
- Delete: `src/coding_agent/model_backends/openai_compatible.py`
- Delete: `src/coding_agent/model_backends/mock.py`
- Delete: `src/coding_agent/model_backends/__init__.py`
- Delete: `src/coding_agent/trajectory/converter.py`
- Delete: `src/coding_agent/trajectory/patch.py`
- Delete: `src/coding_agent/trajectory/summary.py`
- Delete: `src/coding_agent/trajectory/writer.py`
- Delete: `src/coding_agent/trajectory/__init__.py`
- Delete: `src/coding_agent/budgets.py`
- Delete: `src/coding_agent/workspace.py`
- Delete: `src/coding_agent/textio.py`

- [ ] **Step 1: Run full test suite to confirm no remaining deps**

```bash
python -m pytest tests/ -v --tb=short
```

- [ ] **Step 2: Delete old modules**

```bash
git rm src/coding_agent/sandbox/docker_cli.py
git rm src/coding_agent/sandbox/manager.py
git rm src/coding_agent/sandbox/registry.py
git rm src/coding_agent/sandbox/tools.py
git rm src/coding_agent/sandbox/__init__.py
git rm src/coding_agent/model_backends/base.py
git rm src/coding_agent/model_backends/openai_compatible.py
git rm src/coding_agent/model_backends/mock.py
git rm src/coding_agent/model_backends/__init__.py
git rm src/coding_agent/trajectory/converter.py
git rm src/coding_agent/trajectory/patch.py
git rm src/coding_agent/trajectory/summary.py
git rm src/coding_agent/trajectory/writer.py
git rm src/coding_agent/trajectory/__init__.py
git rm src/coding_agent/budgets.py
git rm src/coding_agent/workspace.py
git rm src/coding_agent/textio.py
```

- [ ] **Step 3: Run full test suite to verify nothing broken**

```bash
python -m pytest tests/ -v --tb=short
```

- [ ] **Step 4: Commit**

```bash
git commit -m "ref: remove old modules superseded by ecosystem"
```

---

### Task 14: Integration test — full SWE-bench Lite run

**Files:**
- None (test-only)

- [ ] **Step 1: Run a single-task mock run to validate flow**

```bash
coding-agent run \
  --backend mock \
  --instance-id test__repo-1 \
  --workspace D:\tmp\test-workspace \
  --problem-statement-file D:\tmp\problem.txt \
  --allowed-test "python -m pytest tests/" \
  --max-steps 5 \
  --timeout-seconds 300 \
  --test-timeout-seconds 30 \
  --output-dir D:\tmp\test-run
```

Verify artifacts are written:
```bash
ls D:\tmp\test-run\trajectory.jsonl D:\tmp\test-run\summary.json D:\tmp\test-run\final.patch D:\tmp\test-run\prediction.jsonl
```

- [ ] **Step 2: Verify artifact format compatibility vs old runs**

Compare `summary.json` schema with a previous run's summary.json — keys and value types should match.

- [ ] **Step 3: Run a real SWE-bench Lite instance (if Docker available)**

```bash
coding-agent swebench prepare \
  --dataset data\dev-00000-of-00001.parquet \
  --instance-id django__django-11099 \
  --output-dir runs\django-11099-prepare

coding-agent swebench run \
  --dataset data\dev-00000-of-00001.parquet \
  --instance-id django__django-11099 \
  --backend openai-compatible \
  --max-steps 20 \
  --output-dir runs\django-11099-run
```

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: integration test adjustments"
```

---

## Summary

| Phase | Tasks | Files Created | Files Modified | Files Deleted |
|-------|-------|--------------|----------------|---------------|
| Dependencies | 1 | 2 (templates) | 1 (pyproject.toml) | 0 |
| Core modules | 2-8 | 3 (sandbox, model_backend, trajectory) | 5 (agent + 4 tools + executor) | 0 |
| Simplify | 9-11 | 0 | 3 (models, swebench/*, swesmith/*, cli) | 0 |
| Cleanup | 12-13 | 0 | 1 (cli) | 17 |
| Verify | 14 | 0 | 0 | 0 |
| **Total** | **14 tasks** | **5 files** | **10+ files** | **17 files** |

After refactor: ~18 `.py` files in `src/coding_agent/` (was ~40).
