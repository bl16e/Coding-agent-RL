# Agent Self-Test Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let SWE-Bench agents run policy-approved self-test and diagnostic commands without seeing the hidden official eval script, while keeping final benchmark status based on official eval.

**Architecture:** Add a focused command-policy module for in-loop self-tests, wire it only into official-style container runs, and keep final official eval as the authoritative benchmark validation path. Summary artifacts will preserve both benchmark status and raw agent loop status.

**Tech Stack:** Python 3.11, pytest, existing Docker CLI wrapper, existing `ContainerToolExecutor`, existing SWE-Bench official runtime modules.

---

## File Structure

- Create `src/coding_agent/tools/test_command_policy.py`
  - Owns parsing and allow/reject decisions for agent self-test commands.
  - Has no Docker or filesystem side effects.
- Create `tests/unit/test_test_command_policy.py`
  - Unit tests for allowed and rejected command forms.
- Modify `src/coding_agent/sandbox/tools.py`
  - Use the new policy in `ContainerToolExecutor.run_tests()`.
  - Keep exact allowlist fallback for existing official commands.
- Modify `tests/unit/test_container_tools.py`
  - Cover policy-approved commands and rejected dangerous commands at the container tool boundary.
- Modify `src/coding_agent/agent.py`
  - Change prompt wording from exact allowed commands to self-test guidance when the caller provides guidance commands.
  - Continue supporting local exact allowlist wording for non-official runs if needed.
- Modify `src/coding_agent/swebench/sandbox_run.py`
  - Do not pass the hidden official eval script as agent-visible allowed tests.
  - Preserve `agent_status` and `agent_error` in summary metadata.
  - Set top-level `summary.status` from official eval outcome.
- Modify `tests/integration/test_swebench_official_runtime.py`
  - Cover hidden official eval, self-test policy, and dual status semantics.
- Modify `src/coding_agent/swebench/grading.py`
  - Ensure Django unittest output with docstring lines is parsed into resolved eval reports.
- Modify `tests/unit/test_swebench_grading.py`
  - Cover Django unittest single-line and docstring-style output.

## Task 1: Add Self-Test Command Policy

**Files:**
- Create: `src/coding_agent/tools/test_command_policy.py`
- Create: `tests/unit/test_test_command_policy.py`

- [ ] **Step 1: Write failing tests for allowed command forms**

Create `tests/unit/test_test_command_policy.py`:

```python
import pytest

from coding_agent.tools.test_command_policy import validate_self_test_command


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/test_issue.py",
        "python -m pytest tests/test_issue.py -q",
        "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 test_utils.tests",
        "python -c \"print('diagnostic')\"",
        "python test_newline_fix.py",
        "python scripts/check_issue.py --flag",
    ],
)
def test_self_test_policy_allows_test_and_diagnostic_commands(command):
    assert validate_self_test_command(command).allowed is True
```

- [ ] **Step 2: Write failing tests for rejected command forms**

Append to `tests/unit/test_test_command_policy.py`:

```python
@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/test_issue.py && rm -rf /tmp/x",
        "python -m pytest tests/test_issue.py; git status",
        "python -c \"print('x')\" | tee out.txt",
        "git checkout abc tests/test_issue.py",
        "git apply -v -",
        "git reset --hard",
        "rm -rf django",
        "pip install requests",
        "python -m pip install requests",
        "apt install curl",
        "curl https://example.com",
        "wget https://example.com/file",
        "docker ps",
        "python ../outside.py",
        "/usr/bin/python test.py",
    ],
)
def test_self_test_policy_rejects_mutating_or_shell_commands(command):
    result = validate_self_test_command(command)
    assert result.allowed is False
    assert result.reason
```

- [ ] **Step 3: Run policy tests to verify they fail**

Run:

```powershell
python -m pytest tests\unit\test_test_command_policy.py -q
```

Expected: FAIL because `coding_agent.tools.test_command_policy` does not exist.

- [ ] **Step 4: Implement minimal command policy**

