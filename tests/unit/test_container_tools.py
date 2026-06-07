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


def test_container_executor_rejects_unallowed_test_command():
    executor = ContainerToolExecutor(
        docker=FakeDocker(),
        container_name="task-1",
        repo_path="/workspace/repo",
        allowed_test_commands=("python -m pytest tests/test_issue.py",),
        test_timeout_seconds=30,
    )

    result = executor.execute(ToolName.RUN_TESTS, {"command": "python -m pytest"})

    assert result.status is Outcome.REJECTED
