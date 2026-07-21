from pathlib import Path

from coding_agent.models import Outcome, ToolName
from coding_agent.tools.executor import LocalToolExecutor


def test_local_tool_executor_preserves_read_file_behavior(tmp_path: Path):
    (tmp_path / "README.md").write_bytes(b"hello\n")
    executor = LocalToolExecutor(
        workspace=tmp_path,
        allowed_test_commands=("python -m pytest",),
        test_timeout_seconds=10,
    )

    result = executor.execute(ToolName.READ_FILE, {"path": "README.md"})

    assert result.status is Outcome.OK
    assert result.output["content"] == "hello\n"
    assert result.output["encoding"] == "utf-8"
    assert result.output["newline"] == "lf"


def test_local_tool_executor_preserves_run_tests_rejection(tmp_path: Path):
    executor = LocalToolExecutor(
        workspace=tmp_path,
        allowed_test_commands=("python -m pytest tests/test_example.py",),
        test_timeout_seconds=10,
    )

    result = executor.execute(ToolName.RUN_TESTS, {"command": "python -m pytest"})

    assert result.status is Outcome.REJECTED
    assert "not allowed" in result.output_summary