Create `src/coding_agent/tools/test_command_policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import shlex


@dataclass(frozen=True)
class CommandPolicyResult:
    allowed: bool
    reason: str = ""


_SHELL_CONTROL_MARKERS = ("&&", "||", ";", "|", ">", "<", "$(", "`", "\n", "\r")
_DANGEROUS_COMMANDS = {
    "apt",
    "apt-get",
    "curl",
    "docker",
    "git",
    "pip",
    "rm",
    "sudo",
    "wget",
}
_DANGEROUS_PYTHON_MODULES = {"pip"}


def validate_self_test_command(command: str) -> CommandPolicyResult:
    command = command.strip()
    if not command:
        return CommandPolicyResult(False, "command is empty")
    if any(marker in command for marker in _SHELL_CONTROL_MARKERS):
        return CommandPolicyResult(False, "shell control operators are not allowed")
    try:
        parts = shlex.split(command, posix=True)
    except ValueError as exc:
        return CommandPolicyResult(False, f"command is not parseable: {exc}")
    if not parts:
        return CommandPolicyResult(False, "command is empty")

    executable = parts[0]
    if executable in _DANGEROUS_COMMANDS:
        return CommandPolicyResult(False, f"{executable} is not allowed")
    if executable in {"pytest", "./pytest"}:
        return CommandPolicyResult(True)
    if executable == "./tests/runtests.py":
        return CommandPolicyResult(True)
    if executable not in {"python", "python3"}:
        return CommandPolicyResult(False, "only test and Python diagnostic commands are allowed")
    return _validate_python_command(parts)


def _validate_python_command(parts: list[str]) -> CommandPolicyResult:
    if len(parts) >= 3 and parts[1] == "-m":
        module = parts[2]
        if module in _DANGEROUS_PYTHON_MODULES:
            return CommandPolicyResult(False, f"python -m {module} is not allowed")
        if module == "pytest":
            return CommandPolicyResult(True)
        return CommandPolicyResult(False, "only python -m pytest is allowed")
    if len(parts) >= 2 and parts[1] == "-c":
        return CommandPolicyResult(True)
    if len(parts) >= 2 and _is_repo_relative_python_script(parts[1]):
        return CommandPolicyResult(True)
    return CommandPolicyResult(False, "python command must be -m pytest, -c, or a repo-relative .py script")


def _is_repo_relative_python_script(path: str) -> bool:
    if path.startswith(("/", "\\")):
        return False
    if ".." in path.replace("\\", "/").split("/"):
        return False
    return path.endswith(".py")
```

- [ ] **Step 5: Run policy tests to verify they pass**

Run:

```powershell
python -m pytest tests\unit\test_test_command_policy.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```powershell
git add src\coding_agent\tools\test_command_policy.py tests\unit\test_test_command_policy.py
git commit -m "feat: add agent self-test command policy"
```

## Task 2: Apply Policy in Container `run_tests`

**Files:**
- Modify: `src/coding_agent/sandbox/tools.py`
- Modify: `tests/unit/test_container_tools.py`

- [ ] **Step 1: Write failing container tests for relaxed commands**

Append to `tests/unit/test_container_tools.py`:

```python
def test_container_run_tests_allows_policy_approved_django_test_command():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task",
        repo_path="/testbed",
        allowed_test_commands=("hidden official eval script",),
        test_timeout_seconds=5,
    )

    result = executor.run_tests({"command": "./tests/runtests.py --verbosity 2 test_utils.tests"})

    assert result.status is Outcome.OK
    assert docker.exec_calls[-1][1] == ["sh", "-lc", "cd /testbed && ./tests/runtests.py --verbosity 2 test_utils.tests"]


def test_container_run_tests_allows_python_c_diagnostic():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task",
        repo_path="/testbed",
        allowed_test_commands=("hidden official eval script",),
        test_timeout_seconds=5,
    )

    result = executor.run_tests({"command": "python -c \"print('ok')\""})

    assert result.status is Outcome.OK
```

- [ ] **Step 2: Write failing container tests for rejected commands**

Append to `tests/unit/test_container_tools.py`:

