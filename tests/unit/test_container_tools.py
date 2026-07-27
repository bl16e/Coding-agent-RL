"""Tests for the CLI-dispatch ContainerToolExecutor (R2E-Gym pattern)."""
from __future__ import annotations

from coding_agent.models import Outcome, ToolName
from coding_agent.sandbox_manager import DockerResult
from coding_agent.tools.container_executor import ContainerToolExecutor, install_tool_scripts


class FakeDocker:
    """Simulates Docker CLI for testing tool script dispatch."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], str | None, str | None]] = []
        self.next_stdout: str = ""
        self.next_stderr: str = ""
        self.next_returncode: int = 0
        self._timeout_raised: bool = False

    def exec(
        self, container: str, command: list[str], *,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        workdir: str | None = None,
        check: bool = False,
    ) -> DockerResult:
        self.calls.append((container, command, stdin, workdir))
        return DockerResult(self.next_stdout, self.next_stderr, self.next_returncode)


def _make_executor(**kwargs) -> ContainerToolExecutor:
    docker = kwargs.pop("docker", FakeDocker())
    return ContainerToolExecutor(
        docker=docker,
        container_name=kwargs.pop("container_name", "task-1"),
        repo_path=kwargs.pop("repo_path", "/testbed"),
        **kwargs,
    )


# --- _to_cli_command ---------------------------------------------------------

def test_to_cli_command_read_file_basic():
    cmd = ContainerToolExecutor._to_cli_command(
        ToolName.READ_FILE, {"file_path": "/testbed/src/main.py"},
    )
    assert "read_file --file_path" in cmd
    assert "/testbed/src/main.py" in cmd


def test_to_cli_command_read_file_with_view_range():
    cmd = ContainerToolExecutor._to_cli_command(
        ToolName.READ_FILE, {"file_path": "/testbed/src/main.py", "view_range": [10, 30]},
    )
    assert "--view_range 10 30" in cmd


def test_to_cli_command_apply_patch_update():
    cmd = ContainerToolExecutor._to_cli_command(
        ToolName.APPLY_PATCH,
        {"path": "/x.py", "old_string": "abc", "new_string": "def"},
    )
    assert "apply_patch --path" in cmd
    assert "--old_string abc" in cmd
    assert "--new_string def" in cmd


def test_to_cli_command_apply_patch_create():
    cmd = ContainerToolExecutor._to_cli_command(
        ToolName.APPLY_PATCH,
        {"path": "/new.py", "old_string": "", "new_string": "print(1)"},
    )
    assert "apply_patch --path" in cmd
    assert "--new_string" in cmd
    assert "--old_string" not in cmd


def test_to_cli_command_search_code_basic():
    cmd = ContainerToolExecutor._to_cli_command(
        ToolName.SEARCH_CODE, {"pattern": "def foo", "head_limit": 20},
    )
    assert "search_code --pattern" in cmd
    assert "--head_limit 20" in cmd
    assert "--ignore_case" not in cmd  # removed


# --- _execute_bash -----------------------------------------------------------

def test_execute_bash_runs_command():
    docker = FakeDocker()
    docker.next_stdout = "hello world"
    ex = _make_executor(docker=docker)

    result = ex.execute(ToolName.EXECUTE_BASH, {"command": "echo hello"})

    assert result.status is Outcome.OK
    assert "hello world" in result.output["stdout"]


def test_execute_bash_blocks_dangerous_commands():
    ex = _make_executor()
    for cmd in ("git status", "ipython", "jupyter notebook", "nohup sleep 100"):
        result = ex.execute(ToolName.EXECUTE_BASH, {"command": cmd})
        assert result.status is Outcome.REJECTED, f"should block: {cmd}"


def test_execute_bash_rejects_empty_command():
    ex = _make_executor()
    result = ex.execute(ToolName.EXECUTE_BASH, {"command": ""})
    assert result.status is Outcome.REJECTED


def test_execute_bash_nonzero_with_stdout_is_ok():
    docker = FakeDocker()
    docker.next_stdout = "3 passed, 1 failed"
    docker.next_returncode = 1
    ex = _make_executor(docker=docker)

    result = ex.execute(ToolName.EXECUTE_BASH, {"command": "pytest"})

    assert result.status is Outcome.OK
    assert "3 passed" in result.output["stdout"]


def test_execute_bash_nonzero_without_stdout_is_failed():
    docker = FakeDocker()
    docker.next_stdout = ""
    docker.next_stderr = "command not found"
    docker.next_returncode = 127
    ex = _make_executor(docker=docker)

    result = ex.execute(ToolName.EXECUTE_BASH, {"command": "nonexistent"})

    assert result.status is Outcome.FAILED


# --- _finish ----------------------------------------------------------------

def test_finish_returns_submission():
    ex = _make_executor()
    result = ex.execute(ToolName.FINISH, {"result": "fixed bug in L003"})
    assert result.status is Outcome.OK
    assert result.output["submission"] == "fixed bug in L003"


def test_finish_empty_result():
    ex = _make_executor()
    result = ex.execute(ToolName.FINISH, {})
    assert result.status is Outcome.OK


# --- _run_tool_script (structured tools via CLI) -----------------------------

def test_run_tool_script_read_file():
    docker = FakeDocker()
    docker.next_stdout = "   1\thello world\n   2\tfoo bar"
    ex = _make_executor(docker=docker)

    result = ex.execute(ToolName.READ_FILE, {"file_path": "/testbed/app.py"})

    assert result.status is Outcome.OK
    stdout = result.output["stdout"]
    assert "hello world" in stdout
    assert "foo bar" in stdout
    # rstrip preserves leading spaces but trims trailing newlines
    assert stdout.startswith("   1\t") or stdout.startswith("1\t")


def test_run_tool_script_apply_patch():
    docker = FakeDocker()
    docker.next_stdout = "Patched: /testbed/app.py"
    ex = _make_executor(docker=docker)

    result = ex.execute(
        ToolName.APPLY_PATCH,
        {"path": "/testbed/app.py", "old_string": "old", "new_string": "new"},
    )

    assert result.status is Outcome.OK


def test_run_tool_script_search_code_json_output():
    docker = FakeDocker()
    docker.next_stdout = '{"matches": [{"path": "a.py", "line": 1, "text": "hello"}], "truncated": false, "engine": "rg"}'
    ex = _make_executor(docker=docker)

    result = ex.execute(ToolName.SEARCH_CODE, {"pattern": "hello"})

    assert result.status is Outcome.OK
    assert len(result.output["matches"]) == 1


def test_run_tool_script_nonzero_exit_is_failure():
    docker = FakeDocker()
    docker.next_stdout = ""
    docker.next_stderr = "ERROR: file not found"
    docker.next_returncode = 1
    ex = _make_executor(docker=docker)

    result = ex.execute(ToolName.READ_FILE, {"file_path": "/testbed/missing.py"})

    assert result.status is Outcome.FAILED


# --- Path safety -------------------------------------------------------------

def test_executor_passes_path_to_cli_unchanged():
    """Path validation is done by the script inside the container, not the executor."""
    docker = FakeDocker()
    docker.next_stdout = "ERROR: path not found"
    docker.next_returncode = 1
    ex = _make_executor(docker=docker)

    result = ex.execute(ToolName.READ_FILE, {"file_path": "../../etc/passwd"})

    assert result.status is Outcome.FAILED
    # The command contains the path as-is; script handles validation
    assert "../../etc/passwd" in docker.calls[0][1][-1]


# --- install_tool_scripts ----------------------------------------------------

def test_install_tool_scripts_finds_scripts_dir():
    """install_tool_scripts should find the scripts directory."""
    import os
    from pathlib import Path
    scripts_dir = Path(__file__).resolve().parents[2] / "src" / "coding_agent" / "tools" / "scripts"
    assert scripts_dir.is_dir(), f"scripts dir not found at {scripts_dir}"
    scripts = list(scripts_dir.glob("*.py"))
    names = {s.stem for s in scripts if s.stem != "__init__"}
    assert names >= {"read_file", "apply_patch", "search_code", "finish"}, f"missing scripts: {names}"
