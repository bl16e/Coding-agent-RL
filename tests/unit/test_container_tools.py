import json

from coding_agent.models import Outcome, ToolName
from coding_agent.sandbox_manager import DockerResult
from coding_agent.tools.container_executor import ContainerToolExecutor, _container_helper_script


class FakeDocker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], str | None, str | None]] = []
        self.next_stdout: str | None = None
        self.next_stdout_by_command: dict[str, str] = {}
        self.rg_available = False

    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None, workdir=None) -> DockerResult:
        self.calls.append((container, command, stdin, workdir))
        if command == ["sh", "-lc", "command -v rg >/dev/null 2>&1"]:
            return DockerResult("", "", 0 if self.rg_available else 1)
        command_key = " ".join(command)
        if command_key in self.next_stdout_by_command:
            return DockerResult(self.next_stdout_by_command.pop(command_key), "", 0)
        if self.next_stdout is not None:
            stdout = self.next_stdout
            self.next_stdout = None
            return DockerResult(stdout, "", 0)
        joined = " ".join(command)
        if len(command) >= 5 and "_match_glob" in joined:
            return DockerResult(json.dumps({"matches": [{"path": "app.py", "line": 1, "text": "hello", "encoding": "utf-8", "newline": "lf"}], "truncated": False, "binary_skipped": 0}), "", 0)
        if len(command) >= 2 and command[-2:] == ["", ""]:
            return DockerResult(json.dumps({"content": "   1\thello\n", "encoding": "utf-8", "newline": "lf", "line_start": 1, "line_end": 1, "total_lines": 1, "truncated": False}), "", 0)
        if "splitlines" in joined:
            return DockerResult(json.dumps({"content": "   2\ttwo\n   3\tthree\n", "encoding": "utf-8", "newline": "lf", "line_start": 2, "line_end": 3, "total_lines": 4, "truncated": False}), "", 0)
        if "write_text" in joined:
            return DockerResult(json.dumps({"status": "ok", "encoding": "utf-8", "newline": "lf"}), "", 0)
        return DockerResult("tests passed", "", 0)


class FakeHelper:
    def __init__(self, payload: dict | None = None, *, fail: bool = False) -> None:
        self.payload = payload or {}
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def request(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        if self.fail:
            raise RuntimeError("helper unavailable")
        return self.payload


def test_container_json_rpc_helper_script_is_valid_python():
    compile(_container_helper_script(), "<container-helper-script>", "exec")


def test_container_executor_reads_file_from_repo_path():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.READ_FILE, {"file_path": "README.md"})

    assert result.status is Outcome.OK
    assert result.output["content"] == "   1\thello\n"
    assert result.output["encoding"] == "utf-8"
    assert result.output["newline"] == "lf"
    assert "/workspace/repo/README.md" in docker.calls[0][1]


def test_container_executor_prefers_json_rpc_helper_for_read_file():
    docker = FakeDocker()
    helper = FakeHelper(
        {
            "content": "   1\thello\n",
            "encoding": "utf-8",
            "newline": "lf",
            "line_start": 1,
            "line_end": 1,
            "total_lines": 1,
            "truncated": False,
        }
    )
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
        helper=helper,
    )

    result = executor.execute(ToolName.READ_FILE, {"file_path": "README.md"})

    assert result.status is Outcome.OK
    assert result.output["content"] == "   1\thello\n"
    assert helper.calls == [("read_file", {"path": "/workspace/repo/README.md", "bounds": None})]
    assert docker.calls == []


def test_container_executor_falls_back_when_json_rpc_helper_fails():
    docker = FakeDocker()
    helper = FakeHelper(fail=True)
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
        helper=helper,
    )

    result = executor.execute(ToolName.READ_FILE, {"file_path": "README.md"})

    assert result.status is Outcome.OK
    assert result.output["content"] == "   1\thello\n"
    assert len(docker.calls) == 1


def test_container_executor_reads_gbk_metadata_from_helper_payload():
    docker = FakeDocker()
    docker.next_stdout = json.dumps(
        {"content": "   1\t中文\n", "encoding": "gbk", "newline": "lf", "line_start": 1, "line_end": 1, "total_lines": 1, "truncated": False}
    )
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.READ_FILE, {"file_path": "encoded.txt"})

    assert result.status is Outcome.OK
    assert result.output["content"] == "   1\t中文\n"
    assert result.output["encoding"] == "gbk"


def test_container_executor_reads_requested_line_range():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.READ_FILE, {"file_path": "README.md", "offset": 2, "limit": 2})

    assert result.status is Outcome.OK
    assert result.output["content"] == "   2\ttwo\n   3\tthree\n"
    assert "lines 2-3" in result.output_summary


def test_container_read_file_script_limits_default_characters():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.READ_FILE, {"file_path": "README.md"})

    assert result.status is Outcome.OK
    script = docker.calls[0][1][2]
    assert "50000" in script


def test_container_executor_treats_offset_limit_as_line_window():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.READ_FILE, {"file_path": "README.md", "offset": 2, "limit": 2})

    assert result.status is Outcome.OK
    assert result.output["content"] == "   2\ttwo\n   3\tthree\n"
    assert "lines 2-3" in result.output_summary


def test_container_executor_applies_write():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.APPLY_PATCH, {"type": "write", "file_path": "app.py", "content": "print('fixed')\n"})

    assert result.status is Outcome.OK
    assert docker.calls[0][2] == "print('fixed')\n"
    assert result.output["encoding"] == "utf-8"
    assert result.output["newline"] == "lf"