```python
def test_container_run_tests_rejects_mutating_command_even_in_sandbox():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task",
        repo_path="/testbed",
        allowed_test_commands=("hidden official eval script",),
        test_timeout_seconds=5,
    )

    result = executor.run_tests({"command": "git checkout abc tests/test_issue.py"})

    assert result.status is Outcome.REJECTED
    assert result.test_result is not None
    assert "not allowed" in result.test_result.output_summary
```

- [ ] **Step 3: Run container tests to verify they fail**

Run:

```powershell
python -m pytest tests\unit\test_container_tools.py -q
```

Expected: FAIL because `ContainerToolExecutor.run_tests()` still requires exact command matches.

- [ ] **Step 4: Update `ContainerToolExecutor.run_tests()`**

In `src/coding_agent/sandbox/tools.py`, import the policy:

```python
from coding_agent.tools.test_command_policy import validate_self_test_command
```

Replace the exact-only rejection block:

```python
if command not in self._allowed_test_commands:
    test_result = TestResult(command, TestStatus.REJECTED, 0.0, output_summary="command is not allowed")
    return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.REJECTED, "command is not allowed", test_result=test_result)
```

with:

```python
if command not in self._allowed_test_commands:
    policy = validate_self_test_command(command)
    if not policy.allowed:
        output_summary = f"command is not allowed: {policy.reason}"
        test_result = TestResult(command, TestStatus.REJECTED, 0.0, output_summary=output_summary)
        return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.REJECTED, output_summary, test_result=test_result)
```

- [ ] **Step 5: Run container tests to verify they pass**

Run:

```powershell
python -m pytest tests\unit\test_container_tools.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add src\coding_agent\sandbox\tools.py tests\unit\test_container_tools.py
git commit -m "feat: allow policy-approved container self-tests"
```

## Task 3: Hide Official Eval Script from Agent Prompt

**Files:**
- Modify: `src/coding_agent/agent.py`
- Modify: `src/coding_agent/swebench/sandbox_run.py`
- Modify: `tests/unit/test_agent_run_lifecycle.py`
- Modify: `tests/integration/test_swebench_official_runtime.py`

- [ ] **Step 1: Write failing prompt test**

Append to `tests/integration/test_swebench_official_runtime.py`:

```python
class PromptCapturingBackend:
    def __init__(self) -> None:
        self.first_messages = None

    def next_action(self, messages):
        if self.first_messages is None:
            self.first_messages = messages
        return AgentAction(action=AgentActionType.FINAL, final_status="incomplete")


def test_official_eval_script_is_not_visible_to_agent_prompt(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = EvalRecordingDocker(present_images=set(PRESENT_IMAGES))
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )
    backend = PromptCapturingBackend()

    sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=backend,
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
    )

    prompt = backend.first_messages[0]["content"]
    assert "git apply" not in prompt
    assert "EOF_" not in prompt
    assert "Final benchmark validation is run automatically" in prompt
    assert "python -c" in prompt
```

- [ ] **Step 2: Run prompt test to verify it fails**

Run:

```powershell
python -m pytest tests\integration\test_swebench_official_runtime.py::test_official_eval_script_is_not_visible_to_agent_prompt -q
```

Expected: FAIL because the current prompt exposes exact allowed commands.

- [ ] **Step 3: Add self-test guidance helper**

In `src/coding_agent/swebench/sandbox_run.py`, add:

```python
SELF_TEST_COMMAND_GUIDANCE = (
    "pytest ...",
    "python -m pytest ...",
    "./tests/runtests.py ...",
    "python -c \"...\"",
    "python path/to/diagnostic.py",
)
```

In `run_prepared_swebench_runtime()`, change the `BenchmarkTask` construction from:

```python
allowed_test_commands=validation.allowed_commands,
```

to:

```python
allowed_test_commands=SELF_TEST_COMMAND_GUIDANCE,
```

Leave `ContainerToolExecutor(... allowed_test_commands=validation.allowed_commands ...)` unchanged so exact official commands still remain accepted internally.

- [ ] **Step 4: Update prompt wording**

In `src/coding_agent/agent.py`, replace the exact-command prompt text:

```python
"Allowed test commands (use these exact strings with run_tests):\n"
f"{allowed_tests}\n\n"
```

with:

