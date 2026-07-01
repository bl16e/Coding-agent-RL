import json

from coding_agent.models import Outcome, ToolName
from coding_agent.sandbox.docker_cli import DockerResult
from coding_agent.sandbox.tools import ContainerToolExecutor


class FakeDocker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], str | None]] = []

    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None) -> DockerResult:
        self.calls.append((container, command, stdin))
        joined = " ".join(command)
        if "json.dumps" in joined:
            return DockerResult(json.dumps({"matches": [{"path": "app.py", "line": 1, "text": "hello"}], "truncated": False}), "", 0)
        if "splitlines" in joined:
            return DockerResult("two\nthree\n", "", 0)
        if "read_text" in joined:
            return DockerResult("hello\n", "", 0)
        if "write_text" in joined:
            return DockerResult("", "", 0)
        return DockerResult("tests passed", "", 0)


def test_container_executor_reads_file_from_repo_path():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.READ_FILE, {"path": "README.md"})

    assert result.status is Outcome.OK
    assert result.output["content"] == "hello\n"
    assert "/workspace/repo/README.md" in docker.calls[0][1]


def test_container_executor_reads_requested_line_range():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.READ_FILE, {"path": "README.md", "line": 2, "end_line": 3})

    assert result.status is Outcome.OK
    assert result.output["content"] == "two\nthree\n"
    assert "lines 2-3" in result.output_summary


def test_container_executor_treats_offset_limit_as_line_window():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.READ_FILE, {"path": "README.md", "offset": 2, "limit": 2})

    assert result.status is Outcome.OK
    assert result.output["content"] == "two\nthree\n"
    assert "lines 2-3" in result.output_summary


def test_container_executor_applies_add_file():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.APPLY_PATCH, {"type": "add_file", "path": "app.py", "content": "print('fixed')\n"})

    assert result.status is Outcome.OK
    assert docker.calls[0][2] == "print('fixed')\n"


def test_container_executor_add_file_script_is_valid_python():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.APPLY_PATCH, {"type": "add_file", "path": "app.py", "content": "print('fixed')\n"})

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
            "path": "app.py",
            "old_string": "old",
            "new_string": "new",
        },
    )

    assert result.status is Outcome.OK
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

    result = executor.execute(ToolName.SEARCH_CODE, {"query": "hello", "max_results": 5})

    assert result.status is Outcome.OK
    assert result.output["matches"][0]["path"] == "app.py"


def test_container_executor_search_script_uses_regular_expressions():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.SEARCH_CODE, {"query": r"^class CharField\(Field\):", "max_results": 5})

    assert result.status is Outcome.OK
    script = docker.calls[0][1][2]
    compile(script, "<container-search-script>", "exec")
    assert "re.compile" in script
    assert docker.calls[0][1][-2:] == [r"^class CharField\(Field\):", "5"]


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
    assert docker.calls[-1][1] == ["sh", "-lc", "cd /testbed && ./tests/runtests.py --verbosity 2 test_utils.tests"]


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


def test_container_executor_confines_official_prepared_environment_to_repo_path():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="official-task",
        repo_path="/testbed",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    ok = executor.execute(ToolName.READ_FILE, {"path": "README.md"})
    escaped = executor.execute(ToolName.READ_FILE, {"path": "../outside.txt"})

    assert ok.status is Outcome.OK
    assert "/testbed/README.md" in docker.calls[0][1]
    assert escaped.status is Outcome.REJECTED
    assert len(docker.calls) == 1