def test_container_executor_write_script_is_valid_python():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.APPLY_PATCH, {"type": "write", "file_path": "app.py", "content": "print('fixed')\n"})

    assert result.status is Outcome.OK
    script = docker.calls[0][1][2]
    compile(script, "<container-add-file-script>", "exec")


def test_container_executor_update_script_is_valid_python():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(
        ToolName.APPLY_PATCH,
        {
            "type": "update",
            "file_path": "app.py",
            "old_string": "old",
            "new_string": "new",
        },
    )

    assert result.status is Outcome.OK
    assert result.output["encoding"] == "utf-8"
    assert result.output["newline"] == "lf"
    script = docker.calls[0][1][2]
    compile(script, "<container-update-script>", "exec")


def test_container_executor_searches_with_bounded_results():
    executor = ContainerToolExecutor(
        docker=FakeDocker(),
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.SEARCH_CODE, {"pattern": "hello", "head_limit": 5})

    assert result.status is Outcome.OK
    assert result.output["matches"][0]["path"] == "app.py"
    assert result.output["matches"][0]["encoding"] == "utf-8"


def test_container_executor_search_prefers_rg_json_when_available():
    docker = FakeDocker()
    docker.rg_available = True
    docker.next_stdout_by_command[" ".join(
        [
            "rg",
            "--json",
            "--line-number",
            "--max-count",
            "5",
            "--glob",
            "!.git/**",
            "--glob",
            "!.venv/**",
            "--glob",
            "!venv/**",
            "--glob",
            "!node_modules/**",
            "--glob",
            "!build/**",
            "--glob",
            "!dist/**",
            "--glob",
            "!.tox/**",
            "--glob",
            "!__pycache__/**",
            "--glob",
            "!.pytest_cache/**",
            "hello",
            "/workspace/repo",
        ]
    )] = "\n".join(
        [
            json.dumps({"type": "match", "data": {"path": {"text": "app.py"}, "line_number": 3, "lines": {"text": "hello\n"}}}),
            json.dumps({"type": "summary", "data": {"stats": {"matches": 1}}}),
        ]
    )
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.SEARCH_CODE, {"pattern": "hello", "head_limit": 5})

    assert result.status is Outcome.OK
    assert result.output["matches"] == [{"path": "app.py", "line": 3, "text": "hello", "encoding": "unknown", "newline": "unknown"}]
    assert docker.calls[0][1][:3] == ["sh", "-lc", "command -v rg >/dev/null 2>&1"]
    assert "--json" in docker.calls[1][1]


def test_container_executor_search_script_uses_regular_expressions():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.SEARCH_CODE, {"pattern": r"^class CharField\(Field\):", "head_limit": 5})

    assert result.status is Outcome.OK
    script = docker.calls[1][1][2]
    compile(script, "<container-search-script>", "exec")
    assert "re.compile" in script
    # pattern at index -7, head_limit at -6 (followed by ignore_case, glob, ctx_before, ctx_after, ctx_around)
    assert docker.calls[1][1][-7] == r"^class CharField\(Field\):"
    assert docker.calls[1][1][-6] == "5"


def test_container_executor_rejects_dangerous_test_command():
    executor = ContainerToolExecutor(
        docker=FakeDocker(),
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.RUN_TESTS, {"command": "git checkout abc tests/test_issue.py"})

    assert result.status is Outcome.REJECTED
    assert result.test_result is not None
    assert "not allowed" in result.test_result.output_summary


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
    assert docker.calls[-1][1] == ["./tests/runtests.py", "--verbosity", "2", "test_utils.tests"]
    assert docker.calls[-1][3] == "/testbed"


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
    assert docker.calls[-1][1] == ["python", "-c", "print('ok')"]
    assert docker.calls[-1][3] == "/testbed"


def test_container_run_tests_executes_multiline_python_c_without_shell():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task",
        repo_path="/testbed",
        allowed_test_commands=("hidden official eval script",),
        test_timeout_seconds=5,
    )

    result = executor.run_tests({"command": 'python -c "print(1)\nprint(2)"'})

    assert result.status is Outcome.OK
    assert docker.calls[-1][1] == ["python", "-c", "print(1)\nprint(2)"]
    assert docker.calls[-1][3] == "/testbed"


def test_container_run_tests_keeps_internal_allowlisted_script_on_shell_path():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task",
        repo_path="/testbed",
        allowed_test_commands=("set -euxo pipefail\n./tests/runtests.py test_utils.tests",),
        test_timeout_seconds=5,
    )

    result = executor.run_tests({"command": "set -euxo pipefail\n./tests/runtests.py test_utils.tests"})

    assert result.status is Outcome.OK
    assert docker.calls[-1][1] == ["sh", "-lc", "cd /testbed && set -euxo pipefail\n./tests/runtests.py test_utils.tests"]
    assert docker.calls[-1][3] is None


def test_container_executor_confines_official_prepared_environment_to_repo_path():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="official-task",
        repo_path="/testbed",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    ok = executor.execute(ToolName.READ_FILE, {"file_path": "README.md"})
    escaped = executor.execute(ToolName.READ_FILE, {"file_path": "../outside.txt"})

    assert ok.status is Outcome.OK
    assert "/testbed/README.md" in docker.calls[0][1]
    assert escaped.status is Outcome.REJECTED
    assert len(docker.calls) == 1