```python
"You may use run_tests for focused repository tests and small diagnostics.\n"
"Examples of allowed self-test commands:\n"
f"{allowed_tests}\n\n"
"Final benchmark validation is run automatically after you finish.\n\n"
```

- [ ] **Step 5: Run prompt tests**

Run:

```powershell
python -m pytest tests\integration\test_swebench_official_runtime.py::test_official_eval_script_is_not_visible_to_agent_prompt tests\unit\test_agent_run_lifecycle.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```powershell
git add src\coding_agent\agent.py src\coding_agent\swebench\sandbox_run.py tests\unit\test_agent_run_lifecycle.py tests\integration\test_swebench_official_runtime.py
git commit -m "feat: hide official eval script from agent prompt"
```

## Task 4: Preserve Agent Status While Using Official Eval for Benchmark Status

**Files:**
- Modify: `src/coding_agent/swebench/sandbox_run.py`
- Modify: `tests/integration/test_swebench_official_runtime.py`

- [ ] **Step 1: Write failing solved-overrides-agent-incomplete test**

Append to `tests/integration/test_swebench_official_runtime.py`:

```python
def test_official_eval_resolution_sets_benchmark_status_and_preserves_agent_status(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = EvalRecordingDocker(
        present_images=set(PRESENT_IMAGES),
        diff_output="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
    )
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )

    summary = sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=MockBackend(
            [
                AgentAction(action=AgentActionType.RUN_TESTS, tool_input={"command": "rm -rf django"}),
                AgentAction(action=AgentActionType.FINAL, final_status="solved"),
            ]
        ),
        budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
    )

    payload = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary.status.value == "solved"
    assert payload["status"] == "solved"
    assert payload["agent_status"] == "incomplete"
    assert "unresolved tool failure" in payload["agent_error"]
```

- [ ] **Step 2: Write failing official-failure-not-solved test**

Append to `tests/integration/test_swebench_official_runtime.py`:

```python
class FailingEvalDocker(EvalRecordingDocker):
    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None):
        if command[:2] == ["bash", "-lc"]:
            return DockerResult(
                "\n".join(
                    [
                        ">>>>> Start Test Output",
                        "tests/test_issue.py::test_fix FAILED",
                        ">>>>> End Test Output",
                    ]
                ),
                "",
                0,
            )
        return super().exec(container, command, timeout_seconds=timeout_seconds, stdin=stdin)


def test_agent_solved_does_not_override_failed_official_eval(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = FailingEvalDocker(
        present_images=set(PRESENT_IMAGES),
        diff_output="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
    )
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )

    sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=MockBackend([AgentAction(action=AgentActionType.FINAL, final_status="solved")]),
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
    )

    payload = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert payload["status"] != "solved"
    assert payload["agent_status"] == "solved"
    assert payload["validation"]["eval_report"]["resolved"] is False
```

- [ ] **Step 3: Run status tests to verify they fail**

Run:

```powershell
python -m pytest tests\integration\test_swebench_official_runtime.py::test_official_eval_resolution_sets_benchmark_status_and_preserves_agent_status tests\integration\test_swebench_official_runtime.py::test_agent_solved_does_not_override_failed_official_eval -q
```

Expected: FAIL because `agent_status`/`agent_error` are not yet preserved and status still follows agent loop in some paths.

- [ ] **Step 4: Add agent metadata to official summary**

In `_write_official_summary()` in `src/coding_agent/swebench/sandbox_run.py`, compute:

```python
benchmark_status = RunStatus.SOLVED if eval_report is not None and eval_report.resolved else summary.status
benchmark_error = None if benchmark_status is RunStatus.SOLVED else summary.error
```

Then pass `status=benchmark_status`, `error=benchmark_error`, and include in metadata:

```python
metadata = _runtime_metadata(...)
metadata["agent_status"] = summary.status.value
metadata["agent_error"] = summary.error
```

Use that `metadata` when constructing `RunSummary`.

- [ ] **Step 5: Run status tests**

Run:

```powershell
python -m pytest tests\integration\test_swebench_official_runtime.py::test_official_eval_resolution_sets_benchmark_status_and_preserves_agent_status tests\integration\test_swebench_official_runtime.py::test_agent_solved_does_not_override_failed_official_eval -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```powershell
git add src\coding_agent\swebench\sandbox_run.py tests\integration\test_swebench_official_runtime.py
git commit -m "feat: separate benchmark and agent run status"
```

## Task 5: Parse Django Unittest Output Robustly

**Files:**
- Modify: `src/coding_agent/swebench/grading.py`
- Modify: `tests/unit/test_swebench_grading.py`

- [ ] **Step 1: Write failing tests for Django unittest output**

Append to `tests/unit/test_swebench_grading.py`:

```python
def test_parse_eval_report_accepts_django_unittest_output_with_docstring_lines():
    output = "\n".join(
        [
            "setup text",
            ">>>>> Start Test Output",
            "test_override_file_upload_permissions (test_utils.tests.OverrideSettingsTests)",
            "Overriding the FILE_UPLOAD_PERMISSIONS setting should be reflected in ... ok",
            "",
            "----------------------------------------------------------------------",
            "Ran 100 tests in 0.076s",
            "",
            "OK (skipped=1)",
            ">>>>> End Test Output",
        ]
    )

    report = parse_eval_report(
        output,
        repo="django/django",
        version="3.0",
        fail_to_pass=("test_override_file_upload_permissions (test_utils.tests.OverrideSettingsTests)",),
        raw_output_artifact="eval.log",
    )

    assert report.resolved is True
    assert report.fail_to_pass_success == ("test_override_file_upload_permissions (test_utils.tests.OverrideSettingsTests)",)
```

- [ ] **Step 2: Run grading test to verify it fails**

Run:

```powershell
python -m pytest tests\unit\test_swebench_grading.py::test_parse_eval_report_accepts_django_unittest_output_with_docstring_lines -q
```

Expected: FAIL because the current parser does not map the prior test name to the docstring status line.

- [ ] **Step 3: Implement unittest parser support**

In `src/coding_agent/swebench/grading.py`, add:

```python
def _parse_unittest_statuses(test_output: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    status_aliases = {
        "ok": "PASSED",
        "FAIL": "FAILED",
        "ERROR": "ERROR",
        "skipped": "SKIPPED",
    }
    pending_test: str | None = None
    for line in test_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("test_") and " (" in stripped and " ... " not in stripped:
            pending_test = stripped
            continue
        if " ... " not in stripped:
            continue
        test_name, status = stripped.rsplit(" ... ", 1)
        mapped = status_aliases.get(status.split()[0])
        if mapped:
            statuses[pending_test or test_name] = mapped
        pending_test = None
    return statuses
```

Then update `_status_map_from_official_output()`:

```python
if repo == "django/django":
    return {**_parse_pytest_statuses(test_output), **_parse_unittest_statuses(test_output)}
```

- [ ] **Step 4: Run grading tests**

Run:

```powershell
python -m pytest tests\unit\test_swebench_grading.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```powershell
git add src\coding_agent\swebench\grading.py tests\unit\test_swebench_grading.py
git commit -m "fix: parse django unittest eval output"
```

## Task 6: Final Verification

**Files:**
- Verify all touched files.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m pytest tests\unit\test_test_command_policy.py tests\unit\test_container_tools.py tests\unit\test_agent_run_lifecycle.py tests\unit\test_swebench_grading.py tests\integration\test_swebench_official_runtime.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run whitespace check**

Run:

```powershell
git diff --check -- src tests docs
```

Expected: no output and exit code 0.

- [ ] **Step 4: Inspect final diff**

Run:

```powershell
git diff --stat
git diff -- src tests
```

Expected:

- `run_tests` policy is scoped to container official-style runs.
- Official eval script is not exposed in the agent prompt.
- `summary.status` is benchmark status.
- `agent_status` and `agent_error` are preserved.
- Django unittest eval output is parsed.

- [ ] **Step 5: Commit final verification marker if needed**

If all previous tasks were committed independently, no extra commit is needed. If cleanup edits were made during verification, commit them:

```powershell
git add src tests docs
git commit -m "test: verify agent self-test command flow"
```
